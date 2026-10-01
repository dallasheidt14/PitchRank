"""
When the queue is empty the 15-minute drainer tops up from the teams table,
using drain_queue's selector, instead of exiting with nothing scraped. These
drive process_all end to end so the top-up's own fetch goes through the double.
"""
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import Mock, patch

import scripts.process_missing_games as pmg
from src.scrapers.gotsport import TeamNotFoundError, WAFBlockedError


class _Query:
    """A deferred builder: it records nothing until .execute()."""

    def __init__(self, db, kind, name, payload=None):
        self.db = db
        self.kind = kind
        self.name = name
        self.payload = payload
        self.filters = []

    def __getattr__(self, method):
        def chain(*args, **kwargs):
            if method in ("update", "insert"):
                self.payload = args[0]
            self.filters.append((method, args))
            return self

        return chain

    def execute(self):
        self.db.executed.append((self.kind, self.name, self.payload, self.filters))
        if self.kind == "rpc" and self.name == "find_topup_teams":
            offset = self.payload["p_offset"]
            return Mock(data=self.db.topup_rows[offset : offset + self.payload["p_row_limit"]])
        if self.kind == "table" and self.name == "scrape_requests" and not self.payload:
            return Mock(data=self.db.pending)
        return Mock(data=[])


class _Db:
    def __init__(self, pending=None, topup_rows=None):
        self.pending = pending or []
        self.topup_rows = topup_rows or []
        self.executed = []

    def table(self, name):
        return _Query(self, "table", name)

    def rpc(self, name, payload):
        return _Query(self, "rpc", name, payload)

    def writes_to(self, name):
        return [e for e in self.executed if e[0] == "table" and e[1] == name and e[2]]

    def rpc_calls(self, name):
        return [e for e in self.executed if e[0] == "rpc" and e[1] == name]


def _topup_row(idx):
    return {
        "team_id_master": f"team-{idx}",
        "team_name": f"Team {idx}",
        "provider_id": "prov-gotsport",
        "provider_team_id": str(500 + idx),
        "age_group": "u12",
        "birth_year": 2015,
        "last_scraped_at": "2026-09-10T00:00:00",
    }


def _request(idx):
    return {
        "id": f"req-{idx}",
        "team_id_master": f"team-{idx}",
        "team_name": f"Team {idx}",
        "provider_id": "prov-gotsport",
        "provider_team_id": str(100 + idx),
        "game_date": "2026-08-20",
    }


def _processor(db, scrape):
    with patch.object(pmg, "GotSportScraper"):
        processor = pmg.MissingGamesProcessor(db, dry_run=False)
    processor.scrapers["gotsport"]._get_provider_id.return_value = "prov-gotsport"
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.import_games = Mock(side_effect=lambda games, provider_code: len(games))
    processor.scrape_games_for_date = Mock(side_effect=scrape)
    return processor


def _games(team_id, count):
    return [{"game_date": "2026-09-27", "team_id": team_id} for _ in range(count)]


def test_empty_queue_scrapes_topup_teams_up_to_the_limit():
    db = _Db(topup_rows=[_topup_row(i) for i in range(1, 6)])
    processor = _processor(db, lambda provider, team_id, date: _games(team_id, 2))

    processor.process_all(limit=3)

    scraped = [c.args for c in processor.scrape_games_for_date.call_args_list]
    today = datetime.now().strftime("%Y-%m-%d")
    assert scraped == [("gotsport", "501", today), ("gotsport", "502", today), ("gotsport", "503", today)]
    assert len(db.rpc_calls("find_topup_teams")) == 1
    assert db.rpc_calls("find_topup_teams")[0][2]["p_provider_id"] == "prov-gotsport"
    assert processor.stats["processed"] == 3
    assert processor.stats["successful"] == 3
    assert processor.stats["games_found"] == 6


def test_topup_games_are_imported_and_no_queue_row_is_written():
    db = _Db(topup_rows=[_topup_row(1), _topup_row(2)])
    processor = _processor(db, lambda provider, team_id, date: _games(team_id, 1))

    processor.process_all(limit=40)

    processor.import_games.assert_called_once()
    games, provider_code = processor.import_games.call_args.args
    assert provider_code == "gotsport"
    assert len(games) == 2
    assert db.writes_to("scrape_requests") == []


def test_topup_scrapes_are_logged_and_stamp_last_scraped_at():
    """The stamp is what keeps a topped-up team out of the next 14 days' top-ups."""
    db = _Db(topup_rows=[_topup_row(1), _topup_row(2)])
    processor = _processor(db, lambda provider, team_id, date: _games(team_id, 1) if team_id == "501" else [])

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=2) as bulk_update:
        processor.process_all(limit=40)

    (log_insert,) = db.writes_to("team_scrape_log")
    assert [(row["team_id"], row["provider_id"], row["games_found"], row["status"]) for row in log_insert[2]] == [
        ("team-1", "prov-gotsport", 1, "success"),
        ("team-2", "prov-gotsport", 0, "partial"),
    ]
    stamped = [row["team_id_master"] for row in bulk_update.call_args.args[1]]
    assert stamped == ["team-1", "team-2"]


def test_pending_queue_rows_suppress_the_topup():
    db = _Db(pending=[_request(1)], topup_rows=[_topup_row(1)])
    processor = _processor(db, lambda provider, team_id, date: [])

    processor.process_all(limit=40)

    assert db.rpc_calls("find_topup_teams") == []
    assert [c.args[1] for c in processor.scrape_games_for_date.call_args_list] == ["101"]


def test_team_not_found_logs_an_error_and_moves_on():
    db = _Db(topup_rows=[_topup_row(1), _topup_row(2)])

    def scrape(provider, team_id, date):
        if team_id == "501":
            raise TeamNotFoundError(team_id, "gotsport")
        return _games(team_id, 1)

    processor = _processor(db, scrape)

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=2) as bulk_update:
        processor.process_all(limit=40)

    statuses = [(row["team_id"], row["status"]) for row in db.writes_to("team_scrape_log")[0][2]]
    assert statuses == [("team-1", "error"), ("team-2", "success")]
    assert [row["team_id_master"] for row in bulk_update.call_args.args[1]] == ["team-1", "team-2"]
    assert processor.stats["failed"] == 1
    assert processor.stats["successful"] == 1


def test_unexpected_error_does_not_stamp_last_scraped_at():
    db = _Db(topup_rows=[_topup_row(1), _topup_row(2)])

    def scrape(provider, team_id, date):
        if team_id == "501":
            raise RuntimeError("connection reset")
        return []

    processor = _processor(db, scrape)

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1) as bulk_update:
        processor.process_all(limit=40)

    assert [row["team_id_master"] for row in bulk_update.call_args.args[1]] == ["team-2"]


def test_waf_abort_stops_the_topup_without_stamping():
    db = _Db(topup_rows=[_topup_row(i) for i in range(1, 5)])

    def scrape(provider, team_id, date):
        if team_id == "502":
            raise WAFBlockedError(
                provider="gotsport", url="https://example.test/1", last_retry_after=None, reason="waf"
            )
        return []

    processor = _processor(db, scrape)

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1) as bulk_update:
        processor.process_all(limit=40)

    assert [c.args[1] for c in processor.scrape_games_for_date.call_args_list] == ["501", "502"]
    assert processor.stats["waf_aborted"] == 1
    assert [row["team_id_master"] for row in bulk_update.call_args.args[1]] == ["team-1"]


def test_empty_queue_and_no_eligible_teams_scrapes_nothing():
    db = _Db()
    processor = _processor(db, lambda provider, team_id, date: [])

    processor.process_all(limit=40)

    processor.scrape_games_for_date.assert_not_called()
    processor.import_games.assert_not_called()
    assert processor.stats["processed"] == 0
