"""Fixed, private prospective score study. No fitting or target-result reads during capture."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import subprocess
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from src.predictions.challenger_sources import candidate_execution_paths
from src.predictions.score_challenger import CANDIDATES, OUTCOME_FIELDS, candidate_definition, score_candidate

KIND = "compare_score_confirmation_v1"
ENTRYPOINT = "scripts/capture_compare_score_study.py"
FALLBACKS = ("cross_cohort_fallback", "unseen_team_fallback", "unseen_cohort_fallback")
SHA = re.compile(r"[a-f0-9]{64}")
POLICY = {
    "minimum_pairs": 1000, "minimum_groups": 20,
    "primary_candidate": "blend_25", "secondary_candidate": "tail_guard_full",
    "primary_metric": "mean_absolute_goals_per_team",
    "score_log_loss_basis": ("0..40 independent-Poisson grid reconstructed from frozen goals "
                             "and conditioned on frozen WDL"),
    "metrics": ["mean_absolute_goals_per_team", "exact_score_rate", "margin_mae",
                "score_log_loss", "four_goal_brier", "winner_accuracy", "coverage"],
    "bootstrap": {"unit": "match_group", "repetitions": 10000, "seed": 20261123, "confidence": 0.95},
    "multiplicity": "Holm across two goal-error comparisons; report both candidates without reselection",
    "release": "review_required; insufficient_pairs_or_groups_means_no_decision; no_automatic_promotion",
}


def serialized(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_identity(root: Path) -> dict:
    entrypoints = sorted(path.relative_to(root).as_posix()
                         for path in (root / "scripts").glob("*compare_score_study.py"))
    paths = candidate_execution_paths(root, entrypoints=entrypoints)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    hashes = {}
    for name in sorted(paths):
        raw = (root / name).read_text(encoding="utf-8").encode()
        committed = subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=root)
        if raw != committed.replace(b"\r\n", b"\n"):
            raise ValueError("Score execution dependency is uncommitted: " + name)
        hashes[name] = digest(raw)
    return {"code_revision": revision, "execution_hashes": hashes}


def validate_definition(m: dict, *, registered_at: str | None = None) -> None:
    start, end = (date.fromisoformat(m[key]) for key in ("capture_start", "capture_end"))
    review = date.fromisoformat(m["review_not_before"])
    if (m.get("kind") != KIND or m.get("schema_version") != 1 or start.weekday() != 0
            or end != start + timedelta(days=27) or review <= end or review < date(2027, 1, 11)
            or m.get("entrypoint") != ENTRYPOINT or m.get("policy") != POLICY
            or m.get("candidates") != {key: candidate_definition(key) for key in CANDIDATES}
            or m.get("production_promotion") is not False):
        raise ValueError("Invalid fixed score-study definition")
    for key in ("monitor_signature", "baseline_model_signature"):
        if not SHA.fullmatch(m.get(key, "")):
            raise ValueError("Missing baseline identity")
    if not re.fullmatch(r"[a-f0-9]{40}", m.get("code_revision", "")):
        raise ValueError("Missing committed research revision")
    hashes = m.get("execution_hashes", {})
    if ENTRYPOINT not in hashes or not all(SHA.fullmatch(v) for v in hashes.values()):
        raise ValueError("Missing execution hashes")
    artifact = m["artifact"]
    if (artifact.get("bucket") != "prediction-input-archives"
            or not re.fullmatch(r"compare-score-research/\d{4}-\d{2}-\d{2}/[a-f0-9]{64}\.zip",
                                artifact.get("object", ""))
            or not all(SHA.fullmatch(artifact.get(k, "")) for k in ("zip_sha256", "model_sha256"))
            or artifact.get("model_member") != "prospective/fitted-model.json"
            or artifact.get("training_member") != "prospective/training-games.json"):
        raise ValueError("Invalid existing private model artifact")
    receipt = m["fit_receipt"]
    if (receipt.get("optimizer_success") is not True or receipt.get("penalty") != 4
            or receipt.get("half_life") != 60 or not SHA.fullmatch(receipt.get("data_sha256", ""))
            or not date.fromisoformat(receipt["latest_training_game"])
            < date.fromisoformat(receipt["cutoff"]) <= start):
        raise ValueError("Invalid pre-study training provenance")
    if registered_at and datetime.fromisoformat(registered_at.replace("Z", "+00:00")).date() >= start:
        raise ValueError("Study was not registered before its first target day")


def verified_fit(bundle: bytes, manifest: dict) -> dict:
    """Verify the existing private backup in memory; never extract or execute its members."""
    artifact = manifest["artifact"]
    if len(bundle) > 64 * 1024 * 1024 or digest(bundle) != artifact["zip_sha256"]:
        raise ValueError("Model backup identity differs")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        def member(name, limit):
            matches = [entry for entry in archive.infolist() if entry.filename == name]
            if len(matches) != 1 or matches[0].file_size > limit:
                raise ValueError("Missing, duplicated or oversized model member")
            with archive.open(matches[0]) as handle:
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("Oversized model member")
            return raw

        raw = member(artifact["model_member"], 8 * 1024 * 1024)
        training = json.loads(member(artifact["training_member"], 32 * 1024 * 1024))
    if digest(raw) != artifact["model_sha256"]:
        raise ValueError("Fitted model identity differs")
    fit = json.loads(raw)
    receipt = fit["receipt"]
    if receipt != manifest["fit_receipt"]:
        raise ValueError("Training receipt differs")
    if (len(training) != receipt["games"] or len({g["id"] for g in training}) != len(training)
            or max(g["game_date"] for g in training) != receipt["latest_training_game"]
            or any(g["game_date"] >= receipt["cutoff"] for g in training)
            or digest(serialized([(g["id"], g["home_score"], g["away_score"]) for g in training]).encode())
            != receipt["data_sha256"]):
        raise ValueError("Training games differ from the frozen fit receipt")
    teams, cohorts = fit["teams"], fit["cohorts"]
    counts = Counter(t for g in training for t in (g["home_team_master_id"], g["away_team_master_id"]))
    parameters = np.asarray(fit["parameters"], dtype=float)
    if (len(teams) != len(set(teams)) or len(cohorts) != len(set(cohorts))
            or set(teams) != set(counts) or fit["counts"] != dict(counts)
            or len(teams) != receipt["teams"] or len(cohorts) != receipt["cohorts"]
            or set(cohorts) != {g["cohort"] for g in training}
            or parameters.shape != (len(cohorts) + 2 * len(teams),) or not np.isfinite(parameters).all()):
        raise ValueError("Fitted parameter dimensions or training population differ")
    return fit


def canonical_teams(context: dict) -> tuple[str, str]:
    aliases = context["frozenEvidence"]["aliases"]

    def canonical(team):
        seen = set()
        while team in aliases and aliases[team] != team:
            if team in seen:
                raise ValueError("Cycle in frozen team aliases")
            seen.add(team)
            team = aliases[team]
        return team

    return tuple(canonical(context[key]["team_id_master"]) for key in ("teamAInput", "teamBInput"))


def learned_rates(context: dict, fit: dict) -> tuple[list[float] | None, str]:
    a, b = context["teamAInput"], context["teamBInput"]
    ai, bi = canonical_teams(context)
    if (a["age"], a["gender"]) != (b["age"], b["gender"]):
        return None, FALLBACKS[0]
    if ai not in fit["teams"] or bi not in fit["teams"]:
        return None, FALLBACKS[1]
    cohort = str(a["age"]) + "_" + a["gender"]
    if cohort not in fit["cohorts"]:
        return None, FALLBACKS[2]
    n, k, p = len(fit["teams"]), len(fit["cohorts"]), fit["parameters"]
    x, y = fit["teams"].index(ai), fit["teams"].index(bi)
    intercept = p[fit["cohorts"].index(cohort)]
    return [min(7.5, max(0.15, math.exp(intercept + p[k+i] - p[k+n+j]))) for i, j in ((x, y), (y, x))], "eligible"


def score_payload(row: dict, manifest: dict, fit: dict, signature: str) -> dict:
    parent = row["parent_payload"]
    if (parent["model_signature"] != manifest["baseline_model_signature"]
            or row["monitor_signature"] != manifest["monitor_signature"]
            or fit["receipt"] != manifest["fit_receipt"]
            or fit["receipt"]["latest_training_game"] >= row["game_date"]):
        raise ValueError("Wrong baseline or training provenance")
    baseline = parent["prediction"]
    rates, eligibility = learned_rates(parent["context"], fit)
    teams = canonical_teams(parent["context"])
    inputs = [parent["context"][key] for key in ("teamAInput", "teamBInput")]
    candidates = {}
    for key in CANDIDATES:
        result = score_candidate(baseline, rates, candidate=key, eligibility=eligibility)
        prediction = result.prediction
        if any(prediction[field] != baseline[field] for field in OUTCOME_FIELDS):
            raise ValueError("Score candidate changed the outcome forecast")
        if key == "tail_guard_full":
            if abs(prediction["blowout4PlusProbability"] - baseline["blowout4PlusProbability"]) > 1e-12:
                raise ValueError("Protected score candidate changed baseline blowout risk")
            prediction["blowout4PlusProbability"] = baseline["blowout4PlusProbability"]
        candidates[key] = {"prediction": prediction, "status": result.status}
    return {
        "schema_version": 1, "study_signature": signature,
        "baseline_payload_sha256": row["parent_payload_sha256"],
        "code_revision": manifest["code_revision"], "execution_hashes": manifest["execution_hashes"],
        "model_sha256": manifest["artifact"]["model_sha256"],
        "eligibility": eligibility, "learned_rates": rates, "candidates": candidates,
        "team_pair": sorted(teams), "training_games": [fit["counts"].get(team, 0) for team in teams],
        "cohort_pair": [str(team["age"])+"_"+team["gender"] for team in inputs],
    }
