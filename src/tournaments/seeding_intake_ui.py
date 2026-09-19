"""Operator controls for matchup tiers and full-event or selected-cohort PDFs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config.settings import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_pack import (
    analyze_pack,
    available_cohorts,
    cohort_key,
    cohort_label,
    make_pack,
    pack_matches,
    prediction_request,
    snapshot_ratings,
    team_ids_by_row,
)
from src.tournaments.seeding_pdf import SeedingPdfError, render_seeding_pdf
from src.tournaments.seeding_predictions import load_seeding_predictions
from src.tournaments.seeding_run_store import slugify
from src.tournaments.seeding_sheet import build_cohort_sheets, make_ratings_lookup, render_sheet_html
from src.tournaments.seeding_tiers import TierPolicy

_PACK_KEY = "_seeding_pack"


def invalidate_seeding_exports(state: Any = None) -> None:
    state = st.session_state if state is None else state
    state.pop("_seeding_pdf", None)
    state.pop("_seeding_pdf_hash", None)
    state["_seeding_sheet_html"] = None


def _persist_decisions(save: Callable[[], bool]) -> None:
    st.session_state["_seeding_pack_unsaved"] = not save()


def _actionable_analysis_warnings(warnings: Sequence[str]) -> tuple[str, ...]:
    """Keep only placement warnings that require an operator decision visible."""
    return tuple(warning for warning in warnings if "exceeds the matchup limits" in warning)


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


def _policy_controls(pack: dict[str, Any], save: Callable[[], bool]) -> None:
    policy = pack["policy"]
    version = hashlib.sha256((str(pack["generated_at"]) + str(policy)).encode()).hexdigest()[:12]
    with st.expander("Grouping preferences"):
        st.caption(
            "Every pairing within a suggested tier must meet both limits. "
            "These are placement preferences, not a guarantee of the match result."
        )
        left, right = st.columns(2)
        margin = left.number_input(
            "Maximum predicted goal margin", min_value=0.5, max_value=5.0, step=0.25,
            value=float(policy["max_expected_margin"]), key=f"_seeding_margin_limit_{version}",
        )
        risk = right.number_input(
            "Maximum chance of a 4+ goal margin (%)", min_value=5, max_value=80, step=5,
            value=round(float(policy["max_blowout_probability"]) * 100), key=f"_seeding_risk_limit_{version}",
        )
        if st.button("Apply grouping preferences", key="_seeding_apply_policy"):
            pack["policy"] = {"max_expected_margin": margin, "max_blowout_probability": risk / 100}
            pack["manual_groups"] = {}
            st.session_state[_PACK_KEY] = pack
            invalidate_seeding_exports()
            _persist_decisions(save)
            st.rerun()


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
    counts = " + ".join(str(len(tier.entrant_ids)) for tier in analysis.tiers)
    st.caption(f"{len(analysis.tiers)} tier(s): {counts or 'no rated group'} · "
               f"{len(analysis.review)} need placement review")
    actionable_warnings = _actionable_analysis_warnings(analysis.warnings)
    for warning in actionable_warnings:
        st.warning(str(warning))
    diagnostic_warnings = [warning for warning in analysis.warnings if warning not in actionable_warnings]
    if analysis.boundaries or diagnostic_warnings:
        with st.expander("Analysis details", expanded=False):
            st.caption("Strength analysis describes competitive differences; it does not assign divisions or pools.")
            for boundary in analysis.boundaries:
                st.caption(str(boundary))
            for warning in diagnostic_warnings:
                st.caption(str(warning))
    rows = []
    for tier in analysis.tiers:
        for entrant_id in tier.entrant_ids:
            adjacent = analysis.borderline.get(entrant_id, ())
            if not adjacent:
                placement_note = ""
            elif len(adjacent) > 1:
                placement_note = "Boundary option: move to Tier " + " or Tier ".join(map(str, adjacent))
            else:
                target = adjacent[0]
                direction = "up" if target < tier.number else "down"
                placement_note = f"Boundary option: move {direction} to Tier {target} if needed"
            rows.append({
                "Entrant": entrant_id,
                **_identity_columns(entrant_id, teams, roster_rows),
                "Tier": tier.number,
                "Placement note": placement_note,
            })
    if rows:
        generation = hashlib.sha256((
            str(pack["generated_at"]) + str(pack["policy"]) + str(pack.get("manual_groups", {}).get(key))
        ).encode()).hexdigest()[:12]
        with st.form(f"_seeding_tier_form_{key}_{generation}"):
            edited = st.data_editor(
                pd.DataFrame(rows), hide_index=True, use_container_width=True,
                disabled=["Entrant", "Team", "PitchRank match", "Roster context", "Placement note"],
                column_config={
                    "Entrant": None,
                    "Tier": st.column_config.NumberColumn(
                        "Tier", min_value=1, max_value=len(rows), step=1, required=True,
                    ),
                },
                key=f"_seeding_tier_editor_{key}_{generation}",
            )
            notes = st.text_area(
                "Your placement notes (included on the PDF)",
                value=pack.get("operator_notes", {}).get(key, ""), max_chars=1800,
                key=f"_seeding_tier_notes_{key}_{generation}",
            )
            applied = st.form_submit_button("Save tier decisions")
        if applied:
            groups: dict[int, list[str]] = {}
            try:
                for record in edited.to_dict("records"):
                    number = float(record["Tier"])
                    if not number.is_integer() or not 1 <= number <= len(rows):
                        raise ValueError("Use whole tier numbers starting at 1.")
                    groups.setdefault(int(number), []).append(str(record["Entrant"]))
            except (ValueError, TypeError):
                st.error("Use whole tier numbers starting at 1 for every team.")
            else:
                pack.setdefault("manual_groups", {})[key] = [groups[number] for number in sorted(groups)]
                pack.setdefault("operator_notes", {})[key] = notes.strip()
                st.session_state[_PACK_KEY] = pack
                invalidate_seeding_exports()
                _persist_decisions(save)
                st.rerun()
        if key in pack.get("manual_groups", {}) and st.button(
            "Restore suggested tiers", key=f"_seeding_reset_tiers_{key}",
        ):
            pack["manual_groups"].pop(key)
            st.session_state[_PACK_KEY] = pack
            invalidate_seeding_exports()
            _persist_decisions(save)
            st.rerun()
    if analysis.review:
        st.info("Teams needing placement review remain on the sheet and are not assigned to the weakest tier.")
        st.dataframe(pd.DataFrame([
            {**_identity_columns(entrant, teams, roster_rows), "Reason": reason}
            for entrant, reason in analysis.review.items()
        ]), hide_index=True, use_container_width=True)
    if not rows:
        with st.form(f"_seeding_review_notes_{key}_{pack['generated_at']}"):
            notes = st.text_area("Your placement notes (included on the PDF)",
                                 value=pack.get("operator_notes", {}).get(key, ""), max_chars=1800)
            if st.form_submit_button("Save placement notes"):
                pack.setdefault("operator_notes", {})[key] = notes.strip()
                invalidate_seeding_exports()
                _persist_decisions(save)
                st.rerun()


def render_seeding_pack(
    parsed: ParsedRoster, resolved: Sequence[ResolvedTeam], supabase_client: Any, *,
    event_name: str, save: Callable[[], bool],
) -> None:
    st.markdown("#### Competitive seeding sheets")
    st.caption("Compare every matchup in each selected cohort, review the tiers, then download your PDF pack.")
    if not event_name:
        st.info("Name the event above before preparing its sheets.")
        return
    overrides = st.session_state._seeding_overrides
    pack = st.session_state.get(_PACK_KEY)
    if pack is not None and not isinstance(pack, dict):
        st.warning("This saved pack is unreadable. Build matchup tiers to replace it.")
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
        st.caption("Rebuilding reads fresh data and replaces this pack's manual tier decisions and placement notes.")

    if st.button("Build matchup tiers", type="primary", key="_seeding_build_tiers"):
        try:
            with st.spinner("Reading current team data and comparing every matchup..."):
                request = prediction_request(parsed.rows, resolved, overrides, selected)
                batch = load_seeding_predictions(
                    request, supabase_url=SUPABASE_URL, supabase_key=SUPABASE_SERVICE_ROLE_KEY,
                )
                ids = [team_id for teams in request.values() for team_id in teams.values()]
                ratings = make_ratings_lookup(supabase_client)(ids)
                candidate = make_pack(parsed.rows, resolved, overrides, selected, batch, ratings)
                analyze_pack(candidate, parsed.rows, resolved, overrides)
                st.session_state[_PACK_KEY] = candidate
                pack = candidate
                invalidate_seeding_exports()
                _persist_decisions(save)
        except Exception as exc:
            # No new snapshot or export is published until all input checks pass.
            message = str(exc).replace(str(SUPABASE_SERVICE_ROLE_KEY or "__no_secret__"), "[redacted]")
            st.error(f"Could not build matchup tiers: {message}")

    if not pack_matches(pack, parsed.rows, resolved, overrides, selected):
        invalidate_seeding_exports()
        if pack:
            st.info("The selected cohorts or team matches changed. Build matchup tiers to update this pack.")
        return
    try:
        analyses = analyze_pack(pack, parsed.rows, resolved, overrides)
    except (ValueError, TypeError, KeyError) as exc:
        invalidate_seeding_exports()
        st.error(f"This pack needs rebuilding: {exc}")
        return
    st.caption(f"Saved prediction snapshot: {pack['generated_at']} · "
               f"Ratings as of {pack.get('ratings_as_of') or 'unknown'}")
    _policy_controls(pack, save)
    with st.expander("Review and adjust tiers", expanded=True):
        roster_rows = {str(row.source_index): row for row in parsed.rows}
        for key in selected:
            _render_cohort_review(key, analyses[tuple(key.split("|", 1))], pack, save, roster_rows)
    identities = team_ids_by_row(parsed.rows, resolved, overrides)
    sheets = build_cohort_sheets(
        selected_rows, resolved, overrides, snapshot_ratings(pack, identities), tier_analyses=analyses,
    )
    document = render_sheet_html(
        event_name, sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
        policy=TierPolicy(**pack["policy"]),
        operator_notes={tuple(key.split("|", 1)): value for key, value in pack.get("operator_notes", {}).items()},
    )
    document_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
    if st.session_state.get("_seeding_pdf_hash") != document_hash:
        st.session_state.pop("_seeding_pdf", None)
    st.session_state._seeding_sheet_html = document
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
        "Download printable HTML", document.encode("utf-8"),
        file_name=f"{slugify(event_name)}-matchbalance.html", mime="text/html", key="_seeding_sheet_download",
    )
    with st.expander("Preview sheets", expanded=False):
        components.html(document, height=950, scrolling=True)
