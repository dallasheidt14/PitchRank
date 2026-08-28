"""Tests for the refresh of the teams scrape-activity columns.

The RPC does one keyset page per call and this script walks the table, because a
function cannot raise its own statement_timeout and a service-role PostgREST
request inherits an 8-second budget. The paging contract below is what keeps each
call inside it, so it is load-bearing rather than an implementation detail.
"""

import os
import re
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.refresh_team_scrape_activity as refresh

# Deliberately the workflow's own pattern, not a looser one: the step greps
# `(Would update|Updated): \K\d+`, which requires exactly one space.
SUMMARY_LINE = re.compile(r"(?:Would update|Updated): \d+")


def _page(rows_changed, last_team_id):
    return [{"rows_changed": rows_changed, "last_team_id": last_team_id}]


def _run_main(argv, pages=None, rpc_error=None):
    """Drive main() with a stubbed client. `pages` is one RPC result per call."""
    supabase = Mock()
    calls = []

    seq = list(pages if pages is not None else [_page(0, None)])

    def _rpc(*args, **kwargs):
        calls.append(args)
        result = Mock()
        if rpc_error is not None:
            result.execute.side_effect = rpc_error
        else:
            result.execute.return_value = Mock(data=seq.pop(0) if seq else [])
        return result

    supabase.rpc.side_effect = _rpc

    with (
        patch.object(refresh, "create_client", return_value=supabase),
        patch.object(refresh, "SUPABASE_URL", "https://example.supabase.co"),
        patch.object(refresh, "SUPABASE_KEY", "service-role-key"),
        patch.object(sys, "argv", ["refresh_team_scrape_activity.py", *argv]),
    ):
        refresh.main()

    return calls


def test_first_call_starts_the_walk_at_the_beginning():
    calls = _run_main([], pages=[_page(5, None)])

    assert calls[0][0] == "refresh_team_scrape_activity"
    payload = calls[0][1]
    assert payload["p_after"] is None
    assert payload["p_batch_size"] == refresh.DEFAULT_BATCH_SIZE
    assert payload["p_dry_run"] is False


def test_each_page_feeds_its_last_id_into_the_next_call():
    """This is the whole mechanism: without it the walk repeats page 0 forever."""
    calls = _run_main([], pages=[_page(3, "t-a"), _page(2, "t-b"), _page(0, None)])

    assert [c[1]["p_after"] for c in calls] == [None, "t-a", "t-b"]


def test_totals_accumulate_across_pages(capsys):
    _run_main([], pages=[_page(3, "t-a"), _page(4, "t-b"), _page(5, None)])

    assert SUMMARY_LINE.findall(capsys.readouterr().out) == ["Updated: 12"]


def test_walk_stops_on_an_empty_page():
    calls = _run_main([], pages=[_page(1, "t-a"), []])

    assert len(calls) == 2


def test_walk_stops_when_a_page_carries_no_last_id():
    """The RPC returns a NULL last id for an empty page; stopping there avoids
    a call with p_after=None, which would restart the walk from the beginning."""
    calls = _run_main([], pages=[_page(1, "t-a"), _page(0, None), _page(0, "t-c")])

    assert [c[1]["p_after"] for c in calls] == [None, "t-a"]


def test_dry_run_passes_p_dry_run_true_on_every_page():
    calls = _run_main(["--dry-run"], pages=[_page(1, "t-a"), _page(1, None)])

    assert all(c[1]["p_dry_run"] is True for c in calls)


def test_batch_size_is_overridable():
    calls = _run_main(["--batch-size", "500"], pages=[_page(0, None)])

    assert calls[0][1]["p_batch_size"] == 500


def test_live_run_emits_exactly_one_updated_line(capsys):
    """The workflow greps this line for its summary; a second emission would
    make the count ambiguous, and a different spacing would match nothing."""
    _run_main([], pages=[_page(4321, None)])

    assert SUMMARY_LINE.findall(capsys.readouterr().out) == ["Updated: 4321"]


def test_dry_run_emits_exactly_one_would_update_line(capsys):
    _run_main(["--dry-run"], pages=[_page(4321, None)])

    assert SUMMARY_LINE.findall(capsys.readouterr().out) == ["Would update: 4321"]


def test_summary_line_is_the_last_line_of_stdout(capsys):
    """Rich progress output must not land after it, or `| tail -1` picks up noise."""
    _run_main([], pages=[_page(7, "t-a"), _page(0, None)])

    assert capsys.readouterr().out.strip().splitlines()[-1] == "Updated: 7"


def test_missing_rows_changed_does_not_break_the_total(capsys):
    """PostgREST can hand back a NULL column; the summary must stay a number."""
    _run_main([], pages=[[{"rows_changed": None, "last_team_id": None}]])

    assert SUMMARY_LINE.findall(capsys.readouterr().out) == ["Updated: 0"]


def test_rpc_failure_exits_non_zero():
    """There is no Python fallback by design, so a failure has to go red rather
    than report a silent partial count as success."""
    with pytest.raises(SystemExit) as exc:
        _run_main([], rpc_error=RuntimeError("statement timeout"))

    assert exc.value.code == 1


def test_missing_credentials_exit_non_zero():
    with (
        patch.object(refresh, "SUPABASE_URL", None),
        patch.object(refresh, "SUPABASE_KEY", None),
        patch.object(sys, "argv", ["refresh_team_scrape_activity.py"]),
        pytest.raises(SystemExit) as exc,
    ):
        refresh.main()

    assert exc.value.code == 1
