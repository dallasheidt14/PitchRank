"""Tests for where a GotSport team scrape starts reading the team's games."""

import asyncio
import os
import sys
from datetime import date, datetime
from unittest.mock import Mock, call, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.drain_queue as d
import scripts.process_missing_games as pm
import scripts.scrape_games as s
from src.base import GameData
from src.scrapers.gotsport import scrape_start_date

GS = "gs-provider"
# January-July, where the season year is not the calendar year.
TODAY = date(2027, 3, 1)
SEASON_START = datetime(2026, 8, 1)
# An opponent's import moved the team's last_scraped_at here, after the games we lack were played.
STAMPED = "2027-02-28T18:08:45+00:00"


def _start_as_of_today(anchor=None):
    return scrape_start_date(anchor, today=TODAY)


def _team(team_id, gs_id, last_scraped_at=STAMPED):
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": GS,
        "provider_team_id": gs_id,
        "age_group": "u12",
        "birth_year": 2014,
        "last_scraped_at": last_scraped_at,
    }


def test_in_season_the_start_is_aug_1():
    assert scrape_start_date(today=date(2026, 11, 23)) == date(2026, 8, 1)
    assert scrape_start_date(today=date(2027, 3, 1)) == date(2026, 8, 1)


def test_early_in_a_season_the_start_reaches_90_days_back():
    assert scrape_start_date(today=date(2027, 9, 15)) == date(2027, 6, 17)


def test_a_request_dated_before_aug_1_still_covers_its_own_date():
    assert scrape_start_date(date(2026, 7, 25), today=date(2026, 11, 23)) == date(2026, 4, 26)


def test_a_july_31_request_handled_after_aug_1_covers_its_date():
    assert scrape_start_date(date(2027, 7, 31), today=date(2027, 8, 2)) == date(2027, 5, 2)


def _claim(request_id, team_id, gs_id, game_date):
    return {
        "id": request_id,
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": GS,
        "provider_team_id": gs_id,
        "game_date": game_date,
        "priority": 1,
        "request_type": "missing_game",
    }


def test_clear_queue_reads_each_claimed_request_from_its_own_date_and_top_ups_from_today(tmp_path):
    claimed = [_claim("req-1", "t-1", "564594", "2026-07-25"), _claim("req-3", "t-3", "700003", "2027-02-28")]
    meta = {t: {"age_group": "u12", "birth_year": 2014, "last_scraped_at": STAMPED} for t in ("t-1", "t-3")}

    with (
        patch.object(d, "create_client", return_value=Mock()),
        patch.object(d, "GotSportScraper") as gs,
        patch.object(d, "_claim_queue_items", return_value=claimed),
        patch.object(d, "_fetch_team_metadata", return_value=meta),
        patch.object(d, "_fetch_topup_teams", return_value=[_team("t-2", "600001")]),
        patch.object(d, "_bulk_log_team_scrapes", Mock()),
        patch.object(d, "_finalize_queue_items", Mock()),
        patch.object(d, "scrape_start_date", _start_as_of_today),
    ):
        gs.return_value._get_provider_id.return_value = GS
        gs.return_value.scrape_team_games.return_value = []
        asyncio.run(d.drain_queue(limit=3, concurrency=1, dry_run=False, output_file=str(tmp_path / "out.jsonl")))

    calls = sorted(gs.return_value.scrape_team_games.call_args_list, key=lambda c: c.args[0])
    assert calls == [
        call("564594", since_date=datetime(2026, 4, 26)),
        call("600001", since_date=SEASON_START),
        call("700003", since_date=SEASON_START),
    ]


def _run_manual_scrape(tmp_path, team=None, **kwargs):
    teams_rpc = Mock(return_value=[team or _team("t-1", "564594")])
    with (
        patch.object(s, "create_client", return_value=Mock()),
        patch.object(s, "GotSportScraper") as gs,
        patch.object(s, "call_rpc_with_fallback", teams_rpc),
        patch.object(s, "_bulk_log_team_scrapes", Mock()),
        patch.object(s, "scrape_start_date", _start_as_of_today),
    ):
        gs.return_value._get_provider_id.return_value = GS
        gs.return_value.scrape_team_games.return_value = []
        asyncio.run(s.scrape_games(output_file=str(tmp_path / "out.jsonl"), concurrency=1, **kwargs))
    return gs.return_value.scrape_team_games, teams_rpc


def test_manual_scrape_reads_every_team_from_the_same_start(tmp_path):
    scrape, _ = _run_manual_scrape(tmp_path)
    scrape.assert_called_once_with("564594", since_date=SEASON_START)


def test_manual_bootstrap_scrape_of_a_never_scraped_team_reads_from_the_same_start(tmp_path):
    scrape, teams_rpc = _run_manual_scrape(tmp_path, team=_team("t-1", "564594", None), null_teams_only=True)
    assert teams_rpc.call_args.args[2]["p_null_only"] is True
    scrape.assert_called_once_with("564594", since_date=SEASON_START)


def test_a_typed_start_date_is_used_as_given_even_before_aug_1(tmp_path):
    scrape, _ = _run_manual_scrape(tmp_path, since_date=date(2026, 7, 1))
    scrape.assert_called_once_with("564594", since_date=datetime(2026, 7, 1))


def test_a_typed_start_later_than_the_default_reaches_the_scraper_from_the_command_line(tmp_path):
    out = str(tmp_path / "out.jsonl")
    argv = ["scrape_games.py", "--since-date", "2027-02-01", "--output", out, "--concurrency", "1"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(s, "create_client", return_value=Mock()),
        patch.object(s, "GotSportScraper") as gs,
        patch.object(s, "call_rpc_with_fallback", return_value=[_team("t-1", "564594")]),
        patch.object(s, "_bulk_log_team_scrapes", Mock()),
        patch.object(s, "scrape_start_date", _start_as_of_today),
    ):
        gs.return_value._get_provider_id.return_value = GS
        gs.return_value.scrape_team_games.return_value = []
        s.main()
    gs.return_value.scrape_team_games.assert_called_once_with("564594", since_date=datetime(2027, 2, 1))


def _game(day):
    return GameData(
        provider_id="gotsport",
        team_id="564594",
        opponent_id="250383",
        team_name="",
        opponent_name="Opponent",
        game_date=day,
        home_away="H",
        goals_for=1,
        goals_against=0,
        result="W",
        competition="",
        venue="",
        meta={},
    )


def _drain_request_dated(request_date, game_days):
    processor = pm.MissingGamesProcessor(Mock(), dry_run=False)
    scrape = Mock(return_value=[_game(day) for day in game_days])
    processor.scrapers["gotsport"].scrape_team_games = scrape
    with patch.object(pm, "scrape_start_date", _start_as_of_today):
        rows = processor.scrape_games_for_date("gotsport", "564594", request_date)
    return scrape, [r["game_date"] for r in rows]


def test_the_drainer_reads_from_aug_1_not_90_days_back():
    scrape, kept = _drain_request_dated("2027-03-01", ["2026-07-31", "2026-08-01", "2026-08-24", "2027-02-28"])
    scrape.assert_called_once_with("564594", since_date=SEASON_START)
    assert kept == ["2026-08-01", "2026-08-24", "2027-02-28"]


def test_the_drainer_keeps_an_older_request_date_and_stops_90_days_after_it():
    scrape, kept = _drain_request_dated("2026-07-25", ["2026-04-25", "2026-07-25", "2026-10-23", "2026-10-24"])
    scrape.assert_called_once_with("564594", since_date=datetime(2026, 4, 26))
    assert kept == ["2026-07-25", "2026-10-23"]


def test_a_queued_request_reaches_the_scrape_window_with_its_own_date():
    processor = pm.MissingGamesProcessor(Mock(), dry_run=False)
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.get_gotsport_alias = Mock(return_value=None)
    processor.update_request_status = Mock()
    scrape = Mock(return_value=[_game("2026-07-25")])
    processor.scrapers["gotsport"].scrape_team_games = scrape
    request = {
        "id": "req-1",
        "team_id_master": "t-1",
        "team_name": "Team t-1",
        "game_date": "2026-07-25",
        "provider_id": GS,
        "provider_team_id": "564594",
    }

    with patch.object(pm, "scrape_start_date", _start_as_of_today):
        processor.process_request(request)

    scrape.assert_called_once_with("564594", since_date=datetime(2026, 4, 26))
    assert [[g["game_date"] for g in games] for _, games, _ in processor._pending_imports] == [["2026-07-25"]]
