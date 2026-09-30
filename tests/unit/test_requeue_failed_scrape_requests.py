"""Tests for the filters that decide what a re-queue admits.

The drain finalizes every row it could not scrape with one blanket message, so the
error text is all that separates a provider outage from a permanently stale
provider_team_id. Getting that wrong in either direction is silent: too strict
leaves teams out of the pipeline, too loose spends a ZenRows call on a team the
provider will never serve.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.requeue_failed_scrape_requests import best_request_per_team, is_retryable


def _row(message=None, team=None, priority=2, request_type="active_team"):
    return {
        "id": f"req-{team}-{priority}",
        "team_id_master": team,
        "request_type": request_type,
        "priority": priority,
        "status": "failed",
        "error_message": message,
    }


def test_blanket_drain_message_is_retryable():
    """The message a drain writes for every unscraped row says nothing about the team."""
    assert is_retryable(_row("Team not found or scrape error"))


def test_transport_failure_is_retryable():
    assert is_retryable(
        _row("HTTPSConnectionPool(host='system.gotsport.com', port=443): Max retries exceeded")
    )


def test_missing_error_message_is_retryable():
    """A row stranded in 'processing' never reached the finalize, so it carries none."""
    assert is_retryable(_row(None))


def test_stale_provider_id_is_not_retryable():
    assert not is_retryable(
        _row("Team 421504 not found on gotsport (404) — the provider_team_id appears stale")
    )


def test_unservable_provider_is_not_retryable():
    assert not is_retryable(
        _row("No scraper available for provider 'affinity_wa' and no GotSport alias found")
    )


def test_permanent_marker_matches_regardless_of_case():
    assert not is_retryable(_row("NO SCRAPER AVAILABLE FOR PROVIDER 'sincsports'"))


def test_best_request_keeps_the_highest_priority_a_team_held():
    """A team with several failed rows is re-queued at the most urgent one, so a
    user click is not demoted to the safety net's tier by a later automatic row."""
    rows = [
        _row("x", team="team-a", priority=4, request_type="safety_net"),
        _row("x", team="team-a", priority=1, request_type="missing_game"),
        _row("x", team="team-a", priority=2, request_type="active_team"),
    ]

    best = best_request_per_team(rows)

    assert best["team-a"]["priority"] == 1
    assert best["team-a"]["request_type"] == "missing_game"


def test_best_request_drops_rows_with_no_team():
    rows = [_row("x", team=None, priority=2), _row("x", team="team-b", priority=3)]

    assert set(best_request_per_team(rows)) == {"team-b"}
