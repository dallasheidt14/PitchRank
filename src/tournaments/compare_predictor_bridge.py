"""Batch bridge from Python Backtest runs to the canonical Compare predictor."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIR = _REPO_ROOT / "frontend"
_CALIBRATION_DIR = _FRONTEND_DIR / "public" / "data" / "calibration"
_BATCH_SCRIPT = _FRONTEND_DIR / "scripts" / "run-backtest-predictions.ts"
_TSX_CLI = _FRONTEND_DIR / "node_modules" / "tsx" / "dist" / "cli.mjs"

PREDICTOR_CALIBRATION_AVAILABLE_DATE = "2026-04-20"
PREDICTOR_CALIBRATION_SOURCE_COMMIT = "b76902f95eda14ed0b4c5c68d782ac2c01aa01f2"
PREDICTOR_IDENTITY_FILES = (
    _FRONTEND_DIR / "lib" / "matchPredictor.ts",
    _FRONTEND_DIR / "lib" / "confidenceEngine.ts",
    _FRONTEND_DIR / "lib" / "calibrationLoader.ts",
    _FRONTEND_DIR / "lib" / "teamAge.ts",
    _BATCH_SCRIPT,
    _CALIBRATION_DIR / "age_group_parameters.json",
    _CALIBRATION_DIR / "probability_parameters.json",
    _CALIBRATION_DIR / "margin_parameters_v2.json",
    _CALIBRATION_DIR / "confidence_parameters_v2.json",
    _CALIBRATION_DIR / "heuristic_outcome_calibration.json",
)


def _locked_tsx_version() -> str:
    lock = json.loads((_FRONTEND_DIR / "package-lock.json").read_text(encoding="utf-8"))
    version = str(((lock.get("packages") or {}).get("node_modules/tsx") or {}).get("version") or "")
    if not version:
        raise RuntimeError("frontend/package-lock.json does not contain the required tsx runtime")
    return version


@dataclass(frozen=True)
class ComparePrediction:
    predicted_winner: str
    win_probability_a: float
    win_probability_b: float
    draw_probability: float
    expected_score: dict[str, int]
    expected_margin: float
    expected_absolute_goal_difference: float
    blowout_4plus_probability: float


def canonical_predictor_sha256() -> str:
    """Identify the exact Compare runtime and checked-in calibration files."""

    provenance = json.dumps(
        {
            "calibration_available_date": PREDICTOR_CALIBRATION_AVAILABLE_DATE,
            "calibration_source_commit": PREDICTOR_CALIBRATION_SOURCE_COMMIT,
            "cutoff_policy": "calibration_available_date_strictly_before_event_cutoff",
            "tsx_version": _locked_tsx_version(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest_parts: list[bytes] = [len(provenance).to_bytes(4, "big"), provenance]
    for path in PREDICTOR_IDENTITY_FILES:
        relative = path.relative_to(_REPO_ROOT).as_posix().encode("utf-8")
        digest_parts.append(len(relative).to_bytes(4, "big"))
        digest_parts.append(relative)
        contents = path.read_bytes()
        digest_parts.append(len(contents).to_bytes(8, "big"))
        digest_parts.append(contents)
    return hashlib.sha256(b"".join(digest_parts)).hexdigest()


def validate_predictor_cutoff(cutoff_exclusive: str) -> None:
    """Require calibration that existed before the tournament began."""

    try:
        cutoff = date.fromisoformat(str(cutoff_exclusive).strip()[:10])
        available = date.fromisoformat(PREDICTOR_CALIBRATION_AVAILABLE_DATE)
    except ValueError as exc:
        raise ValueError(f"Invalid exclusive Backtest cutoff: {cutoff_exclusive!r}") from exc
    if available >= cutoff:
        raise ValueError(
            "PitchRank Compare calibration was not available before the event cutoff "
            f"{cutoff.isoformat()}; earliest supported cutoff is 2026-04-21"
        )


def _predictor_runtime_command() -> list[str]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to run the canonical PitchRank Compare predictor")
    if not _TSX_CLI.is_file():
        raise RuntimeError(
            "The PitchRank Compare predictor runtime is not installed; "
            "run `npm ci --prefix frontend` before running Backtest"
        )
    return [node, str(_TSX_CLI)]


def validate_predictor_runtime(*, timeout_seconds: int = 15) -> None:
    """Probe the Node-20-compatible TypeScript runtime before a cohort starts."""

    command = [*_predictor_runtime_command(), "--version"]
    try:
        completed = subprocess.run(
            command,
            cwd=_FRONTEND_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"PitchRank Compare predictor runtime check failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tsx error"
        raise RuntimeError(f"PitchRank Compare predictor runtime check failed: {detail}")


def _finite_float(value: Any, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Compare predictor returned non-finite {name}")
    return result


def _probability(value: Any, *, name: str) -> float:
    result = _finite_float(value, name=name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"Compare predictor returned invalid {name}: {result}")
    return result


def _parse_prediction(row: dict[str, Any]) -> ComparePrediction:
    winner = str(row.get("predicted_winner") or "")
    if winner not in {"team_a", "team_b", "draw"}:
        raise ValueError(f"Compare predictor returned invalid winner: {winner!r}")
    expected_score = row.get("expected_score")
    if not isinstance(expected_score, dict):
        raise ValueError("Compare predictor returned no expected score")
    return ComparePrediction(
        predicted_winner=winner,
        win_probability_a=_probability(row.get("win_probability_a"), name="win_probability_a"),
        win_probability_b=_probability(row.get("win_probability_b"), name="win_probability_b"),
        draw_probability=_probability(row.get("draw_probability"), name="draw_probability"),
        expected_score={
            "teamA": int(expected_score["teamA"]),
            "teamB": int(expected_score["teamB"]),
        },
        expected_margin=_finite_float(row.get("expected_margin"), name="expected_margin"),
        expected_absolute_goal_difference=_finite_float(
            row.get("expected_absolute_goal_difference"),
            name="expected_absolute_goal_difference",
        ),
        blowout_4plus_probability=_probability(
            row.get("blowout_4plus_probability"), name="blowout_4plus_probability"
        ),
    )


def _json_safe(value: Any) -> Any:
    """Convert dataframe scalars and missing values into strict JSON values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    scalar_item = getattr(value, "item", None)
    if callable(scalar_item):
        try:
            return _json_safe(scalar_item())
        except ValueError:
            return None
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    return value


def run_compare_prediction_batch(
    teams_by_entrant_id: dict[str, dict[str, Any]],
    games: list[dict[str, Any]],
    *,
    timeout_seconds: int = 120,
) -> dict[tuple[str, str], ComparePrediction]:
    """Run every ordered entrant matchup through frontend/lib/matchPredictor.ts."""

    entrant_ids = sorted(teams_by_entrant_id)
    if len(entrant_ids) < 2:
        return {}
    runtime_command = _predictor_runtime_command()

    payload = {
        "schema_version": 1,
        "teams": [
            {"entrant_id": entrant_id, "team": teams_by_entrant_id[entrant_id]}
            for entrant_id in entrant_ids
        ],
        "games": games,
    }
    with tempfile.TemporaryDirectory(prefix="matchbalance-compare-") as temp_dir:
        input_path = Path(temp_dir) / "input.json"
        output_path = Path(temp_dir) / "output.json"
        input_path.write_text(
            json.dumps(_json_safe(payload), sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        command = [
            *runtime_command,
            str(_BATCH_SCRIPT),
            str(input_path),
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            cwd=_FRONTEND_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Node error"
            raise RuntimeError(f"Canonical Compare predictor failed: {detail}")
        if not output_path.is_file():
            raise RuntimeError("Canonical Compare predictor did not write its result file")
        result = json.loads(output_path.read_text(encoding="utf-8"))

    rows = result.get("predictions") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Canonical Compare predictor returned an invalid batch")
    predictions: dict[tuple[str, str], ComparePrediction] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Canonical Compare predictor returned an invalid prediction row")
        key = (str(row.get("entrant_a") or ""), str(row.get("entrant_b") or ""))
        if not all(key) or key in predictions:
            raise ValueError(f"Canonical Compare predictor returned an invalid matchup key: {key!r}")
        predictions[key] = _parse_prediction(row)

    expected_keys = {(left, right) for left in entrant_ids for right in entrant_ids if left != right}
    if set(predictions) != expected_keys:
        missing = sorted(expected_keys - set(predictions))
        extra = sorted(set(predictions) - expected_keys)
        raise ValueError(
            "Canonical Compare predictor returned incomplete matchup coverage "
            f"(missing={missing[:3]}, extra={extra[:3]})"
        )
    return predictions
