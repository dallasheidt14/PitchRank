from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.predictions.model_laboratory import report_digest
from src.predictions.model_registry import (
    activate_model_version,
    eligible_registry_artifacts,
    load_registry,
    register_model_version,
)


def _write_candidate(tmp_path: Path) -> tuple[Path, Path]:
    artifact = tmp_path / "candidate" / "point_in_time_match_model.pkl"
    artifact.parent.mkdir()
    artifact.write_bytes(b"reviewed-model-artifact")
    metadata = {
        "model_data_end_date": "2026-08-31",
        "probability_strategy": "score_distribution",
        "selection_objective": "competitive_match_quality",
        "training_dataset_sha256": "dataset-sha",
    }
    artifact.with_name("point_in_time_match_model_metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "matchbalance-model-laboratory-v1",
        "dataset": {"sha256": "dataset-sha"},
        "promotion": {
            "candidate-v2": {
                "decision": "promote",
                "automatic_activation": False,
                "shared_games": 1200,
            }
        },
    }
    manifest["report_sha256"] = report_digest(manifest)
    manifest_path = tmp_path / "laboratory_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return artifact, manifest_path


def test_registration_is_immutable_and_does_not_activate(tmp_path):
    artifact, manifest = _write_candidate(tmp_path)
    registry_root = tmp_path / "registry"

    entry = register_model_version(
        registry_root=registry_root,
        version="2026.09.13-v2",
        artifact=artifact,
        laboratory_manifest=manifest,
        candidate="candidate-v2",
    )

    registry = load_registry(registry_root)
    assert entry["activated_at"] is None
    assert registry["active_version"] is None
    assert eligible_registry_artifacts(
        registry_root,
        cutoff_exclusive="2026-09-05",
    ) == []
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        register_model_version(
            registry_root=registry_root,
            version="2026.09.13-v2",
            artifact=artifact,
            laboratory_manifest=manifest,
            candidate="candidate-v2",
        )


def test_activation_enables_only_pre_cutoff_hash_valid_artifact(tmp_path):
    artifact, manifest = _write_candidate(tmp_path)
    registry_root = tmp_path / "registry"
    register_model_version(
        registry_root=registry_root,
        version="2026.09.13-v2",
        artifact=artifact,
        laboratory_manifest=manifest,
        candidate="candidate-v2",
    )

    activated = activate_model_version(
        registry_root=registry_root,
        version="2026.09.13-v2",
    )

    eligible = eligible_registry_artifacts(
        registry_root,
        cutoff_exclusive="2026-09-05",
    )
    assert activated["activated_at"]
    assert len(eligible) == 1
    assert eligible[0][0] == "2026-08-31"
    assert eligible_registry_artifacts(
        registry_root,
        cutoff_exclusive="2026-08-31",
    ) == []

    eligible[0][1].write_bytes(b"corrupted")
    assert eligible_registry_artifacts(
        registry_root,
        cutoff_exclusive="2026-09-05",
    ) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest["promotion"]["candidate-v2"].update(decision="hold"), "does not recommend"),
        (lambda manifest: manifest["dataset"].update(sha256="different"), "same training dataset"),
    ],
)
def test_registration_rejects_unpromoted_or_mismatched_evidence(tmp_path, mutation, message):
    artifact, manifest_path = _write_candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("report_sha256")
    mutation(manifest)
    manifest["report_sha256"] = report_digest(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        register_model_version(
            registry_root=tmp_path / "registry",
            version="candidate-v2",
            artifact=artifact,
            laboratory_manifest=manifest_path,
            candidate="candidate-v2",
        )
