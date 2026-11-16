"""Exercise workflow event permissions without ever invoking GitHub or a shell."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("event,upstream,conclusion,branch,enabled,expected", [
    ("workflow_run", "schedule", "success", "main", True, True),
    ("workflow_run", "workflow_dispatch", "success", "main", True, False),
    ("workflow_run", "schedule", "failure", "main", True, False),
    ("workflow_run", "schedule", "success", "unreviewed-branch", True, False),
    ("workflow_run", "schedule", "success", "main", False, False),
    ("workflow_dispatch", "", "", "", True, True),
    ("schedule", "", "", "", True, True),
])
def test_only_authorized_events_can_start_collection(event, upstream, conclusion, branch, enabled, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/compare-score-study.yml").read_text())
    expression = workflow["jobs"]["capture"]["if"].replace("&&", " and ").replace("||", " or ")
    github = SimpleNamespace(event_name=event, event=SimpleNamespace(workflow_run=SimpleNamespace(
        event=upstream, conclusion=conclusion, head_branch=branch)))
    variables = SimpleNamespace(COMPARE_SCORE_STUDY_SIGNATURE="a"*64 if enabled else "")
    assert eval(expression, {"__builtins__": {}}, {"github": github, "vars": variables}) is expected


def test_capture_uses_registered_revision_and_never_uploads_public_artifacts():
    workflow = yaml.safe_load((ROOT / ".github/workflows/compare-score-study.yml").read_text())
    steps = workflow["jobs"]["capture"]["steps"]
    checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts[-1]["with"]["ref"] == "${{ steps.study.outputs.revision }}"
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)
    assert not any("upload-artifact" in step.get("uses", "") for step in steps)


def test_bootstrap_resolves_frozen_revision_without_using_mutable_main_policy(monkeypatch, tmp_path):
    from scripts import settle_prospective_match_predictions as settle
    from src.predictions import score_study_capture
    from src.predictions.score_study import digest, serialized
    from tests.score_study_fixtures import definition

    manifest = definition()
    signature = digest(serialized(manifest).encode())

    class Query:
        def table(self, name):
            assert name == "compare_score_studies"
            return self

        def select(self, fields):
            assert fields == "manifest"
            return self

        def eq(self, key, value):
            assert (key, value) == ("signature", signature)
            return self

        def single(self):
            return self

        def execute(self):
            return SimpleNamespace(data={"manifest": manifest})

    monkeypatch.setattr(settle, "_supabase_client", lambda: Query())
    def changed_policy(*args, **kwargs):
        raise AssertionError("Main policy must not validate an older revision before checkout")
    monkeypatch.setattr(score_study_capture, "validate_definition", changed_policy)
    monkeypatch.setenv("STUDY_SIGNATURE", signature)
    output = tmp_path/"github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    workflow = yaml.safe_load((ROOT/".github/workflows/compare-score-study.yml").read_text())
    bootstrap = next(step for step in workflow["jobs"]["capture"]["steps"] if step.get("id") == "study")["run"]
    source = bootstrap.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    exec(compile(source, "workflow-bootstrap", "exec"), {})
    assert output.read_text() == "revision="+"c"*40+"\n"
