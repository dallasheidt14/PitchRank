"""Coverage for the post-scrape pool-enrichment orchestrator.

Stubs the schedule-page fetcher with a dict of ``group_id -> html`` so
the test stays HTTP-free. Persistence is exercised against ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from src.scrapers.gotsport_pool_enricher import (
    collect_group_ids,
    enrich_event_with_pools,
    enrich_event_with_schedule,
)
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.pool_assignments import read_pool_assignments

EVENT_KEY = "gotsport__42433__unknown"


def _ensure_intake(tmp_path: Path) -> None:
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)


def _schedule_html(label: str, panel_id: str, team_ids: list[str]) -> str:
    rows = "".join(
        f'<tr><td>{i+1}</td><td>'
        f'<a href="/org_event/events/42433/schedules?team={tid}">T{tid}</a>'
        f"</td></tr>"
        for i, tid in enumerate(team_ids)
    )
    return (
        f'<html><body>'
        f'<a role="button" aria-controls="{panel_id}">Bracket {label}</a>'
        f'<div id="{panel_id}"><table><tbody>{rows}</tbody></table></div>'
        f"</body></html>"
    )


def test_collect_group_ids_dedupes_and_sorts():
    records = [
        {"group_id": 365847},
        {"group_id": 365848},
        {"group_id": 365847},
        {"group_id": None},
        {"group_id": "365849"},
    ]
    assert collect_group_ids(records) == [365847, 365848, 365849]


def test_collect_group_ids_skips_unparseable_values():
    assert collect_group_ids([{"group_id": "abc"}, {"group_id": 365847}]) == [365847]


def test_enrich_persists_pools_for_each_unique_group_id(tmp_path: Path):
    _ensure_intake(tmp_path)
    records = [
        {"group_id": 365847, "bracket_name": "U13B", "group_name": "Red"},
        {"group_id": 365848, "bracket_name": "U13B", "group_name": "Washington"},
    ]
    htmls = {
        365847: _schedule_html("A", "collapse-1", ["100", "101"]) + _schedule_html("B", "collapse-2", ["200", "201"]),
        365848: _schedule_html("A", "collapse-3", ["300", "301", "302"]),
    }
    pools = enrich_event_with_pools(EVENT_KEY, records, fetcher=lambda gid: htmls[gid], base_dir=tmp_path)
    assert set(pools.keys()) == {"365847", "365848"}
    assert [p.team_count for p in pools["365847"]] == [2, 2]
    assert [p.team_count for p in pools["365848"]] == [3]
    # And the persisted artifact round-trips.
    loaded = read_pool_assignments(EVENT_KEY, base_dir=tmp_path)
    assert loaded == pools


def test_enrich_skips_failing_fetches(tmp_path: Path):
    """A fetcher exception for one group_id must not abort the whole pass —
    other tiers still get captured and persisted."""
    _ensure_intake(tmp_path)
    records = [
        {"group_id": 1, "bracket_name": "U13B", "group_name": "Red"},
        {"group_id": 2, "bracket_name": "U13B", "group_name": "White"},
    ]

    def fetcher(gid: int) -> str:
        if gid == 1:
            raise RuntimeError("boom")
        return _schedule_html("A", "collapse-3", ["1", "2"])

    pools = enrich_event_with_pools(EVENT_KEY, records, fetcher=fetcher, base_dir=tmp_path)
    assert "1" not in pools
    assert "2" in pools


def test_enrich_writes_empty_artifact_when_no_pools_captured(tmp_path: Path):
    _ensure_intake(tmp_path)
    records = [{"group_id": 1, "bracket_name": "U13B", "group_name": "Red"}]
    pools = enrich_event_with_pools(
        EVENT_KEY,
        records,
        fetcher=lambda gid: "<html><body>nothing</body></html>",
        base_dir=tmp_path,
    )
    assert pools == {}
    # File is written so callers can distinguish "ran enrichment, no pools"
    # from "never ran enrichment".
    assert (intake_dir(EVENT_KEY, base_dir=tmp_path) / "pool_assignments.json").exists()


# ---- enrich_event_with_schedule (pools + games + standings in one pass) ----


def _full_schedule_html(group_id: int, match_id: str, home: str, away: str, score: str) -> str:
    """Synthetic schedule page combining pool standings + match table."""
    return (
        "<html><body>"
        # Standings table (pool A header + 2 teams)
        f'<a role="button" aria-controls="collapse-{group_id*10}">Bracket A</a>'
        '<table>'
        '<tr><th></th><th>Team</th><th>MP</th><th>W</th><th>L</th><th>D</th>'
        '<th>GF</th><th>GA</th><th>GD</th><th>PTS</th></tr>'
        f'<tr><td>1</td><td><a href="/org_event/events/42433/schedules?team={home}">H</a></td>'
        '<td>1</td><td>1</td><td>0</td><td>0</td><td>2</td><td>0</td><td>2</td><td>3</td></tr>'
        f'<tr><td>2</td><td><a href="/org_event/events/42433/schedules?team={away}">A</a></td>'
        '<td>1</td><td>0</td><td>1</td><td>0</td><td>0</td><td>2</td><td>-2</td><td>0</td></tr>'
        '</table>'
        # Pool panel
        f'<div id="collapse-{group_id*10}">'
        f'<table><tbody>'
        f'<tr><td>1</td><td><a href="/org_event/events/42433/schedules?team={home}">H</a></td></tr>'
        f'<tr><td>2</td><td><a href="/org_event/events/42433/schedules?team={away}">A</a></td></tr>'
        '</tbody></table></div>'
        # Match table
        '<table>'
        '<tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>'
        '<th>Away Team</th><th>Location</th><th>Division</th></tr>'
        '<tr><td>1</td>'
        '<td>Feb 13, 2026<div class="text-color">5:00PM MST</div></td>'
        f'<td><a href="/org_event/events/42433/schedules?team={home}">H</a></td>'
        f'<td><a href="/org_event/events/42433/schedules?match={match_id}">{score}</a></td>'
        f'<td><a href="/org_event/events/42433/schedules?team={away}">A</a></td>'
        '<td><a href="#">Reach 11</a></td>'
        '<td><a href="#">U13 Boys Red</a></td></tr>'
        '</table>'
        "</body></html>"
    )


def test_enrich_with_schedule_writes_all_three_artifacts(tmp_path: Path):
    _ensure_intake(tmp_path)
    records = [{"group_id": 365847, "bracket_name": "U13B", "group_name": "Red"}]
    htmls = {365847: _full_schedule_html(365847, "1001", "100", "200", "2 - 0")}
    pools, games, standings = enrich_event_with_schedule(
        EVENT_KEY, records, fetcher=lambda gid: htmls[gid], base_dir=tmp_path
    )
    assert "365847" in pools
    assert len(games) == 1 and games[0].match_id == "1001"
    assert games[0].home_score == 2 and games[0].away_score == 0
    assert len(standings) == 2
    assert standings[0][0] == "365847"  # group_id paired with each Standing


def test_enrich_with_schedule_dedupes_games_across_tiers(tmp_path: Path):
    """A match_id appearing in two tier pages (rare cross-bracket) is
    written once — last-fetched wins."""
    _ensure_intake(tmp_path)
    records = [
        {"group_id": 1, "bracket_name": "U13B", "group_name": "Red"},
        {"group_id": 2, "bracket_name": "U13B", "group_name": "White"},
    ]
    htmls = {
        1: _full_schedule_html(1, "9999", "100", "200", "1 - 0"),
        2: _full_schedule_html(2, "9999", "100", "200", "1 - 0"),
    }
    _, games, _ = enrich_event_with_schedule(
        EVENT_KEY, records, fetcher=lambda gid: htmls[gid], base_dir=tmp_path
    )
    assert len(games) == 1
    assert games[0].match_id == "9999"


def test_enrich_with_schedule_isolates_per_tier_failures(tmp_path: Path):
    _ensure_intake(tmp_path)
    records = [
        {"group_id": 1, "bracket_name": "U13B", "group_name": "Red"},
        {"group_id": 2, "bracket_name": "U13B", "group_name": "White"},
    ]

    def fetcher(gid: int) -> str:
        if gid == 1:
            raise RuntimeError("boom")
        return _full_schedule_html(2, "2002", "100", "200", "1 - 1")

    pools, games, _ = enrich_event_with_schedule(
        EVENT_KEY, records, fetcher=fetcher, base_dir=tmp_path
    )
    assert "1" not in pools and "2" in pools
    assert len(games) == 1 and games[0].match_id == "2002"
