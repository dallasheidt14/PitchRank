"""The club/state chain must reach the database over PostgREST, and fail loudly.

Two defects took this workflow off the air for a full weekly cycle, and both are
invisible in a green diff.

The first: Step 0 opened a direct Postgres connection. The Supabase db host
publishes an AAAA record and no A record, and GitHub-hosted runners have no IPv6
egress, so ``psycopg2.connect`` raised "Network is unreachable" on every run from
the day that step landed. No step carries ``continue-on-error``, so Steps 1-6
inherited the failure and never ran at all -- the whole club and state backfill,
not just the one heuristic.

The second: only Step 0 set ``pipefail``. Every other step pipes its script into
``tee``, which returns tee's exit code, so a crashed script exited 0 and the
grep-with-default that follows reported "0 updated". A dead step and a step with
nothing to do were indistinguishable in the logs.

These assertions pin both invariants against the workflow file rather than the
one script that broke, because the next direct-Postgres step will be added by
someone who never read this history.
"""

import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "update-missing-club-and-state.yml"

# Reaching Postgres directly is the defect, however it is spelled: the env var
# that carries the URL, and the driver that would dial it.
DIRECT_POSTGRES_MARKERS = ("DATABASE_URL", "psycopg2")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list:
    return _workflow()["jobs"]["update-missing-club-and-state"]["steps"]


def _run_blocks() -> list:
    return [(step.get("name", step.get("id", "?")), step["run"]) for step in _steps() if step.get("run")]


def _invoked_scripts() -> set:
    scripts = set()
    for _, block in _run_blocks():
        scripts.update(re.findall(r"python\s+(scripts/\S+\.py)", block))
    return scripts


def test_workflow_env_does_not_carry_a_direct_postgres_url():
    assert "DATABASE_URL" not in (_workflow().get("env") or {})


@pytest.mark.parametrize("marker", DIRECT_POSTGRES_MARKERS)
def test_no_step_reaches_postgres_directly(marker):
    offenders = [name for name, block in _run_blocks() if marker in block]
    assert not offenders, f"{marker} appears in: {offenders}"


def test_invoked_scripts_do_not_import_psycopg2():
    offenders = []
    for script in sorted(_invoked_scripts()):
        path = PROJECT_ROOT / script
        if not path.exists():
            pytest.fail(f"{script} is invoked by the workflow but does not exist")
        if re.search(r"^\s*(import|from)\s+psycopg2", path.read_text(encoding="utf-8"), re.M):
            offenders.append(script)
    assert not offenders, f"these run on a runner with no IPv6 egress: {offenders}"


def test_workflow_actually_invokes_scripts():
    """Guards the two tests above from passing because the parse found nothing."""
    assert len(_invoked_scripts()) >= 6


def test_every_step_that_pipes_into_tee_sets_pipefail():
    offenders = [name for name, block in _run_blocks() if "| tee " in block and "set -o pipefail" not in block]
    assert not offenders, f"a crash in these exits 0 and reports zero rows: {offenders}"
