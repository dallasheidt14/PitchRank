"""Evaluate the actual workflow condition on scheduled, preview and manual-capture events."""

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind,upstream_event,conclusion,branch,signature,expected", [
    ("workflow_run", "schedule", "success", "refs/heads/main", "a" * 64, True),
    ("workflow_run", "workflow_dispatch", "success", "refs/heads/main", "a" * 64, False),
    ("workflow_run", "schedule", "failure", "refs/heads/main", "a" * 64, False),
    ("workflow_run", "schedule", "success", "refs/heads/main", "", False),
    ("workflow_dispatch", "", "", "refs/heads/main", "a" * 64, True),
    ("workflow_dispatch", "", "", "refs/heads/feature", "a" * 64, False),
])
def test_challenger_trigger_never_turns_upstream_preview_into_writes(
    kind, upstream_event, conclusion, branch, signature, expected,
):
    workflow = yaml.load((ROOT / ".github/workflows/capture-compare-challenger.yml").read_text(), Loader=yaml.BaseLoader)
    condition = workflow["jobs"]["capture"]["if"]
    values = {"vars.COMPARE_CHALLENGER_SIGNATURE": signature, "github.event_name": kind,
              "github.event.workflow_run.conclusion": conclusion, "github.event.workflow_run.event": upstream_event,
              "github.ref": branch}
    condition = re.sub(r"\b(?:vars|github)(?:\.[A-Za-z_]+)+", lambda match: repr(values[match[0]]), condition)
    expression = ast.parse(condition.replace("&&", " and ").replace("||", " or "), mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq, ast.NotEq, ast.Constant)
    assert all(isinstance(node, allowed) for node in ast.walk(expression))
    assert eval(compile(expression, "workflow-condition", "eval"), {"__builtins__": {}}, {}) is expected
    assert workflow["on"]["workflow_run"]["branches"] == ["main"]


def test_both_collection_stages_use_the_same_balanced_policy():
    workflow = yaml.load((ROOT / ".github/workflows/weekly-prospective-refresh.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["capture"]["steps"]
    intake = next(step["run"] for step in steps if step.get("name") == "Prepare stored fixtures")
    capture = next(step["run"] for step in steps if step.get("name") == "Freeze current Compare forecasts")
    assert "--selection balanced" in intake and "--selection balanced" in capture
    assert workflow["jobs"]["capture"]["env"]["CAPTURE_LIMIT"] == "${{ inputs.limit || '500' }}"
