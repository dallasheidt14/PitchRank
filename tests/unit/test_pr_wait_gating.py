"""What pr_wait.py will and will not treat as a green PR.

Both decisions it makes are one-way. Calling a PR green merges it, and calling a
Codex review absent merges past findings nobody read. So the two are pinned here
against the shapes GitHub actually returns: a check rollup mixes CheckRun objects
with StatusContext ones and spells conclusions differently in each, and a check
that has not been created yet is missing from the rollup rather than pending in it.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.pr_wait import check_states

REQUIRED = {"Python Tests", "Frontend Lint"}


def _run(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def test_all_required_checks_green_is_the_only_way_through() -> None:
    assert check_states([_run("Python Tests"), _run("Frontend Lint")], REQUIRED) == ([], [])


def test_a_running_check_is_pending_not_green() -> None:
    rollup = [_run("Python Tests", status="IN_PROGRESS", conclusion=None), _run("Frontend Lint")]
    pending, failing = check_states(rollup, REQUIRED)
    assert pending == ["Python Tests"] and failing == []


def test_a_check_that_has_not_reported_at_all_is_pending() -> None:
    pending, failing = check_states([_run("Frontend Lint")], REQUIRED)
    assert pending == ["Python Tests"] and failing == []


def test_cancelled_counts_as_failing() -> None:
    rollup = [_run("Python Tests", conclusion="CANCELLED"), _run("Frontend Lint")]
    pending, failing = check_states(rollup, REQUIRED)
    assert pending == [] and failing == ["Python Tests"]


def test_skipped_and_neutral_do_not_block() -> None:
    rollup = [_run("Python Tests", conclusion="SKIPPED"), _run("Frontend Lint", conclusion="NEUTRAL")]
    assert check_states(rollup, REQUIRED) == ([], [])


def test_advisory_checks_are_ignored_entirely() -> None:
    # claude-review is red on every PR and is not in the ruleset, so it never counts.
    rollup = [_run("Python Tests"), _run("Frontend Lint"), _run("claude-review", conclusion="FAILURE")]
    assert check_states(rollup, REQUIRED) == ([], [])


def test_legacy_status_contexts_are_read_too() -> None:
    # Vercel and other integrations post StatusContext, which has no conclusion field.
    rollup = [
        {"__typename": "StatusContext", "context": "Python Tests", "state": "FAILURE"},
        {"__typename": "StatusContext", "context": "Frontend Lint", "state": "PENDING"},
    ]
    pending, failing = check_states(rollup, REQUIRED)
    assert pending == ["Frontend Lint"] and failing == ["Python Tests"]
