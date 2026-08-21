"""
A CloudFront WAF abort is a session-wide condition, not a per-row failure. Verify
process_all stops the batch on WAFBlockedError and leaves the rows it never reached
pending, instead of marking every remaining row failed with no retry path.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import Mock

import pytest

from scripts.process_missing_games import MissingGamesProcessor
from src.scrapers.gotsport import WAFBlockedError


def _waf_error():
    return WAFBlockedError(
        provider="gotsport",
        url="https://system.gotsport.com/api/v1/matches",
        last_retry_after=300.0,
        reason="cloudfront-waf-second-trip",
    )


def _request(idx):
    """A minimally valid pending row; provider_team_id encodes the index."""
    return {
        "id": f"req-{idx}",
        "team_id_master": f"team-{idx}",
        "team_name": f"Team {idx}",
        "provider_id": "prov-1",
        "provider_team_id": str(100 + idx),
        "game_date": "2026-08-20",
    }


def _build_processor(requests):
    processor = MissingGamesProcessor(Mock(), dry_run=False)
    processor.get_pending_requests = Mock(return_value=requests)
    processor.update_request_status = Mock()
    processor.get_provider_code = Mock(return_value="gotsport")
    processor.import_games = Mock(return_value=0)
    return processor


def _status_writes(processor, status):
    return [c for c in processor.update_request_status.call_args_list if c.args[1] == status]


def test_process_request_reraises_waf_blocked_error():
    processor = _build_processor([])
    processor.scrape_games_for_date = Mock(side_effect=_waf_error())

    with pytest.raises(WAFBlockedError):
        processor.process_request(_request(1))


def test_process_request_marks_waf_row_failed_with_waf_marker():
    """The in-flight row must not be left in 'processing' — nothing reclaims those."""
    processor = _build_processor([])
    processor.scrape_games_for_date = Mock(side_effect=_waf_error())

    with pytest.raises(WAFBlockedError):
        processor.process_request(_request(1))

    failed = _status_writes(processor, "failed")
    assert len(failed) == 1, f"expected exactly one 'failed' write, got {failed}"
    assert "waf" in failed[0].kwargs["error_message"].lower()


def test_process_all_stops_on_waf_abort_leaving_unreached_rows_pending():
    requests = [_request(i) for i in range(1, 6)]
    processor = _build_processor(requests)

    def scrape(provider_code, team_id, game_date):
        if team_id == "103":
            raise _waf_error()
        return []

    processor.scrape_games_for_date = Mock(side_effect=scrape)

    processor.process_all(limit=5)

    touched = {c.args[0] for c in processor.update_request_status.call_args_list}
    assert "req-4" not in touched, "row after the WAF abort must be left pending"
    assert "req-5" not in touched, "row after the WAF abort must be left pending"
    assert processor.stats["processed"] == 3


def test_process_all_records_waf_abort_in_stats():
    requests = [_request(i) for i in range(1, 4)]
    processor = _build_processor(requests)
    processor.scrape_games_for_date = Mock(side_effect=_waf_error())

    processor.process_all(limit=3)

    assert processor.stats["waf_aborted"] == 1


def test_abort_from_the_real_breaker_stops_the_batch():
    """The error the live WAFBreaker raises on its second trip must be the one
    process_all catches — a hand-built WAFBlockedError could hide a wiring change."""
    from src.scrapers.gotsport import _waf_breaker

    _waf_breaker.reset()
    try:
        _waf_breaker.trip(300, url="https://system.gotsport.com/api/v1/matches")
        # A trip while still OPEN is a no-op; the terminal abort needs the
        # cooldown to have elapsed first.
        _waf_breaker._resume()

        requests = [_request(i) for i in range(1, 5)]
        processor = _build_processor(requests)

        def scrape(provider_code, team_id, game_date):
            if team_id == "102":
                # Second trip: the breaker itself raises, terminally.
                _waf_breaker.trip(300, url="https://system.gotsport.com/api/v1/matches")
            return []

        processor.scrape_games_for_date = Mock(side_effect=scrape)

        processor.process_all(limit=4)

        touched = {c.args[0] for c in processor.update_request_status.call_args_list}
        assert "req-3" not in touched
        assert "req-4" not in touched
        assert processor.stats["waf_aborted"] == 1
    finally:
        _waf_breaker.reset()
