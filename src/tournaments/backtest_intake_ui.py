"""Backtest-only event totals, structure inspection and editable team matches."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, replace
from typing import Any

import pandas as pd
import streamlit as st

from src.tournaments.backtest_event_rollup import build_event_rollup, event_rollup_export
from src.tournaments.backtest_historical_preflight import (
    HistoricalPreflightUnavailable,
    load_historical_preflight,
    preflight_input_sha256,
    run_historical_preflight,
    write_historical_preflight,
)
from src.tournaments.backtest_intake_state import (
    BacktestSnapshot,
    CaptureVerification,
    CohortDecision,
    DivisionReview,
    assert_capture_preserved,
    effective_roster,
    entrant_key,
    read_snapshot,
    reviews_for_capture,
    structure_hash,
    tournament_totals,
    write_snapshot,
)
from src.tournaments.backtest_link_store import (
    CollisionAcknowledgement,
    EventLinks,
    TeamLink,
    link_decision_state,
    load_links,
    update_links,
)
from src.tournaments.backtest_reviewed_report import (
    model_comparison_rows,
    movement_rows,
    observed_result_values,
)
from src.tournaments.backtest_reviewed_run import (
    ReviewedCohortReadiness,
    build_reviewed_cohort_readiness,
    capture_verification_blockers,
    default_model_artifact,
    execute_reviewed_run,
    list_failed_reviewed_runs,
    list_reviewed_runs,
    load_reviewed_run,
    model_artifact_sha256,
    resolve_model_artifact,
    reviewed_run_export,
)
from src.tournaments.gotsport_event_structure import summarize_structure_quality
from src.tournaments.roster_resolver import make_team_details_lookup, resolve_manual_reference
from src.tournaments.storage._io import utc_now_iso
from src.tournaments.storage.event_key import existing_event_key


def _pool_labels(team: Any, division: Any) -> list[str]:
    if division is None:
        return []
    if team.registration_id:
        return [pool.label for pool in division.pools
                if any(member.registration_id == team.registration_id for member in pool.members)]
    source_key = getattr(team, "source_entry_key", "")
    return [pool.label for index, pool in enumerate(division.pools)
            if any(not member.registration_id
                   and source_key == f"pool:{division.group_id}:{pool.pool_id or index}:{member.standings_position}"
                   for member in pool.members)]


def match_table(
    snapshot: BacktestSnapshot,
    links: EventLinks,
    details: dict[str, dict],
    *,
    conflicts: dict[str, tuple[str, ...]] | None = None,
) -> list[dict]:
    """Every event entrant appears, including unmatched and manually cleared rows."""
    by_registration = {link.registration_id: link for link in links.links}
    by_index = {outcome.source_index: outcome for outcome in snapshot.resolved}
    divisions = {division.group_id: division for division in snapshot.roster.divisions}
    removed = set(links.removed_registration_ids)
    not_found = set(links.not_found_registration_ids)
    conflicts = conflicts or {}
    collisions = _canonical_collisions(links)
    rows = []
    for team in snapshot.roster.teams:
        match_key = entrant_key(team)
        link = by_registration.get(match_key)
        team_id = link.team_id_master if link and match_key not in removed else ""
        canonical = details.get(team_id, {})
        division = divisions.get(team.group_id)
        pools = _pool_labels(team, division)
        outcome = by_index[team.source_index]
        confirmed_method = link is not None and link.matched_by in {"gotsport_id", "operator"}
        status = "Matched" if team_id and canonical and confirmed_method else "Needs review"
        if match_key in removed:
            status = "Match cleared"
        elif match_key in not_found:
            status = "Not found"
        elif team_id and not canonical:
            status = "Linked team unavailable"
        conflict = conflicts.get(match_key, ())
        if conflict and match_key not in removed and (link is None or link.matched_by != "operator"):
            status = "Needs review"
        source_changed = bool(link and not team.registration_id
                              and (not team.team_name.strip() or link.event_team_name != team.team_name))
        if source_changed and match_key not in removed:
            status = "Needs review"
        issues = ["Conflicting provider matches: " + ", ".join(conflict)] if conflict else []
        if match_key in collisions:
            status = "Needs review"
            issues.append("This PitchRank team is also linked to: " + ", ".join(collisions[match_key]))
        if source_changed:
            issues.append(f"This source position previously held {link.event_team_name!r}; "
                          "its saved match needs identity confirmation for the current team.")
        rows.append({
            "Event team": team.team_name,
            "Division": team.division_label,
            "Tournament cohort": (division.age_group if division else getattr(team, "published_age_group", "")).upper(),
            "Gender": division.gender if division else team.gender,
            "Pools": ", ".join(pools),
            "Registration ID": team.registration_id,
            "Match key": match_key,
            "GotSport team ID": team.provider_team_id or "",
            "PitchRank team": canonical.get("team_name", ""),
            "PitchRank ID": team_id,
            "Match method": link.matched_by if team_id else outcome.status,
            "Status": status,
            "Match issue": " ".join(issues),
            "source_index": team.source_index,
        })
    return rows


def _canonical_collisions(links: EventLinks) -> dict[str, tuple[str, ...]]:
    """Map each distinct entrant in an unacknowledged reverse collision to its peers."""
    excluded = set(links.removed_registration_ids) | set(links.not_found_registration_ids)
    by_team: dict[str, set[str]] = {}
    for link in links.links:
        if link.registration_id not in excluded:
            by_team.setdefault(link.team_id_master, set()).add(link.registration_id)
    acknowledged = {
        (item.team_id_master, tuple(sorted(item.registration_ids)))
        for item in links.collision_acknowledgements
    }
    collisions: dict[str, tuple[str, ...]] = {}
    for team_id, registrations in by_team.items():
        members = tuple(sorted(registrations))
        if len(members) < 2 or (team_id, members) in acknowledged:
            continue
        for registration in members:
            collisions[registration] = tuple(item for item in members if item != registration)
    return collisions


def _details(client: Any, team_ids: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    ids = sorted(set(team_ids))
    for offset in range(0, len(ids), 100):
        batch = client.table("teams").select(
            "team_id_master,team_name,club_name,age_group,gender,state_code,is_deprecated"
        ).in_("team_id_master", ids[offset:offset + 100]).execute().data or []
        for row in batch:
            if not row.get("is_deprecated"):
                rows[str(row["team_id_master"])] = row
    return rows


def search_master_teams(
    client: Any, *, name: str = "", club: str = "", page: int = 0, page_size: int = 20
) -> list[dict[str, Any]]:
    """Read-only, paginated historical-team search without an age restriction."""
    name, club = name.strip(), club.strip()
    if not name and not club:
        return []
    query = client.table("teams").select(
        "team_id_master,team_name,club_name,age_group,gender,state_code,is_deprecated"
    ).eq("is_deprecated", False)
    if name:
        query = query.ilike("team_name", f"%{name}%")
    if club:
        query = query.ilike("club_name", f"%{club}%")
    start = max(page, 0) * page_size
    return query.range(start, start + page_size - 1).execute().data or []


def _sync_matches(snapshot: BacktestSnapshot, client: Any, base_dir) -> tuple[EventLinks, dict, dict]:
    from tournament_intake import _merge_map_loaded, _seeding_merge_resolver

    event_id = snapshot.roster.event_id
    key = existing_event_key("gotsport", event_id, base_dir=base_dir)
    teams = {team.source_index: team for team in snapshot.roster.teams}
    resolver = _seeding_merge_resolver(client)
    if not _merge_map_loaded(resolver):
        raise ValueError("Team merge information could not be loaded; retry team matching")
    by_entrant: dict[str, dict[str, TeamLink]] = {}
    for outcome in snapshot.resolved:
        # Name-only matches on a historical roster are suggestions until the
        # operator confirms identity; older saved walks get the same treatment.
        if outcome.status != "gotsport_id" or not outcome.team_id_master:
            continue
        team = teams[outcome.source_index]
        canonical_id = resolver.resolve(outcome.team_id_master) or outcome.team_id_master
        by_entrant.setdefault(entrant_key(team), {}).setdefault(canonical_id, TeamLink(
            entrant_key(team), team.team_name,
            canonical_id,
            outcome.status, utc_now_iso(),
        ))
    conflicts = {key: tuple(sorted(matches)) for key, matches in by_entrant.items() if len(matches) > 1}
    automatic = [next(iter(matches.values())) for matches in by_entrant.values() if len(matches) == 1]
    links = update_links(key, event_id=event_id, changed_links=automatic, base_dir=base_dir)
    canonical_links = tuple(replace(link, team_id_master=resolver.resolve(link.team_id_master) or link.team_id_master)
                            for link in links.links)
    canonical_acknowledgements = tuple(
        replace(item, team_id_master=resolver.resolve(item.team_id_master) or item.team_id_master)
        for item in links.collision_acknowledgements
    )
    links = replace(
        links,
        links=canonical_links,
        collision_acknowledgements=canonical_acknowledgements,
    )
    return links, _details(client, [link.team_id_master for link in links.links]), conflicts


def _load_saved(base_dir) -> None:
    from tournament_intake import _BACKTEST_KEYS

    paths = sorted(base_dir.glob("gotsport__*/intake/event_intake.json"))
    if not paths:
        return
    with st.expander("Open a saved Backtest event", expanded=False):
        keys = [path.parent.parent.name for path in paths]
        labels = {}
        for key in keys:
            try:
                saved = read_snapshot(key, base_dir=base_dir)
                dates = saved.roster.event_start_date or "date not stated"
                labels[key] = f"{saved.roster.event_name or key} · {dates}"
            except Exception:
                labels[key] = key
        selected = st.selectbox(
            "Saved event", keys, format_func=lambda key: labels[key], key="_backtest_saved_event"
        )
        if st.button("Open saved intake", key="_backtest_open_saved"):
            try:
                snapshot = read_snapshot(selected, base_dir=base_dir)
            except Exception as exc:
                st.error(f"Could not open this saved intake: {exc}")
                return
            # This is the only object the Backtest results and save path read.
            st.session_state[_BACKTEST_KEYS.snapshot] = snapshot
            st.session_state[f"bt_review_drafts_{snapshot.generation}"] = {
                review.group_id: asdict(review) for review in reviews_for_capture(snapshot.roster, snapshot.reviews)
            }
            st.session_state[f"bt_cohort_drafts_{snapshot.generation}"] = {
                decision.group_id: asdict(decision) for decision in snapshot.cohort_decisions
            }
            # Fresh widget identities discard a stale session's rejected edits.
            epoch_key = f"bt_review_epoch_{snapshot.generation}"
            st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1
            st.rerun()


def _restore_review_baseline(snapshot: BacktestSnapshot, base_dir) -> BacktestSnapshot:
    """Load prior operator work once per new capture, before rendering editors."""
    from tournament_intake import _BACKTEST_KEYS

    loaded_key = f"bt_reviews_loaded_{snapshot.generation}"
    if st.session_state.get(loaded_key):
        return snapshot
    if not snapshot.reviews or not snapshot.cohort_decisions:
        key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
        try:
            saved = read_snapshot(key, base_dir=base_dir)
        except FileNotFoundError:
            pass
        except Exception as exc:
            st.warning(f"Saved division reviews could not be loaded: {exc}")
        else:
            valid_groups = {division.group_id for division in snapshot.roster.divisions}
            snapshot = replace(
                snapshot,
                reviews=(snapshot.reviews or reviews_for_capture(snapshot.roster, saved.reviews)),
                cohort_decisions=(
                    snapshot.cohort_decisions
                    or tuple(
                        decision for decision in saved.cohort_decisions
                        if decision.group_id in valid_groups
                    )
                ),
            )
            st.session_state[_BACKTEST_KEYS.snapshot] = snapshot
    # Even absence is a baseline. Reading again on every rerender could turn
    # another session's new notes into the baseline for our already-open form.
    st.session_state[loaded_key] = True
    return snapshot


def _render_match_editor(
    snapshot: BacktestSnapshot,
    rows: list[dict],
    links: EventLinks,
    client: Any,
    base_dir,
) -> None:
    from tournament_intake import _as_plain_text, _seeding_provider_id_lookup

    if not rows:
        return
    generation = snapshot.generation
    mode = st.radio("Show teams", ("Needs review", "All teams"), horizontal=True, key=f"bt_filter_{generation}")
    candidates = rows if mode == "All teams" else [row for row in rows if row["Status"] != "Matched"]
    filters = st.columns(4)
    division = filters[0].selectbox(
        "Division", ("All",) + tuple(sorted({row["Division"] for row in candidates})),
        key=f"bt_team_division_{generation}",
    )
    cohort = filters[1].selectbox(
        "Cohort", ("All",) + tuple(sorted({row["Tournament cohort"] or "Not stated" for row in candidates})),
        key=f"bt_team_cohort_{generation}",
    )
    gender = filters[2].selectbox(
        "Gender", ("All",) + tuple(sorted({row["Gender"] or "Not stated" for row in candidates})),
        key=f"bt_team_gender_{generation}",
    )
    issue = filters[3].selectbox(
        "Issue", ("All",) + tuple(sorted({row["Status"] for row in candidates})),
        key=f"bt_team_issue_{generation}",
    )
    visible = [row for row in candidates if (
        (division == "All" or row["Division"] == division)
        and (cohort == "All" or (row["Tournament cohort"] or "Not stated") == cohort)
        and (gender == "All" or (row["Gender"] or "Not stated") == gender)
        and (issue == "All" or row["Status"] == issue)
    )]
    st.dataframe(
        pd.DataFrame(visible).drop(columns=["source_index", "Match key"], errors="ignore"),
        hide_index=True, width="stretch"
    )
    if not visible:
        st.success("No teams match these filters.")
        return
    by_index = {row["source_index"]: row for row in visible}
    selected = st.selectbox(
        "Inspect or change a team match", list(by_index),
        format_func=lambda index: f"{by_index[index]['Event team']} — {by_index[index]['Division']}",
        key=f"bt_selected_{generation}_{mode}",
    )
    display = by_index[selected]
    row = next(row for row in snapshot.parsed.rows if row.source_index == selected)
    outcome = next(item for item in snapshot.resolved if item.source_index == selected)
    event_key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
    registration = display["Match key"]
    saved_links = load_links(event_key, base_dir=base_dir)
    expected_key = f"bt_link_expected_{generation}_{registration}"
    if expected_key not in st.session_state:
        st.session_state[expected_key] = link_decision_state(saved_links, registration)
    expected_state = st.session_state[expected_key]

    def rerun_after_link_change() -> None:
        st.session_state.pop(expected_key, None)
        st.rerun()

    st.caption(_as_plain_text(f"Entered in: {display['Division']} · Registration {registration}"))
    if display["Match issue"]:
        st.warning(_as_plain_text(display["Match issue"]))
    collision_peers = _canonical_collisions(links).get(registration, ())
    if collision_peers and display["PitchRank ID"]:
        collision_note = st.text_input(
            "Why do these registrations represent the same squad?",
            key=f"bt_collision_note_{generation}_{selected}",
        )
        if st.button(
            "Confirm intentional duplicate entry",
            disabled=not collision_note.strip(),
            key=f"bt_collision_ack_{generation}_{selected}",
        ):
            acknowledgement = CollisionAcknowledgement(
                team_id_master=display["PitchRank ID"],
                registration_ids=tuple(sorted((registration, *collision_peers))),
                note=collision_note.strip(),
                acknowledged_at=utc_now_iso(),
            )
            update_links(
                event_key, event_id=snapshot.roster.event_id,
                collision_acknowledgements=(acknowledgement,), base_dir=base_dir,
            )
            st.rerun()
    if display["PitchRank ID"]:
        label = "Current match" if display["Status"] == "Matched" else "Saved suggestion"
        st.write(f"{label}: {display['PitchRank team']} ({display['PitchRank ID']})")
        if st.button("Clear this match", key=f"bt_clear_{generation}_{selected}"):
            try:
                update_links(event_key, event_id=snapshot.roster.event_id,
                             removed_registration_ids=(registration,),
                             expected_links={registration: expected_state},
                             base_dir=base_dir)
            except Exception as exc:
                st.error(f"The match was not cleared: {exc}")
            else:
                rerun_after_link_change()

    if display["Status"] == "Not found":
        st.info("Reviewed and marked as not found in PitchRank. The entrant and its results are preserved.")
        if st.button("Reopen review", key=f"bt_reopen_{generation}_{selected}"):
            update_links(event_key, event_id=snapshot.roster.event_id,
                         reopened_registration_ids=(registration,),
                         expected_links={registration: expected_state},
                         base_dir=base_dir)
            rerun_after_link_change()

    if outcome.candidates:
        st.caption("Suggested candidates — confirm the squad before choosing one.")
        st.dataframe(pd.DataFrame(list(outcome.candidates)), hide_index=True, width="stretch")
    with st.form(f"bt_search_{generation}_{selected}"):
        search_columns = st.columns(2)
        name_query = search_columns[0].text_input("Search PitchRank team name", value=display["Event team"])
        club_query = search_columns[1].text_input("Club contains")
        search_submitted = st.form_submit_button("Search PitchRank")
    search_key = f"bt_search_results_{generation}_{selected}"
    page_key = f"bt_search_page_{generation}_{selected}"
    params_key = f"bt_search_params_{generation}_{selected}"
    if search_submitted:
        st.session_state[page_key] = 0
        st.session_state[params_key] = (name_query, club_query)
        try:
            st.session_state[search_key] = search_master_teams(client, name=name_query, club=club_query)
        except Exception as exc:
            st.warning(f"PitchRank search is unavailable: {exc}")
            st.session_state[search_key] = []
    search_results = st.session_state.get(search_key, [])
    if search_results:
        st.dataframe(pd.DataFrame(search_results).drop(columns=["is_deprecated"], errors="ignore"),
                     hide_index=True, width="stretch")
        chosen = st.selectbox(
            "Search result", range(len(search_results)),
            format_func=lambda index: (
                f"{search_results[index].get('team_name', '')} · "
                f"{search_results[index].get('club_name', '')} · "
                f"{search_results[index].get('age_group', '')}"
            ), key=f"bt_search_choice_{generation}_{selected}",
        )
        if st.button("Use selected PitchRank team", key=f"bt_search_use_{generation}_{selected}"):
            chosen_id = str(search_results[chosen]["team_id_master"])
            update_links(
                event_key, event_id=snapshot.roster.event_id,
                changed_links=(TeamLink(registration, row.team_name_raw, chosen_id, "operator", utc_now_iso()),),
                expected_links={registration: expected_state}, base_dir=base_dir,
            )
            rerun_after_link_change()
        previous, page_label, following = st.columns([1, 2, 1])
        page = st.session_state.get(page_key, 0)
        page_label.caption(f"Search page {page + 1}")
        move = 0
        if previous.button("Previous", disabled=page == 0, key=f"bt_search_previous_{generation}_{selected}"):
            move = -1
        if following.button(
            "Next", disabled=len(search_results) < 20, key=f"bt_search_next_{generation}_{selected}"
        ):
            move = 1
        if move:
            page += move
            st.session_state[page_key] = page
            saved_name, saved_club = st.session_state[params_key]
            try:
                st.session_state[search_key] = search_master_teams(
                    client, name=saved_name, club=saved_club, page=page
                )
            except Exception as exc:
                st.warning(f"PitchRank search is unavailable: {exc}")
            else:
                st.rerun()

    reference = st.text_input("PitchRank team link or ID, or GotSport team link or ID",
                              value=display["PitchRank ID"], key=f"bt_reference_{generation}_{selected}")
    if not reference:
        if display["Status"] != "Not found" and st.button(
            "Mark not found in PitchRank", key=f"bt_not_found_{generation}_{selected}"
        ):
            update_links(
                event_key, event_id=snapshot.roster.event_id,
                not_found_registration_ids=(registration,),
                expected_links={registration: expected_state}, base_dir=base_dir,
            )
            rerun_after_link_change()
        return
    try:
        candidate = resolve_manual_reference(
            reference, row, lookup_provider_id=_seeding_provider_id_lookup(client),
            lookup_team_details=make_team_details_lookup(client),
        )
    except Exception as exc:
        st.error(f"Could not check that team: {exc}")
        return
    if candidate.status != "ok":
        st.warning("No PitchRank team was found for that link or ID.")
        return
    detail = candidate.details or {}
    st.dataframe(pd.DataFrame([detail]), hide_index=True, width="stretch")
    st.caption("Check the squad identity. Its current database age can differ from this historical bracket.")
    if st.button("Use this team", key=f"bt_use_{generation}_{selected}"):
        link = TeamLink(registration, row.team_name_raw, candidate.team_id_master, "operator", utc_now_iso())
        try:
            update_links(
                event_key, event_id=snapshot.roster.event_id, changed_links=(link,),
                expected_links={registration: expected_state}, base_dir=base_dir,
            )
        except Exception as exc:
            st.error(f"The match was not saved: {exc}")
        else:
            rerun_after_link_change()


def _review_drafts(snapshot: BacktestSnapshot) -> dict[str, dict[str, Any]]:
    key = f"bt_review_drafts_{snapshot.generation}"
    if key not in st.session_state:
        previous = {review.group_id: review for review in reviews_for_capture(snapshot.roster, snapshot.reviews)}
        st.session_state[key] = {
            division.group_id: asdict(previous.get(
                division.group_id, DivisionReview(division.group_id, structure_hash(division))
            ))
            for division in snapshot.roster.divisions
        }
    return st.session_state[key]


def _cohort_drafts(snapshot: BacktestSnapshot) -> dict[str, dict[str, str]]:
    key = f"bt_cohort_drafts_{snapshot.generation}"
    if key not in st.session_state:
        st.session_state[key] = {item.group_id: asdict(item) for item in snapshot.cohort_decisions}
    return st.session_state[key]


def _save_review_field(draft_key: str, group_id: str, field: str, widget_key: str) -> None:
    drafts = dict(st.session_state[draft_key])
    item = dict(drafts[group_id])
    item[field] = st.session_state[widget_key]
    drafts[group_id] = item
    st.session_state[draft_key] = drafts


def _save_review_format(draft_key: str, group_id: str, widget_key: str) -> None:
    drafts = dict(st.session_state[draft_key])
    item = dict(drafts[group_id])
    item["format_code"] = st.session_state[widget_key]
    item["checked"] = False
    drafts[group_id] = item
    st.session_state[draft_key] = drafts


def _save_cohort_field(
    cohort_key: str, review_key: str, group_id: str, field: str, widget_key: str
) -> None:
    drafts = dict(st.session_state[cohort_key])
    item = dict(drafts.get(group_id, {}))
    item[field] = st.session_state[widget_key]
    drafts[group_id] = item
    st.session_state[cohort_key] = drafts
    reviews = dict(st.session_state[review_key])
    review = dict(reviews[group_id])
    review["checked"] = False
    reviews[group_id] = review
    st.session_state[review_key] = reviews


def _current_reviews(snapshot: BacktestSnapshot) -> tuple[DivisionReview, ...]:
    return tuple(DivisionReview(**item) for item in _review_drafts(snapshot).values())


def _current_cohort_decisions(snapshot: BacktestSnapshot) -> tuple[CohortDecision, ...]:
    decisions = []
    saved = {item.group_id: item for item in snapshot.cohort_decisions}
    for group_id, item in _cohort_drafts(snapshot).items():
        age = str(item.get("age_group", "")).strip().lower()
        gender = str(item.get("gender", "")).strip()
        note = str(item.get("note", "")).strip()
        source_url = str(item.get("source_url", "")).strip()
        if (
            re.fullmatch(r"u[0-9]{1,2}(?:/u[0-9]{1,2})*", age)
            and gender in {"Male", "Female"}
            and note
            and source_url
        ):
            decisions.append(CohortDecision(group_id, age, gender, note, source_url))
        elif group_id in saved:
            decisions.append(saved[group_id])
    return tuple(decisions)


def _render_structure(snapshot: BacktestSnapshot) -> tuple[tuple[DivisionReview, ...], tuple[CohortDecision, ...]]:
    from src.tournaments.backtest_event_intake import summarize_structure
    from tournament_intake import _as_plain_text

    display_divisions = effective_roster(snapshot).divisions
    st.markdown("#### Tournament structure")
    st.dataframe(pd.DataFrame(summarize_structure(display_divisions)), hide_index=True, width="stretch")
    review_key = f"bt_review_drafts_{snapshot.generation}"
    cohort_key = f"bt_cohort_drafts_{snapshot.generation}"
    reviews = _review_drafts(snapshot)
    cohorts = _cohort_drafts(snapshot)
    by_group = {division.group_id: division for division in display_divisions}
    filter_mode = st.radio(
        "Show divisions", ("Unchecked", "Needs attention", "All divisions"), horizontal=True,
        key=f"bt_structure_filter_{snapshot.generation}",
    )
    if filter_mode == "Unchecked":
        options = [group for group in by_group if not reviews[group]["checked"]]
    elif filter_mode == "Needs attention":
        options = [group for group, division in by_group.items() if (
            division.warnings or not division.pools_readable or not division.fixtures_readable
            or not division.published_age_group or not division.gender
        )]
    else:
        options = list(by_group)
    if not options:
        st.success("No divisions match this filter.")
        return _current_reviews(snapshot), _current_cohort_decisions(snapshot)
    select_key = f"bt_structure_selected_{snapshot.generation}_{filter_mode}"
    if st.button("Next unchecked", disabled=not any(not reviews[group]["checked"] for group in by_group),
                 key=f"bt_next_unchecked_{snapshot.generation}"):
        unchecked = [group for group in by_group if not reviews[group]["checked"]]
        if unchecked:
            st.session_state[select_key] = unchecked[0]
    selected = st.selectbox(
        "Division to review", options,
        format_func=lambda group: by_group[group].division_label or f"Division {group}", key=select_key,
    )
    division = by_group[selected]
    saved = reviews[selected]
    epoch = st.session_state.get(f"bt_review_epoch_{snapshot.generation}", 0)
    widget = f"bt_division_{snapshot.generation}_{selected}" + (f"_{epoch}" if epoch else "")
    if division.source_url:
        st.link_button("Open published division", division.source_url)
    memberships = [
        {"Pool": pool.label, "Team": member.team_name, "Registration ID": member.registration_id,
         "Final standing (not seed)": member.standings_position}
        for pool in division.pools for member in pool.members
    ]
    st.dataframe(pd.DataFrame(memberships), hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame([asdict(fixture) for fixture in division.fixtures]), hide_index=True, width="stretch")
    for warning in division.warnings:
        st.warning(_as_plain_text(warning))
    if division.rules_links:
        st.dataframe(pd.DataFrame([asdict(link) for link in division.rules_links]), hide_index=True)
    format_options = ("", "ROUND_ROBIN", "F_ONLY", "SF_F", "SF_F_3P")
    format_key = f"{widget}_format_code"
    current_format = saved.get("format_code", "")
    st.selectbox(
        "Verified replay format",
        format_options,
        index=format_options.index(current_format) if current_format in format_options else 0,
        format_func=lambda value: value or "Select a supported format",
        key=format_key,
        on_change=_save_review_format,
        args=(review_key, selected, format_key),
        help="Choose only after confirming the published pool and playoff structure.",
    )
    for field, label in (("notes", "Published format / advancement / tiebreaker notes"),
                         ("source_url", "Rules source URL")):
        widget_key = f"{widget}_{field}"
        render = st.text_area if field == "notes" else st.text_input
        render(label, value=saved[field], key=widget_key, on_change=_save_review_field,
               args=(review_key, selected, field, widget_key))
    checked_key = f"{widget}_checked"
    st.checkbox(
        "I checked this division's teams, pools and fixtures against the source",
        value=saved["checked"], disabled=not saved.get("format_code"), key=checked_key, on_change=_save_review_field,
        args=(review_key, selected, "checked", checked_key),
    )

    with st.expander("Correct tournament cohort interpretation"):
        captured_age = division.published_age_group or ""
        if selected not in cohorts:
            cohorts = dict(cohorts)
            cohorts[selected] = {
                "group_id": selected,
                "age_group": captured_age,
                "gender": division.gender or "Male",
                "note": "",
                "source_url": "",
            }
            st.session_state[cohort_key] = cohorts
        existing = cohorts[selected]
        age_key, gender_key = f"{widget}_cohort_age", f"{widget}_cohort_gender"
        age = st.text_input(
            "Tournament cohort", value=existing.get("age_group", captured_age).upper(), key=age_key,
            help="Examples: U13 or U10/U11", on_change=_save_cohort_field,
            args=(cohort_key, review_key, selected, "age_group", age_key),
        )
        gender_options = ("Male", "Female")
        current_gender = existing.get("gender", division.gender or "Male")
        st.selectbox(
            "Tournament gender", gender_options, index=gender_options.index(current_gender), key=gender_key,
            on_change=_save_cohort_field,
            args=(cohort_key, review_key, selected, "gender", gender_key),
        )
        for field, label in (("note", "Reason / source evidence"), ("source_url", "Cohort source URL")):
            field_key = f"{widget}_cohort_{field}"
            st.text_input(
                label, value=existing.get(field, ""), key=field_key, on_change=_save_cohort_field,
                args=(cohort_key, review_key, selected, field, field_key),
            )
        normalized_age = age.strip().lower()
        correction_started = bool(existing.get("note") or existing.get("source_url")
                                  or normalized_age != captured_age.lower()
                                  or existing.get("gender") != division.gender)
        if correction_started and (not re.fullmatch(r"u[0-9]{1,2}(?:/u[0-9]{1,2})*", normalized_age)
                                   or not cohorts[selected].get("note") or not cohorts[selected].get("source_url")):
            st.info("A cohort correction is saved only after it has a valid U-age, reason, and source URL.")
    return _current_reviews(snapshot), _current_cohort_decisions(snapshot)


def _render_results(results: dict[str, Any]) -> None:
    st.markdown("#### Actual tournament results")
    values = (
        ("Games counted", results["scored_games"]),
        ("Average goal margin", f"{results['average_goal_margin']:.2f}"
         if results["average_goal_margin"] is not None else "—"),
        ("Total goal margin", results["total_goal_margin"]),
        ("Blowout games (4+ goals)", results["blowout_games"]),
        ("Blowout rate", f"{results['blowout_percentage']:.1f}%"
         if results["blowout_percentage"] is not None else "—"),
    )
    for column, (label, value) in zip(st.columns(5), values):
        column.metric(label, value)
    st.caption("Goal margin is the absolute score difference: 5–1 contributes 4, and a draw contributes 0. "
               "Shootout goals are excluded. A blowout has a margin of 4 or more goals. "
               "The average and blowout rate use only the games counted.")
    st.caption(f"Captured: {results['fixture_rows']} fixture listings, {results['unique_fixtures']} identified games. "
               f"{results['excluded_games']} entries excluded from result totals. "
               f"{results['duplicate_rows']} repeated fixture listings combined.")
    if results["is_partial"]:
        st.warning("Partial capture: these results cover only the fixtures captured so far.")
    if results["scored_games"] == 0:
        st.info("No eligible scored games are available in this capture. "
                "An average margin and blowout rate cannot be calculated yet.")
    if results["conflicting_games"]:
        st.warning(f"{results['conflicting_games']} fixtures have conflicting results or division assignments. "
                   "They are excluded until their source evidence is resolved.")
    if results["fixtures_without_identity"]:
        st.warning(f"{results['fixtures_without_identity']} fixture rows have no match ID or match number. "
                   "They are excluded because duplicate listings cannot be ruled out.")
    if results["legacy_scored_games"]:
        st.caption(f"Includes {results['legacy_scored_games']} scored games from older captures "
                   "whose original result status was not retained.")

    def table_rows(rows, *, division=False):
        return [
            {
                **({"Division": row["division_label"], "Group ID": row["group_id"]} if division else {}),
                "Tournament cohort": row["age_group"].upper() or "Not stated",
                "Gender": {"Male": "Boys", "Female": "Girls"}.get(row["gender"], row["gender"] or "Not stated"),
                "Games counted": row["scored_games"],
                "Total goal margin": row["total_goal_margin"],
                "Average goal margin": row["average_goal_margin"],
                "Blowout games (4+ goals)": row["blowout_games"],
                "Blowout rate (%)": row["blowout_percentage"],
                "Excluded fixtures": row["excluded_games"],
            }
            for row in rows
        ]

    with st.expander("Results by cohort and division"):
        st.caption("Breakdowns follow tournament divisions. Event averages weight every counted game equally. "
                   "A fixture with conflicting division assignments appears as excluded in each affected group.")
        st.dataframe(pd.DataFrame(table_rows(results["by_cohort"])), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(table_rows(results["by_division"], division=True)),
                     hide_index=True, width="stretch")
        if results["exclusion_reasons"]:
            st.markdown("**Fixtures excluded from result totals**")
            st.dataframe(pd.DataFrame([
                {"Reason": reason.replace("_", " ").capitalize(), "Fixtures": count}
                for reason, count in results["exclusion_reasons"].items()
            ]), hide_index=True, width="stretch")


def _preserve_review_state_after_capture(
    current: BacktestSnapshot,
    previous: BacktestSnapshot,
    refreshed_roster: Any,
    verification: CaptureVerification,
) -> BacktestSnapshot:
    """Carry saved operator work into a targeted recovery's new generation."""
    return replace(
        current,
        reviews=reviews_for_capture(refreshed_roster, previous.reviews),
        cohort_decisions=previous.cohort_decisions,
        verification=verification,
    )


def _render_capture_details(snapshot: BacktestSnapshot, supabase_client: Any, base_dir) -> None:
    from src.tournaments.gotsport_event_roster import (
        EVENT_BASE,
        capture_event_divisions,
        make_zenrows_fetcher,
        verify_event_divisions,
    )
    from tournament_intake import _BACKTEST_KEYS, _park_event_roster, _render_seeding_event_scrape

    quality = summarize_structure_quality(snapshot.roster.divisions)
    st.markdown("#### Capture evidence")
    st.dataframe(pd.DataFrame([quality]), hide_index=True, width="stretch")
    if snapshot.roster.warnings:
        with st.expander(f"Capture details ({len(snapshot.roster.warnings)} messages)"):
            for warning in snapshot.roster.warnings:
                st.write("• " + warning)

    existing = tuple(division.group_id for division in snapshot.roster.divisions)
    api_key = os.getenv("ZENROWS_API_KEY")
    if st.button("Verify division list", disabled=not api_key, type="primary"):
        try:
            with st.spinner("Checking the event's division list only..."):
                group_ids, counts, stable = verify_event_divisions(
                    snapshot.roster.event_id,
                    fetch=make_zenrows_fetcher(api_key),
                    existing_group_ids=existing,
                )
        except Exception as exc:
            st.error(f"Division verification failed: {exc}")
        else:
            missing = set(group_ids) - set(existing)
            roster = snapshot.roster
            if stable and not missing:
                roster = replace(
                    roster,
                    divisions_found=len(group_ids),
                    divisions_stable=True,
                    warnings=tuple(
                        item for item in roster.warnings
                        if "listed different divisions on each read" not in item
                    ),
                )
            st.session_state[_BACKTEST_KEYS.snapshot] = replace(
                snapshot,
                roster=roster,
                verification=CaptureVerification(group_ids, counts, utc_now_iso(), stable),
            )
            st.rerun()
    if not api_key:
        st.info("ZENROWS_API_KEY is required to verify the published division list.")
    verification = snapshot.verification
    if verification:
        missing = tuple(group for group in verification.group_ids if group not in set(existing))
        unreadable = tuple(
            division.group_id for division in snapshot.roster.divisions
            if not (division.pools_readable and division.fixtures_readable)
        )
        targets = tuple(dict.fromkeys(missing + unreadable))
        state = "stable" if verification.stable else "not stable"
        st.caption(
            f"Last division check: {state} · reads {list(verification.observed_counts)} · "
            f"{len(missing)} new divisions"
        )
        if targets and st.button(f"Capture {len(targets)} missing or unreadable divisions", disabled=not api_key):
            progress = st.progress(0.0, text="Preparing targeted capture...")
            operator_state = replace(
                snapshot,
                reviews=_current_reviews(snapshot),
                cohort_decisions=_current_cohort_decisions(snapshot),
            )

            def phase(name: str, done: int, total: int) -> None:
                progress.progress(done / max(total, 1), text=f"{name}: {done} of {total}")

            try:
                refreshed = capture_event_divisions(
                    snapshot.roster,
                    targets,
                    fetch=make_zenrows_fetcher(api_key),
                    all_group_ids=verification.group_ids,
                    divisions_stable=verification.stable,
                    max_workers=8,
                    on_phase=phase,
                )
                assert_capture_preserved(snapshot.roster, refreshed)
                _park_event_roster(
                    f"{EVENT_BASE}/{snapshot.roster.event_id}", refreshed, None,
                    supabase_client, keys=_BACKTEST_KEYS,
                )
                current = st.session_state[_BACKTEST_KEYS.snapshot]
                st.session_state[_BACKTEST_KEYS.snapshot] = _preserve_review_state_after_capture(
                    current, operator_state, refreshed, verification
                )
            except Exception as exc:
                st.error(f"Missing divisions were not captured: {exc}")
            else:
                st.rerun()
            finally:
                progress.empty()

    with st.expander("Start or repeat a Backtest capture"):
        _render_seeding_event_scrape(supabase_client, keys=_BACKTEST_KEYS)


def _display_gender(value: str) -> str:
    return {"Male": "Boys", "Female": "Girls"}.get(value, value or "Not stated")


def _format_model_value(value: Any, unit: str) -> str:
    if value is None:
        return "Unavailable"
    number = float(value)
    return f"{number * 100:.1f}%" if unit == "rate" else f"{number:.2f}"


def _render_reviewed_result(event_key: str, base_dir) -> None:
    records = list_reviewed_runs(event_key, base_dir=base_dir)
    st.markdown("#### Backtest results")
    if not records:
        st.caption("No completed Backtest runs yet for this event.")
        return
    by_id = {record.run_id: record for record in records}
    selected_id = st.selectbox(
        "Completed run",
        tuple(by_id),
        format_func=lambda run_id: (
            f"{_display_gender(by_id[run_id].gender)} {by_id[run_id].age_group.upper()} · "
            f"{by_id[run_id].ended_at or run_id}"
        ),
        key=f"bt_completed_run_{event_key}",
    )
    record = by_id[selected_id]
    try:
        summary, metadata = load_reviewed_run(record)
    except Exception as exc:
        st.error(f"This completed run could not be read: {exc}")
        return

    comparison = summary.get("seeding_comparison") or {}
    if comparison.get("status") != "comparable":
        st.warning(
            "A fair original-versus-proposed comparison is unavailable: "
            + str(comparison.get("reason") or "the modeled matchup evidence is incomplete")
        )
    observed = observed_result_values(summary)
    actual_columns = st.columns(4)
    actual_columns[0].metric("Observed games", observed["game_count"])
    actual_columns[1].metric(
        "Observed average margin",
        _format_model_value(observed["average_goal_differential"], "goals"),
    )
    actual_columns[2].metric(
        "Observed 4+ blowouts",
        observed["blowout_4plus_count"],
    )
    actual_columns[3].metric(
        "Observed blowout rate",
        _format_model_value(observed["blowout_4plus_rate"], "rate"),
    )
    st.caption(
        "Observed results describe what happened. The comparison below evaluates both arrangements "
        "with the same frozen historical model."
    )
    comparison_rows = model_comparison_rows(summary)
    comparison_display = [
        {
            "Metric": row["Metric"],
            "Original model": _format_model_value(row["Original model"], row["Unit"]),
            "MatchBalance model": _format_model_value(row["MatchBalance model"], row["Unit"]),
            "Improvement": _format_model_value(row["Improvement"], row["Unit"]),
        }
        for row in comparison_rows
    ]
    st.markdown("##### Modeled original versus MatchBalance")
    st.dataframe(pd.DataFrame(comparison_display), hide_index=True, width="stretch")

    moves = movement_rows(summary)
    changed = sum(row["Decision"] != "Stayed" for row in moves)
    move_columns = st.columns(3)
    move_columns[0].metric("Teams evaluated", len(moves))
    move_columns[1].metric("Teams moved", changed)
    move_columns[2].metric("Teams kept", len(moves) - changed)
    movement_filter = st.radio(
        "Team placement rows",
        ("All teams", "Changes only"),
        horizontal=True,
        key=f"bt_movement_filter_{selected_id}",
    )
    visible_moves = moves if movement_filter == "All teams" else [
        row for row in moves if row["Decision"] != "Stayed"
    ]
    st.dataframe(pd.DataFrame(visible_moves), hide_index=True, width="stretch")

    historical = summary.get("historical_inputs") or {}
    predictor = summary.get("predictor") or {}
    with st.expander("Historical evidence used"):
        st.write(f"Exclusive event cutoff: {predictor.get('prediction_date') or 'Unavailable'}")
        st.write(f"Historical games used: {summary.get('historical_games_used_for_prediction', 0)}")
        st.write(f"Probability strategy: {predictor.get('probability_strategy') or 'Unavailable'}")
        st.write(f"Model SHA-256: {historical.get('model_artifact_sha256') or 'Unavailable'}")
        st.write(f"Frozen input digest: {historical.get('input_digest_sha256') or 'Unavailable'}")
    downloads = st.columns(3)
    html_path = record.run_dir / "comparison.html"
    if html_path.is_file():
        downloads[0].download_button(
            "Download director report",
            html_path.read_bytes(),
            file_name=f"{record.run_id}-backtest.html",
            mime="text/html",
            key=f"bt_report_html_{selected_id}",
        )
    downloads[1].download_button(
        "Download result JSON",
        (record.run_dir / "summary.json").read_bytes(),
        file_name=f"{record.run_id}-summary.json",
        mime="application/json",
        key=f"bt_report_json_{selected_id}",
    )
    downloads[2].download_button(
        "Download evidence package",
        reviewed_run_export(record),
        file_name=f"{record.run_id}-evidence.zip",
        mime="application/zip",
        key=f"bt_report_zip_{selected_id}",
    )


def _render_event_rollup(
    snapshot: BacktestSnapshot,
    readiness: list[ReviewedCohortReadiness],
    event_key: str,
    base_dir,
    *,
    model_sha256: str | None,
) -> None:
    records = (*list_reviewed_runs(event_key, base_dir=base_dir),
               *list_failed_reviewed_runs(event_key, base_dir=base_dir))
    rollup = build_event_rollup(
        snapshot,
        readiness,
        records,
        model_sha256=model_sha256,
    )
    modelled = rollup["modelled_pool_matchups"]
    movements = rollup["team_movements"]
    coverage = rollup["coverage"]
    st.markdown("#### Tournament-wide sales summary")
    st.caption(modelled["scope_note"] + ". Each cohort uses the same selected historical model.")
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Original projected margin",
        _format_model_value(modelled["original_average_goal_margin"], "goals"),
    )
    metric_columns[1].metric(
        "MatchBalance margin",
        _format_model_value(modelled["matchbalance_average_goal_margin"], "goals"),
        delta=(
            _format_model_value(modelled["goal_margin_improvement"], "goals") + " lower"
            if modelled["goal_margin_improvement"] is not None else None
        ),
        delta_color="off",
    )
    metric_columns[2].metric(
        "Original projected 4+ rate",
        _format_model_value(modelled["original_blowout_4plus_rate"], "rate"),
    )
    metric_columns[3].metric(
        "MatchBalance 4+ rate",
        _format_model_value(modelled["matchbalance_blowout_4plus_rate"], "rate"),
        delta=(
            _format_model_value(modelled["blowout_4plus_rate_improvement"], "rate") + " lower"
            if modelled["blowout_4plus_rate_improvement"] is not None else None
        ),
        delta_color="off",
    )
    move_columns = st.columns(3)
    move_columns[0].metric("Teams moved up", movements["moved_up"])
    move_columns[1].metric("Teams moved down", movements["moved_down"])
    move_columns[2].metric("Teams unchanged", movements["unchanged"])
    coverage_columns = st.columns(4)
    coverage_columns[0].metric("Cohorts completed", coverage["completed"])
    coverage_columns[1].metric("Failed", coverage["failed"])
    coverage_columns[2].metric("Awaiting matches", coverage["awaiting_matches"])
    coverage_columns[3].metric(
        "Other remaining",
        coverage["awaiting_review"] + coverage["awaiting_history"] + coverage["ready"],
    )
    st.dataframe(
        pd.DataFrame(
            {
                "Cohort": f"{_display_gender(row['gender'])} {row['age_group'].upper()}",
                "Teams": row["team_count"],
                "Status": row["status"].replace("_", " ").title(),
                "What remains": row["what_remains"],
            }
            for row in coverage["rows"]
        ),
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        "Download tournament-director report",
        event_rollup_export(rollup),
        file_name=f"{event_key}-tournament-backtest.zip",
        mime="application/zip",
        key=f"bt_event_rollup_{snapshot.generation}_{model_sha256 or 'none'}",
    )


def _run_reviewed_requests(
    event_key: str,
    readiness: list[ReviewedCohortReadiness],
    *,
    model_artifact: str,
    base_dir,
) -> None:
    had_failure = False
    for index, cohort in enumerate(readiness, start=1):
        if cohort.request is None:
            continue
        label = f"{_display_gender(cohort.gender)} {cohort.age_group.upper()}"
        with st.status(
            f"Running {label} ({index} of {len(readiness)})",
            expanded=True,
            state="running",
        ) as status:
            progress = st.progress(0.0, text="Preparing historical evidence...")
            phase_line = st.empty()
            log = st.empty()

            def on_progress(event) -> None:
                if event.phase:
                    phase_line.caption(f"{label}: {event.phase}")
                    status.update(label=f"{label}: {event.phase}")
                if event.completed is not None and event.total:
                    progress.progress(
                        event.completed / event.total,
                        text=f"{event.raw_line}",
                    )
                elif event.raw_line and not event.phase:
                    log.caption(event.raw_line[-500:])

            try:
                outcome = execute_reviewed_run(
                    event_key,
                    cohort.request,
                    model_artifact=model_artifact,
                    base_dir=base_dir,
                    on_progress=on_progress,
                )
            except Exception as exc:
                status.update(label=f"{label}: could not start", state="error")
                st.error(str(exc))
                had_failure = True
                continue
            if outcome.state == "failed":
                status.update(label=f"{label}: failed", state="error")
                st.error(outcome.error or "The Backtest run failed")
                had_failure = True
                continue
            progress.progress(1.0, text="Completed")
            status.update(label=f"{label}: completed", state="complete")
            st.success(f"{label}: completed")
            st.session_state[f"bt_completed_run_{event_key}"] = outcome.run_dir.name
    if not had_failure:
        st.rerun()


def _render_backtest_runner(
    snapshot: BacktestSnapshot,
    links: EventLinks,
    event_key: str,
    base_dir,
    *,
    supabase_client: Any,
    matching_blocker: str = "",
) -> None:
    st.markdown("#### Run Backtest")
    st.caption(
        "Reseed matched teams within each tournament cohort while keeping division sizes, pool sizes, "
        "and reviewed formats fixed. Runs and evidence stay local."
    )
    operator_snapshot = replace(
        snapshot,
        reviews=_current_reviews(snapshot),
        cohort_decisions=_current_cohort_decisions(snapshot),
    )
    unsaved_reason = ""
    try:
        saved_snapshot = read_snapshot(event_key, base_dir=base_dir)
    except Exception:
        saved_snapshot = operator_snapshot
        unsaved_reason = "Save progress before running this event"
    else:
        if saved_snapshot.generation != operator_snapshot.generation:
            unsaved_reason = "Save this capture before running it"
        elif (
            saved_snapshot.reviews != operator_snapshot.reviews
            or saved_snapshot.cohort_decisions != operator_snapshot.cohort_decisions
            or saved_snapshot.verification != operator_snapshot.verification
        ):
            unsaved_reason = "Save the current review and verification changes before running"
    readiness = list(build_reviewed_cohort_readiness(saved_snapshot, links))
    if unsaved_reason:
        readiness = [
            replace(item, request=None, blockers=(unsaved_reason, *item.blockers))
            for item in readiness
        ]
    if matching_blocker:
        readiness = [
            replace(item, request=None, blockers=(matching_blocker, *item.blockers))
            for item in readiness
        ]

    artifact_value = st.text_input(
        "Historical model artifact",
        value=default_model_artifact(),
        key=f"bt_model_artifact_{snapshot.roster.event_id}",
        help="A point-in-time model trained only on data before this tournament.",
    )
    try:
        artifact_path = resolve_model_artifact(artifact_value)
        model_ready = artifact_path.is_file()
    except (OSError, ValueError):
        artifact_path = None
        model_ready = False
    model_blocker = "" if model_ready else "Historical model artifact not found"
    selected_model_sha = model_artifact_sha256(artifact_path) if model_ready else None
    if not model_ready:
        st.info(
            "Provide a point-in-time model trained with data ending before this event. "
            "Use `python scripts/train_point_in_time_match_model.py --max-game-date YYYY-MM-DD`, "
            "then select its point_in_time_match_model.pkl file above."
        )
    request_items = [item for item in readiness if item.request is not None]
    preflight = None
    expected_preflight_sha = ""
    if model_ready and request_items:
        expected_preflight_sha = preflight_input_sha256(
            (item.request for item in request_items if item.request is not None),
            artifact_path,
        )
        try:
            cached_preflight = load_historical_preflight(event_key, base_dir=base_dir)
        except Exception as exc:
            st.warning(f"Saved historical preflight could not be read: {exc}")
        else:
            if cached_preflight and cached_preflight.input_sha256 == expected_preflight_sha:
                preflight = cached_preflight
    if st.button(
        "Check historical ratings",
        disabled=not (model_ready and request_items),
        help=model_blocker or "Read-only check of every matched entrant before any cohort runs.",
        key=f"bt_historical_preflight_{snapshot.generation}",
    ):
        with st.spinner("Checking pre-event rating snapshots for every matched team..."):
            try:
                preflight = run_historical_preflight(
                    (item.request for item in request_items if item.request is not None),
                    supabase_client,
                    model_artifact=artifact_path,
                )
                write_historical_preflight(event_key, preflight, base_dir=base_dir)
            except HistoricalPreflightUnavailable as exc:
                st.error(f"Historical data could not be checked: {exc}")
            except Exception as exc:
                st.error(f"Historical preflight failed: {exc}")
    preflight_by_cohort = {
        (item.age_group, item.gender): item for item in (preflight.cohorts if preflight else ())
    }
    if preflight:
        eligible = sum(item.eligible for item in preflight.cohorts)
        total = sum(item.total for item in preflight.cohorts)
        if preflight.ready:
            st.success(
                f"Historical ratings ready: {eligible} of {total} entrants have eligible "
                f"pre-event snapshots before {preflight.cutoff_exclusive}."
            )
        else:
            st.warning(f"Historical ratings need attention: {eligible} of {total} entrants are eligible.")
            with st.expander("Missing historical evidence"):
                missing_rows = [
                    {
                        "Cohort": f"{_display_gender(cohort.gender)} {cohort.age_group.upper()}",
                        "Team": entrant.event_team_name,
                        "Reason": entrant.reason,
                    }
                    for cohort in preflight.cohorts
                    for entrant in cohort.entrants
                    if not entrant.eligible
                ]
                st.dataframe(pd.DataFrame(missing_rows), hide_index=True, width="stretch")
    if model_ready:
        enriched = []
        for item in readiness:
            cohort_preflight = preflight_by_cohort.get((item.age_group, item.gender))
            history_blocker = ""
            if item.request is not None and cohort_preflight is None:
                history_blocker = "Check historical ratings before running this cohort"
            elif cohort_preflight is not None and not cohort_preflight.ready:
                missing = cohort_preflight.total - cohort_preflight.eligible
                history_blocker = f"{missing} entrants lack eligible pre-event ratings"
            enriched.append(
                replace(
                    item,
                    request=item.request,
                    blockers=((*item.blockers, history_blocker) if history_blocker else item.blockers),
                )
            )
        readiness = enriched
    table_rows = []
    for item in readiness:
        blockers = list(item.blockers)
        if model_blocker:
            blockers.append(model_blocker)
        table_rows.append(
            {
                "Cohort": f"{_display_gender(item.gender)} {item.age_group.upper()}",
                "Teams": item.team_count,
                "Divisions": item.division_count,
                "Status": "Ready" if item.ready and model_ready else "Blocked",
                "What remains": "; ".join(blockers),
            }
        )
    st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")
    if not readiness:
        st.info("No tournament cohorts are available to run.")
        _render_event_rollup(
            saved_snapshot, readiness, event_key, base_dir, model_sha256=selected_model_sha
        )
        _render_reviewed_result(event_key, base_dir)
        return
    selected_index = st.selectbox(
        "Cohort to run",
        tuple(range(len(readiness))),
        format_func=lambda index: (
            f"{_display_gender(readiness[index].gender)} {readiness[index].age_group.upper()}"
        ),
        key=f"bt_run_cohort_{snapshot.generation}",
    )
    selected = readiness[selected_index]
    ready = [item for item in readiness if item.ready]
    actions = st.columns(2)
    run_selected = actions[0].button(
        "Run selected cohort",
        type="primary",
        disabled=not (selected.ready and model_ready),
        help="\n".join((*selected.blockers, model_blocker)) or None,
        key=f"bt_run_selected_{snapshot.generation}",
    )
    run_all = actions[1].button(
        f"Run all ready cohorts ({len(ready)})",
        disabled=not (ready and model_ready),
        help=model_blocker or None,
        key=f"bt_run_all_{snapshot.generation}",
    )
    if run_selected:
        _run_reviewed_requests(
            event_key,
            [selected],
            model_artifact=str(artifact_path),
            base_dir=base_dir,
        )
    if run_all:
        _run_reviewed_requests(
            event_key,
            ready,
            model_artifact=str(artifact_path),
            base_dir=base_dir,
        )
    _render_event_rollup(
        saved_snapshot, readiness, event_key, base_dir, model_sha256=selected_model_sha
    )
    _render_reviewed_result(event_key, base_dir)


def render_intake(supabase_client: Any) -> None:
    from tournament_intake import _BACKTEST_KEYS, _as_plain_text, _render_seeding_event_scrape, reports_dir

    base_dir = reports_dir()
    st.markdown("### Completed tournament intake")
    st.caption("Capture the event, review its teams and structure, and save it for later Backtest work.")
    _load_saved(base_dir)
    snapshot = st.session_state.get(_BACKTEST_KEYS.snapshot)
    if snapshot is None:
        _render_seeding_event_scrape(supabase_client, keys=_BACKTEST_KEYS)
        return
    snapshot = _restore_review_baseline(snapshot, base_dir)
    if st.session_state.pop(f"bt_saved_{snapshot.generation}", False):
        st.success("Saved the tournament name, teams, structure, matching outcomes and division reviews.")
    decisions = _current_cohort_decisions(snapshot)
    snapshot = replace(snapshot, cohort_decisions=decisions)
    display_snapshot = replace(snapshot, roster=effective_roster(snapshot))
    totals = tournament_totals(display_snapshot.roster)
    st.markdown("### " + _as_plain_text(totals["event_name"]))
    start = getattr(snapshot.roster, "event_start_date", None)
    end = getattr(snapshot.roster, "event_end_date", None)
    st.caption(f"Event {snapshot.roster.event_id} · {start or 'Date not stated'}"
               + (f" to {end}" if end and end != start else ""))
    event_key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
    matching_blocker = ""
    try:
        links, details, conflicts = _sync_matches(display_snapshot, supabase_client, base_dir)
    except Exception as exc:
        st.warning(f"Team matching is unavailable right now: {exc}. The captured event can still be saved.")
        matching_blocker = "Retry team matching before running; merge-synchronized team IDs are unavailable"
        details, conflicts = {}, {}
        links = load_links(event_key, base_dir=base_dir)
    rows = match_table(display_snapshot, links, details, conflicts=conflicts)
    matched = len({row["Match key"] for row in rows if row["Status"] == "Matched"})
    reviewed = sum(review.checked for review in _current_reviews(snapshot))
    status_columns = st.columns(3)
    capture_verified = not capture_verification_blockers(snapshot)
    status_columns[0].metric("Capture verification", "Verified" if capture_verified else "Needs review")
    status_columns[1].metric(
        "Team matching",
        "Unavailable" if matching_blocker else f"{matched} / {totals['total_teams']}",
    )
    status_columns[2].metric("Division review", f"{reviewed} / {len(snapshot.roster.divisions)}")
    section = st.radio(
        "Backtest intake section", ("Overview", "Teams", "Structure", "Capture Details"),
        horizontal=True, key=f"bt_section_{snapshot.generation}", label_visibility="collapsed",
    )

    if section == "Overview":
        columns = st.columns(4)
        for column, name, key in zip(columns, ("Total teams", "Divisions", "Pools", "Fixtures"),
                                     ("total_teams", "divisions", "pools", "fixtures")):
            column.metric(name, totals[key])
        st.markdown("#### Teams by tournament cohort and gender")
        st.caption("Counts use the bracket entered. A U11 team playing in a U12 bracket counts under U12.")
        st.dataframe(pd.DataFrame(totals["cohorts"]), hide_index=True, width="stretch")
        if totals["cohort_entries"] != totals["total_teams"]:
            st.info(
                f"{totals['total_teams']} distinct registrations appear in "
                f"{totals['cohort_entries']} cohort entries; registrations entered in more than one "
                "cohort count in each."
            )
        if totals["unidentified_teams"]:
            st.warning(f"{totals['unidentified_teams']} source team entries have no registration ID and need review.")
        _render_results(totals["results"])
        outstanding = len({row["Match key"] for row in rows if row["Status"] != "Matched"})
        issue_parts = []
        if not capture_verified:
            issue_parts.append("capture verification")
        if outstanding:
            issue_parts.append(f"{outstanding} team identities")
        if matching_blocker:
            issue_parts.append("team matching availability")
        if reviewed < len(snapshot.roster.divisions):
            issue_parts.append(f"{len(snapshot.roster.divisions) - reviewed} division reviews")
        if issue_parts:
            st.warning("Remaining work: " + ", ".join(issue_parts) + ".")
        else:
            st.success("This intake is fully captured, matched, and reviewed.")
        _render_backtest_runner(
            snapshot,
            links,
            event_key,
            base_dir,
            supabase_client=supabase_client,
            matching_blocker=matching_blocker,
        )
    elif section == "Teams":
        st.markdown("#### Match tournament teams to PitchRank")
        st.caption(f"{matched} of {totals['total_teams']} teams matched")
        _render_match_editor(display_snapshot, rows, links, supabase_client, base_dir)
    elif section == "Structure":
        reviews, decisions = _render_structure(snapshot)
    else:
        _render_capture_details(snapshot, supabase_client, base_dir)

    reviews = _current_reviews(snapshot)
    decisions = _current_cohort_decisions(snapshot)
    if st.button("Save progress", type="primary", key=f"bt_save_{snapshot.generation}"):
        saved = replace(snapshot, reviews=reviews, cohort_decisions=decisions)
        try:
            write_snapshot(
                event_key,
                saved,
                base_dir=base_dir,
                review_baseline=snapshot.reviews,
                cohort_baseline=snapshot.cohort_decisions,
            )
            saved = read_snapshot(event_key, base_dir=base_dir)
        except Exception as exc:
            st.error(f"The intake was not saved: {exc}")
        else:
            st.session_state[_BACKTEST_KEYS.snapshot] = saved
            st.session_state[f"bt_review_drafts_{saved.generation}"] = {
                review.group_id: asdict(review) for review in saved.reviews
            }
            st.session_state[f"bt_cohort_drafts_{saved.generation}"] = {
                decision.group_id: asdict(decision) for decision in saved.cohort_decisions
            }
            epoch_key = f"bt_review_epoch_{saved.generation}"
            st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1
            st.session_state[f"bt_saved_{saved.generation}"] = True
            st.rerun()
    export = {**replace(snapshot, reviews=reviews, cohort_decisions=decisions).to_dict(),
              "tournament_totals": totals, "team_matches": rows, "links": asdict(links),
              "matching_conflicts": conflicts}
    import json

    st.download_button("Download Backtest intake JSON", json.dumps(export, indent=2, ensure_ascii=False),
                       file_name=f"gotsport-{snapshot.roster.event_id}-backtest-intake.json",
                       mime="application/json", key=f"bt_export_{snapshot.generation}")
