"""Read-only live Seeding bridge to Compare's shared data loader and predictor.

Credentials travel only through the subprocess environment. A failed predictor or
database read aborts the batch; there is no approximate PowerScore fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.tournaments.compare_predictor_bridge import (
    ComparePrediction,
    _parse_prediction,
    canonical_predictor_sha256,
)

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_SCRIPT = _FRONTEND_DIR / "scripts" / "run-seeding-predictions.ts"
_SHIM = _FRONTEND_DIR / "scripts" / "server-only-shim.cjs"
_TSX_CLI = _FRONTEND_DIR / "node_modules" / "tsx" / "dist" / "cli.mjs"
_UUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class SeedingPredictionBatch:
    predictions: dict[str, dict[tuple[str, str], ComparePrediction]]
    teams: dict[str, dict[str, dict[str, Any]]]
    unavailable: dict[str, dict[str, str]]
    generated_at: str
    ratings_as_of: str | None
    predictor_sha256: str


def seeding_predictor_sha256() -> str:
    """Include live input mapping and the bridge alongside Compare/calibration."""
    digest = hashlib.sha256(canonical_predictor_sha256().encode("ascii"))
    for path in (
        _FRONTEND_DIR / "lib" / "matchPredictionService.ts",
        _FRONTEND_DIR / "lib" / "seedingPredictions.ts",
        _SCRIPT,
        _SHIM,
        Path(__file__),
    ):
        contents = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _validate_cohorts(cohorts: dict[str, dict[str, str]]) -> None:
    if not isinstance(cohorts, dict):
        raise ValueError("Seeding cohorts must be a mapping")
    for cohort_key, entrants in cohorts.items():
        if not isinstance(cohort_key, str) or not cohort_key or not isinstance(entrants, dict):
            raise ValueError("Invalid Seeding cohort")
        for entrant_id, team_id in entrants.items():
            if not isinstance(entrant_id, str) or not entrant_id:
                raise ValueError("Seeding entrant IDs must be nonempty strings")
            if not isinstance(team_id, str) or not _UUID.fullmatch(team_id):
                raise ValueError("Seeding team IDs must be PitchRank UUIDs")


def _validate_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Seeding Compare result contains a non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite(item)
    elif isinstance(value, list):
        for item in value:
            _validate_finite(item)


def _parse_batch(result: Any, cohorts: dict[str, dict[str, str]], predictor_sha256: str) -> SeedingPredictionBatch:
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise ValueError("Invalid Seeding Compare result schema")
    _validate_finite(result)
    outputs = result.get("cohorts")
    if not isinstance(outputs, dict) or set(outputs) != set(cohorts):
        raise ValueError("Seeding Compare result has incomplete cohort coverage")
    stamp = result.get("generated_at")
    if not isinstance(stamp, str) or datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("Seeding Compare result has no valid generation timestamp")
    ratings_as_of = result.get("ratings_as_of")
    if ratings_as_of is not None and not isinstance(ratings_as_of, str):
        raise ValueError("Seeding Compare result has an invalid ratings timestamp")
    predictions = {}
    teams = {}
    unavailable = {}
    for cohort_key, entrants in cohorts.items():
        output = outputs[cohort_key]
        if not isinstance(output, dict):
            raise ValueError("Invalid Seeding Compare cohort result")
        cohort_teams = output.get("teams")
        missing = output.get("unavailable")
        rows = output.get("predictions")
        if not isinstance(cohort_teams, dict) or not isinstance(missing, dict) or not isinstance(rows, list):
            raise ValueError("Invalid Seeding Compare team or prediction list")
        if set(cohort_teams) & set(missing) or set(cohort_teams) | set(missing) != set(entrants):
            raise ValueError("Seeding Compare result has incomplete entrant coverage")
        if any(not isinstance(reason, str) or not reason for reason in missing.values()):
            raise ValueError("Seeding Compare result is missing an unavailable reason")
        for team in cohort_teams.values():
            if not isinstance(team, dict) or not _UUID.fullmatch(str(team.get("team_id_master", ""))):
                raise ValueError("Seeding Compare result has an invalid team identity")
            count = team.get("prediction_game_count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("Seeding Compare result has an invalid scored game count")
        parsed = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid Seeding Compare prediction")
            key = (row.get("entrant_a"), row.get("entrant_b"))
            if any(not isinstance(item, str) for item in key) or key in parsed:
                raise ValueError("Invalid or duplicate Seeding Compare matchup")
            score = row.get("expected_score")
            if not isinstance(score, dict) or set(score) != {"teamA", "teamB"}:
                raise ValueError("Invalid Seeding Compare expected score")
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in score.values()):
                raise ValueError("Invalid Seeding Compare expected score")
            prediction = _parse_prediction(row)
            if (
                abs(prediction.win_probability_a + prediction.win_probability_b + prediction.draw_probability - 1)
                > 1e-6
                or prediction.expected_absolute_goal_difference < 0
                or prediction.confidence not in {"low", "medium", "high"}
                or prediction.confidence_score is None
            ):
                raise ValueError("Invalid Seeding Compare probabilities or confidence")
            parsed[key] = prediction
        expected = {(a, b) for a in cohort_teams for b in cohort_teams if a != b}
        if set(parsed) != expected:
            raise ValueError("Seeding Compare result has incomplete matchup coverage")
        for (a, b), forward in parsed.items():
            reverse = parsed[(b, a)]
            expected_winner = {"team_a": "team_b", "team_b": "team_a", "draw": "draw"}[forward.predicted_winner]
            if (
                reverse.predicted_winner != expected_winner
                or reverse.win_probability_a != forward.win_probability_b
                or reverse.win_probability_b != forward.win_probability_a
                or reverse.expected_margin != -forward.expected_margin
                or reverse.draw_probability != forward.draw_probability
                or reverse.expected_score
                != {"teamA": forward.expected_score["teamB"], "teamB": forward.expected_score["teamA"]}
                or reverse.blowout_4plus_probability != forward.blowout_4plus_probability
                or reverse.expected_absolute_goal_difference != forward.expected_absolute_goal_difference
                or reverse.confidence != forward.confidence
                or reverse.confidence_score != forward.confidence_score
            ):
                raise ValueError("Seeding Compare matchup orientations disagree")
        predictions[cohort_key] = parsed
        teams[cohort_key] = cohort_teams
        unavailable[cohort_key] = missing
    return SeedingPredictionBatch(
        predictions=predictions,
        teams=teams,
        unavailable=unavailable,
        generated_at=stamp,
        ratings_as_of=ratings_as_of,
        predictor_sha256=predictor_sha256,
    )


def load_seeding_predictions(
    cohorts: dict[str, dict[str, str]],
    *,
    supabase_url: str,
    supabase_key: str,
    timeout_seconds: int = 300,
) -> SeedingPredictionBatch:
    """Fetch current Compare inputs and every pair for the selected cohorts."""
    _validate_cohorts(cohorts)
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials are required for Seeding predictions")
    node = shutil.which("node")
    if not node or not _TSX_CLI.is_file():
        raise RuntimeError("Seeding requires Node.js and `npm ci --prefix frontend` for the Compare predictor")
    predictor_sha256 = seeding_predictor_sha256()
    environment = os.environ.copy()
    environment.update({"SUPABASE_URL": supabase_url, "SUPABASE_KEY": supabase_key})
    with tempfile.TemporaryDirectory(prefix="matchbalance-seeding-") as directory:
        input_path = Path(directory) / "input.json"
        output_path = Path(directory) / "output.json"
        input_path.write_text(json.dumps({"schema_version": 1, "cohorts": cohorts}, allow_nan=False), encoding="utf-8")
        command = [node, str(_TSX_CLI), "-r", str(_SHIM), str(_SCRIPT), str(input_path), str(output_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=_FRONTEND_DIR,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Seeding Compare prediction timed out; no pack was generated") from exc
        except OSError as exc:
            raise RuntimeError("Seeding Compare runtime could not start; no pack was generated") from exc
        if completed.returncode != 0:
            # Never reflect HTTP/database stderr, which could carry credentials.
            raise RuntimeError("Seeding Compare prediction failed; verify database access and ranking inputs")
        if not output_path.is_file():
            raise RuntimeError("Seeding Compare predictor did not write a result")
        result = json.loads(output_path.read_text(encoding="utf-8"))
    return _parse_batch(result, cohorts, predictor_sha256)
