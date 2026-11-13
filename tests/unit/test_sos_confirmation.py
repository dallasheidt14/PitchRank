"""Registered selection remains fixed through untouched future confirmation."""

from copy import deepcopy

import pytest

from src.predictions.sos_monitoring import evaluate_sos
from tests.unit.test_sos_monitoring import case, model


@pytest.fixture(scope="module")
def study():
    development = [case(i) for i in range(1000)]
    qualified = evaluate_sos(development, development, model(), None, "2030-02-01T00:00:00Z")
    selection = {
        "multiplier": 0.5,
        "qualification": qualified,
        "confirmation_start": "2030-02-04",
        "confirmation_end": "2030-03-03",
    }
    confirmation = [case(i + 1000, day="2030-02-10") for i in range(1000)]
    for row in confirmation:
        row["group"] = "confirmation-" + row["group"]
        # This arm wins confirmation, but cannot replace the registered selection.
        row["payload"]["variants"]["0"].update(winProbabilityA=0.98, drawProbability=0.01, winProbabilityB=0.01)
    return development, selection, confirmation


def test_open_confirmation_never_returns_accuracy_or_adoption(study):
    development, selection, confirmation = study
    rows = development + confirmation
    result = evaluate_sos(development, rows, model(), selection, "2030-02-20T00:00:00Z")
    assert result["status"] == "collecting_confirmation"
    assert result["selected"] == "0.5"
    assert "candidate" not in result


def test_registered_candidate_stays_fixed_even_if_another_arm_wins(study):
    development, selection, confirmation = study
    rows = development + confirmation
    result = evaluate_sos(rows, rows, model(), selection, "2030-03-04T00:00:00Z")
    assert result["selected"] == "0.5"
    assert result["status"] == "release_review_required"
    assert result["paired_games"] == 1000
    assert result["log_loss_delta_95"][1] < 0
    assert result["production_promotion"] is False


def test_changed_development_cannot_silently_reselect(study):
    development, selection, confirmation = study
    changed = deepcopy(development)
    changed[0]["scores"] = [0, 1]
    rows = changed + confirmation
    result = evaluate_sos(rows, rows, model(), selection, "2030-03-04T00:00:00Z")
    assert result["status"] == "development_evidence_changed_review_required"


def test_insufficient_or_adverse_confirmation_retains_formula(study):
    development, selection, confirmation = study
    rows = development + confirmation[:999]
    assert evaluate_sos(rows, rows, model(), selection, "2030-03-04T00:00:00Z")["status"] == "insufficient_confirmation"
    adverse = deepcopy(confirmation)
    for row in adverse:
        row["payload"]["variants"]["0.5"].update(winProbabilityA=0.5, drawProbability=0.25, winProbabilityB=0.25)
    rows = development + adverse
    assert evaluate_sos(rows, rows, model(), selection, "2030-03-04T00:00:00Z")["status"] == "retain_baseline"
