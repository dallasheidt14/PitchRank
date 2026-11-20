"""Synthetic winner-study contracts; no saved private match data."""

from copy import deepcopy
from datetime import date, timedelta

from src.predictions.winner_study import ENTRYPOINT, KIND, POLICY, WEIGHTS


def definition(start=None, monitor_signature="a" * 64, model_signature="b" * 64):
    start = start or date(2026, 11, 23)
    return {
        "kind": KIND,
        "schema_version": 1,
        "entrypoint": ENTRYPOINT,
        "capture_start": start.isoformat(),
        "capture_end": (start + timedelta(days=27)).isoformat(),
        "review_not_before": max(date(2027, 1, 11), start + timedelta(days=28)).isoformat(),
        "monitor_signature": monitor_signature,
        "baseline_model_signature": model_signature,
        "code_revision": "c" * 40,
        "execution_hashes": {ENTRYPOINT: "d" * 64},
        "weights": dict.fromkeys(WEIGHTS, 1.0),
        "policy": deepcopy(POLICY),
        "training_data_sha256": "e" * 64,
        "research_receipt_sha256": "f" * 64,
        "latest_training_game": "2026-11-15",
        "training_evidence": "exposed_retrospective_research_only",
        "production_promotion": False,
    }
