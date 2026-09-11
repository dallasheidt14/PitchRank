"""Backtest-only event totals, structure inspection and editable team matches."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

import pandas as pd
import streamlit as st

from src.tournaments.backtest_intake_state import (
    BacktestSnapshot,
    DivisionReview,
    entrant_key,
    read_snapshot,
    reviews_for_capture,
    structure_hash,
    tournament_totals,
    write_snapshot,
)
from src.tournaments.backtest_link_store import EventLinks, TeamLink, load_links, update_links
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
    conflicts = conflicts or {}
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
    links = replace(links, links=canonical_links)
    return links, _details(client, [link.team_id_master for link in links.links]), conflicts


def _load_saved(base_dir) -> None:
    from tournament_intake import _BACKTEST_KEYS

    paths = sorted(base_dir.glob("gotsport__*/intake/event_intake.json"))
    if not paths:
        return
    with st.expander("Open a saved Backtest event", expanded=False):
        keys = [path.parent.parent.name for path in paths]
        selected = st.selectbox("Saved event", keys, key="_backtest_saved_event")
        if st.button("Open saved intake", key="_backtest_open_saved"):
            try:
                snapshot = read_snapshot(selected, base_dir=base_dir)
            except Exception as exc:
                st.error(f"Could not open this saved intake: {exc}")
                return
            # This is the only object the Backtest results and save path read.
            st.session_state[_BACKTEST_KEYS.snapshot] = snapshot
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
    if not snapshot.reviews:
        key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
        try:
            saved = read_snapshot(key, base_dir=base_dir)
        except FileNotFoundError:
            pass
        except Exception as exc:
            st.warning(f"Saved division reviews could not be loaded: {exc}")
        else:
            snapshot = replace(snapshot, reviews=reviews_for_capture(snapshot.roster, saved.reviews))
            st.session_state[_BACKTEST_KEYS.snapshot] = snapshot
    # Even absence is a baseline. Reading again on every rerender could turn
    # another session's new notes into the baseline for our already-open form.
    st.session_state[loaded_key] = True
    return snapshot


def _render_match_editor(snapshot: BacktestSnapshot, rows: list[dict], client: Any, base_dir) -> None:
    from tournament_intake import _as_plain_text, _seeding_provider_id_lookup

    if not rows:
        return
    generation = snapshot.generation
    mode = st.radio("Show teams", ("All teams", "Needs review"), horizontal=True, key=f"bt_filter_{generation}")
    visible = rows if mode == "All teams" else [row for row in rows if row["Status"] != "Matched"]
    st.dataframe(
        pd.DataFrame(visible).drop(columns=["source_index", "Match key"], errors="ignore"),
        hide_index=True, width="stretch"
    )
    if not visible:
        st.success("Every captured team has a match. Choose All teams to inspect or change one.")
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
    st.caption(_as_plain_text(f"Entered in: {display['Division']} · Registration {registration}"))
    if display["Match issue"]:
        st.warning(_as_plain_text(display["Match issue"]))
    if display["PitchRank ID"]:
        label = "Current match" if display["Status"] == "Matched" else "Saved suggestion"
        st.write(f"{label}: {display['PitchRank team']} ({display['PitchRank ID']})")
        if st.button("Clear this match", key=f"bt_clear_{generation}_{selected}"):
            try:
                update_links(event_key, event_id=snapshot.roster.event_id,
                             removed_registration_ids=(registration,), base_dir=base_dir)
            except Exception as exc:
                st.error(f"The match was not cleared: {exc}")
            else:
                st.rerun()

    if outcome.candidates:
        st.caption("Suggested candidates — confirm the squad before choosing one.")
        st.dataframe(pd.DataFrame(list(outcome.candidates)), hide_index=True, width="stretch")
    reference = st.text_input("PitchRank team link or ID, or GotSport team link or ID",
                              value=display["PitchRank ID"], key=f"bt_reference_{generation}_{selected}")
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
            update_links(event_key, event_id=snapshot.roster.event_id, changed_links=(link,), base_dir=base_dir)
        except Exception as exc:
            st.error(f"The match was not saved: {exc}")
        else:
            st.rerun()


def _render_structure(snapshot: BacktestSnapshot) -> tuple[DivisionReview, ...]:
    from src.tournaments.backtest_event_intake import summarize_structure
    from tournament_intake import _as_plain_text

    st.markdown("#### Tournament structure")
    st.dataframe(pd.DataFrame(summarize_structure(snapshot.roster.divisions)), hide_index=True, width="stretch")
    previous = {review.group_id: review for review in reviews_for_capture(snapshot.roster, snapshot.reviews)}
    reviews = []
    for division in snapshot.roster.divisions:
        label = division.division_label or f"Division {division.group_id}"
        digest = structure_hash(division)
        saved = previous.get(division.group_id)
        if saved is None:
            saved = DivisionReview(division.group_id, digest)
        widget = f"bt_division_{snapshot.generation}_{division.group_id}"
        epoch = st.session_state.get(f"bt_review_epoch_{snapshot.generation}", 0)
        if epoch:
            widget += f"_{epoch}"
        with st.expander(label, expanded=False):
            if division.source_url:
                st.link_button("Open published division", division.source_url)
            memberships = [
                {"Pool": pool.label, "Team": member.team_name, "Registration ID": member.registration_id,
                 "Final standing (not seed)": member.standings_position}
                for pool in division.pools for member in pool.members
            ]
            st.dataframe(pd.DataFrame(memberships), hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame([asdict(fixture) for fixture in division.fixtures]),
                         hide_index=True, width="stretch")
            for warning in division.warnings:
                st.warning(_as_plain_text(warning))
            if division.rules_links:
                st.dataframe(pd.DataFrame([asdict(link) for link in division.rules_links]), hide_index=True)
            notes = st.text_area("Published format / advancement / tiebreaker notes", value=saved.notes,
                                 key=f"{widget}_notes",
                                 help="Record the source's rules; final standings do not prove advancement rules.")
            source_url = st.text_input("Rules source URL", value=saved.source_url, key=f"{widget}_source")
            checked = st.checkbox("I checked this division's teams, pools and fixtures against the source",
                                   value=saved.checked, key=f"{widget}_checked")
            reviews.append(DivisionReview(division.group_id, digest, notes, source_url, checked))
    return tuple(reviews)


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


def render_intake(supabase_client: Any) -> None:
    from tournament_intake import _BACKTEST_KEYS, _as_plain_text, _render_seeding_event_scrape, reports_dir

    base_dir = reports_dir()
    st.markdown("### Completed tournament intake")
    st.caption("Capture the event, review its teams and structure, and save it for later Backtest work.")
    _load_saved(base_dir)
    _render_seeding_event_scrape(supabase_client, keys=_BACKTEST_KEYS)
    snapshot = st.session_state.get(_BACKTEST_KEYS.snapshot)
    if snapshot is None:
        return
    snapshot = _restore_review_baseline(snapshot, base_dir)
    if st.session_state.pop(f"bt_saved_{snapshot.generation}", False):
        st.success("Saved the tournament name, teams, structure, matching outcomes and division reviews.")
    totals = tournament_totals(snapshot.roster)
    st.markdown("### " + _as_plain_text(totals["event_name"]))
    start = getattr(snapshot.roster, "event_start_date", None)
    end = getattr(snapshot.roster, "event_end_date", None)
    st.caption(f"Event {snapshot.roster.event_id} · {start or 'Date not stated'}"
               + (f" to {end}" if end and end != start else ""))
    columns = st.columns(4)
    for column, name, key in zip(columns, ("Total teams", "Divisions", "Pools", "Fixtures"),
                                 ("total_teams", "divisions", "pools", "fixtures")):
        column.metric(name, totals[key])
    st.markdown("#### Teams by tournament cohort and gender")
    st.caption("Counts use the bracket entered. A U11 team playing in a U12 bracket counts under U12.")
    st.dataframe(pd.DataFrame(totals["cohorts"]), hide_index=True, width="stretch")
    if totals["cohort_entries"] != totals["total_teams"]:
        st.info(f"{totals['total_teams']} distinct registrations appear in {totals['cohort_entries']} cohort entries; "
                "registrations entered in more than one cohort count in each.")
    if totals["unidentified_teams"]:
        st.warning(f"{totals['unidentified_teams']} source team entries have no registration ID. "
                   "They are included in the totals and need identity review for possible duplicates.")

    _render_results(totals["results"])
    quality = summarize_structure_quality(snapshot.roster.divisions)
    if not getattr(snapshot.roster, "completed_event", False):
        st.warning("This saved walk predates full-event Backtest capture. Its coverage has not been verified.")
    if not snapshot.roster.is_complete:
        st.warning("Partial capture: the totals above describe the teams found so far.")
    for warning in snapshot.roster.warnings:
        st.caption(_as_plain_text(warning))
    st.markdown("#### Capture checks")
    st.dataframe(pd.DataFrame([quality]), hide_index=True, width="stretch")
    reviews = _render_structure(snapshot)

    st.markdown("#### Match tournament teams to PitchRank")
    event_key = existing_event_key("gotsport", snapshot.roster.event_id, base_dir=base_dir)
    try:
        links, details, conflicts = _sync_matches(snapshot, supabase_client, base_dir)
    except Exception as exc:
        st.warning(f"Team matching is unavailable right now: {exc}. The captured event can still be saved.")
        details, conflicts = {}, {}
        try:
            links = load_links(event_key, base_dir=base_dir)
        except Exception as saved_exc:
            st.warning(f"Saved team links could not be read: {saved_exc}")
            links = EventLinks(event_id=snapshot.roster.event_id)
    rows = match_table(snapshot, links, details, conflicts=conflicts)
    matched = len({row["Match key"] for row in rows if row["Status"] == "Matched"})
    st.caption(f"{matched} of {totals['total_teams']} teams matched · "
               f"{sum(review.checked for review in reviews)} of {len(reviews)} divisions checked")
    _render_match_editor(snapshot, rows, supabase_client, base_dir)

    if st.button("Save Backtest intake", type="primary", key=f"bt_save_{snapshot.generation}"):
        saved = replace(snapshot, reviews=reviews)
        try:
            write_snapshot(event_key, saved, base_dir=base_dir, review_baseline=snapshot.reviews)
            saved = read_snapshot(event_key, base_dir=base_dir)
        except Exception as exc:
            st.error(f"The intake was not saved: {exc}")
        else:
            st.session_state[_BACKTEST_KEYS.snapshot] = saved
            epoch_key = f"bt_review_epoch_{saved.generation}"
            st.session_state[epoch_key] = st.session_state.get(epoch_key, 0) + 1
            st.session_state[f"bt_saved_{saved.generation}"] = True
            st.rerun()
    export = {**replace(snapshot, reviews=reviews).to_dict(),
              "tournament_totals": totals, "team_matches": rows, "links": asdict(links),
              "matching_conflicts": conflicts}
    import json

    st.download_button("Download Backtest intake JSON", json.dumps(export, indent=2, ensure_ascii=False),
                       file_name=f"gotsport-{snapshot.roster.event_id}-backtest-intake.json",
                       mime="application/json", key=f"bt_export_{snapshot.generation}")
