"""Compact quote assessment and one-registration-at-a-time operator review."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.tournaments.reports.render_csv import csv_safe
from src.tournaments.roster_paste import split_roster_markers
from src.tournaments.seeding_assessment import assess_roster, corrected_identities, effective_roster
from src.tournaments.seeding_intake_ui import invalidate_seeding_exports


def assessment_for(parsed, resolved, overrides):
    metadata = st.session_state.get("_seeding_assessment", {})
    return assess_roster(parsed, resolved, overrides, coverage=metadata.get("coverage", "unknown"),
                         completed=metadata.get("completed"))


def render_assessment(parsed, resolved, overrides):
    assessment = assessment_for(parsed, resolved, overrides)
    columns = st.columns(3)
    total = str(assessment.total)
    if assessment.possible_total != assessment.total:
        total += f"–{assessment.possible_total}"
    columns[0].metric("Total U10+ teams", total, help=(
        "All imported U10+ teams count toward the quote, whether matched or not. "
        "A range means some entries still need their age or input clarified."
    ))
    if assessment.possible_total != assessment.total:
        st.caption(f"{assessment.total} confirmed U10+ teams; up to {assessment.possible_total} after input review.")
    columns[1].metric("Matched", assessment.matched, help=(
        "Teams linked to a PitchRank team. Some may still need their tournament age or cohort clarified."
    ))
    columns[2].metric("Manual matches needed", len(assessment.manual), help=(
        "Teams whose PitchRank match needs your review. Includes teams that also have cohort or input questions. "
        "Unfinished automatic lookups are counted separately."
    ))
    cohort_only = len(assessment.cohort_review - assessment.manual - assessment.pending)
    left, right = st.columns(2)
    left.metric("Additional cohort / input fixes", cohort_only, help=(
        f"{len(assessment.cohort_review)} teams have cohort or input questions in total. "
        "This number counts only additional, already-matched teams. The others are already counted "
        "under Manual matches needed or Awaiting lookup."
    ))
    right.metric("Suggested event price", assessment.price)
    summary = [f"{len(assessment.manual)} need matching", f"{cohort_only} more need cohort/input fixes"]
    if assessment.pending:
        summary.append(f"{len(assessment.pending)} awaiting lookup")
    summary.append(f"{len(assessment.attention)} teams total to review")
    st.caption(" · ".join(summary) + ".")
    st.caption(f"Manual matches applied: {sum(row.source_index in overrides for row in parsed.rows)} · "
               f"Younger teams excluded: {assessment.excluded}")
    if assessment.provisional:
        st.info("Provisional quote: confirm the full U10+ roster and resolve cohort or input questions. "
                "The count covers imported entries; an incomplete import may contain more teams.")
    else:
        st.success("Quote ready. Price includes every U10+ team, including unmatched and unranked teams.")
    if assessment.pending:
        st.caption("Unfinished lookups are separate from manual work. Retry matching to finish the assessment.")
    if assessment.cohorts:
        st.dataframe(pd.DataFrame(assessment.cohorts).drop(columns="key"), hide_index=True, width="stretch")
    ready = [cohort for cohort in assessment.cohorts if cohort["Status"] == "Ready"]
    if ready:
        st.success("Ready cohorts: " + " · ".join(cohort["Cohort"] for cohort in ready))
        choice = st.selectbox("Free sample cohort", options=[row["key"] for row in ready],
                              format_func=lambda key: next(row["Cohort"] for row in ready if row["key"] == key))
        if st.button("Prepare this free sample", key="_seeding_sample"):
            st.session_state["_seeding_pack_scope"] = "Choose cohorts"
            st.session_state["_seeding_pack_cohorts"] = [choice]
            invalidate_seeding_exports()
    else:
        st.caption("No cohort is ready yet. Confirm complete coverage, assign cohorts and match every team.")
    return assessment


def render_review(raw, resolved, overrides, frame, render_override, save):
    decisions = dict(st.session_state.get("_seeding_cohort_decisions", {}))
    before = effective_roster(raw, decisions, include_excluded=True)
    parsed = effective_roster(raw, decisions)
    assessment = assessment_for(parsed, resolved, overrides)
    st.markdown("#### Review teams")
    left, right = st.columns(2)
    issue = left.selectbox(
        "Show", ["Needs attention", "Manual matches", "Cohort / input questions", "Awaiting lookup", "All teams"]
    )
    cohort = right.selectbox("Filter cohort", ["All cohorts", *dict.fromkeys(frame["Cohort"].tolist())])
    sets = {"Needs attention": assessment.attention, "Manual matches": assessment.manual,
            "Cohort / input questions": assessment.cohort_review, "Awaiting lookup": assessment.pending}
    indices = sets.get(issue, {row.source_index for row in parsed.rows})
    filtered = frame[frame["#"].isin([index + 1 for index in indices])]
    if cohort != "All cohorts":
        filtered = filtered[filtered["Cohort"] == cohort]
    st.dataframe(filtered, hide_index=True, width="stretch")
    if not filtered.empty:
        st.download_button("Download filtered review as CSV",
                           data=filtered.apply(lambda column: column.map(csv_safe)).to_csv(index=False).encode("utf-8"),
                           file_name="seeding-review.csv", mime="text/csv", help=(
                               "Downloads only the rows shown by your current review and cohort filters. "
                               "An internal work list you can open in Excel, not the director's finished workbook."
                           ))
    choices = [int(number) - 1 for number in filtered["#"]]
    rows = {row.source_index: row for row in parsed.rows}
    if choices:
        index = st.selectbox("Team to review", choices,
                             format_func=lambda value: f"{value + 1}. {rows[value].team_name_raw}")
        row = rows[index]
        outcomes = {item.source_index: item for item in resolved}
        render_override(row, outcomes[index])
        with st.expander("Correct cohort or input", expanded=index in assessment.cohort_review):
            if row.intake_issue:
                st.info(row.intake_issue)
            name = st.text_input("Submitted team name", value=row.team_name_raw, key=f"_seed_name_{index}")
            ages = ["Unassigned", *[f"u{age}" for age in range(7, 20)]]
            age = st.selectbox("Tournament age group", ages,
                               index=ages.index(row.section_age_group) if row.section_age_group in ages else 0,
                               key=f"_seed_age_{index}")
            genders = ["Unassigned", "Male", "Female"]
            gender = st.selectbox("Tournament gender", genders,
                                  index=genders.index(row.section_gender) if row.section_gender in genders else 0,
                                  key=f"_seed_gender_{index}")
            exclude = st.checkbox("Exclude this entry: it is not an accepted team", key=f"_seed_exclude_{index}")
            bulk = bool(row.listed_division) and st.checkbox(
                "Apply age and gender to every team in this listed division", key=f"_seed_bulk_{index}")
            if st.button("Apply correction", key=f"_seed_apply_{index}"):
                if not exclude and not name.strip():
                    st.error("Enter a team name or exclude the entry.")
                    return
                targets = [candidate for candidate in parsed.rows if candidate.source_index == index or
                           (bulk and candidate.listed_division == row.listed_division)]
                for candidate in targets:
                    decision = dict(decisions.get(candidate.source_index, {}))
                    decision.update(section_age_group="" if age == "Unassigned" else "u19" if age == "u18" else age,
                                    section_gender="" if gender == "Unassigned" else gender)
                    if candidate.source_index == index:
                        stripped, star, suffix = split_roster_markers(name)
                        decision.update(team_name_raw=name.strip(), team_name_stripped=stripped,
                                        has_star_marker=star, has_c_marker=suffix, intake_issue="", exclude=exclude)
                    decisions[candidate.source_index] = decision
                updated, manual, reset = corrected_identities(
                    before, effective_roster(raw, decisions, include_excluded=True), resolved, overrides
                )
                metadata = dict(st.session_state.get("_seeding_assessment", {}))
                changed = {candidate.source_index for candidate in targets} | reset
                metadata["completed"] = [value for value in metadata.get("completed", []) if value not in changed]
                st.session_state["_seeding_review_update"] = {
                    "raw": raw, "resolved": updated, "overrides": manual,
                    "decisions": decisions, "metadata": metadata,
                }
                st.rerun()
    excluded = [row for row in raw.rows if decisions.get(row.source_index, {}).get("exclude")]
    if excluded:
        with st.expander(f"Excluded entries ({len(excluded)})"):
            restore = st.selectbox("Entry to restore", [row.source_index for row in excluded],
                                   format_func=lambda index: next(
                                       row.team_name_raw for row in excluded if row.source_index == index))
            if st.button("Restore entry"):
                decisions[restore]["exclude"] = False
                st.session_state["_seeding_review_update"] = {
                    "raw": raw, "resolved": resolved, "overrides": overrides,
                    "decisions": decisions, "metadata": dict(st.session_state.get("_seeding_assessment", {})),
                }
                st.rerun()
