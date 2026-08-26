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

from scripts.pr_wait import MERGE_METHOD, check_states, main

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


def test_a_finished_check_counts_even_when_status_lags() -> None:
    """GitHub returned IN_PROGRESS alongside conclusion SUCCESS and a completedAt.

    Reading status there stranded the poll on a check that had already finished.
    """
    rollup = [
        {"__typename": "CheckRun", "name": "Python Tests", "status": "IN_PROGRESS", "conclusion": "SUCCESS"},
        _run("Frontend Lint"),
    ]
    assert check_states(rollup, REQUIRED) == ([], [])


def test_a_check_with_no_conclusion_yet_is_pending() -> None:
    rollup = [_run("Python Tests", status="COMPLETED", conclusion=None), _run("Frontend Lint")]
    pending, failing = check_states(rollup, REQUIRED)
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


def test_a_gate_naming_no_checks_stops_the_run(monkeypatch, capsys) -> None:
    """An empty required set reads as "nothing outstanding" to every check below."""
    monkeypatch.setattr(sys, "argv", ["pr_wait.py", "--pr", "1"])
    monkeypatch.setattr(
        "scripts.pr_wait.resolve_pr",
        lambda _: {"number": 1, "title": "t", "url": "u", "baseRefName": "main", "state": "OPEN"},
    )
    monkeypatch.setattr("scripts.pr_wait.required_contexts", lambda _: set())
    assert main() == 1
    assert "refusing to merge" in capsys.readouterr().out


def test_a_still_running_check_stops_short_of_merging(monkeypatch, capsys) -> None:
    """The wait ends on Codex, so a gate still moving lands here rather than merging.

    This used to arm `gh pr merge --auto`, which stays armed across a later push
    and would merge a commit Codex never saw.
    """
    ran = []
    monkeypatch.setattr(sys, "argv", ["pr_wait.py", "--pr", "1"])
    monkeypatch.setattr("scripts.pr_wait.required_contexts", lambda _: REQUIRED)
    monkeypatch.setattr("scripts.pr_wait.codex_findings", lambda *_: [])
    monkeypatch.setattr("scripts.pr_wait.gh", lambda *a: ran.append(a) or "")
    monkeypatch.setattr(
        "scripts.pr_wait.resolve_pr",
        lambda _: {
            "number": 1,
            "title": "t",
            "url": "u",
            "baseRefName": "main",
            "state": "OPEN",
            "createdAt": "2020-01-01T00:00:00Z",
            "headRefOid": "abc",
            "statusCheckRollup": [_run("Python Tests", status="IN_PROGRESS", conclusion=None), _run("Frontend Lint")],
        },
    )
    assert main() == 1
    assert ran == []
    assert "Still running: Python Tests" in capsys.readouterr().out


def test_legacy_status_contexts_are_read_too() -> None:
    # Vercel and other integrations post StatusContext, which has no conclusion field.
    rollup = [
        {"__typename": "StatusContext", "context": "Python Tests", "state": "FAILURE"},
        {"__typename": "StatusContext", "context": "Frontend Lint", "state": "PENDING"},
    ]
    pending, failing = check_states(rollup, REQUIRED)
    assert pending == ["Frontend Lint"] and failing == ["Python Tests"]


def test_the_merge_is_pinned_to_the_commit_that_was_inspected(monkeypatch) -> None:
    """A green run merges the polled head by SHA, not whatever the head is by then.

    Codex reviews one commit. Without `--match-head-commit`, a push landing between
    the last poll and the merge call would be merged on the strength of a review of
    the commit before it -- the same hole that ruled out `gh pr merge --auto`.
    """
    ran = []
    monkeypatch.setattr(sys, "argv", ["pr_wait.py", "--pr", "1"])
    monkeypatch.setattr("scripts.pr_wait.required_contexts", lambda _: REQUIRED)
    monkeypatch.setattr("scripts.pr_wait.codex_findings", lambda *_: [])
    monkeypatch.setattr("scripts.pr_wait.gh", lambda *a: ran.append(a) or "")
    monkeypatch.setattr(
        "scripts.pr_wait.resolve_pr",
        lambda _: {
            "number": 1,
            "title": "t",
            "url": "u",
            "baseRefName": "main",
            "state": "OPEN",
            "createdAt": "2020-01-01T00:00:00Z",
            "headRefOid": "deadbeef",
            "statusCheckRollup": [_run(name) for name in REQUIRED],
        },
    )
    assert main() == 0
    assert ran == [("pr", "merge", "1", MERGE_METHOD, "--match-head-commit", "deadbeef")]
