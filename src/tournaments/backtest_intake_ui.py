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
    EventTiebreakDecision,
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
from src.tournaments.backtest_rating_fallback import (
    MISSING_HISTORY_FALLBACK_POLICY,
    RATING_FALLBACK_POLICY,
)
from src.tournaments.backtest_replay_format import assess_replay_format
from src.tournaments.backtest_reviewed_report import (
    actual_vs_matchbalance_rows,
    movement_rows,
    observed_result_values,
)
from src.tournaments.backtest_reviewed_run import (
    ReviewedCohortReadiness,
    build_reviewed_cohort_readiness,
    canonical_predictor_sha256,
    capture_verification_blockers,
    execute_reviewed_run,
    list_failed_reviewed_runs,
    list_reviewed_runs,
    load_reviewed_run,
    reviewed_run_export,
)
from src.tournaments.backtest_scope import backtest_scope_snapshot
from src.tournaments.gotsport_event_structure import summarize_structure_quality
from src.tournaments.roster_resolver import make_team_details_lookup, resolve_manual_reference
from src.tournaments.schedule_simulator import (
    DEFAULT_TIEBREAK_ORDER,
    STANDARD_SCORING_POLICY,
    SUPPORTED_SCORING_POLICIES,
    TIGER_TOURNAMENTS_SCORING_POLICY,
    TIGER_TOURNAMENTS_TIEBREAK_ORDER,
    normalize_tiebreak_order,
)
from src.tournaments.storage._io import utc_now_iso
from src.tournaments.storage.event_key import existing_event_key


def _set_session_value(key: str, value: Any) -> None:
    st.session_state[key] = value


_TIEBREAK_NOT_VERIFIED = "Not verified"
_TIEBREAK_COMMON = "Points → goal differential → goals scored → wins"
_TIEBREAK_TIGER = "Tiger Tournaments published order"
_TIEBREAK_CUSTOM = "Custom supported order"
_SCORING_NOT_VERIFIED = "Not verified"
_SCORING_STANDARD = "Standard: 3 win / 1 draw / 0 loss; uncapped goal differential"
_SCORING_TIGER = "Tiger: 3/1/0 points; goal differential and goals scored capped at 5 per game"
_SCORING_UNSUPPORTED = "Other scoring or standings modifiers"
_TIEBREAK_ALIASES = {
    "points": "points",
    "head to head": "head_to_head",
    "head-to-head": "head_to_head",
    "head_to_head": "head_to_head",
    "goal differential": "goal_differential",
    "goal difference": "goal_differential",
    "goal diff": "goal_differential",
    "goal_differential": "goal_differential",
    "goals scored": "goals_for",
    "goals for": "goals_for",
    "goals_for": "goals_for",
    "fewest goals conceded": "goals_against",
    "goals conceded": "goals_against",
    "goals against": "goals_against",
    "goals_against": "goals_against",
    "wins": "wins",
}


def _format_tiebreak_order(order: tuple[str, ...]) -> str:
    labels = {
        "points": "points",
        "head_to_head": "head-to-head",
        "goal_differential": "goal differential",
        "goals_for": "goals scored",
        "goals_against": "fewest goals conceded",
        "wins": "wins",
    }
    return ", ".join(labels.get(item, item) for item in order)


def _parse_tiebreak_order(value: str) -> tuple[str, ...]:
    normalized = value.casefold().replace("→", ",").replace(">", ",")
    tokens = [token.strip() for token in re.split(r"[,;\n]+", normalized) if token.strip()]
    unknown = [token for token in tokens if token not in _TIEBREAK_ALIASES]
    if unknown:
        raise ValueError(f"Unsupported criterion: {unknown[0]}")
    return tuple(_TIEBREAK_ALIASES[token] for token in tokens)


def _first_tiebreak_source(snapshot: BacktestSnapshot) -> str:
    return next(
        (
            link.url
            for division in snapshot.roster.divisions
            for link in division.rules_links
            if link.url
        ),
        "",
    )


def _decision_to_tiebreak_draft(snapshot: BacktestSnapshot) -> dict[str, str]:
    decision = snapshot.tiebreak_decision
    if decision is None:
        return {
            "mode": _TIEBREAK_NOT_VERIFIED,
            "custom_order": _format_tiebreak_order(DEFAULT_TIEBREAK_ORDER),
            "scoring_mode": _SCORING_NOT_VERIFIED,
            "note": "",
            "source_url": _first_tiebreak_source(snapshot),
        }
    if decision.order == DEFAULT_TIEBREAK_ORDER:
        mode = _TIEBREAK_COMMON
    elif decision.order == TIGER_TOURNAMENTS_TIEBREAK_ORDER:
        mode = _TIEBREAK_TIGER
    else:
        mode = _TIEBREAK_CUSTOM
    return {
        "mode": mode,
        "custom_order": _format_tiebreak_order(decision.order),
        "scoring_mode": (
            _SCORING_STANDARD
            if decision.scoring_policy == STANDARD_SCORING_POLICY
            else _SCORING_TIGER
            if decision.scoring_policy == TIGER_TOURNAMENTS_SCORING_POLICY
            else _SCORING_NOT_VERIFIED
        ),
        "note": decision.note,
        "source_url": decision.source_url,
    }


def _tiebreak_ready(decision: EventTiebreakDecision | None) -> bool:
    return bool(
        decision is not None
        and decision.scoring_policy in SUPPORTED_SCORING_POLICIES
    )


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
    scoped_match_keys = {entrant_key(team) for team in snapshot.roster.teams}
    collisions = _canonical_collisions(links, registration_ids=scoped_match_keys)
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


def _canonical_collisions(
    links: EventLinks,
    *,
    registration_ids: set[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Map each distinct entrant in an unacknowledged reverse collision to its peers."""
    excluded = set(links.removed_registration_ids) | set(links.not_found_registration_ids)
    by_team: dict[str, set[str]] = {}
    for link in links.links:
        if (
            link.registration_id not in excluded
            and (registration_ids is None or link.registration_id in registration_ids)
        ):
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


def _sync_matches(
    snapshot: BacktestSnapshot, client: Any, base_dir
) -> tuple[EventLinks, dict, dict, str]:
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
    return (
        links,
        _details(client, [link.team_id_master for link in links.links]),
        conflicts,
        str(resolver.version),
    )


def _activate_saved_snapshot(snapshot: BacktestSnapshot) -> None:
    from tournament_intake import _BACKTEST_KEYS

    # This is the only object the Backtest results and save path read.
    st.session_state[_BACKTEST_KEYS.snapshot] = snapshot
    st.session_state[f"bt_review_drafts_{snapshot.generation}"] = {
        review.group_id: asdict(review) for review in reviews_for_capture(snapshot.roster, snapshot.reviews)
    }
    st.session_state[f"bt_cohort_drafts_{snapshot.generation}"] = {
        decision.group_id: asdict(decision) for decision in snapshot.cohort_decisions
    }
    st.session_state[f"bt_tiebreak_draft_{snapshot.generation}"] = (
        _decision_to_tiebreak_draft(snapshot)
    )
    # Fresh widget identities discard a stale session's rejected edits.
    epoch_key = f"bt_review_epoch_{snapshot.generation}"
    st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1


def _load_saved(base_dir) -> None:
    from tournament_intake import _BACKTEST_KEYS

    paths = sorted(base_dir.glob("gotsport__*/intake/event_intake.json"))
    if not paths:
        return
    if len(paths) == 1 and st.session_state.get(_BACKTEST_KEYS.snapshot) is None:
        try:
            _activate_saved_snapshot(read_snapshot(paths[0].parent.parent.name, base_dir=base_dir))
        except Exception as exc:
            st.error(f"Could not open the saved intake: {exc}")
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
            _activate_saved_snapshot(snapshot)
            st.rerun()


def _restore_review_baseline(snapshot: BacktestSnapshot, base_dir) -> BacktestSnapshot:
    """Load prior operator work once per new capture, before rendering editors."""
    from tournament_intake import _BACKTEST_KEYS

    loaded_key = f"bt_reviews_loaded_{snapshot.generation}"
    if st.session_state.get(loaded_key):
        return snapshot
    if (
        not snapshot.reviews
        or not snapshot.cohort_decisions
        or snapshot.tiebreak_decision is None
    ):
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
                tiebreak_decision=(
                    snapshot.tiebreak_decision or saved.tiebreak_decision
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
    with st.expander("Filter review queue"):
        mode = st.radio(
            "Show teams",
            ("Needs review", "All teams"),
            horizontal=True,
            key=f"bt_filter_{generation}",
        )
        completed_statuses = {"Matched", "Not found"}
        candidates = (
            rows
            if mode == "All teams"
            else [row for row in rows if row["Status"] not in completed_statuses]
        )
        filters = st.columns(4)
        division = filters[0].selectbox(
            "Division", ("All",) + tuple(sorted({row["Division"] for row in candidates})),
            key=f"bt_team_division_{generation}",
        )
        cohort = filters[1].selectbox(
            "Cohort",
            ("All",)
            + tuple(sorted({row["Tournament cohort"] or "Not stated" for row in candidates})),
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
    st.caption(f"{len(visible)} team registration(s) in this queue.")
    with st.expander("View review queue"):
        st.dataframe(
            pd.DataFrame(visible).drop(columns=["source_index", "Match key"], errors="ignore"),
            hide_index=True,
            width="stretch",
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

    st.markdown(f"#### {_as_plain_text(display['Event team'])}")
    identity_columns = st.columns(2)
    identity_columns[0].write(f"**Tournament division:** {_as_plain_text(display['Division'])}")
    identity_columns[0].write(
        f"**Tournament cohort:** {_as_plain_text(display['Tournament cohort'] or 'Not stated')}"
    )
    identity_columns[1].write(f"**Gender:** {_as_plain_text(display['Gender'] or 'Not stated')}")
    identity_columns[1].write(f"**Pool:** {_as_plain_text(display['Pools'] or 'Not stated')}")
    with st.expander("IDs and source details"):
        st.write(f"Registration ID: {registration}")
        st.write(f"GotSport team ID: {display['GotSport team ID'] or 'Not captured'}")
        st.write(f"PitchRank ID: {display['PitchRank ID'] or 'Not selected'}")
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
        st.info(
            "Reviewed and marked as not found in PitchRank. The entrant and its results are preserved; "
            "Backtest uses a clearly labeled average pre-event strength estimate."
        )
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

    if display["Status"] != "Not found" and st.button(
        "Mark not found in PitchRank", key=f"bt_not_found_{generation}_{selected}"
    ):
        update_links(
            event_key,
            event_id=snapshot.roster.event_id,
            not_found_registration_ids=(registration,),
            expected_links={registration: expected_state},
            base_dir=base_dir,
        )
        rerun_after_link_change()

    with st.expander("Advanced link or ID lookup"):
        reference = st.text_input(
            "PitchRank team link or ID, or GotSport team link or ID",
            value=display["PitchRank ID"],
            key=f"bt_reference_{generation}_{selected}",
        )
        if not reference:
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
    previous = {
        review.group_id: review for review in reviews_for_capture(snapshot.roster, snapshot.reviews)
    }
    drafts = dict(st.session_state.get(key, {}))
    for division in snapshot.roster.divisions:
        drafts.setdefault(
            division.group_id,
            asdict(
                previous.get(
                    division.group_id,
                    DivisionReview(division.group_id, structure_hash(division)),
                )
            ),
        )
    st.session_state[key] = drafts
    return st.session_state[key]


def _cohort_drafts(snapshot: BacktestSnapshot) -> dict[str, dict[str, str]]:
    key = f"bt_cohort_drafts_{snapshot.generation}"
    if key not in st.session_state:
        st.session_state[key] = {item.group_id: asdict(item) for item in snapshot.cohort_decisions}
    return st.session_state[key]


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


def _tiebreak_draft(snapshot: BacktestSnapshot) -> dict[str, str]:
    key = f"bt_tiebreak_draft_{snapshot.generation}"
    if key not in st.session_state:
        st.session_state[key] = _decision_to_tiebreak_draft(snapshot)
    return st.session_state[key]


def _save_tiebreak_field(draft_key: str, field: str, widget_key: str) -> None:
    draft = dict(st.session_state[draft_key])
    draft[field] = st.session_state[widget_key]
    st.session_state[draft_key] = draft


def _current_tiebreak_decision(
    snapshot: BacktestSnapshot,
) -> tuple[EventTiebreakDecision | None, str]:
    draft = _tiebreak_draft(snapshot)
    mode = str(draft.get("mode") or _TIEBREAK_NOT_VERIFIED)
    if mode == _TIEBREAK_NOT_VERIFIED:
        return None, ""
    scoring_mode = str(draft.get("scoring_mode") or _SCORING_NOT_VERIFIED)
    if scoring_mode == _SCORING_UNSUPPORTED:
        return (
            None,
            "This event uses scoring or standings modifiers that Backtest cannot replay yet",
        )
    if scoring_mode not in {_SCORING_STANDARD, _SCORING_TIGER}:
        return (
            None,
            "Confirm the published points and goal-differential scoring policy",
        )
    note = str(draft.get("note") or "").strip()
    source_url = str(draft.get("source_url") or "").strip()
    if not note or not source_url:
        return (
            None,
            "A verified tiebreak rule needs a verification note and source URL",
        )
    try:
        order = (
            DEFAULT_TIEBREAK_ORDER
            if mode == _TIEBREAK_COMMON
            else TIGER_TOURNAMENTS_TIEBREAK_ORDER
            if mode == _TIEBREAK_TIGER
            else _parse_tiebreak_order(str(draft.get("custom_order") or ""))
        )
        scoring_policy = (
            STANDARD_SCORING_POLICY
            if scoring_mode == _SCORING_STANDARD
            else TIGER_TOURNAMENTS_SCORING_POLICY
        )
        decision = EventTiebreakDecision(
            order=normalize_tiebreak_order(order, allow_empty=False),
            note=note,
            source_url=source_url,
            scoring_policy=scoring_policy,
        )
    except ValueError as exc:
        return None, str(exc)
    return decision, ""


def _render_tiebreak_editor(snapshot: BacktestSnapshot) -> None:
    draft_key = f"bt_tiebreak_draft_{snapshot.generation}"
    draft = _tiebreak_draft(snapshot)
    epoch = st.session_state.get(f"bt_review_epoch_{snapshot.generation}", 0)
    suffix = f"_{epoch}" if epoch else ""
    with st.expander("Tournament tiebreak rule"):
        st.caption(
            "Verify this once for the event. MatchBalance uses the same published rule order "
            "when simulated pool standings decide who advances."
        )
        source = _first_tiebreak_source(snapshot)
        if source:
            st.link_button("Open a captured tiebreak source", source)
        mode_key = f"bt_tiebreak_mode_{snapshot.generation}{suffix}"
        mode_options = (
            _TIEBREAK_NOT_VERIFIED,
            _TIEBREAK_COMMON,
            _TIEBREAK_TIGER,
            _TIEBREAK_CUSTOM,
        )
        mode = str(draft.get("mode") or _TIEBREAK_NOT_VERIFIED)
        if mode not in mode_options:
            mode = _TIEBREAK_NOT_VERIFIED
        st.selectbox(
            "Published rule order",
            mode_options,
            index=mode_options.index(mode),
            key=mode_key,
            on_change=_save_tiebreak_field,
            args=(draft_key, "mode", mode_key),
        )
        active_mode = str(_tiebreak_draft(snapshot).get("mode") or _TIEBREAK_NOT_VERIFIED)
        if active_mode == _TIEBREAK_NOT_VERIFIED:
            st.info(
                "Backtest runs remain blocked until the published rule is verified; the software "
                "will not guess which team advances from a tied pool."
            )
            return
        if active_mode == _TIEBREAK_CUSTOM:
            custom_key = f"bt_tiebreak_custom_{snapshot.generation}{suffix}"
            st.text_input(
                "Rule order",
                value=str(draft.get("custom_order") or ""),
                key=custom_key,
                help=(
                    "Enter supported criteria in order: points, goal differential, goals scored, wins."
                ),
                on_change=_save_tiebreak_field,
                args=(draft_key, "custom_order", custom_key),
            )
        scoring_key = f"bt_tiebreak_scoring_{snapshot.generation}{suffix}"
        scoring_options = (
            _SCORING_NOT_VERIFIED,
            _SCORING_STANDARD,
            _SCORING_TIGER,
            _SCORING_UNSUPPORTED,
        )
        scoring_mode = str(draft.get("scoring_mode") or _SCORING_NOT_VERIFIED)
        if scoring_mode not in scoring_options:
            scoring_mode = _SCORING_NOT_VERIFIED
        st.selectbox(
            "Published scoring policy",
            scoring_options,
            index=scoring_options.index(scoring_mode),
            key=scoring_key,
            help=(
                "Choose standard only when the published rules award 3 points for a win, "
                "1 for a draw, 0 for a loss, and do not cap goal differential."
            ),
            on_change=_save_tiebreak_field,
            args=(draft_key, "scoring_mode", scoring_key),
        )
        note_key = f"bt_tiebreak_note_{snapshot.generation}{suffix}"
        source_key = f"bt_tiebreak_source_{snapshot.generation}{suffix}"
        st.text_input(
            "Verification note",
            value=str(draft.get("note") or ""),
            key=note_key,
            help="Record where you confirmed the published standings rules.",
            on_change=_save_tiebreak_field,
            args=(draft_key, "note", note_key),
        )
        st.text_input(
            "Source URL",
            value=str(draft.get("source_url") or source),
            key=source_key,
            on_change=_save_tiebreak_field,
            args=(draft_key, "source_url", source_key),
        )
        decision, error = _current_tiebreak_decision(snapshot)
        if error:
            st.warning(error)
        elif decision is not None:
            st.success("This verified order will be used for every simulated pool standing.")


def _render_structure(snapshot: BacktestSnapshot) -> tuple[tuple[DivisionReview, ...], tuple[CohortDecision, ...]]:
    from tournament_intake import _as_plain_text

    display_divisions = effective_roster(snapshot).divisions
    st.markdown("#### Tournament structure")
    review_key = f"bt_review_drafts_{snapshot.generation}"
    cohort_key = f"bt_cohort_drafts_{snapshot.generation}"
    _review_drafts(snapshot)
    cohorts = _cohort_drafts(snapshot)
    by_group = {division.group_id: division for division in display_divisions}
    assessments = {group: assess_replay_format(division) for group, division in by_group.items()}
    ready_groups = {group for group, assessment in assessments.items() if assessment.ready}
    attention_groups = [group for group in by_group if group not in ready_groups]
    pool_count = sum(len(division.pools) for division in display_divisions)
    fixture_count = sum(len(division.fixtures) for division in display_divisions)
    st.success(
        f"Captured {len(by_group)} divisions, {pool_count} pools, and {fixture_count} fixtures."
    )
    st.caption(
        "You do not need to review divisions one by one. MatchBalance checks the captured structure "
        "automatically. Open the details below only when you want to inspect the source."
    )
    _render_tiebreak_editor(snapshot)
    with st.expander(f"View division list ({len(by_group)})"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Division": division.division_label,
                    "Cohort": division.age_group.upper(),
                    "Gender": _display_gender(division.gender),
                    "Teams": sum(len(pool.members) for pool in division.pools),
                    "Pools": len(division.pools),
                    "Fixtures": len(division.fixtures),
                }
                for division in by_group.values()
            ]),
            hide_index=True,
            width="stretch",
        )
    with st.expander("Inspect one division"):
        selected = st.selectbox(
            "Division",
            tuple(by_group),
            format_func=lambda group: by_group[group].division_label or f"Division {group}",
            key=f"bt_structure_selected_{snapshot.generation}",
        )
        division = by_group[selected]
        detail_columns = st.columns(4)
        detail_columns[0].metric("Teams", sum(len(pool.members) for pool in division.pools))
        detail_columns[1].metric("Pools", len(division.pools))
        detail_columns[2].metric("Fixtures", len(division.fixtures))
        detail_columns[3].metric("Cohort", division.age_group.upper())
        if division.source_url:
            st.link_button("Open published division", division.source_url)
        evidence = st.radio(
            "Show",
            ("Teams and pools", "Fixtures and results", "Source notes"),
            horizontal=True,
            key=f"bt_structure_evidence_{snapshot.generation}_{selected}",
        )
        if evidence == "Teams and pools":
            memberships = [
                {
                    "Pool": pool.label,
                    "Team": member.team_name,
                    "Registration ID": member.registration_id,
                    "Final standing (not seed)": member.standings_position,
                }
                for pool in division.pools
                for member in pool.members
            ]
            st.dataframe(pd.DataFrame(memberships), hide_index=True, width="stretch")
        elif evidence == "Fixtures and results":
            st.dataframe(
                pd.DataFrame([asdict(fixture) for fixture in division.fixtures]),
                hide_index=True,
                width="stretch",
            )
        else:
            for warning in division.warnings:
                st.warning(_as_plain_text(warning))
            if division.rules_links:
                st.dataframe(
                    pd.DataFrame([asdict(link) for link in division.rules_links]),
                    hide_index=True,
                )
            if not division.warnings and not division.rules_links:
                st.caption("No additional source notes were captured for this division.")

    with st.expander("Backtest replay readiness"):
        st.write(f"{len(ready_groups)} of {len(by_group)} division schedules are replay-ready.")
        if attention_groups:
            st.info(
                f"{len(attention_groups)} unusual schedule patterns still need MatchBalance engine "
                "support. There is nothing for you to approve or correct here."
            )
            st.dataframe(
                pd.DataFrame([
                    {
                        "Division": by_group[group].division_label,
                        "Schedule pattern": assessments[group].reason,
                    }
                    for group in attention_groups
                ]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.success("Every captured division schedule is replay-ready.")

    with st.expander("Correct a tournament cohort"):
        st.caption(
            "Use this only when the published division label assigns the wrong age or gender. "
            "The correction needs a note and source URL."
        )
        selected = st.selectbox(
            "Division to update",
            tuple(by_group),
            format_func=lambda group: by_group[group].division_label or f"Division {group}",
            key=f"bt_structure_update_{snapshot.generation}",
        )
        division = by_group[selected]
        epoch = st.session_state.get(f"bt_review_epoch_{snapshot.generation}", 0)
        widget = f"bt_division_{snapshot.generation}_{selected}" + (f"_{epoch}" if epoch else "")
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
        tiebreak_decision=previous.tiebreak_decision,
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


def _format_reduction(value: Any, unit: str) -> str:
    if value is None:
        return "Unavailable"
    number = float(value)
    direction = "lower" if number >= 0 else "higher"
    return f"{_format_model_value(abs(number), unit)} {direction}"


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

    proposed = summary.get("proposed_schedule_projection") or summary.get(
        "proposed_model_projection"
    ) or {}
    observed = observed_result_values(summary)
    validation = summary.get("model_validation") or {}
    if validation and validation.get("status") != "passed":
        st.warning(
            "This cohort is available for internal review, but it is not ready for the "
            "tournament-director report because the model check needs attention."
        )
        original = summary.get("original_schedule_projection") or {}
        with st.expander("Why this cohort needs model review"):
            st.write(
                "Original schedule check: actual average margin "
                f"{_format_model_value(observed['average_goal_differential'], 'goals')} versus "
                "model expectation "
                f"{_format_model_value(original.get('average_goal_differential'), 'goals')}; "
                "actual 4+ blowout rate "
                f"{_format_model_value(observed['blowout_4plus_rate'], 'rate')} versus "
                "model expectation "
                f"{_format_model_value(original.get('blowout_4plus_probability'), 'rate')}."
            )
            for blocker in validation.get("blockers") or ():
                st.write(f"• {blocker}")
    if proposed.get("average_goal_differential") is None:
        st.warning(
            "The MatchBalance projection is unavailable because its modeled matchup evidence is incomplete."
        )
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
        "The tournament values come directly from the captured results. The MatchBalance values "
        "project the reseeded division and pool assignments using only pre-event evidence."
    )
    comparison_rows = actual_vs_matchbalance_rows(
        summary,
        require_validated_model=False,
    )
    comparison_display = [
        {
            "Metric": row["Metric"],
            "Actual tournament": _format_model_value(row["Actual tournament"], row["Unit"]),
            "MatchBalance projection": _format_model_value(
                row["MatchBalance projection"], row["Unit"]
            ),
            "Estimated reduction": _format_reduction(row["Estimated reduction"], row["Unit"]),
        }
        for row in comparison_rows
    ]
    st.markdown("##### Actual tournament versus MatchBalance")
    st.dataframe(pd.DataFrame(comparison_display), hide_index=True, width="stretch")

    moves = movement_rows(summary, require_validated_model=False)
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
        st.write(f"Prediction engine: {predictor.get('source') or 'Unavailable'}")
        st.write(f"Predictor SHA-256: {historical.get('predictor_sha256') or 'Unavailable'}")
        st.write(
            "Calibration available: "
            f"{historical.get('calibration_available_date') or 'Unavailable'}"
        )
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
    predictor_sha256: str | None,
    merge_map_version: str | None,
) -> None:
    records = (*list_reviewed_runs(event_key, base_dir=base_dir),
               *list_failed_reviewed_runs(event_key, base_dir=base_dir))
    rollup = build_event_rollup(
        snapshot,
        readiness,
        records,
        predictor_sha256=predictor_sha256,
        merge_map_version=merge_map_version,
    )
    comparison = rollup["actual_vs_matchbalance"]
    movements = rollup["team_movements"]
    coverage = rollup["coverage"]
    st.markdown("#### Tournament-wide Backtest result")
    if not rollup["selected_runs"]:
        if coverage["failed"]:
            st.warning(
                f"{coverage['failed']} cohort run(s) failed. Open the details below to inspect or retry them."
            )
            with st.expander("Failed cohort details"):
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Cohort": f"{_display_gender(row['gender'])} {row['age_group'].upper()}",
                            "Teams": row["team_count"],
                            "Status": row["status"].replace("_", " ").title(),
                            "What remains": row["what_remains"],
                        }
                        for row in coverage["rows"]
                        if row["status"] == "failed"
                    ),
                    hide_index=True,
                    width="stretch",
                )
        else:
            st.caption(
                "No current Backtest result yet. Run the full tournament to build the comparison."
            )
        return
    coverage_columns = st.columns(4)
    coverage_columns[0].metric("Cohorts completed", coverage["completed"])
    coverage_columns[1].metric("Failed", coverage["failed"])
    coverage_columns[2].metric("Awaiting matches", coverage["awaiting_matches"])
    coverage_columns[3].metric(
        "Waiting to run",
        coverage["awaiting_review"] + coverage["awaiting_history"] + coverage["ready"],
    )
    with st.expander("Cohort status details"):
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
    st.caption(comparison["scope_note"] + ". Each cohort uses the same selected historical model.")
    validation = rollup.get("model_validation") or {}
    event_validation = validation.get("event_validation") or {}
    if event_validation.get("status") == "passed":
        st.caption(
            "Model check passed across "
            f"{event_validation.get('actual_scored_game_count', 0)} scored games "
            f"({float(event_validation.get('fixture_count_coverage') or 0):.0%} fixture coverage)."
        )
    if not comparison["comparison_ready"]:
        all_cohorts_complete = coverage["completed"] == len(coverage["rows"])
        if all_cohorts_complete and event_validation.get("status") == "failed":
            st.warning(
                "The completed runs are saved, but MatchBalance is withholding the sales comparison "
                "because the model did not reproduce the unchanged tournament closely enough "
                "across the whole event."
            )
        else:
            st.info("Complete every cohort before producing the tournament-wide comparison.")
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Actual tournament margin",
        _format_model_value(comparison["actual_average_goal_margin"], "goals"),
    )
    metric_columns[1].metric(
        "MatchBalance projected margin",
        _format_model_value(comparison["matchbalance_projected_average_goal_margin"], "goals"),
        delta=(
            _format_reduction(comparison["estimated_goal_margin_reduction"], "goals")
            if comparison["estimated_goal_margin_reduction"] is not None else None
        ),
        delta_color="off",
    )
    metric_columns[2].metric(
        "Actual tournament 4+ rate",
        _format_model_value(comparison["actual_blowout_4plus_rate"], "rate"),
    )
    metric_columns[3].metric(
        "MatchBalance projected 4+ rate",
        _format_model_value(comparison["matchbalance_projected_blowout_4plus_rate"], "rate"),
        delta=(
            _format_reduction(comparison["estimated_blowout_4plus_rate_reduction"], "rate")
            if comparison["estimated_blowout_4plus_rate_reduction"] is not None else None
        ),
        delta_color="off",
    )
    if comparison["comparison_ready"]:
        move_columns = st.columns(4)
        move_columns[0].metric("Teams moved up", movements["moved_up"])
        move_columns[1].metric("Teams moved down", movements["moved_down"])
        move_columns[2].metric("Division unchanged", movements["unchanged"])
        move_columns[3].metric(
            "Pool changed within division",
            movements.get("pool_changed_within_division", 0),
        )
        with st.expander("Review team placements"):
            placement_filter = st.radio(
                "Team placement rows",
                ("Placement changes", "All teams"),
                horizontal=True,
                key=f"bt_event_placement_filter_{snapshot.generation}",
            )
            placement_rows = list(movements.get("rows") or ())
            if placement_filter == "Placement changes":
                placement_rows = [
                    row
                    for row in placement_rows
                    if str(row.get("move") or "stay") != "stay"
                    or str(row.get("actual_pool") or "")
                    != str(row.get("recommended_pool") or "")
                ]
            st.dataframe(
                pd.DataFrame(
                    {
                        "Team": row.get("event_team_name") or row.get("canonical_team_name") or "",
                        "Cohort": f"{_display_gender(row.get('gender'))} {str(row.get('age_group') or '').upper()}",
                        "Original division": row.get("actual_division") or "",
                        "MatchBalance division": row.get("recommended_division") or "",
                        "Original pool": row.get("actual_pool") or "",
                        "MatchBalance pool": row.get("recommended_pool") or "",
                        "Division decision": str(row.get("move") or "stay").replace("_", " ").title(),
                    }
                    for row in placement_rows
                ),
                hide_index=True,
                width="stretch",
            )
    else:
        st.caption(
            "Team placement recommendations remain hidden until every cohort finishes and the "
            "event-wide model check passes."
        )
    st.download_button(
        "Download tournament-director report",
        event_rollup_export(rollup),
        file_name=f"{event_key}-tournament-backtest.zip",
        mime="application/zip",
        key=f"bt_event_rollup_{snapshot.generation}_{predictor_sha256 or 'none'}",
        disabled=not comparison["comparison_ready"],
        help=(
            None
            if comparison["comparison_ready"]
            else "Available after every cohort finishes and unchanged-fixture calibration passes."
        ),
    )


def _run_reviewed_requests(
    event_key: str,
    readiness: list[ReviewedCohortReadiness],
    *,
    merge_map_version: str,
    base_dir,
) -> None:
    had_failure = False
    cancel_notice_key = f"bt_cancel_notice_{event_key}"
    for index, cohort in enumerate(readiness, start=1):
        if cohort.request is None:
            continue
        label = f"{_display_gender(cohort.gender)} {cohort.age_group.upper()}"
        with st.status(
            f"Running {label} ({index} of {len(readiness)})",
            expanded=True,
            state="running",
        ) as status:
            st.button(
                "Stop current run",
                key=f"bt_cancel_run_{event_key}_{cohort.age_group}_{cohort.gender}_{index}",
                on_click=_set_session_value,
                args=(cancel_notice_key, label),
                help="Stops the active cohort safely. You can run it again from this page.",
            )
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
                    merge_map_version=merge_map_version,
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
            st.session_state[f"bt_show_completed_{event_key}"] = True
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
    merge_map_version: str = "",
    team_reviewed: int = 0,
    team_total: int = 0,
) -> None:
    st.markdown("#### Run Backtest")
    st.caption(
        "Reseed matched teams within each tournament cohort while keeping every captured division, "
        "pool capacity, and fixture path fixed. MatchBalance treats the captured division order as strongest "
        "to weakest regardless of the division names, then balances pools within each division. "
        "Runs and evidence stay local."
    )
    cancelled_label = st.session_state.pop(f"bt_cancel_notice_{event_key}", "")
    if cancelled_label:
        st.info(f"{cancelled_label} was stopped safely. Select it and run it again when ready.")
    operator_snapshot = replace(
        snapshot,
        reviews=_current_reviews(snapshot),
        cohort_decisions=_current_cohort_decisions(snapshot),
        tiebreak_decision=_current_tiebreak_decision(snapshot)[0],
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
            or saved_snapshot.tiebreak_decision != operator_snapshot.tiebreak_decision
        ):
            unsaved_reason = "Save the current review, verification, and tiebreak changes before running"
    readiness = list(build_reviewed_cohort_readiness(saved_snapshot, links))
    if unsaved_reason:
        readiness = [
            replace(item, blockers=(unsaved_reason, *item.blockers))
            for item in readiness
        ]
    if not merge_map_version and not matching_blocker:
        matching_blocker = "Retry team matching; merge-synchronized team IDs are unavailable"
    if matching_blocker:
        readiness = [
            replace(item, request=None, blockers=(matching_blocker, *item.blockers))
            for item in readiness
        ]

    base_readiness = readiness
    selected_predictor_sha = canonical_predictor_sha256()
    request_items = [item for item in base_readiness if item.request is not None]
    base_ready = [item for item in base_readiness if item.ready]
    event_ready_for_history = bool(base_readiness) and len(base_ready) == len(base_readiness)
    preflight = None
    preflight_load_warning = ""
    expected_preflight_sha = ""
    if request_items:
        expected_preflight_sha = preflight_input_sha256(
            (item.request for item in request_items if item.request is not None),
            merge_map_version=merge_map_version,
            predictor_sha256=selected_predictor_sha,
        )
        try:
            cached_preflight = load_historical_preflight(event_key, base_dir=base_dir)
        except Exception as exc:
            preflight_load_warning = f"Saved historical preparation could not be read: {exc}"
        else:
            if cached_preflight and cached_preflight.input_sha256 == expected_preflight_sha:
                preflight = cached_preflight

    def prepare_history():
        if not request_items:
            return None
        with st.spinner("Preparing pre-event team ratings..."):
            try:
                result = run_historical_preflight(
                    (item.request for item in request_items if item.request is not None),
                    supabase_client,
                )
                write_historical_preflight(event_key, result, base_dir=base_dir)
                return result
            except HistoricalPreflightUnavailable as exc:
                st.error(f"MatchBalance could not prepare the historical ratings: {exc}")
            except Exception as exc:
                st.error(f"Historical rating preparation failed: {exc}")
        return None

    def apply_history(source, prepared):
        by_cohort = {
            (item.age_group, item.gender): item
            for item in (prepared.cohorts if prepared else ())
        }
        enriched = []
        for item in source:
            cohort_preflight = by_cohort.get((item.age_group, item.gender))
            history_blocker = ""
            if item.request is not None and cohort_preflight is None:
                history_blocker = "Historical ratings have not been prepared"
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
        return enriched

    scoped_divisions = backtest_scope_snapshot(saved_snapshot).roster.divisions
    schedule_attention = [
        assessment.reason
        for division in scoped_divisions
        if not (assessment := assess_replay_format(division)).ready
    ]
    capture_reasons = capture_verification_blockers(saved_snapshot)
    tiebreak_ready = _tiebreak_ready(saved_snapshot.tiebreak_decision)
    remaining_team_decisions = max(team_total - team_reviewed, 0)
    technical_rows = [
                {
                    "Check": "Event capture",
                    "Status": "Ready" if not capture_reasons else "Needs action",
                    "Action": "; ".join(capture_reasons) or "Published division list verified",
                },
                {
                    "Check": "Team identities",
                    "Status": (
                        "Unavailable"
                        if matching_blocker
                        else "Ready" if team_total and team_reviewed == team_total else "Needs action"
                    ),
                    "Action": (
                        matching_blocker
                        or (
                            f"All {team_total} team decisions complete"
                            if team_total and not remaining_team_decisions
                            else f"{remaining_team_decisions} team decisions remaining"
                        )
                    ),
                },
                {
                    "Check": "Tournament tiebreak rule",
                    "Status": "Ready" if tiebreak_ready else "Needs action",
                    "Action": (
                        "Published rule verified once for the event"
                        if tiebreak_ready
                        else "Verify the published rule once for the event"
                    ),
                },
                {
                    "Check": "Captured schedules",
                    "Status": "Ready" if not schedule_attention else "Needs engineering",
                    "Action": (
                        f"All {len(scoped_divisions)} division schedules are replay-ready"
                        if not schedule_attention
                        else f"{len(schedule_attention)} schedule patterns are unsupported"
                    ),
                },
                {
                    "Check": "Prediction engine",
                    "Status": "Ready",
                    "Action": "PitchRank Compare predictor with historical inputs",
                },
                {
                    "Check": "Pre-event team ratings",
                    "Status": (
                        "Ready"
                        if preflight and preflight.ready
                        else "Needs attention" if preflight else "Prepared when you run"
                    ),
                    "Action": (
                        f"{sum(item.eligible for item in preflight.cohorts)} entrants eligible"
                        if preflight and preflight.ready
                        else "Resolve missing pre-event ratings"
                        if preflight
                        else "Automatic"
                    ),
                },
            ]
    readiness = apply_history(base_readiness, preflight)
    ready = [item for item in readiness if item.ready]
    event_ready = bool(readiness) and len(ready) == len(readiness)
    cohort_count_label = f"{len(readiness)} cohort{'s' if len(readiness) != 1 else ''}"
    if not event_ready_for_history:
        all_blockers = list(dict.fromkeys(blocker for item in readiness for blocker in item.blockers))
        next_step = all_blockers[0] if all_blockers else "No tournament cohorts are available to run"
        st.warning(f"Next step: {next_step}")
    elif preflight is None:
        st.info(
            f"Ready to run {cohort_count_label}. MatchBalance will prepare the historical ratings "
            "automatically when you start."
        )
    elif event_ready:
        eligible = sum(item.eligible for item in preflight.cohorts)
        st.success(f"Ready to run {len(ready)} cohorts covering {eligible} entrants.")
    else:
        blocked = len(readiness) - len(ready)
        st.warning(f"{blocked} cohort(s) need historical evidence before the Backtest can run.")

    if preflight is None:
        primary_label = f"Prepare and run full tournament Backtest ({cohort_count_label})"
    elif preflight.ready:
        primary_label = f"Run full tournament Backtest ({cohort_count_label})"
    else:
        primary_label = f"Retry ratings and run full tournament Backtest ({cohort_count_label})"
    run_full = st.button(
        primary_label,
        type="primary",
        disabled=not event_ready_for_history,
        key=f"bt_run_full_{snapshot.generation}",
    )
    if run_full and event_ready_for_history:
        active_preflight = preflight if preflight and preflight.ready else prepare_history()
        if active_preflight is not None:
            targets = apply_history(base_ready, active_preflight)
            runnable = [item for item in targets if item.ready]
            if len(runnable) != len(base_ready):
                st.error("Some cohorts still lack usable pre-event ratings. Open advanced details below.")
            else:
                _run_reviewed_requests(
                    event_key,
                    runnable,
                    merge_map_version=merge_map_version,
                    base_dir=base_dir,
                )

    table_rows = []
    for index, item in enumerate(readiness):
        blockers = list(item.blockers)
        base_item = base_readiness[index]
        waiting_for_automatic_history = preflight is None and base_item.ready
        table_rows.append(
            {
                "Cohort": f"{_display_gender(item.gender)} {item.age_group.upper()}",
                "Teams": item.team_count,
                "Divisions": item.division_count,
                "Status": "Ready" if item.ready or waiting_for_automatic_history else "Blocked",
                "What remains": (
                    "Historical ratings are prepared automatically"
                    if waiting_for_automatic_history
                    else "; ".join(blockers)
                ),
            }
        )
    run_selected = False
    selected_base = None
    with st.expander("Advanced: run one cohort or inspect readiness"):
        st.caption(
            "MatchBalance uses the PitchRank Compare predictor with only ratings and games recorded "
            "before this tournament began."
        )
        if preflight_load_warning:
            st.warning(preflight_load_warning)
        st.dataframe(pd.DataFrame(technical_rows), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")
        if preflight:
            fallbacks = [
                entrant
                for cohort in preflight.cohorts
                for entrant in cohort.entrants
                if entrant.rating_basis != "historical_snapshot" and entrant.eligible
            ]
            if fallbacks:
                not_found_fallbacks = sum(
                    entrant.rating_fallback == RATING_FALLBACK_POLICY for entrant in fallbacks
                )
                missing_history_fallbacks = sum(
                    entrant.rating_fallback == MISSING_HISTORY_FALLBACK_POLICY
                    for entrant in fallbacks
                )
                st.caption(
                    f"Average estimates: {not_found_fallbacks} Not Found team(s) and "
                    f"{missing_history_fallbacks} matched team(s) without eligible pre-event history."
                )
        if readiness:
            selected_index = st.selectbox(
                "Cohort to run",
                tuple(range(len(readiness))),
                format_func=lambda index: (
                    f"{_display_gender(readiness[index].gender)} {readiness[index].age_group.upper()}"
                ),
                key=f"bt_run_cohort_{snapshot.generation}",
            )
            selected = readiness[selected_index]
            selected_base = base_readiness[selected_index]
            run_selected = st.button(
                (
                    "Run only this cohort"
                    if preflight and preflight.ready
                    else "Retry ratings and run only this cohort"
                    if preflight
                    else "Prepare ratings and run only this cohort"
                ),
                disabled=not selected_base.ready,
                help="\n".join(selected.blockers) or None,
                key=f"bt_run_selected_{snapshot.generation}",
            )
    if not readiness:
        st.info("No tournament cohorts are available to run.")
        _render_event_rollup(
            saved_snapshot,
            readiness,
            event_key,
            base_dir,
            predictor_sha256=selected_predictor_sha,
            merge_map_version=merge_map_version or None,
        )
        with st.expander("Cohort diagnostics (optional)"):
            _render_reviewed_result(event_key, base_dir)
        return
    if run_selected and selected_base is not None and selected_base.ready:
        active_preflight = preflight if preflight and preflight.ready else prepare_history()
        if active_preflight is not None:
            target = apply_history([selected_base], active_preflight)[0]
            if target.ready:
                _run_reviewed_requests(
                    event_key,
                    [target],
                    merge_map_version=merge_map_version,
                    base_dir=base_dir,
                )
            else:
                st.error("This cohort still lacks usable pre-event ratings.")
    completed_records = list_reviewed_runs(event_key, base_dir=base_dir)
    if completed_records:
        with st.expander(
            f"Previous cohort run files ({len(completed_records)})",
            expanded=bool(st.session_state.pop(f"bt_show_completed_{event_key}", False)),
        ):
            _render_reviewed_result(event_key, base_dir)
    _render_event_rollup(
        saved_snapshot,
        readiness,
        event_key,
        base_dir,
        predictor_sha256=selected_predictor_sha,
        merge_map_version=merge_map_version or None,
    )


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
        st.success("Saved the tournament capture, team decisions, cohort corrections, and tiebreak rule.")
    cohort_baseline = snapshot.cohort_decisions
    tiebreak_baseline = snapshot.tiebreak_decision
    decisions = _current_cohort_decisions(snapshot)
    tiebreak_decision, tiebreak_error = _current_tiebreak_decision(snapshot)
    snapshot = replace(
        snapshot,
        cohort_decisions=decisions,
        tiebreak_decision=tiebreak_decision,
    )
    effective = effective_roster(snapshot)
    raw_totals = tournament_totals(effective)
    display_snapshot = backtest_scope_snapshot(snapshot)
    scoped_roster = display_snapshot.roster
    totals = tournament_totals(scoped_roster)
    st.markdown("### " + _as_plain_text(totals["event_name"]))
    start = getattr(snapshot.roster, "event_start_date", None)
    end = getattr(snapshot.roster, "event_end_date", None)
    st.caption(f"Event {snapshot.roster.event_id} · {start or 'Date not stated'}"
               + (f" to {end}" if end and end != start else ""))
    event_key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
    matching_blocker = ""
    try:
        links, details, conflicts, merge_map_version = _sync_matches(
            display_snapshot, supabase_client, base_dir
        )
    except Exception as exc:
        st.warning(f"Team matching is unavailable right now: {exc}. The captured event can still be saved.")
        matching_blocker = "Retry team matching before running; merge-synchronized team IDs are unavailable"
        merge_map_version = ""
        details, conflicts = {}, {}
        links = load_links(event_key, base_dir=base_dir)
    rows = match_table(display_snapshot, links, details, conflicts=conflicts)
    matched = len({row["Match key"] for row in rows if row["Status"] == "Matched"})
    not_found = len({row["Match key"] for row in rows if row["Status"] == "Not found"})
    identity_reviewed = matched + not_found
    reviewed = sum(
        assess_replay_format(division).ready
        for division in scoped_roster.divisions
    )
    status_columns = st.columns(3)
    capture_verified = not capture_verification_blockers(snapshot)
    status_columns[0].metric("Capture verification", "Verified" if capture_verified else "Verify once")
    status_columns[1].metric(
        "Team review",
        "Unavailable" if matching_blocker else f"{identity_reviewed} / {totals['total_teams']}",
        help=(
            f"{matched} matched to PitchRank; {not_found} reviewed as not found."
            if not matching_blocker else None
        ),
    )
    status_columns[2].metric(
        "Structure",
        f"{reviewed} / {len(scoped_roster.divisions)} schedules ready",
        help=(
            f"{reviewed} schedules are replay-ready. Tournament tiebreak rule: "
            f"{'verified' if _tiebreak_ready(snapshot.tiebreak_decision) else 'not verified'}."
        ),
    )
    excluded_teams = raw_totals["total_teams"] - totals["total_teams"]
    excluded_divisions = raw_totals["divisions"] - totals["divisions"]
    if excluded_teams or excluded_divisions:
        st.caption(
            f"Backtest scope is U10-U18. The source capture retains {excluded_teams} teams "
            f"across {excluded_divisions} out-of-scope divisions."
        )
    section_key = f"bt_section_{snapshot.generation}"
    section = st.radio(
        "Backtest intake section",
        ("Overview", "Teams", "Backtest"),
        horizontal=True,
        key=section_key,
        label_visibility="collapsed",
    )

    if section == "Overview":
        columns = st.columns(4)
        for column, name, key in zip(columns, ("U10-U18 teams", "Divisions", "Pools", "Fixtures"),
                                     ("total_teams", "divisions", "pools", "fixtures")):
            column.metric(name, totals[key])
        st.markdown("#### Teams by tournament cohort and gender")
        st.caption("Counts use the bracket entered. A U11 team playing in a U12 bracket counts under U12.")
        with st.expander("View cohort team counts"):
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
        outstanding = len({
            row["Match key"] for row in rows if row["Status"] not in {"Matched", "Not found"}
        })
        st.markdown("#### What do I do next?")
        if not capture_verified:
            st.warning("Verify the published division list once so the Backtest uses the complete event.")
            capture_key = f"bt_show_capture_{snapshot.generation}"
            st.button(
                "Open capture verification",
                type="primary",
                key=f"bt_open_capture_{snapshot.generation}",
                on_click=_set_session_value,
                args=(capture_key, True),
            )
        elif matching_blocker:
            st.warning("Team matching is temporarily unavailable. Retry before running the Backtest.")
            st.button(
                "Retry team matching",
                type="primary",
                key=f"bt_retry_matching_{snapshot.generation}",
            )
        elif outstanding:
            st.warning(f"Review the remaining {outstanding} team identities.")
            st.button(
                "Continue matching teams",
                type="primary",
                key=f"bt_continue_teams_{snapshot.generation}",
                on_click=_set_session_value,
                args=(section_key, "Teams"),
            )
        elif not _tiebreak_ready(snapshot.tiebreak_decision):
            st.warning(
                "Verify the tournament's published tiebreak order once so tied simulated pools "
                "advance the correct team."
            )
            st.button(
                "Open tournament tiebreak rule",
                type="primary",
                key=f"bt_open_tiebreak_{snapshot.generation}",
                on_click=_set_session_value,
                args=(f"bt_show_structure_{snapshot.generation}", True),
            )
        else:
            st.success("The event capture and team identities are ready for Backtest checks.")
            st.button(
                "Continue to Backtest",
                type="primary",
                key=f"bt_continue_backtest_{snapshot.generation}",
                on_click=_set_session_value,
                args=(section_key, "Backtest"),
            )
        if reviewed < len(scoped_roster.divisions):
            st.info(
                f"MatchBalance setup: support is still being added for "
                f"{len(scoped_roster.divisions) - reviewed} unusual schedule patterns. "
                "You do not need to review those divisions."
            )
        st.markdown("#### Supporting details")
        show_structure = st.checkbox(
            "Inspect tournament structure",
            key=f"bt_show_structure_{snapshot.generation}",
        )
        show_capture = st.checkbox(
            "Show capture diagnostics",
            key=f"bt_show_capture_{snapshot.generation}",
        )
        if show_structure:
            _render_structure(display_snapshot)
        if show_capture:
            _render_capture_details(snapshot, supabase_client, base_dir)
    elif section == "Teams":
        st.markdown("#### Match tournament teams to PitchRank")
        st.caption(
            f"{identity_reviewed} of {totals['total_teams']} team identities reviewed · "
            f"{matched} matched · {not_found} not found with a Backtest rating fallback"
        )
        _render_match_editor(display_snapshot, rows, links, supabase_client, base_dir)
    else:
        _render_backtest_runner(
            snapshot,
            links,
            event_key,
            base_dir,
            supabase_client=supabase_client,
            matching_blocker=matching_blocker,
            merge_map_version=merge_map_version,
            team_reviewed=identity_reviewed,
            team_total=totals["total_teams"],
        )

    reviews = _current_reviews(snapshot)
    decisions = _current_cohort_decisions(snapshot)
    if st.button("Save progress", type="primary", key=f"bt_save_{snapshot.generation}"):
        if tiebreak_error:
            st.error(f"The intake was not saved: {tiebreak_error}")
        else:
            saved = replace(
                snapshot,
                reviews=reviews,
                cohort_decisions=decisions,
                tiebreak_decision=tiebreak_decision,
            )
            try:
                write_snapshot(
                    event_key,
                    saved,
                    base_dir=base_dir,
                    review_baseline=snapshot.reviews,
                    cohort_baseline=cohort_baseline,
                    tiebreak_baseline=tiebreak_baseline,
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
                st.session_state[f"bt_tiebreak_draft_{saved.generation}"] = (
                    _decision_to_tiebreak_draft(saved)
                )
                epoch_key = f"bt_review_epoch_{saved.generation}"
                st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1
                st.session_state[f"bt_saved_{saved.generation}"] = True
                st.rerun()
    export = {**replace(
                  snapshot,
                  reviews=reviews,
                  cohort_decisions=decisions,
                  tiebreak_decision=tiebreak_decision,
              ).to_dict(),
              "tournament_totals": raw_totals, "backtest_scope_totals": totals,
              "team_matches": rows, "links": asdict(links),
              "matching_conflicts": conflicts}
    import json

    st.download_button("Download Backtest intake JSON", json.dumps(export, indent=2, ensure_ascii=False),
                       file_name=f"gotsport-{snapshot.roster.event_id}-backtest-intake.json",
                       mime="application/json", key=f"bt_export_{snapshot.generation}")
