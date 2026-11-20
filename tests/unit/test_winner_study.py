"""Fixed candidate, honest qualification and workflow boundaries."""

from copy import deepcopy
from pathlib import Path

import pytest

from src.predictions.winner_study import accuracy_report, validate_definition
from tests.score_study_fixtures import baseline
from tests.winner_study_fixtures import definition


def test_definition_requires_fixed_rules_and_provenance():
    m = definition()
    validate_definition(m, registered_at="2026-11-20T01:00:00Z")
    for change in ("weights", "policy", "training", "review", "late"):
        v = deepcopy(m)
        if change == "weights":
            v["weights"]["schedule"] = float("nan")
        elif change == "policy":
            v["policy"]["minimum_pairs"] = 1
        elif change == "training":
            v["latest_training_game"] = v["capture_start"]
        elif change == "review":
            v["review_not_before"] = v["capture_end"]
        with pytest.raises(ValueError):
            validate_definition(v, registered_at=v["capture_start"] + "T00:00:00Z" if change == "late" else None)


def records(n=1000, groups=20):
    rows = []
    for i in range(n):
        p = baseline()
        weighted = {**p, "winProbabilityA": 0.7, "winProbabilityB": 0.1}
        if i % 4 == 0:
            p = {**p, "predictedWinner": "team_b"}
        rows.append(
            {
                "baseline_forecast_id": str(i),
                "source_game_id": str(i),
                "game_date": "2026-11-23",
                "captured_at": "2026-11-20T01:00:00Z",
                "group_kind": "event",
                "provider": "gotsport",
                "group": f"gotsport:{i % groups}",
                "source_event_id": str(i % groups),
                "fixture_payload": {"source_snapshot": {"source_url": f"https://example.test/events/{i % groups}/"}},
                "result": {"home_score": 2, "away_score": 1},
                "payload": {
                    "team_pair": [f"a{i}", f"b{i}"],
                    "slices": {"age": "12|12", "history": "8+", "ranked": "True", "same_cohort": "True"},
                    "candidates": {"baseline": {"prediction": p}, "weighted": {"prediction": weighted}},
                },
            }
        )
    return rows


def test_qualification_requires_future_pairs_groups_accuracy_and_probability_guardrails():
    result = accuracy_report(records())
    assert result["status"] == "qualified_for_release_review"
    assert result["production_promotion"] is False
    assert result["accuracy_difference_interval_95"][0] > 0
    assert result["group_provenance"] == {"event": 1000}
    assert accuracy_report(records(999))["status"] == "insufficient_data"
    assert accuracy_report(records(groups=19))["status"] == "insufficient_data"
    worse = records()
    for r in worse:
        r["payload"]["candidates"]["weighted"]["prediction"].update(
            winProbabilityA=0.2, drawProbability=0.2, winProbabilityB=0.6
        )
    assert accuracy_report(worse)["status"] == "criteria_not_met"


def test_duplicates_changed_sources_and_unverified_groups_do_not_inflate_counts():
    rows = records(4)
    rows.append(deepcopy(rows[0]))
    rows[1]["result"] = None
    rows[2]["group"] = "fabricated"
    report = accuracy_report(rows)
    assert report["paired_matches"] == 2
    assert report["coverage"] == {
        "duplicate_or_ambiguous_source": 1,
        "missing_or_changed_exact_source_result": 1,
        "unverified_group": 1,
    }


def test_winner_workflow_is_an_independent_success_only_child_and_pins_source():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github/workflows/compare-winner-study.yml").read_text()
    assert "workflows: [Compare Live Monitoring]" in text
    assert "workflow_run.conclusion == 'success'" in text
    assert "workflow_run.event == 'schedule'" in text
    assert "workflow_run.head_branch == 'main'" in text
    assert "COMPARE_WINNER_STUDY_SIGNATURE" in text
    assert "steps.study.outputs.revision" in text
    assert "npm ci --ignore-scripts" in text
    assert "compare_score_studies" not in text
