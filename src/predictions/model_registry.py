"""Immutable local registry for reviewed MatchBalance model artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.predictions.model_laboratory import report_digest

REGISTRY_SCHEMA_VERSION = "matchbalance-model-registry-v1"
LABORATORY_SCHEMA_VERSION = "matchbalance-model-laboratory-v1"
VERSION_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,78}[a-z0-9])?$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "active_version": None,
        "versions": {},
    }


def load_registry(registry_root: str | Path) -> dict[str, Any]:
    root = Path(registry_root).resolve()
    path = root / "registry.json"
    if not path.is_file():
        return _empty_registry()
    registry = _read_json(path)
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported MatchBalance model registry: {path}")
    if not isinstance(registry.get("versions"), dict):
        raise ValueError(f"Registry versions must be an object: {path}")
    return registry


def _validate_laboratory_manifest(
    laboratory_manifest: Path,
    *,
    candidate: str,
) -> tuple[dict[str, Any], str]:
    manifest = _read_json(laboratory_manifest)
    if manifest.get("schema_version") != LABORATORY_SCHEMA_VERSION:
        raise ValueError("Laboratory manifest has an unsupported schema version")
    recorded_digest = str(manifest.get("report_sha256") or "")
    digest_payload = dict(manifest)
    digest_payload.pop("report_sha256", None)
    calculated_digest = report_digest(digest_payload)
    if not recorded_digest or recorded_digest != calculated_digest:
        raise ValueError("Laboratory manifest report digest does not match its contents")
    promotion = manifest.get("promotion", {}).get(candidate)
    if not isinstance(promotion, dict) or promotion.get("decision") != "promote":
        raise ValueError(f"Laboratory evidence does not recommend promoting '{candidate}'")
    if promotion.get("automatic_activation") is not False:
        raise ValueError("Laboratory promotion evidence must prohibit automatic activation")
    return manifest, calculated_digest


def register_model_version(
    *,
    registry_root: str | Path,
    version: str,
    artifact: str | Path,
    laboratory_manifest: str | Path,
    candidate: str,
) -> dict[str, Any]:
    """Copy a reviewed artifact into a new immutable registry version."""

    normalized_version = str(version).strip().lower()
    if not VERSION_PATTERN.fullmatch(normalized_version):
        raise ValueError("Version must use lowercase letters, numbers, dots, dashes, or underscores")
    root = Path(registry_root).resolve()
    registry = load_registry(root)
    if normalized_version in registry["versions"] or (root / normalized_version).exists():
        raise FileExistsError(f"Model version already exists and cannot be overwritten: {normalized_version}")

    artifact_path = Path(artifact).resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Model artifact does not exist: {artifact_path}")
    metadata_path = artifact_path.with_name(f"{artifact_path.stem}_metadata.json")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Model metadata does not exist: {metadata_path}")
    metadata = _read_json(metadata_path)
    data_end = str(metadata.get("model_data_end_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_end):
        raise ValueError("Model metadata must contain model_data_end_date")
    strategy = str(metadata.get("probability_strategy") or "").strip().lower()
    if strategy != "score_distribution":
        raise ValueError("Registered Backtest models must use the coherent score_distribution strategy")

    manifest_path = Path(laboratory_manifest).resolve()
    manifest, report_sha = _validate_laboratory_manifest(
        manifest_path,
        candidate=candidate,
    )
    trained_dataset_sha = str(metadata.get("training_dataset_sha256") or "")
    laboratory_dataset_sha = str((manifest.get("dataset") or {}).get("sha256") or "")
    if not trained_dataset_sha or trained_dataset_sha != laboratory_dataset_sha:
        raise ValueError(
            "Model metadata and laboratory manifest must reference the same training dataset SHA-256"
        )

    artifact_sha = _sha256(artifact_path)
    metadata_sha = _sha256(metadata_path)
    manifest_sha = _sha256(manifest_path)
    registered_at = _utc_now()
    entry = {
        "version": normalized_version,
        "registered_at": registered_at,
        "activated_at": None,
        "artifact": f"{normalized_version}/point_in_time_match_model.pkl",
        "metadata": f"{normalized_version}/point_in_time_match_model_metadata.json",
        "laboratory_manifest": f"{normalized_version}/laboratory_manifest.json",
        "artifact_sha256": artifact_sha,
        "metadata_sha256": metadata_sha,
        "laboratory_manifest_sha256": manifest_sha,
        "laboratory_report_sha256": report_sha,
        "training_dataset_sha256": trained_dataset_sha,
        "model_data_end_date": data_end,
        "probability_strategy": strategy,
        "selection_objective": str(metadata.get("selection_objective") or ""),
        "candidate": candidate,
        "promotion": manifest["promotion"][candidate],
    }

    destination = root / normalized_version
    destination.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(artifact_path, destination / "point_in_time_match_model.pkl")
        shutil.copy2(metadata_path, destination / "point_in_time_match_model_metadata.json")
        shutil.copy2(manifest_path, destination / "laboratory_manifest.json")
        (destination / "version.json").write_text(
            json.dumps(entry, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        registry["versions"][normalized_version] = entry
        _write_json_atomic(root / "registry.json", registry)
    except Exception:
        if destination.exists() and normalized_version not in load_registry(root)["versions"]:
            shutil.rmtree(destination)
        raise
    return entry


def activate_model_version(
    *,
    registry_root: str | Path,
    version: str,
) -> dict[str, Any]:
    """Explicitly make a registered version eligible for Backtest selection."""

    root = Path(registry_root).resolve()
    registry = load_registry(root)
    normalized_version = str(version).strip().lower()
    entry = registry["versions"].get(normalized_version)
    if not isinstance(entry, dict):
        raise KeyError(f"Unknown registered model version: {version}")
    artifact_path = root / str(entry["artifact"])
    if not artifact_path.is_file() or _sha256(artifact_path) != entry.get("artifact_sha256"):
        raise ValueError(f"Registered artifact is missing or corrupted: {normalized_version}")
    if not entry.get("activated_at"):
        entry["activated_at"] = _utc_now()
    registry["active_version"] = normalized_version
    _write_json_atomic(root / "registry.json", registry)
    return dict(entry)


def eligible_registry_artifacts(
    registry_root: str | Path,
    *,
    cutoff_exclusive: str,
) -> list[tuple[str, Path]]:
    """Return activated, hash-valid artifacts strictly before an event cutoff."""

    cutoff = str(cutoff_exclusive).strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
        return []
    root = Path(registry_root).resolve()
    try:
        registry = load_registry(root)
    except (OSError, ValueError, TypeError):
        return []
    eligible: list[tuple[str, Path]] = []
    for version, entry in registry["versions"].items():
        if not isinstance(entry, dict) or not entry.get("activated_at"):
            continue
        data_end = str(entry.get("model_data_end_date") or "")
        if not data_end or data_end >= cutoff:
            continue
        artifact_path = root / str(entry.get("artifact") or "")
        metadata_path = root / str(entry.get("metadata") or "")
        manifest_path = root / str(entry.get("laboratory_manifest") or "")
        expected_files = (
            (artifact_path, entry.get("artifact_sha256")),
            (metadata_path, entry.get("metadata_sha256")),
            (manifest_path, entry.get("laboratory_manifest_sha256")),
        )
        try:
            intact = all(
                path.is_file() and expected_sha and _sha256(path) == expected_sha
                for path, expected_sha in expected_files
            )
        except OSError:
            intact = False
        if intact:
            eligible.append((data_end, artifact_path.resolve()))
    return sorted(eligible, key=lambda item: (item[0], str(item[1])))
