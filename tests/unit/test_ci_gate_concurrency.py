"""The quality gate supersedes stale PR runs without touching runs on main.

Two pushes to a branch 32 seconds apart each ran the full seven-job gate. Once a
PR's head moves the older run's checks gate nothing, so cancelling it costs
nothing and returns about three minutes of runner time.

Runs on main are a different thing wearing the same workflow name. The ruleset
does not require a PR to be up to date with main before merging, so the run that
fires after a squash lands is the only signal that main itself is green. Widening
`cancel-in-progress` to every event would cancel that run whenever two merges land
close together, which is exactly when it is worth having.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _concurrency() -> dict:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    concurrency = doc.get("concurrency")
    assert isinstance(concurrency, dict), "ci.yml runs every push and PR with no concurrency group"
    return concurrency


def test_group_is_keyed_per_pull_request() -> None:
    group = _concurrency()["group"]
    assert "github.event.pull_request.number" in group, group
    assert "github.ref" in group, f"{group} leaves runs on main sharing one key with PRs"


def test_only_pull_request_runs_are_cancelled() -> None:
    cancel = _concurrency().get("cancel-in-progress")
    assert cancel is not True, "cancels the post-merge run on main, the only check that main is green"
    assert "pull_request" in str(cancel), cancel
