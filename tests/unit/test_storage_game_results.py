"""Round-trip + coverage check for ``intake/game_results.jsonl`` /
``intake/standings.jsonl`` artifacts."""

from __future__ import annotations

from pathlib import Path

from src.scrapers.gotsport_results_parser import GameResult, Standing
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.game_results import (
    check_local_results_coverage,
    read_game_results,
    read_standings,
    write_game_results,
    write_standings,
)

EVENT_KEY = "gotsport__42433__unknown"


def _game(match_id: str, home: str, away: str, hs: int | None = 1, as_: int | None = 0) -> GameResult:
    return GameResult(
        match_id=match_id,
        home_provider_team_id=home,
        home_team_name=f"Home {home}",
        away_provider_team_id=away,
        away_team_name=f"Away {away}",
        home_score=hs,
        away_score=as_,
        date_text="Feb 13, 2026",
        time_text="5:00PM MST",
        location="Reach 11",
        division_label="U13 Boys Red",
    )


def test_game_results_round_trip(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    games = [_game("1", "100", "200"), _game("2", "300", "400", 2, 2)]
    write_game_results(EVENT_KEY, games, base_dir=tmp_path)
    loaded = read_game_results(EVENT_KEY, base_dir=tmp_path)
    assert loaded == games


def test_standings_round_trip_preserves_group_id(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    rows = [
        ("365847", Standing(rank=1, provider_team_id="100", team_name="Rush", matches_played=3,
                             wins=2, losses=0, draws=1, goals_for=9, goals_against=2,
                             goal_diff=7, points=7)),
        ("365847", Standing(rank=2, provider_team_id="200", team_name="Phoenix", matches_played=3,
                             wins=2, losses=0, draws=1, goals_for=7, goals_against=1,
                             goal_diff=5, points=7)),
    ]
    write_standings(EVENT_KEY, rows, base_dir=tmp_path)
    loaded = read_standings(EVENT_KEY, base_dir=tmp_path)
    assert loaded == rows


def test_check_coverage_not_imported_when_file_absent(tmp_path: Path):
    assert check_local_results_coverage(EVENT_KEY, ["100", "200"], base_dir=tmp_path) == "not_imported"


def test_check_coverage_complete_when_all_teams_have_games(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    write_game_results(
        EVENT_KEY,
        [_game("1", "100", "200"), _game("2", "300", "400")],
        base_dir=tmp_path,
    )
    assert (
        check_local_results_coverage(EVENT_KEY, ["100", "200", "300", "400"], base_dir=tmp_path)
        == "complete"
    )


def test_check_coverage_partial_when_some_teams_missing(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    write_game_results(EVENT_KEY, [_game("1", "100", "200")], base_dir=tmp_path)
    assert (
        check_local_results_coverage(EVENT_KEY, ["100", "200", "300"], base_dir=tmp_path)
        == "partial"
    )


def test_check_coverage_treats_either_side_as_played(tmp_path: Path):
    """A team appearing as away (not home) still counts as having games."""
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    write_game_results(EVENT_KEY, [_game("1", "100", "200")], base_dir=tmp_path)
    assert check_local_results_coverage(EVENT_KEY, ["200"], base_dir=tmp_path) == "complete"


def test_check_coverage_not_imported_when_file_empty(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    write_game_results(EVENT_KEY, [], base_dir=tmp_path)
    assert check_local_results_coverage(EVENT_KEY, ["100"], base_dir=tmp_path) == "not_imported"
