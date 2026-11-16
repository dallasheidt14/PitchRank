"""Synthetic artifacts only; no saved match data or credentials."""

import io
import json
import zipfile
from copy import deepcopy
from datetime import date, timedelta

from src.predictions.score_challenger import CANDIDATES, candidate_definition
from src.predictions.score_study import ENTRYPOINT, KIND, POLICY, digest, serialized


def sample_artifact():
    games = [{"id": "synthetic-game", "game_date": "2026-11-01", "home_team_master_id": "a",
              "away_team_master_id": "b", "home_score": 2, "away_score": 1, "cohort": "12_M"}]
    fit = {"teams": ["a", "b"], "cohorts": ["12_M"], "counts": {"a": 1, "b": 1},
           "parameters": [0.5, 0.4, -0.1, 0.2, -0.2], "pooled_rate": 1.5,
           "receipt": {"optimizer_success": True, "cutoff": "2026-11-15", "latest_training_game": "2026-11-01",
                       "penalty": 4, "half_life": 60, "games": 1, "teams": 2, "cohorts": 1,
                       "data_sha256": digest(serialized([("synthetic-game", 2, 1)]).encode())}}
    raw = serialized(fit).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("prospective/fitted-model.json", raw)
        archive.writestr("prospective/training-games.json", serialized(games))
    bundle = output.getvalue()
    artifact = {"bucket": "prediction-input-archives", "object": "compare-score-research/2026-11-15/" + "e"*64 + ".zip",
                "zip_sha256": digest(bundle), "model_sha256": digest(raw),
                "model_member": "prospective/fitted-model.json", "training_member": "prospective/training-games.json"}
    return fit, bundle, artifact


def definition(start=None, monitor_signature="a" * 64, model_signature="b" * 64):
    start = start or date(2026, 11, 23)
    fit, _, artifact = sample_artifact()
    return {"schema_version": 1, "kind": KIND, "capture_start": start.isoformat(),
            "capture_end": (start + timedelta(days=27)).isoformat(),
            "review_not_before": max(date(2027, 1, 11), start + timedelta(days=28)).isoformat(),
            "monitor_signature": monitor_signature, "baseline_model_signature": model_signature,
            "entrypoint": ENTRYPOINT, "code_revision": "c"*40, "execution_hashes": {ENTRYPOINT: "d"*64},
            "artifact": artifact, "fit_receipt": deepcopy(fit["receipt"]), "policy": deepcopy(POLICY),
            "candidates": {key: candidate_definition(key) for key in CANDIDATES}, "production_promotion": False}


def baseline():
    return {"winProbabilityA": 0.55, "drawProbability": 0.2, "winProbabilityB": 0.25,
            "predictedWinner": "team_a", "blowout4PlusProbability": 0.1,
            "expectedScore": {"teamA": 2, "teamB": 1},
            "expectedGoals": {"teamA": 2.2, "teamB": 1.3}, "expectedMargin": 0.9}


def parent_row():
    return {"baseline_forecast_id": "synthetic-forecast", "game_date": "2026-11-23",
            "monitor_signature": "a"*64, "parent_payload_sha256": "e"*64,
            "parent_payload": {"model_signature": "b"*64, "prediction": baseline(), "context": {
                "teamAInput": {"team_id_master": "a", "age": 12, "gender": "M"},
                "teamBInput": {"team_id_master": "b", "age": 12, "gender": "M"},
                "frozenEvidence": {"aliases": {}}}}}
