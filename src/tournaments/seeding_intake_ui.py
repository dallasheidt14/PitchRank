"""Operator controls for format-neutral MatchBalance cheat sheets."""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config.settings import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from src.tournaments.reports.render_csv import csv_safe
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_assessment import assess_roster, could_belong
from src.tournaments.seeding_pack import (
    analyze_pack,
    available_cohorts,
    cohort_key,
    cohort_label,
    has_snapshot_identity_conflict,
    make_pack,
    pack_matches,
    prediction_request,
    snapshot_ratings,
    team_ids_by_row,
)
from src.tournaments.seeding_pdf import SeedingPdfError, render_seeding_pdf
from src.tournaments.seeding_predictions import load_seeding_predictions, seeding_predictor_sha256
from src.tournaments.seeding_run_store import slugify
from src.tournaments.seeding_sheet import build_cohort_sheets, make_ratings_lookup, render_sheet_html
from src.tournaments.seeding_workbook import build_seeding_workbook, validate_seeding_workbook

_PACK_KEY = "_seeding_pack"


def team_csv(rows, resolved, overrides, *, draft: bool = False) -> bytes:
    """Editable roster export preserves every selected registration, matched or not."""
    outcomes = {item.source_index: item for item in resolved}
    identities = team_ids_by_row(rows, resolved, overrides)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Cohort", "Submitted team name", "PitchRank team name", "Match method",
                     "PitchRank ID", "Listed division", "Requested flight", "Notes", "Delivery status"])
    for row in rows:
        item = outcomes.get(row.source_index)
        override = overrides.get(row.source_index, {})
        if override.get("not_found"):
            match_method = "Not found in PitchRank"
            notes = "Accepted roster team has no PitchRank match."
        else:
            match_method = "Manual" if override else (item.status if item else "unresolved")
            notes = row.intake_issue or (item.review_reason if item and not override else "") or ""
        writer.writerow([csv_safe(value) for value in [
            cohort_label(cohort_key(row.section_age_group, row.section_gender)), row.registered_name,
            override.get("team_name") or (item.matched_name if item else "") or "",
            match_method,
            identities.get(str(row.source_index)) or "", row.listed_division, row.requested_flight,
            notes,
            "Draft — roster review needed" if draft else "",
        ]])
    return stream.getvalue().encode("utf-8-sig")


def invalidate_seeding_exports(state: Any = None) -> None:
    state = st.session_state if state is None else state
    state.pop("_seeding_pdf", None)
    state.pop("_seeding_pdf_hash", None)
    state.pop("_seeding_xlsx", None)
    state.pop("_seeding_xlsx_hash", None)
    state["_seeding_sheet_html"] = None


def _persist_decisions(save: Callable[[], bool]) -> None:
    st.session_state["_seeding_pack_unsaved"] = not save()


def _selected_cohorts(parsed: ParsedRoster, saved: dict[str, Any] | None) -> list[str]:
    choices = available_cohorts(parsed.rows)
    saved_selection = (saved or {}).get("selected_cohorts")
    if not isinstance(saved_selection, list) or any(not isinstance(key, str) for key in saved_selection):
        saved_selection = None
    scope = st.radio(
        "Sheet pack", ["All imported cohorts", "Choose cohorts"], horizontal=True,
        index=1 if saved_selection and set(saved_selection) != set(choices) else 0,
        key="_seeding_pack_scope",
    )
    if scope == "All imported cohorts":
        return list(choices)
    return st.multiselect(
        "Age groups and genders", choices,
        default=[key for key in (saved_selection or choices) if key in choices],
        format_func=cohort_label, key="_seeding_pack_cohorts",
    )


def _identity_columns(
    entrant_id: str, teams: Mapping[str, dict[str, Any]], roster_rows: Mapping[str, RosterRow],
) -> dict[str, str]:
    row = roster_rows.get(entrant_id)
    team = teams.get(entrant_id, {})
    registered_name = row.registered_name if row else ""
    pitchrank_name = str(team.get("team_name") or "").strip()

    def comparable(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    different_name = bool(pitchrank_name and comparable(registered_name) != comparable(pitchrank_name))

    roster_note = ""
    if row and row.has_star_marker:
        age = team.get("age")
        entered = row.section_age_group.lower().removeprefix("u")
        entered_age = int(entered) if entered.isdigit() else None
        if (
            isinstance(age, int)
            and not isinstance(age, bool)
            and entered_age is not None
            and age < entered_age
        ):
            roster_note = f"Plays up from U{age}"
        else:
            roster_note = "Plays up"
    if row:
        requested = str(getattr(row, "requested_flight", "") or "").strip()
        listed = str(getattr(row, "listed_division", "") or "").strip()
        flight_note = f"Requested: {requested}" if requested else f"Listed: {listed}" if listed else ""
        roster_note = " · ".join(value for value in (roster_note, flight_note) if value)

    return {
        "Team": registered_name or pitchrank_name or "Unknown team",
        "PitchRank match": pitchrank_name if different_name else "",
        "Roster context": roster_note,
    }


def _render_cohort_review(
    key: str, analysis: Any, pack: dict[str, Any], save: Callable[[], bool],
    roster_rows: Mapping[str, RosterRow],
) -> None:
    teams = pack["teams"].get(key, {})
    st.markdown(f"##### {cohort_label(key)}")
    statuses = analysis.placement_status
    seeded = len(analysis.ordered_ids)
    age_group, gender = key.split("|", 1)
    accepted = sum(
        row.section_age_group == age_group and row.section_gender == gender
        for row in roster_rows.values()
    )
    unrated = sum(status in {"Not found in PitchRank", "No current rating"} for status in statuses.values())
    data_review = sum(status == "Data review required" for status in statuses.values())
    first, second, third, fourth = st.columns(4)
    first.metric("Accepted", accepted)
    second.metric("Seeded", seeded)
    third.metric("Unrated / not found", unrated)
    fourth.metric("Data review", data_review)
    st.caption(
        "Continuous seed order is shown below. Strength markers are reference points; "
        "they do not assign divisions or pools."
    )
    rows = []
    for seed, entrant_id in enumerate(analysis.ordered_ids, 1):
        rows.append({
            "Seed": seed,
            "Entrant": entrant_id,
            **_identity_columns(entrant_id, teams, roster_rows),
            "Strength marker": analysis.marker_for_seed(seed),
            "Placement status": statuses.get(entrant_id, "Seeded"),
        })
    for entrant_id, reason in analysis.review.items():
        rows.append({
            "Seed": "",
            "Entrant": entrant_id,
            **_identity_columns(entrant_id, teams, roster_rows),
            "Strength marker": "",
            "Placement status": statuses.get(entrant_id, reason),
        })
    if rows:
        generation = hashlib.sha256((
            str(pack["generated_at"]) + str(pack.get("operator_notes", {}).get(key))
        ).encode()).hexdigest()[:12]
        with st.form(f"_seeding_cheat_sheet_form_{key}_{generation}"):
            st.data_editor(
                pd.DataFrame(rows), hide_index=True, use_container_width=True,
                disabled=list(pd.DataFrame(rows).columns),
                key=f"_seeding_cheat_sheet_editor_{key}_{generation}",
            )
            notes = st.text_area(
                "Director notes (included on the PDF)",
                value=pack.get("operator_notes", {}).get(key, ""), max_chars=1800,
                key=f"_seeding_cheat_sheet_notes_{key}_{generation}",
            )
            applied = st.form_submit_button("Save director notes")
        if applied:
            pack.setdefault("operator_notes", {})[key] = notes.strip()
            st.session_state[_PACK_KEY] = pack
            invalidate_seeding_exports()
            _persist_decisions(save)
            st.rerun()
    if data_review:
        st.warning(f"{data_review} team(s) need identity or cohort review before delivery.")


def render_seeding_pack(
    parsed: ParsedRoster, resolved: Sequence[ResolvedTeam], supabase_client: Any, *,
    event_name: str, save: Callable[[], bool],
) -> None:
    st.markdown("#### Competitive seeding sheets")
    st.caption(
        "Compare every matchup in each selected cohort, review the seed order, "
        "then download the director sheets."
    )
    if not event_name:
        st.info("Name the event above before preparing its sheets.")
        return
    overrides = st.session_state._seeding_overrides
    pack = st.session_state.get(_PACK_KEY)
    if pack is not None and not isinstance(pack, dict):
        st.warning("This saved pack is unreadable. Build seeding sheets to replace it.")
        pack = None
    if st.session_state.get("_seeding_pack_unsaved"):
        st.warning("Your latest pack decisions are only in memory: saving failed. Retry before closing this run.")
        if st.button("Retry saving pack", key="_seeding_retry_pack_save"):
            _persist_decisions(save)
            st.rerun()
    selected = _selected_cohorts(parsed, pack)
    selected_rows = [row for row in parsed.rows if cohort_key(row.section_age_group, row.section_gender) in selected]
    st.caption(f"Selected: {len(selected)} cohort(s), {len(selected_rows)} accepted teams. "
               "Unmatched teams stay in the pack.")
    if not selected:
        return
    if pack:
        st.caption("Rebuilding reads fresh data while preserving director notes and roster decisions.")

    if st.button("Build seeding sheets", type="primary", key="_seeding_build_tiers"):
        try:
            with st.spinner("Reading current team data and comparing every matchup..."):
                request = prediction_request(parsed.rows, resolved, overrides, selected)
                batch = load_seeding_predictions(
                    request, supabase_url=SUPABASE_URL, supabase_key=SUPABASE_SERVICE_ROLE_KEY,
                )
                ids = [team_id for teams in request.values() for team_id in teams.values()]
                ratings = make_ratings_lookup(supabase_client)(ids)
                candidate = make_pack(parsed.rows, resolved, overrides, selected, batch, ratings)
                if isinstance(pack, dict):
                    # Rebuilds refresh predictions but preserve operator choices
                    # that are independent of the predictor snapshot.
                    candidate["policy"] = dict(pack.get("policy", candidate["policy"]))
                    candidate["operator_notes"] = dict(pack.get("operator_notes", {}))
                    candidate["legacy_manual_groups"] = dict(
                        pack.get("legacy_manual_groups", pack.get("manual_groups", {}))
                    )
                analyze_pack(candidate, parsed.rows, resolved, overrides)
                st.session_state[_PACK_KEY] = candidate
                pack = candidate
                invalidate_seeding_exports()
                _persist_decisions(save)
        except Exception as exc:
            # No new snapshot or export is published until all input checks pass.
            message = str(exc).replace(str(SUPABASE_SERVICE_ROLE_KEY or "__no_secret__"), "[redacted]")
            st.error(f"Could not build seeding sheets: {message}")

    current_pack = pack_matches(pack, parsed.rows, resolved, overrides, selected)
    metadata = st.session_state.get("_seeding_assessment") or {}
    assessment = assess_roster(parsed, resolved, overrides, coverage=metadata.get("coverage", "unknown"),
                               completed=metadata.get("completed"))
    selected_indices = {row.source_index for row in selected_rows}
    uncertain = [row for row in parsed.rows if row.source_index in assessment.cohort_review]
    draft = metadata.get("coverage") != "complete" or bool(assessment.attention & selected_indices) or any(
        could_belong(row, *key.split("|", 1)) for row in uncertain for key in selected
    ) or (current_pack and has_snapshot_identity_conflict(pack, selected))
    if draft:
        st.info("Delivery status: draft. Confirm coverage, resolve matches and assign cohorts before sending.")
    else:
        st.caption("Delivery status: roster assessed. Review seed order and director notes before sending.")
    st.download_button(
        "Download all selected teams as CSV", team_csv(selected_rows, resolved, overrides, draft=draft),
        file_name=f"{slugify(event_name)}-teams.csv", mime="text/csv", key="_seeding_all_teams_csv",
    )
    if not current_pack:
        invalidate_seeding_exports()
        if pack:
            st.info("The selected cohorts or team matches changed. Build seeding sheets to update this pack.")
        return
    if pack.get("predictor_sha256") != seeding_predictor_sha256():
        invalidate_seeding_exports()
        st.info("The predictor has been updated since this pack was built. After rankings finish, "
                "click Build seeding sheets to refresh predictions. Your team matches and tournament "
                "age assignments are saved.")
        return
    try:
        analyses = analyze_pack(pack, parsed.rows, resolved, overrides)
    except (ValueError, TypeError, KeyError) as exc:
        invalidate_seeding_exports()
        st.error(f"This pack needs rebuilding: {exc}")
        return
    st.caption(f"Saved prediction snapshot: {pack['generated_at']} · "
               f"Ratings as of {pack.get('ratings_as_of') or 'unknown'}")
    with st.expander("Analysis details", expanded=False):
        st.caption(
            f"Strength breaks use the saved limits of {pack['policy']['max_expected_margin']:.2f} expected goals "
            f"and {pack['policy']['max_blowout_probability']:.0%} four-goal risk. "
            "The analysis does not assign divisions, pools, schedules, or advancement."
        )
        for key in selected:
            detail = analyses[tuple(key.split("|", 1))]
            if detail.diagnostics:
                st.markdown(f"**{cohort_label(key)}**")
                for diagnostic in detail.diagnostics:
                    st.caption(diagnostic)
    with st.expander("Review seed order and director notes", expanded=True):
        roster_rows = {str(row.source_index): row for row in parsed.rows}
        for key in selected:
            _render_cohort_review(key, analyses[tuple(key.split("|", 1))], pack, save, roster_rows)
    identities = team_ids_by_row(parsed.rows, resolved, overrides)
    sheets = build_cohort_sheets(
        selected_rows, resolved, overrides, snapshot_ratings(pack, identities), tier_analyses=analyses,
    )
    document = render_sheet_html(
        f"{event_name} · DRAFT — roster review needed" if draft else event_name,
        sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
        operator_notes={tuple(key.split("|", 1)): value for key, value in pack.get("operator_notes", {}).items()},
    )
    document_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
    if st.session_state.get("_seeding_pdf_hash") != document_hash:
        st.session_state.pop("_seeding_pdf", None)
    st.session_state._seeding_sheet_html = document
    workbook = build_seeding_workbook(
        f"{event_name} · DRAFT — roster review needed" if draft else event_name,
        sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
    )
    validate_seeding_workbook(
        workbook,
        [f"{sheet.age_group.upper()} {'Boys' if sheet.gender == 'Male' else 'Girls'}"[:31] for sheet in sheets],
    )
    workbook_hash = hashlib.sha256(workbook).hexdigest()
    if st.session_state.get("_seeding_xlsx_hash") != workbook_hash:
        st.session_state["_seeding_xlsx"] = workbook
        st.session_state["_seeding_xlsx_hash"] = workbook_hash
    if st.button("Generate PDF pack", key="_seeding_generate_pdf"):
        try:
            with st.spinner("Laying out the printable sheets..."):
                pdf = render_seeding_pdf(document)
            st.session_state._seeding_pdf = pdf
            st.session_state._seeding_pdf_hash = document_hash
        except SeedingPdfError as exc:
            st.error(str(exc))
    pdf = st.session_state.get("_seeding_pdf")
    if pdf and st.session_state.get("_seeding_pdf_hash") == document_hash:
        st.download_button(
            "Download PDF pack", pdf, file_name=f"{slugify(event_name)}-matchbalance.pdf", mime="application/pdf",
        )
    st.download_button(
        "Download Excel workbook", workbook, file_name=f"{slugify(event_name)}-matchbalance.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="_seeding_workbook_download",
    )
    st.download_button(
        "Download printable HTML", document.encode("utf-8"),
        file_name=f"{slugify(event_name)}-matchbalance.html", mime="text/html", key="_seeding_sheet_download",
    )
    with st.expander("Preview sheets", expanded=False):
        components.html(document, height=950, scrolling=True)
