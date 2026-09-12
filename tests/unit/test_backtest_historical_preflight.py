from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from src.tournaments.backtest_historical_preflight import (
    HistoricalPreflight,
    HistoricalPreflightUnavailable,
    preflight_input_sha256,
    run_historical_preflight,
)
from src.tournaments.backtest_intake_state import CaptureVerification
from src.tournaments.backtest_reviewed_run import build_reviewed_cohort_readiness
from tests.unit.test_backtest_request import _links, _snapshot


class _Resolver:
    version = "merge-v1"

    def __init__(self, _client):
        pass

    def load_merge_map(self):
        return None

    def resolve(self, team_id):
        return team_id

    def get_deprecated_teams(self):
        return []


def _request():
    snapshot = replace(
        _snapshot(),
        verification=CaptureVerification(
            ("group-1",),
            (1, 1),
            "2026-09-12T00:00:00+00:00",
            True,
        ),
    )
    return build_reviewed_cohort_readiness(snapshot, _links())[0].request


def _snapshot_rows():
    return pd.DataFrame(
        [
            {
                "snapshot_date": "2025-05-09",
                "team_id": team_id,
                "age_group": "u14",
                "gender": "Male",
                "status": "Active",
                "rank_in_cohort_final": rank,
                "power_score_final": power,
                "sos_norm": 0.5,
                "offense_norm": 0.5,
                "defense_norm": 0.5,
                "glicko_rating": 1500.0,
                "glicko_rd": 80.0,
                "glicko_volatility": 0.06,
                "games_played": 10,
                "last_calculated": "2025-05-09T10:00:00Z",
                "created_at": "2025-05-09T11:00:00Z",
            }
            for team_id, rank, power in (
                ("canonical-a", 1, 0.7),
                ("canonical-b", 2, 0.5),
            )
        ]
    )


def test_preflight_checks_every_entrant_with_same_strict_cutoff(tmp_path, monkeypatch):
    from src.tournaments import backtest_historical_preflight as preflight

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"model")
    monkeypatch.setattr(preflight, "MergeResolver", _Resolver)
    monkeypatch.setattr(
        preflight.PointInTimeMatchModel,
        "load",
        lambda _path: SimpleNamespace(training_metadata={"model_data_end_date": "2025-05-08"}),
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_rows_by_ids",
        lambda *_args, **_kwargs: [
            {"team_id_master": "canonical-a", "team_name": "Alpha"},
            {"team_id_master": "canonical-b", "team_name": "Bravo"},
        ],
    )

    async def snapshots(*_args, **_kwargs):
        return _snapshot_rows()

    monkeypatch.setattr(preflight, "fetch_prediction_feature_snapshots", snapshots)

    result = run_historical_preflight((_request(),), object(), model_artifact=artifact)

    assert result.ready is True
    assert result.cutoff_exclusive == "2025-05-10"
    assert result.model_data_end_date == "2025-05-08"
    assert result.cohorts[0].eligible == result.cohorts[0].total == 2
    assert HistoricalPreflight.from_dict(result.to_dict()) == result


def test_preflight_reports_missing_snapshot_as_team_evidence_gap(tmp_path, monkeypatch):
    from src.tournaments import backtest_historical_preflight as preflight

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"model")
    monkeypatch.setattr(preflight, "MergeResolver", _Resolver)
    monkeypatch.setattr(
        preflight.PointInTimeMatchModel,
        "load",
        lambda _path: SimpleNamespace(training_metadata={"model_data_end_date": "2025-05-08"}),
    )
    monkeypatch.setattr(preflight, "_fetch_rows_by_ids", lambda *_args, **_kwargs: [])

    async def snapshots(*_args, **_kwargs):
        return _snapshot_rows().iloc[:1]

    monkeypatch.setattr(preflight, "fetch_prediction_feature_snapshots", snapshots)

    result = run_historical_preflight((_request(),), object(), model_artifact=artifact)

    assert result.ready is False
    assert result.cohorts[0].eligible == 1
    assert "No prediction_feature_history snapshot" in result.cohorts[0].entrants[1].reason


def test_preflight_keeps_database_outage_distinct_from_missing_history(tmp_path, monkeypatch):
    from src.tournaments import backtest_historical_preflight as preflight

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"model")
    monkeypatch.setattr(preflight, "MergeResolver", _Resolver)
    monkeypatch.setattr(
        preflight.PointInTimeMatchModel,
        "load",
        lambda _path: SimpleNamespace(training_metadata={"model_data_end_date": "2025-05-08"}),
    )
    monkeypatch.setattr(
        preflight,
        "_fetch_rows_by_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    with pytest.raises(HistoricalPreflightUnavailable, match="could not be read"):
        run_historical_preflight((_request(),), object(), model_artifact=artifact)


def test_preflight_cache_key_changes_with_merge_map_version(tmp_path, monkeypatch):
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"model")
    monkeypatch.setattr(
        "src.tournaments.backtest_historical_preflight.model_artifact_sha256",
        lambda _path: "model-sha",
    )

    first = preflight_input_sha256((_request(),), artifact, merge_map_version="merge-v1")
    second = preflight_input_sha256((_request(),), artifact, merge_map_version="merge-v2")

    assert first != second
