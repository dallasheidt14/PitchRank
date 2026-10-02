from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "enrich-instagram-handles.yml"


def test_workflow_uses_supported_rank_balanced_selection_flags():
    yaml = WORKFLOW.read_text(encoding="utf-8")

    assert 'FLAGS="$FLAGS --phase ${PHASE:-2}"' in yaml
    assert "--top-n-per-cohort $TOP_N_PER_COHORT --national" in yaml
    assert "github.event.inputs.min_power_score" not in yaml
