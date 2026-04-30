"""Unit tests for ``src.tournaments.bracket_report``.

Covers the per-tier join of ``pool_assignments.json`` +
``standings.jsonl`` + ``game_results.jsonl`` into structured bracket
tables and a knockout / showcase block. All file I/O hits ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from src.scrapers.gotsport_pool_parser import PoolAssignment
from src.scrapers.gotsport_results_parser import GameResult, Standing
from src.tournaments.bracket_report import (
    KnockoutMatch,
    PoolTable,
    TierReport,
    build_tier_reports,
)
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.game_results import write_game_results, write_standings
from src.tournaments.storage.pool_assignments import write_pool_assignments

EVENT_KEY = "gotsport__42433__unknown"


def _ensure_intake(tmp_path: Path) -> None:
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)


def _standing(rank: int, pid: str, *, name: str | None = None, points: int = 0) -> Standing:
    return Standing(
        rank=rank,
        provider_team_id=pid,
        team_name=name or f"Team {pid}",
        matches_played=3,
        wins=points // 3,
        losses=0,
        draws=0,
        goals_for=points,
        goals_against=0,
        goal_diff=points,
        points=points,
    )


def _game(
    match_id: str,
    home_pid: str,
    away_pid: str,
    *,
    home_score: int | None = 1,
    away_score: int | None = 0,
    division_label: str | None = "U13 Boys Red",
) -> GameResult:
    return GameResult(
        match_id=match_id,
        home_provider_team_id=home_pid,
        home_team_name=f"Home {home_pid}",
        away_provider_team_id=away_pid,
        away_team_name=f"Away {away_pid}",
        home_score=home_score,
        away_score=away_score,
        date_text="Feb 14, 2026",
        time_text="9:00AM MST",
        location="Reach 11",
        division_label=division_label,
    )


def _two_pool_layout() -> dict[str, list[PoolAssignment]]:
    return {
        "365840": [
            PoolAssignment(label="A", bracket_id="501337", provider_team_ids=("100", "101", "102", "103")),
            PoolAssignment(label="B", bracket_id="501338", provider_team_ids=("200", "201", "202", "203")),
        ],
    }


def test_build_tier_reports_returns_empty_when_no_group_ids_requested(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    assert build_tier_reports(EVENT_KEY, [], base_dir=tmp_path) == []


def test_build_tier_reports_skips_groups_without_pool_assignments(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    reports = build_tier_reports(EVENT_KEY, ["999999"], base_dir=tmp_path)
    assert reports == []


def test_build_tier_reports_filters_standings_by_pool_provider_ids(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(
        EVENT_KEY,
        [
            ("365840", _standing(1, "100", points=9)),
            ("365840", _standing(2, "101", points=6)),
            ("365840", _standing(3, "102", points=3)),
            ("365840", _standing(4, "103", points=0)),
            ("365840", _standing(1, "200", points=7)),
            ("365840", _standing(2, "201", points=6)),
            ("365840", _standing(3, "202", points=3)),
            ("365840", _standing(4, "203", points=1)),
        ],
        base_dir=tmp_path,
    )
    write_game_results(EVENT_KEY, [], base_dir=tmp_path)
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert isinstance(tier, TierReport)
    assert tier.group_id == "365840"
    assert [pool.bracket_label for pool in tier.pool_play] == ["A", "B"]
    assert [s.provider_team_id for s in tier.pool_play[0].rows] == ["100", "101", "102", "103"]
    assert [s.provider_team_id for s in tier.pool_play[1].rows] == ["200", "201", "202", "203"]


def test_build_tier_reports_orders_pool_rows_by_rank(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    # Write in rank-shuffled order; the reader must restore on-page order.
    write_standings(
        EVENT_KEY,
        [
            ("365840", _standing(3, "102")),
            ("365840", _standing(1, "100")),
            ("365840", _standing(4, "103")),
            ("365840", _standing(2, "101")),
        ],
        base_dir=tmp_path,
    )
    write_game_results(EVENT_KEY, [], base_dir=tmp_path)
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert [s.rank for s in tier.pool_play[0].rows] == [1, 2, 3, 4]


def test_build_tier_reports_classifies_pool_play_vs_knockout(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(EVENT_KEY, [], base_dir=tmp_path)
    write_game_results(
        EVENT_KEY,
        [
            _game("pool-A", "100", "101"),         # within Bracket A → pool play
            _game("pool-B", "200", "203"),         # within Bracket B → pool play
            _game("knockout-1", "100", "200"),     # cross-pool → knockout
            _game("knockout-2", "201", "102", home_score=2, away_score=2),
        ],
        base_dir=tmp_path,
    )
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert {m.match_id for m in tier.knockout} == {"knockout-1", "knockout-2"}


def test_build_tier_reports_marks_winner_on_knockout_match(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(EVENT_KEY, [], base_dir=tmp_path)
    write_game_results(
        EVENT_KEY,
        [
            _game("home-wins", "100", "200", home_score=3, away_score=1),
            _game("away-wins", "101", "201", home_score=0, away_score=2),
            _game("draw", "102", "202", home_score=1, away_score=1),
            _game("unplayed", "103", "203", home_score=None, away_score=None),
        ],
        base_dir=tmp_path,
    )
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    winners = {m.match_id: m.winner for m in tier.knockout}
    assert winners == {"home-wins": "home", "away-wins": "away", "draw": "draw", "unplayed": "tbd"}


def test_build_tier_reports_uses_division_label_as_title(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(EVENT_KEY, [], base_dir=tmp_path)
    write_game_results(
        EVENT_KEY,
        [_game("m1", "100", "101", division_label="U13 Boys Red")],
        base_dir=tmp_path,
    )
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert tier.title == "U13 Boys Red"


def test_build_tier_reports_empty_pool_table_when_standings_missing(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(EVENT_KEY, [], base_dir=tmp_path)
    write_game_results(EVENT_KEY, [], base_dir=tmp_path)
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert tier.pool_play[0].rows == ()
    assert tier.pool_play[1].rows == ()


def test_build_tier_reports_drops_games_referencing_unknown_provider_ids(tmp_path: Path):
    _ensure_intake(tmp_path)
    write_pool_assignments(EVENT_KEY, _two_pool_layout(), base_dir=tmp_path)
    write_standings(EVENT_KEY, [], base_dir=tmp_path)
    write_game_results(
        EVENT_KEY,
        [
            _game("orphan", "9999", "8888"),  # neither team in any pool
            _game("knockout-1", "100", "200"),
        ],
        base_dir=tmp_path,
    )
    [tier] = build_tier_reports(EVENT_KEY, ["365840"], base_dir=tmp_path)
    assert {m.match_id for m in tier.knockout} == {"knockout-1"}


def test_pool_table_and_knockout_match_are_frozen_dataclasses():
    pool = PoolTable(bracket_label="A", rows=())
    knockout = KnockoutMatch(
        match_id="m1",
        home_team_name="H",
        away_team_name="A",
        home_score=1,
        away_score=0,
        location=None,
        date_text="",
        time_text="",
        winner="home",
    )
    # Frozen dataclasses raise FrozenInstanceError on attribute mutation.
    import dataclasses

    try:
        pool.bracket_label = "B"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("PoolTable should be frozen")
    try:
        knockout.winner = "draw"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("KnockoutMatch should be frozen")
