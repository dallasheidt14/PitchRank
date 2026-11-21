"""Evaluate the actual workflow condition on scheduled, preview and manual-capture events."""

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", [
    "weekly-prospective-refresh.yml",
    "process-prospective-heuristic-predictions.yml",
])
def test_registered_studies_keep_the_original_collecting_predictor(name):
    workflow = yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                if step.get("with", {}).get("path") == ".archive-publisher":
                    assert step["with"]["ref"] == "${{ github.sha }}"
                else:
                    assert step["with"]["ref"] == "15cc5f4f38858f2a48a3ac2aeaef8f2bab76c81b"


def test_archive_publisher_uses_workflow_source_only_after_locked_inputs_are_saved():
    path = ROOT / ".github/workflows/weekly-prospective-refresh.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["capture"]["steps"]
    capture = next(i for i, step in enumerate(steps) if step.get("name") == "Freeze current Compare forecasts")
    archive = next(i for i, step in enumerate(steps) if step.get("name") == "Preserve frozen forecast inputs locally")
    tooling = next(i for i, step in enumerate(steps) if step.get("name") == "Checkout archive publisher")
    publish = next(i for i, step in enumerate(steps) if step.get("name") == "Publish frozen forecast inputs privately")
    assert capture < archive < tooling < publish
    assert steps[0]["with"]["ref"] == "15cc5f4f38858f2a48a3ac2aeaef8f2bab76c81b"
    assert steps[tooling]["with"] == {
        "ref": "${{ github.sha }}", "path": ".archive-publisher", "persist-credentials": "false",
    }
    assert [steps[i]["id"] for i in (capture, archive, tooling)] == ["freeze", "archive", "publisher"]
    assert steps[archive]["if"] == ("!cancelled() && (steps.freeze.outcome == 'success' || "
                                    "steps.freeze.outcome == 'failure') && env.EXECUTE == 'true' && "
                                    "vars.COMPARE_INPUT_ARCHIVE_ENABLED == 'true'")
    assert steps[tooling]["if"] == "!cancelled() && steps.archive.outcome == 'success'"
    assert steps[publish]["if"] == ("!cancelled() && steps.archive.outcome == 'success' && "
                                    "steps.publisher.outcome == 'success'")
    receipt = next(s for s in steps if s.get("name") == "Verify partial capture was archived")
    assert steps[publish]["id"] == "publish"
    assert receipt["if"] == "!cancelled() && steps.freeze.outcome == 'failure' && steps.publish.outcome == 'success'"
    assert "python scripts/archive_compare_forecasts.py" in steps[archive]["run"]
    assert "python .archive-publisher/scripts/publish_ranking_input_archive.py" in steps[publish]["run"]
    assert '"$RUNNER_TEMP/frozen-forecast-inputs" --execute' in steps[publish]["run"]


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
    path = ROOT / ".github/workflows/capture-compare-challenger.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
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
    path = ROOT / ".github/workflows/weekly-prospective-refresh.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["capture"]["steps"]
    intake = next(step["run"] for step in steps if step.get("name") == "Prepare stored fixtures")
    capture = next(step["run"] for step in steps if step.get("name") == "Freeze current Compare forecasts")
    assert "--selection balanced" in intake and "--selection balanced" in capture
    assert workflow["jobs"]["capture"]["env"]["CAPTURE_LIMIT"] == "${{ inputs.limit || '500' }}"
    assert workflow["on"]["workflow_dispatch"]["inputs"]["retry_errors"]["default"] == "false"
    env = workflow["jobs"]["capture"]["env"]
    assert env["HEURISTIC_STATUS"] == "${{ inputs.retry_errors && 'error' || 'pending' }}"
    assert '--source database --status "$HEURISTIC_STATUS"' in capture
    for name in ("Prepare stored fixtures", "Audit collection coverage without inspecting results"):
        assert next(s for s in steps if s.get("name") == name)["if"] == "env.HEURISTIC_STATUS == 'pending'"
