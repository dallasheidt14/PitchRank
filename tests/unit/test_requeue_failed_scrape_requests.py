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

from scripts.requeue_failed_scrape_requests import (
    _scrape_covered_failure,
    attempt_time,
    best_request_per_team,
    is_retryable,
    latest_attempt_per_team,
)


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


def _attempted(when, team="team-a", priority=2, request_type="active_team", game_date="2026-09-20"):
    row = _row("Team not found or scrape error", team=team, priority=priority, request_type=request_type)
    row["processed_at"] = when
    row["game_date"] = game_date
    return row


def test_scrape_after_the_failure_counts_as_coverage():
    assert _scrape_covered_failure("2026-09-29T10:00:00+00:00", attempt_time(_attempted("2026-09-28T05:00:00+00:00")))


def test_scrape_before_the_failure_is_not_coverage():
    """The defect a wall-clock window hides: a recent scrape that predates the
    failure has not covered it, and the team still needs re-queueing."""
    assert not _scrape_covered_failure(
        "2026-09-29T10:00:00+00:00", attempt_time(_attempted("2026-09-30T16:00:00+00:00"))
    )


def test_never_scraped_team_is_not_treated_as_covered():
    assert not _scrape_covered_failure(None, attempt_time(_attempted("2026-09-28T05:00:00+00:00")))


def test_attempt_time_prefers_the_claim_over_the_retirement_stamp():
    """retire_stranded_scrape_requests.py stamps completed_at with the cleanup, so
    reading that would date a days-old failure to the sweep that swept it up."""
    row = _row("Retired by retire_stranded_scrape_requests.py: never finalized", team="team-a")
    row["processed_at"] = "2026-09-27T18:39:00+00:00"
    row["completed_at"] = "2026-09-30T22:22:00+00:00"

    assert attempt_time(row).isoformat() == "2026-09-27T18:39:00+00:00"


def test_latest_attempt_wins_so_an_older_success_cannot_suppress_a_new_failure():
    rows = [
        _attempted("2026-09-27T18:39:00+00:00"),
        _attempted("2026-09-30T16:00:00+00:00"),
    ]

    latest = latest_attempt_per_team(rows)

    assert latest["team-a"].isoformat() == "2026-09-30T16:00:00+00:00"
    assert not _scrape_covered_failure("2026-09-29T10:00:00+00:00", latest["team-a"])


def test_best_request_breaks_a_priority_tie_on_the_later_attempt():
    """game_date comes from the chosen row, so the tie-break decides which date
    the re-queued request carries."""
    rows = [
        _attempted("2026-09-27T18:39:00+00:00", game_date="2026-06-01"),
        _attempted("2026-09-30T16:00:00+00:00", game_date="2026-09-29"),
    ]

    assert best_request_per_team(rows)["team-a"]["game_date"] == "2026-09-29"
