"""Tests for the scrape-attempt logging the 15-minute drainer writes.

Until this shipped, process_missing_games.py was the one queue consumer that
recorded nothing: no ``team_scrape_log`` row and no ``teams.last_scraped_at``
bump. Two things downstream depend on those writes — ``teams.scrape_attempts``
counts the non-error rows, and the six-month scrape-eligibility re-probe reads
``last_scraped_at`` — so the per-outcome mapping below is load-bearing rather
than bookkeeping.
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.process_missing_games as pmg
from src.scrapers.gotsport import TeamNotFoundError, WAFBlockedError


def _processor(dry_run=False, supabase=None):
    with patch.object(pmg, "GotSportScraper"):
        return pmg.MissingGamesProcessor(supabase or Mock(), dry_run=dry_run)


def _request(**overrides):
    request = {
        "id": "req-1",
        "team_id_master": "t-1",
        "team_name": "Team A",
        "game_date": "2026-08-20",
        "provider_id": "prov-gotsport",
        "provider_team_id": "12345",
    }
    request.update(overrides)
    return request


def _waf_error():
    return WAFBlockedError(provider="gotsport", url="https://example.test/1", last_retry_after=None, reason="waf")


def _run_request(processor, scrape_result, request=None):
    """Drive process_request with the scrape stubbed to return or raise."""
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.get_gotsport_alias = Mock(return_value=None)
    processor.update_request_status = Mock()
    if isinstance(scrape_result, Exception):
        processor.scrape_games_for_date = Mock(side_effect=scrape_result)
    else:
        processor.scrape_games_for_date = Mock(return_value=scrape_result)
    return processor.process_request(request or _request())


def test_games_found_logs_success_and_advances_the_timestamp():
    processor = _processor()

    _run_request(processor, [{"game_date": "2026-08-20"}, {"game_date": "2026-08-21"}])

    assert processor._scrape_log_buffer == [
        {
            "team_id_master": "t-1",
            "provider_id": "prov-gotsport",
            "games_found": 2,
            "status": "success",
            "update_last_scraped_at": True,
        }
    ]


def test_zero_games_logs_partial_and_still_advances_the_timestamp():
    """Load-bearing: a probe that finds nothing is still a probe. Without the
    bump, the six-month re-probe clock never restarts and a filtered team is
    re-admitted every single week instead of twice a year."""
    processor = _processor()

    _run_request(processor, [])

    (entry,) = processor._scrape_log_buffer
    assert entry["status"] == "partial"
    assert entry["games_found"] == 0
    assert entry["update_last_scraped_at"] is True


def test_team_not_found_logs_error_and_advances_the_timestamp():
    """A 404 is a completed probe: the provider answered, the team is not there."""
    processor = _processor()

    assert _run_request(processor, TeamNotFoundError("12345", "gotsport")) is False

    (entry,) = processor._scrape_log_buffer
    assert entry["status"] == "error"
    assert entry["update_last_scraped_at"] is True


def test_waf_block_logs_error_without_advancing_the_timestamp():
    """Load-bearing: the request never reached the provider. Stamping it would
    buy six months of silence for a scrape that did not happen."""
    processor = _processor()

    with pytest.raises(WAFBlockedError):
        _run_request(processor, _waf_error())

    (entry,) = processor._scrape_log_buffer
    assert entry["status"] == "error"
    assert entry["update_last_scraped_at"] is False


def test_unexpected_failure_logs_error_without_advancing_the_timestamp():
    processor = _processor()

    assert _run_request(processor, RuntimeError("connection reset")) is False

    (entry,) = processor._scrape_log_buffer
    assert entry["status"] == "error"
    assert entry["update_last_scraped_at"] is False


def test_error_status_keeps_transient_failures_out_of_the_attempt_counter():
    """teams.scrape_attempts excludes status='error', which is what stops ten WAF
    blocks from retiring a live team as never-productive."""
    processor = _processor()

    with pytest.raises(WAFBlockedError):
        _run_request(processor, _waf_error())
    _run_request(processor, RuntimeError("boom"))

    assert {e["status"] for e in processor._scrape_log_buffer} == {"error"}


def test_request_without_a_team_id_master_logs_nothing():
    """team_scrape_log.team_id is NOT NULL REFERENCES teams(team_id_master), but
    process_request treats the field as optional."""
    processor = _processor()

    _run_request(processor, [{"game_date": "2026-08-20"}], request=_request(team_id_master=None))

    assert processor._scrape_log_buffer == []


def test_alias_reroute_logs_the_provider_actually_scraped():
    processor = _processor()
    processor.get_provider_code = Mock(return_value="modular11")
    processor.get_gotsport_alias = Mock(return_value={"provider_id": "prov-gs", "provider_team_id": "999"})
    processor.update_request_status = Mock()
    processor.scrape_games_for_date = Mock(return_value=[])

    processor.process_request(_request(provider_id="prov-m11"))

    (entry,) = processor._scrape_log_buffer
    assert entry["provider_id"] == "prov-gs"


def test_flush_writes_log_rows_and_advances_only_the_flagged_teams():
    supabase = Mock()
    processor = _processor(supabase=supabase)
    processor._scrape_log_buffer = [
        {
            "team_id_master": "t-1",
            "provider_id": "prov-gotsport",
            "games_found": 3,
            "status": "success",
            "update_last_scraped_at": True,
        },
        {
            "team_id_master": "t-2",
            "provider_id": "prov-gotsport",
            "games_found": 0,
            "status": "error",
            "update_last_scraped_at": False,
        },
    ]

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1) as bulk_update:
        processor._flush_scrape_log()

    rows = supabase.table.return_value.insert.call_args.args[0]
    assert supabase.table.call_args.args[0] == "team_scrape_log"
    assert [r["team_id"] for r in rows] == ["t-1", "t-2"]
    assert [r["games_found"] for r in rows] == [3, 0]
    assert [r["status"] for r in rows] == ["success", "error"]
    assert all(r["provider_id"] == "prov-gotsport" and r["scraped_at"] for r in rows)

    payload = bulk_update.call_args.args[1]
    assert [p["team_id_master"] for p in payload] == ["t-1"]

    assert processor._scrape_log_buffer == []


def test_flush_writes_nothing_in_dry_run():
    supabase = Mock()
    processor = _processor(dry_run=True, supabase=supabase)
    processor._scrape_log_buffer = [
        {
            "team_id_master": "t-1",
            "provider_id": "prov-gotsport",
            "games_found": 1,
            "status": "success",
            "update_last_scraped_at": True,
        }
    ]

    with patch.object(pmg, "bulk_update_last_scraped_at") as bulk_update:
        processor._flush_scrape_log()

    supabase.table.assert_not_called()
    bulk_update.assert_not_called()


def test_flush_on_an_empty_buffer_touches_nothing():
    supabase = Mock()
    processor = _processor(supabase=supabase)

    with patch.object(pmg, "bulk_update_last_scraped_at") as bulk_update:
        processor._flush_scrape_log()

    supabase.table.assert_not_called()
    bulk_update.assert_not_called()


def test_a_failed_log_insert_does_not_abort_the_timestamp_update():
    """Bookkeeping is best-effort; neither write may fail an otherwise good run."""
    supabase = Mock()
    supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
    processor = _processor(supabase=supabase)
    processor._scrape_log_buffer = [
        {
            "team_id_master": "t-1",
            "provider_id": "prov-gotsport",
            "games_found": 1,
            "status": "success",
            "update_last_scraped_at": True,
        }
    ]

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1) as bulk_update:
        processor._flush_scrape_log()  # must not raise

    bulk_update.assert_called_once()


def test_a_failed_timestamp_update_does_not_raise():
    supabase = Mock()
    processor = _processor(supabase=supabase)
    processor._scrape_log_buffer = [
        {
            "team_id_master": "t-1",
            "provider_id": "prov-gotsport",
            "games_found": 1,
            "status": "success",
            "update_last_scraped_at": True,
        }
    ]

    with patch.object(pmg, "bulk_update_last_scraped_at", side_effect=RuntimeError("boom")):
        processor._flush_scrape_log()  # must not raise


def test_process_all_flushes_the_buffer():
    supabase = Mock()
    processor = _processor(supabase=supabase)
    processor.get_pending_requests = Mock(return_value=[_request()])
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.get_gotsport_alias = Mock(return_value=None)
    processor.update_request_status = Mock()
    processor.scrape_games_for_date = Mock(return_value=[])

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1) as bulk_update:
        processor.process_all(limit=1)

    bulk_update.assert_called_once()
    assert processor._scrape_log_buffer == []


def test_waf_abort_still_flushes_what_the_run_logged():
    """process_all breaks out of the loop on a WAF block, so the flush is the only
    thing that records the attempts made before it."""
    supabase = Mock()
    processor = _processor(supabase=supabase)
    processor.get_pending_requests = Mock(return_value=[_request(id="req-1"), _request(id="req-2")])
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.get_gotsport_alias = Mock(return_value=None)
    processor.update_request_status = Mock()
    processor.scrape_games_for_date = Mock(side_effect=[[{"game_date": "2026-08-20"}], _waf_error()])

    with patch.object(pmg, "bulk_update_last_scraped_at", return_value=1):
        processor.process_all(limit=2)

    rows = supabase.table.return_value.insert.call_args.args[0]
    assert [r["status"] for r in rows] == ["success", "error"]
    assert processor._scrape_log_buffer == []
