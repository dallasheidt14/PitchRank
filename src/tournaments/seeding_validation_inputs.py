"""Versioned pre-event inputs and forecasts for offline accuracy comparisons."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date

TEAM_NUMERIC_FIELDS = (
    "rank_in_cohort_final", "rank_in_state_final", "power_score_final", "glicko_rating", "glicko_rd",
    "glicko_volatility", "sos_norm", "sos_norm_state", "offense_norm", "defense_norm", "same_age_games",
    "same_age_game_share", "same_age_unique_opponents", "same_age_top100_opp_count", "same_age_top500_opp_count",
    "same_age_avg_opp_power_adj", "repeat_opponent_share", "positive_ml_evidence_scale", "publication_cap_rank",
    "publication_cap_score", "wins", "losses", "draws", "games_played", "win_percentage", "exp_margin",
    "exp_win_rate", "exp_goals_for", "exp_goals_against",
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _dated(value, cutoff, message):
    if not isinstance(value, str) or date.fromisoformat(value[:10]) > cutoff:
        raise ValueError(message)


def _calibrations(values):
    paths = {
        "probability_parameters.json": ("sensitivity",),
        "margin_parameters_v2.json": ("margin_scale", *[f"age_groups.u{age}.margin_mult" for age in range(10, 19)]),
        "age_group_parameters.json": tuple(f"u{age}.{field}" for age in range(10, 19)
                                            for field in ("avg_goals", "margin_mult")),
        "confidence_parameters_v2.json": ("weights.composite_diff", "weights.variance", "weights.sample_strength",
                                           "intercept", "thresholds.high", "thresholds.medium"),
        "heuristic_outcome_calibration.json": ("alpha", "prior.team_a", "prior.draw", "prior.team_b",
                                                "draw_override_max_win_gap"),
    }
    try:
        for name, fields in paths.items():
            for field in fields:
                value = values[name]
                for key in field.split("."):
                    value = value[key]
                if not _number(value):
                    raise ValueError("Invalid frozen calibration value")
        outcome = values["heuristic_outcome_calibration.json"]
        if not isinstance(outcome["enabled"], bool) or not isinstance(outcome["draw_override_age_thresholds"], dict):
            raise ValueError("Invalid frozen calibration settings")
        if not all(_number(value) for value in outcome["draw_override_age_thresholds"].values()):
            raise ValueError("Invalid frozen calibration thresholds")
    except (KeyError, TypeError) as exc:
        raise ValueError("Incomplete frozen calibration inputs") from exc


def _candidate(candidate, cutoff):
    try:
        _dated(candidate["captured_at"], cutoff, "Inputs were not frozen before the event cutoff")
        if not re.fullmatch(r"[0-9a-f]{64}", candidate["model_sha256"]):
            raise ValueError("Invalid frozen model identity")
        _calibrations(candidate["calibration_inputs"])
        evidence = candidate["evidence"]
        if evidence["schema_version"] != 1 or evidence["model"] not in {"legacy", "cohort", "results"}:
            raise ValueError("Invalid frozen evidence model")
        _dated(evidence["as_of"], cutoff, "Frozen analysis uses post-cutoff information")
        _dated(evidence["window_start"], date.fromisoformat(evidence["as_of"]), "Invalid frozen history window")
        parameters = evidence["model_parameters"]
        if evidence["model"] == "results":
            if (parameters["version"] != "opponent_adjusted_results_v1"
                    or not all(_number(parameters[key]) and parameters[key] > 0
                               for key in ("halfLifeDays", "marginCap", "priorWeight"))
                    or not _number(parameters["previousSeasonWeight"])
                    or not 0 <= parameters["previousSeasonWeight"] <= 1):
                raise ValueError("Invalid frozen result-model parameters")
        teams = [*evidence["teams"].values(), *evidence["opponents"].values()]
        for team in teams:
            if (not isinstance(team["team_id_master"], str) or not team["team_id_master"]
                    or not isinstance(team["team_name"], str) or team["gender"] not in {"M", "F"}
                    or not isinstance(team["age"], int) or isinstance(team["age"], bool) or team["age"] < 1
                    or not isinstance(team["has_modular11_alias"], bool)):
                raise ValueError("Invalid frozen team features")
            for key in ("club_name", "league", "distinction", "state", "last_scraped_at"):
                if team[key] is not None and not isinstance(team[key], str):
                    raise ValueError("Invalid frozen team features")
            if any(team[key] is not None and not _number(team[key]) for key in TEAM_NUMERIC_FIELDS):
                raise ValueError("Invalid frozen rating features")
            _dated(team["ratings_as_of"], cutoff, "Frozen ratings contain post-cutoff information")
        if not isinstance(evidence["games"], list):
            raise ValueError("Invalid frozen history")
        game_ids = set()
        for game in evidence["games"]:
            if (not isinstance(game["id"], str) or not game["id"] or game["id"] in game_ids
                    or not all(isinstance(game[key], str) and game[key]
                               for key in ("home_team_master_id", "away_team_master_id"))
                    or game["home_team_master_id"] == game["away_team_master_id"]
                    or not all(isinstance(game[key], int) and not isinstance(game[key], bool) and game[key] >= 0
                               for key in ("home_score", "away_score"))):
                raise ValueError("Invalid frozen scored-game inputs")
            game_ids.add(game["id"])
            if game["ml_overperformance"] is not None and not _number(game["ml_overperformance"]):
                raise ValueError("Invalid frozen game form feature")
            if game["is_excluded"] is not False:
                raise ValueError("Frozen history must contain only eligible games")
            if any(game[key] is not None and not isinstance(game[key], str)
                   for key in ("event_name", "competition")):
                raise ValueError("Invalid frozen game event identity")
            _dated(game["game_date"], cutoff, "Frozen history contains a future result")
        order = candidate["order"]
        entrants = {team["team_id_master"]: team for team in evidence["teams"].values()}
        if (not isinstance(order, list) or len(order) != len(set(order))
                or not set(order) <= entrants.keys()):
            raise ValueError("Invalid frozen candidate order")
        if any(not _number(entrants[key]["power_score_final"])
               or not 0 <= entrants[key]["power_score_final"] <= 1 for key in order):
            raise ValueError("Seeded frozen participants need a usable PowerScore")
        return evidence, teams
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Incomplete frozen model inputs") from exc


def frozen_validation_inputs(pack: dict, cohort: str, *, candidate_packs: dict | None = None) -> tuple[str, dict]:
    """Freeze named saved candidates, including their suggested seeds and forecasts."""
    from src.tournaments.compare_predictor_bridge import PREDICTOR_CALIBRATION_AVAILABLE_DATE
    candidates = {}
    for label, saved in (candidate_packs or {pack.get("prediction_model", "legacy"): pack}).items():
        evidence = json.loads(saved["input_evidence"][cohort]["canonical_json"])
        identities = {key: team["team_id_master"] for key, team in evidence["teams"].items()}
        order = [identities[key] for key in saved["ordering"][cohort]["suggested_order"]]
        forecasts = []
        for prediction in saved["predictions"][cohort]:
            a, b = identities[prediction["entrant_a"]], identities[prediction["entrant_b"]]
            forecasts.append({"team_a": a, "team_b": b,
                              "probabilities": [prediction["win_probability_a"], prediction["draw_probability"],
                                                prediction["win_probability_b"]],
                              "margin": prediction["expected_margin"],
                              "blowout_probability": prediction["blowout_4plus_probability"]})
        candidates[label] = {"cohort": cohort, "captured_at": saved["generated_at"], "evidence": evidence,
                             "model_sha256": saved["predictor_sha256"], "order": order, "forecasts": forecasts,
                             "calibration_inputs": saved["calibration_inputs"]}
    cutoff = max(date.fromisoformat(item["captured_at"][:10]) for item in candidates.values())
    checked = [_candidate(item, cutoff) for item in candidates.values()]
    payload = json.dumps({"schema_version": 2, "candidates": candidates}, sort_keys=True, allow_nan=False)
    manifest = {"sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "ratings_available_date": max(team["ratings_as_of"][:10] for _, teams in checked for team in teams),
                "history_max_date": max(max((game["game_date"][:10] for game in evidence["games"]),
                                            default=evidence["window_start"]) for evidence, _ in checked),
                "calibration_available_date": PREDICTOR_CALIBRATION_AVAILABLE_DATE}
    return payload, manifest


def validate_frozen_row(row, models, cutoff):
    payload = row["frozen_inputs_json"]
    if hashlib.sha256(payload.encode()).hexdigest() != row["input_manifest"]["sha256"]:
        raise ValueError("Frozen input hash mismatch")
    inputs = json.loads(payload)
    if inputs.get("schema_version") != 2 or not isinstance(inputs.get("candidates"), dict):
        raise ValueError("Incomplete frozen input schema")
    if set(inputs["candidates"]) != models:
        raise ValueError("Frozen candidate coverage differs from observed predictions")
    identities = {}
    for model, candidate in inputs["candidates"].items():
        if not isinstance(candidate.get("cohort"), str) or not candidate["cohort"]:
            raise ValueError("Frozen candidate cohort identity is required")
        _, teams = _candidate(candidate, cutoff)
        a, b = row["team_a"], row["team_b"]
        if not {a, b} <= {team["team_id_master"] for team in teams} or not {a, b} <= set(candidate["order"]):
            raise ValueError("Frozen participant inputs do not cover the observed game")
        matches = [item for item in candidate.get("forecasts", [])
                   if item.get("team_a") == a and item.get("team_b") == b]
        if len(matches) != 1:
            raise ValueError("The frozen candidate must contain exactly one forecast for the observed pair")
        expected = {key: matches[0][key] for key in ("probabilities", "margin", "blowout_probability")}
        expected.update(seed_a=candidate["order"].index(a)+1, seed_b=candidate["order"].index(b)+1)
        if row["predictions"][model] != expected:
            raise ValueError("Reported seeds or predictions differ from the frozen candidate")
        digest = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        identities[model] = (candidate["cohort"], digest)
    return identities
