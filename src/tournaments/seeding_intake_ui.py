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
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from config.settings import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from src.tournaments.reports.render_csv import csv_safe
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_assessment import assess_roster, could_belong
from src.tournaments.seeding_content import DIRECTOR_LEGEND, build_director_cohort, export_fingerprint
from src.tournaments.seeding_pack import (
    analyze_pack,
    available_cohorts,
    cohort_key,
    cohort_label,
    make_pack,
    needs_placement_review,
    pack_matches,
    placement_review_fingerprint,
    prediction_request,
    snapshot_matches_roster,
    snapshot_ratings,
    team_ids_by_row,
    upgrade_pack_analysis,
)
from src.tournaments.seeding_pdf import SeedingPdfError, render_seeding_pdf
from src.tournaments.seeding_predictions import load_seeding_predictions, seeding_predictor_sha256
from src.tournaments.seeding_run_store import PackRecovery, slugify
from src.tournaments.seeding_sheet import CohortSheet, build_cohort_sheets, make_ratings_lookup, render_sheet_html
from src.tournaments.seeding_tiers import DATA_REVIEW, NO_CURRENT_RATING, NOT_FOUND
from src.tournaments.seeding_workbook import build_seeding_workbook, validate_seeding_workbook, workbook_sheet_titles

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
            "" if override.get("not_found") else override.get("team_name") or (item.matched_name if item else "") or "",
            match_method,
            identities.get(str(row.source_index)) or "", row.listed_division, row.requested_flight,
            notes,
            "Draft — review needed" if draft else "",
        ]])
    return stream.getvalue().encode("utf-8-sig")


def invalidate_seeding_exports(state: Any = None) -> None:
    state = st.session_state if state is None else state
    state.pop("_seeding_pdf", None)
    state.pop("_seeding_pdf_hash", None)
    state.pop("_seeding_xlsx", None)
    state.pop("_seeding_xlsx_hash", None)
    state.pop("_seeding_export_fingerprint", None)
    state["_seeding_sheet_html"] = None


def _persist_decisions(save: Callable[[], bool]) -> None:
    st.session_state["_seeding_pack_unsaved"] = not save()


def _offer_interrupted_build(
    recovery: PackRecovery, parsed: ParsedRoster, resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]], pack: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Offer back a finished build that a rerun cut off; return it when the operator restores it.

    The returned pack still has to pass the same export checks as a fresh build
    before it replaces the saved one.
    """
    recovered = recovery.load()
    if recovered is None:
        return None
    saved_at = str((pack or {}).get("generated_at") or "")
    if (
        not snapshot_matches_roster(recovered, parsed.rows, resolved, overrides)
        or str(recovered.get("generated_at") or "") <= saved_at
    ):
        # A pack in memory whose save failed may be this very build, so the
        # file stays until a save lands.
        if not st.session_state.get("_seeding_pack_unsaved"):
            recovery.clear()
        return None
    slot = st.empty()
    with slot.container():
        st.warning("A build finished but was interrupted before it was saved.")
        restore, discard = st.columns(2)
        restoring = restore.button("Restore the interrupted build", key="_seeding_restore_build")
        discarding = discard.button("Discard it", key="_seeding_discard_build")
    if discarding:
        recovery.clear()
        st.rerun()
    if not restoring:
        return None
    slot.empty()
    restored = dict(recovered)
    if isinstance(pack, dict):
        # Notes and reviews saved while the build ran are newer than its copy.
        restored["operator_notes"] = {**recovered.get("operator_notes", {}), **pack.get("operator_notes", {})}
        if isinstance(pack.get("placement_reviews"), dict):
            restored["placement_reviews"] = {**recovered.get("placement_reviews", {}), **pack["placement_reviews"]}
    # A keyed multiselect keeps the browser's value when only its default
    # changes, so the pickers are set outright.
    selection = list(restored["selected_cohorts"])
    st.session_state["_seeding_pack_scope"] = (
        "All imported cohorts" if set(selection) == set(available_cohorts(parsed.rows)) else "Choose cohorts"
    )
    st.session_state["_seeding_pack_cohorts"] = selection
    return restored


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


def _render_director_notes(key: str, pack: dict[str, Any], save: Callable[[], bool]) -> None:
    generation = hashlib.sha256((
        str(pack["generated_at"]) + str(pack.get("operator_notes", {}).get(key))
    ).encode()).hexdigest()[:12]
    notes_key = f"_seeding_cheat_sheet_notes_{key}"
    generation_key = f"{notes_key}_generation"
    if st.session_state.get(generation_key) != generation:
        # Install a newly loaded or saved note before the stable widget is created.
        # A generation in the widget key leaves AppTest and fast browser reruns
        # holding a widget whose state Streamlit has already cleaned up.
        st.session_state[notes_key] = pack.get("operator_notes", {}).get(key, "")
        st.session_state[generation_key] = generation
    with st.form(f"_seeding_cheat_sheet_form_{key}_{generation}"):
        notes = st.text_area(
            "Director notes (included in PDF and Excel)",
            max_chars=1800,
            key=notes_key,
        )
        applied = st.form_submit_button("Save director notes")
    if applied:
        if ILLEGAL_CHARACTERS_RE.search(notes):
            st.error("This note contains an unsupported control character. Remove it before saving.")
            return
        pack.setdefault("operator_notes", {})[key] = notes.strip()
        st.session_state[_PACK_KEY] = pack
        invalidate_seeding_exports()
        _persist_decisions(save)
        st.rerun()


def _render_cohort_review(
    key: str, analysis: Any, pack: dict[str, Any], save: Callable[[], bool],
    roster_rows: Mapping[str, RosterRow], sheet: CohortSheet,
) -> None:
    st.markdown(f"##### {cohort_label(key)}")
    statuses = analysis.placement_status
    seeded = len(analysis.ordered_ids)
    age_group, gender = key.split("|", 1)
    accepted = sum(
        row.section_age_group == age_group and row.section_gender == gender
        for row in roster_rows.values()
    )
    unrated = sum(status in {NOT_FOUND, NO_CURRENT_RATING} for status in statuses.values())
    data_review = sum(status == DATA_REVIEW for status in statuses.values())
    first, second, third, fourth = st.columns(4)
    first.metric("Accepted", accepted)
    second.metric("Seeded", seeded)
    third.metric("Unrated / not found", unrated)
    fourth.metric("Data review", data_review)
    st.caption(DIRECTOR_LEGEND)
    rows = []
    content = build_director_cohort(sheet, pack.get("operator_notes", {}).get(key, ""))
    for observation in analysis.notes:
        st.caption(observation)
    for row in content.rows:
        rows.append({
            "Suggested seed": row.seed,
            "Team": row.team.team_name,
            "PowerScore": row.score,
            "State rank": row.state_rank or "—",
            "Compare evidence": row.observation,
            "Placement status": row.display_status,
            "PitchRank match": row.team.pitchrank_team_name or "",
            "Roster context": " · ".join(row.roster_context),
        })
    if rows:
        st.caption(
            "PowerScore sets the suggested order. Compare flags placements for review; it does not reorder teams yet."
        )
        st.data_editor(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            disabled=list(pd.DataFrame(rows).columns),
            column_config={"PowerScore": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100)},
            key=f"_seeding_cheat_sheet_editor_{key}",
        )
        _render_director_notes(key, pack, save)
    _render_placement_checks(key, analysis, pack, roster_rows, save)
    if data_review:
        st.warning(f"{data_review} team(s) need identity or cohort review before delivery.")


def _render_placement_checks(key, analysis, pack, roster_rows, save) -> None:
    if not analysis.limited_history and not analysis.placement_checks:
        return
    pending = needs_placement_review(pack, key, analysis)
    with st.expander("Placement checks — internal", expanded=pending):
        st.caption(
            "Review these placements using team identity, recent results or club context. "
            "Seed order stays in published order. Add any delivery guidance to Director notes above."
        )
        seed_by_id = {entrant: seed for seed, entrant in enumerate(analysis.ordered_ids, 1)}
        for entrant in analysis.limited_history:
            st.write(f"Seed {seed_by_id[entrant]} · {roster_rows[entrant].registered_name}: limited ranked history.")
        for check in analysis.placement_checks:
            upper = roster_rows[analysis.ordered_ids[check.upper_seed - 1]].registered_name
            lower = roster_rows[analysis.ordered_ids[check.lower_seed - 1]].registered_name
            st.write(
                f"Seed {check.lower_seed} · {lower} is favored by {check.lower_expected_advantage:.1f} expected "
                f"goals against seed {check.upper_seed} · {upper}. Check the placement before delivery."
            )
        if pending:
            st.caption("This pack remains a draft until these placements have been reviewed.")
            if st.button("Mark placement review complete", key=f"_seeding_placement_review_{key}"):
                reviews = pack.get("placement_reviews")
                if not isinstance(reviews, dict):
                    reviews = {}
                pack["placement_reviews"] = {**reviews, key: placement_review_fingerprint(pack, key, analysis)}
                st.session_state[_PACK_KEY] = pack
                invalidate_seeding_exports()
                _persist_decisions(save)
                st.rerun()
        else:
            st.caption("Placement review complete for this evidence and these director notes.")


def _render_analysis_details(selected: Sequence[str], analyses: Mapping, pack: dict[str, Any]) -> None:
    st.caption(
        "Score steps use published scores plus the direction of nearby Compare predictions. "
        f"The separate matchup diagnostics use limits of {pack['policy']['max_expected_margin']:.2f} expected goals "
        f"and {pack['policy']['max_blowout_probability']:.0%} four-goal risk. "
        "Passing these limits does not establish equal strength or interchangeable placement."
        " Placement checks flag lower seeds favored by at least one expected goal; minor reversals stay here."
    )
    for key in selected:
        detail = analyses[tuple(key.split("|", 1))]
        st.markdown(f"**{cohort_label(key)}**")
        for diagnostic in detail.diagnostics:
            st.caption(diagnostic)
        seed_by_id = {entrant: seed for seed, entrant in enumerate(detail.ordered_ids, 1)}
        if seed_by_id:
            st.dataframe(pd.DataFrame([
                {"Seed": seed, "Entrant": entrant} for entrant, seed in seed_by_id.items()
            ]), hide_index=True)
        if detail.boundary_windows:
            st.caption("Evidence for every tested boundary, including windows that did not support a strength break.")
            st.dataframe(pd.DataFrame([{
                "After seed": item.after_seed, "Window size": item.size,
                "Upper seeds": ", ".join(str(seed_by_id[value]) for value in item.upper_ids),
                "Lower seeds": ", ".join(str(seed_by_id[value]) for value in item.lower_ids),
                "Upper favored": item.favored_fraction, "Over limits": item.over_limit_fraction,
                "Average advantage": item.average_expected_margin, "Supports direction": item.supported,
            } for item in detail.boundary_windows]), hide_index=True)
        if detail.close_ranges:
            st.caption("Local ranges within analysis limits. Overlapping ranges do not form a larger group.")
            st.dataframe(pd.DataFrame([{
                "Seeds": f"{item.start_seed}–{item.end_seed}",
                "Largest expected margin": item.max_expected_margin,
                "Largest four-goal risk": item.max_blowout_probability,
            } for item in detail.close_ranges]), hide_index=True)


def _render_export_waiting(message: str) -> None:
    st.info(message)


def render_seeding_pack(
    parsed: ParsedRoster, resolved: Sequence[ResolvedTeam], supabase_client: Any, *,
    event_name: str, save: Callable[[], bool], recovery: PackRecovery | None = None,
    view: str = "all",
) -> None:
    if view not in {"all", "build", "export"}:
        raise ValueError(f"Unknown seeding pack view: {view}")
    if view != "export":
        st.markdown("### 3. Review the seed order" if view == "build" else "### 3. Build and review the seed order")
        st.caption(
            "PowerScore sets the starting order. Compare predictions then flag placements that need your review; "
            "they do not automatically move teams."
        )
    else:
        st.markdown("### 4. Export the director pack")
        st.caption("Check readiness, then download the PDF. Excel and printable HTML are available as backups.")
    if not event_name:
        st.info("Name the event above before preparing its sheets.")
        _render_export_waiting("The next step unlocks after the event is named and a seed order is built.")
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
    restored = (
        _offer_interrupted_build(recovery, parsed, resolved, overrides, pack)
        if view != "export" and recovery
        else None
    )
    choices = available_cohorts(parsed.rows)
    selected = (
        _selected_cohorts(parsed, restored or pack)
        if view != "export"
        else [key for key in (pack or {}).get("selected_cohorts", []) if key in choices]
    )
    selected_rows = [row for row in parsed.rows if cohort_key(row.section_age_group, row.section_gender) in selected]
    st.caption(
        f"Selected: {len(selected)} cohort(s), {len(selected_rows)} accepted teams. "
        "Unmatched teams stay in the pack."
    )
    if not selected:
        _render_export_waiting(
            "Select at least one tournament cohort, then build the seed order."
            if view != "export"
            else "Go back to step 3 and build a seed order before exporting."
        )
        return
    if pack and view != "export":
        st.caption("Rebuilding reads fresh data while preserving director notes and roster decisions.")

    pending_replacement = restored is not None
    pending_upgrade = False
    if restored is not None:
        pack = restored
    if view != "export" and st.button("Build seeding sheets", type="primary", key="_seeding_build_tiers"):
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
                    # Every cohort's notes and reviews carry forward, selected or not;
                    # a review only counts while its fingerprint still matches.
                    candidate["operator_notes"] = dict(pack.get("operator_notes", {}))
                    if isinstance(pack.get("placement_reviews"), dict):
                        candidate["placement_reviews"] = dict(pack["placement_reviews"])
                    candidate["legacy_manual_groups"] = dict(
                        pack.get("legacy_manual_groups", pack.get("manual_groups", {}))
                    )
                analyze_pack(candidate, parsed.rows, resolved, overrides)
                # A click during the build reruns the script before the pack reaches
                # session state, so the file is written before anything can yield.
                if recovery is not None:
                    recovery.write(candidate)
                pack = candidate
                pending_replacement = True
        except Exception as exc:
            # No new snapshot or export is published until all input checks pass.
            message = str(exc).replace(str(SUPABASE_SERVICE_ROLE_KEY or "__no_secret__"), "[redacted]")
            st.error(f"Could not build seeding sheets: {message}")

    if isinstance(pack, dict) and pack.get("schema_version") == 3 and pack.get("analysis_schema_version") in (1, 2):
        try:
            pack = upgrade_pack_analysis(
                pack, parsed.rows, resolved, overrides, selected, predictor_sha256=seeding_predictor_sha256(),
            )
            pending_replacement = pending_upgrade = True
        except (ValueError, TypeError, KeyError) as exc:
            invalidate_seeding_exports()
            st.info(f"The saved pack needs a fresh build: {exc}")
            _render_export_waiting("Rebuild the seed order before exporting.")
            return

    current_pack = pack_matches(pack, parsed.rows, resolved, overrides, selected)
    analyses = {}
    analysis_error = None
    if current_pack:
        try:
            analyses = analyze_pack(pack, parsed.rows, resolved, overrides)
        except (ValueError, TypeError, KeyError) as exc:
            analysis_error = exc
    metadata = st.session_state.get("_seeding_assessment") or {}
    assessment = assess_roster(parsed, resolved, overrides, coverage=metadata.get("coverage", "unknown"),
                               completed=metadata.get("completed"))
    selected_indices = {row.source_index for row in selected_rows}
    uncertain = [row for row in parsed.rows if row.source_index in assessment.cohort_review]
    pending_reviews = [
        "|".join(key) for key, analysis in analyses.items()
        if needs_placement_review(pack, "|".join(key), analysis)
    ]
    has_data_review = any(
        status == DATA_REVIEW
        for analysis in analyses.values() for status in analysis.placement_status.values()
    )
    draft = metadata.get("coverage") != "complete" or bool(assessment.attention & selected_indices) or any(
        could_belong(row, *key.split("|", 1)) for row in uncertain for key in selected
    ) or analysis_error is not None or has_data_review or bool(pending_reviews)
    if draft and view != "export":
        st.info("Delivery status: draft. Complete roster and placement checks before sending.")
        if pending_reviews:
            st.caption("Placement review pending: " + ", ".join(cohort_label(key) for key in pending_reviews))
    elif view != "export":
        st.caption("Delivery status: roster assessed. Review seed order and director notes before sending.")
    if view != "export":
        with st.expander("Internal roster CSV (optional)", expanded=False):
            st.caption("This is a review file, not the director pack.")
            st.download_button(
                "Download all selected teams as CSV", team_csv(selected_rows, resolved, overrides, draft=draft),
                file_name=f"{slugify(event_name)}-teams.csv", mime="text/csv", key="_seeding_all_teams_csv",
            )
    if not current_pack:
        invalidate_seeding_exports()
        if pack:
            st.info("The selected cohorts or team matches changed. Build seeding sheets to update this pack.")
        _render_export_waiting("Build the seed order in step 3 before exporting.")
        return
    if pack.get("predictor_sha256") != seeding_predictor_sha256():
        invalidate_seeding_exports()
        st.info("The predictor has been updated since this pack was built. After rankings finish, "
                "click Build seeding sheets to refresh predictions. Your team matches and tournament "
                "age assignments are saved.")
        _render_export_waiting("Rebuild the seed order with the current predictor before exporting.")
        return
    if analysis_error is not None:
        invalidate_seeding_exports()
        st.error(f"This pack needs rebuilding: {analysis_error}")
        _render_export_waiting("Rebuild the seed order before exporting.")
        return
    st.caption(f"Saved prediction snapshot: {pack['generated_at']} · "
               f"Ratings as of {pack.get('ratings_as_of') or 'unknown'}")
    identities = team_ids_by_row(parsed.rows, resolved, overrides)
    title = f"{event_name} · DRAFT — review needed" if draft else event_name
    notes = {tuple(key.split("|", 1)): value for key, value in pack.get("operator_notes", {}).items()}
    try:
        sheets = build_cohort_sheets(
            selected_rows, resolved, overrides, snapshot_ratings(pack, identities), tier_analyses=analyses,
        )
        document = render_sheet_html(
            title, sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
            operator_notes=notes,
        )
        workbook = build_seeding_workbook(
            title, sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
            operator_notes=notes,
        )
        validate_seeding_workbook(workbook, workbook_sheet_titles(sheets))
        content_hash = export_fingerprint(
            title, sheets, generated_on=pack["generated_at"][:10], ranking_run=pack.get("ratings_as_of") or "unknown",
            operator_notes=notes, analysis_version=pack["analysis_schema_version"], policy=pack["policy"],
        )
    except Exception as exc:
        invalidate_seeding_exports()
        st.error(f"Could not prepare the director sheets. Your previous saved pack is preserved: {exc}")
        if pending_replacement and recovery is not None:
            # The failed build gives up the slot: to a pack still waiting on a failed save, or to nothing.
            waiting = st.session_state.get(_PACK_KEY)
            if st.session_state.get("_seeding_pack_unsaved") and isinstance(waiting, dict):
                recovery.write(waiting)
            else:
                recovery.clear()
        saved_pack = st.session_state.get(_PACK_KEY)
        if isinstance(saved_pack, dict):
            for key in selected:
                if key in saved_pack.get("selected_cohorts", []):
                    st.markdown(f"##### {cohort_label(key)}")
                    _render_director_notes(key, saved_pack, save)
        _render_export_waiting("Fix the sheet error and rebuild the seed order before exporting.")
        return
    if pending_replacement:
        # Marked unsaved first, so a rerun between here and the save leaves the
        # retry banner and the recovery file in place.
        st.session_state["_seeding_pack_unsaved"] = True
        st.session_state[_PACK_KEY] = pack
        invalidate_seeding_exports()
        _persist_decisions(save)
        if recovery is not None and not st.session_state.get("_seeding_pack_unsaved"):
            recovery.clear()
        if pending_upgrade:
            st.caption("Sheet guidance updated using saved predictions. Team choices and director notes are preserved.")
    if st.session_state.get("_seeding_export_fingerprint") != content_hash:
        invalidate_seeding_exports()
    # The document hash also invalidates a cached PDF when its layout changes.
    document_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
    if st.session_state.get("_seeding_pdf_hash") != document_hash:
        st.session_state.pop("_seeding_pdf", None)
    st.session_state._seeding_sheet_html = document
    st.session_state["_seeding_xlsx"] = workbook
    st.session_state["_seeding_xlsx_hash"] = content_hash
    st.session_state["_seeding_export_fingerprint"] = content_hash
    if view != "export":
        with st.expander("Review seed order and director notes", expanded=True):
            roster_rows = {str(row.source_index): row for row in parsed.rows}
            by_cohort = {cohort_key(sheet.age_group, sheet.gender): sheet for sheet in sheets}
            for key in selected:
                _render_cohort_review(
                    key, analyses[tuple(key.split("|", 1))], pack, save, roster_rows, by_cohort[key]
                )
        with st.expander("Analysis details", expanded=False):
            _render_analysis_details(selected, analyses, pack)
        if view == "build":
            return

    if view == "all":
        st.markdown("### 4. Export the director pack")
        st.caption("PDF is the normal handoff; Excel and printable HTML are available as backups.")

    st.markdown("#### Readiness")
    match_ready = not bool(assessment.attention & selected_indices)
    coverage_ready = metadata.get("coverage") == "complete"
    placement_ready = not pending_reviews and not has_data_review
    readiness = [
        ("Accepted-team roster confirmed", coverage_ready, "Confirm the complete roster in step 2."),
        ("Match decisions complete", match_ready, "Resolve the remaining teams in step 2."),
        ("PowerScore and Compare snapshot current", True, "Rebuild the seed order in step 3."),
        ("Placement checks complete", placement_ready, "Review flagged placements in step 3."),
    ]
    for label, ready, action in readiness:
        st.markdown(f"{'✅' if ready else '⚠️'} **{label}**" + ("" if ready else f" — {action}"))
    st.caption("Director notes are optional and can be edited in step 3.")
    if view == "export":
        with st.expander("Advanced downloads", expanded=False):
            st.caption("The CSV is an internal review file, not the director pack.")
            st.download_button(
                "Download all selected teams as CSV", team_csv(selected_rows, resolved, overrides, draft=draft),
                file_name=f"{slugify(event_name)}-teams.csv", mime="text/csv", key="_seeding_all_teams_csv",
            )
    if draft:
        st.warning(
            "These files are marked DRAFT. They are safe to inspect, but finish the remaining roster or "
            "placement checks before sending them to the tournament director."
        )
    else:
        st.success("The reviewed director pack is ready to export.")
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
