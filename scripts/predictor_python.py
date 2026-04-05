"""
Python match predictor aligned with frontend/lib/matchPredictor.ts.

This module is intentionally self-contained so offline backtests and calibration
scripts use the same prediction logic as the live compare UI:

- Glicko rating edge when available, with published score as fallback context
- SOS, recent form, and offense/defense matchup asymmetry
- Head-to-head history
- Probability calibration and age-specific margin calibration
- Glicko-aware confidence scoring
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DIR = REPO_ROOT / "frontend" / "public" / "data" / "calibration"


BASE_WEIGHTS = {
    "POWER_SCORE": 0.50,
    "SOS": 0.18,
    "RECENT_FORM": 0.28,
    "MATCHUP": 0.04,
}

BLOWOUT_WEIGHTS = {
    "POWER_SCORE": 0.85,
    "SOS": 0.06,
    "RECENT_FORM": 0.07,
    "MATCHUP": 0.02,
}

SKILL_GAP_THRESHOLDS = {
    "LARGE": 0.08,
    "MEDIUM": 0.05,
}

DEFAULT_SENSITIVITY = 4.5
MARGIN_COEFFICIENT = 8.0
RECENT_GAMES_COUNT = 5
GLICKO_ELO_DIVISOR = 400.0
DRAW_THRESHOLD = 0.03
MAX_TEAM_SCORE = 10

DEFAULT_CONFIDENCE_THRESHOLDS = {
    "high": 0.65,
    "medium": 0.50,
}


@dataclass
class TeamRanking:
    """Subset of ranking data used by the predictor."""

    team_id_master: str
    power_score_final: Optional[float] = None
    sos_norm: Optional[float] = None
    offense_norm: Optional[float] = None
    defense_norm: Optional[float] = None
    age: Optional[int] = None
    games_played: int = 0
    team_name: Optional[str] = None
    glicko_rating: Optional[float] = None
    glicko_rd: Optional[float] = None
    glicko_volatility: Optional[float] = None


@dataclass
class Game:
    """Game data used for recent form, H2H, and confidence."""

    id: str
    home_team_master_id: Optional[str]
    away_team_master_id: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    game_date: str


@dataclass
class MatchPrediction:
    """Prediction payload mirroring the frontend contract."""

    predicted_winner: str
    win_probability_a: float
    win_probability_b: float
    expected_score: Dict[str, int]
    expected_margin: float
    confidence: str
    confidence_score: Optional[float] = None
    components: Dict[str, float] = field(default_factory=dict)
    form_a: float = 0.0
    form_b: float = 0.0
    h2h: Optional[Dict[str, float]] = None


@lru_cache(maxsize=1)
def _load_calibration_payload() -> Dict[str, Dict]:
    def _load_json(filename: str) -> Dict:
        path = CALIBRATION_DIR / filename
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    return {
        "age_group": _load_json("age_group_parameters.json"),
        "probability": _load_json("probability_parameters.json"),
        "margin_v2": _load_json("margin_parameters_v2.json"),
        "confidence_v2": _load_json("confidence_parameters_v2.json"),
    }


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _get_sensitivity() -> float:
    probability_params = _load_calibration_payload()["probability"]
    return float(probability_params.get("sensitivity", DEFAULT_SENSITIVITY))


def _soccer_season_year() -> int:
    from datetime import datetime

    now = datetime.now()
    return now.year if now.month >= 8 else now.year - 1


def extract_age_from_team_name(team_name: Optional[str]) -> Optional[int]:
    if not team_name:
        return None

    import re

    u_match = re.search(r"\bU(\d{1,2})\b", team_name, flags=re.IGNORECASE)
    if u_match:
        age = int(u_match.group(1))
        if 8 <= age <= 19:
            return 19 if age == 18 else age

    season_year = _soccer_season_year()

    birth_year_match = re.search(r"\b(0[89]|1[0-9])[BG]\b", team_name, flags=re.IGNORECASE)
    if birth_year_match:
        birth_year = 2000 + int(birth_year_match.group(1))
        age_group = season_year - birth_year + 1
        if 6 <= age_group <= 19:
            return 19 if age_group == 18 else age_group

    standalone_match = re.search(r"\b(0[89]|1[0-9])\b", team_name)
    if standalone_match:
        birth_year = 2000 + int(standalone_match.group(1))
        age_group = season_year - birth_year + 1
        if 6 <= age_group <= 19:
            return 19 if age_group == 18 else age_group

    return None


def calculate_recent_form(team_id: str, all_games: List[Game], n: int = RECENT_GAMES_COUNT) -> float:
    team_games = [
        game for game in all_games if game.home_team_master_id == team_id or game.away_team_master_id == team_id
    ]
    team_games.sort(key=lambda game: game.game_date, reverse=True)
    team_games = team_games[:n]

    if not team_games:
        return 0.0

    total_goal_diff = 0.0
    games_with_scores = 0

    for game in team_games:
        is_home = game.home_team_master_id == team_id
        team_score = game.home_score if is_home else game.away_score
        opp_score = game.away_score if is_home else game.home_score

        if team_score is None or opp_score is None:
            continue

        total_goal_diff += team_score - opp_score
        games_with_scores += 1

    if games_with_scores == 0:
        return 0.0

    avg_goal_diff = total_goal_diff / games_with_scores
    sample_size_weight = games_with_scores / n
    return avg_goal_diff * sample_size_weight


def normalize_recent_form(goal_diff: float) -> float:
    return 1.0 / (1.0 + math.exp(-goal_diff * 0.5))


def calculate_head_to_head(team_a_id: str, team_b_id: str, all_games: List[Game]) -> Dict[str, float]:
    h2h_games = [
        game
        for game in all_games
        if (
            (
                game.home_team_master_id == team_a_id
                and game.away_team_master_id == team_b_id
            )
            or (
                game.home_team_master_id == team_b_id
                and game.away_team_master_id == team_a_id
            )
        )
    ]

    if not h2h_games:
        return {"advantage": 0.0, "gamesPlayed": 0.0, "avgMargin": 0.0}

    total_goal_diff = 0.0
    games_with_scores = 0

    for game in h2h_games:
        is_team_a_home = game.home_team_master_id == team_a_id
        team_a_score = game.home_score if is_team_a_home else game.away_score
        team_b_score = game.away_score if is_team_a_home else game.home_score

        if team_a_score is None or team_b_score is None:
            continue

        total_goal_diff += team_a_score - team_b_score
        games_with_scores += 1

    if games_with_scores == 0:
        return {"advantage": 0.0, "gamesPlayed": 0.0, "avgMargin": 0.0}

    avg_margin = total_goal_diff / games_with_scores
    advantage = avg_margin * 0.04
    return {"advantage": advantage, "gamesPlayed": float(games_with_scores), "avgMargin": avg_margin}


def detect_mismatch(
    power_diff: float,
    offense_a: float,
    offense_b: float,
    defense_a: float,
    defense_b: float,
) -> Dict[str, float]:
    abs_power_diff = abs(power_diff)
    offense_gap = abs(offense_a - offense_b)
    defense_gap = abs(defense_a - defense_b)
    matchup_asymmetry = abs(offense_a - defense_b - (offense_b - defense_a))

    power_score = min(abs_power_diff / 0.12, 1.0)
    offense_score = min(offense_gap / 0.18, 1.0)
    defense_score = min(defense_gap / 0.18, 1.0)
    asymmetry_score = min(matchup_asymmetry / 0.30, 1.0)

    mismatch_score = power_score * 0.35 + offense_score * 0.25 + defense_score * 0.25 + asymmetry_score * 0.15
    is_mismatch = (
        mismatch_score > 0.4
        or abs_power_diff > 0.1
        or offense_gap > 0.15
        or defense_gap > 0.15
        or matchup_asymmetry > 0.25
    )

    return {"isMismatch": float(is_mismatch), "mismatchScore": mismatch_score}


def get_adaptive_weights(
    power_diff: float,
    offense_a: float,
    offense_b: float,
    defense_a: float,
    defense_b: float,
) -> Dict[str, Dict[str, float] | float]:
    mismatch = detect_mismatch(power_diff, offense_a, offense_b, defense_a, defense_b)
    is_mismatch = bool(mismatch["isMismatch"])
    mismatch_score = mismatch["mismatchScore"]
    abs_power_diff = abs(power_diff)

    if is_mismatch and mismatch_score > 0.6:
        return {"weights": BLOWOUT_WEIGHTS.copy(), "mismatchScore": mismatch_score}

    if abs_power_diff >= SKILL_GAP_THRESHOLDS["LARGE"]:
        return {"weights": BLOWOUT_WEIGHTS.copy(), "mismatchScore": mismatch_score}

    if abs_power_diff < SKILL_GAP_THRESHOLDS["MEDIUM"] and not is_mismatch:
        return {"weights": BASE_WEIGHTS.copy(), "mismatchScore": mismatch_score}

    transition_progress = max(
        (abs_power_diff - SKILL_GAP_THRESHOLDS["MEDIUM"])
        / (SKILL_GAP_THRESHOLDS["LARGE"] - SKILL_GAP_THRESHOLDS["MEDIUM"]),
        mismatch_score,
    )

    weights = {
        "POWER_SCORE": BASE_WEIGHTS["POWER_SCORE"]
        + (BLOWOUT_WEIGHTS["POWER_SCORE"] - BASE_WEIGHTS["POWER_SCORE"]) * transition_progress,
        "SOS": BASE_WEIGHTS["SOS"] + (BLOWOUT_WEIGHTS["SOS"] - BASE_WEIGHTS["SOS"]) * transition_progress,
        "RECENT_FORM": BASE_WEIGHTS["RECENT_FORM"]
        + (BLOWOUT_WEIGHTS["RECENT_FORM"] - BASE_WEIGHTS["RECENT_FORM"]) * transition_progress,
        "MATCHUP": BASE_WEIGHTS["MATCHUP"] + (BLOWOUT_WEIGHTS["MATCHUP"] - BASE_WEIGHTS["MATCHUP"]) * transition_progress,
    }

    return {"weights": weights, "mismatchScore": mismatch_score}


def calibrate_probability(raw_prob: float) -> float:
    calibration_points = [
        (0.50, 0.50),
        (0.525, 0.526),
        (0.575, 0.587),
        (0.625, 0.686),
        (0.675, 0.686),
        (0.725, 0.686),
        (0.775, 0.700),
        (0.850, 0.796),
        (1.00, 1.00),
    ]

    if math.isclose(raw_prob, 0.5, abs_tol=1e-9):
        return 0.5

    if raw_prob <= 0.5:
        mirrored_raw = 1 - raw_prob
        mirrored_calibrated = calibrate_probability(mirrored_raw)
        return 1 - mirrored_calibrated

    lower_point = calibration_points[0]
    upper_point = calibration_points[-1]

    for idx in range(len(calibration_points) - 1):
        start = calibration_points[idx]
        end = calibration_points[idx + 1]
        if start[0] <= raw_prob < end[0]:
            lower_point = start
            upper_point = end
            break

    lower_x, lower_y = lower_point
    upper_x, upper_y = upper_point
    if upper_x == lower_x:
        calibrated = upper_y
    else:
        progress = (raw_prob - lower_x) / (upper_x - lower_x)
        calibrated = lower_y + progress * (upper_y - lower_y)

    return max(0.01, min(0.99, calibrated))


def get_league_average_goals(age: Optional[int]) -> float:
    if age is None:
        return 2.5

    age_key = f"u{age}"
    age_group_params = _load_calibration_payload()["age_group"]
    if age_key in age_group_params and "avg_goals" in age_group_params[age_key]:
        return float(age_group_params[age_key]["avg_goals"])

    if age <= 11:
        return 2.0
    if age <= 14:
        return 2.5
    if age <= 18:
        return 2.8
    return 3.0


def get_age_specific_margin_multiplier(age: Optional[int], abs_power_diff: float, mismatch_score: float = 0.0) -> float:
    margin_params = _load_calibration_payload()["margin_v2"]
    age_group_params = _load_calibration_payload()["age_group"]
    age_key = f"u{age}" if age is not None else None

    base_multiplier = 1.0
    if age_key and age_key in margin_params.get("age_groups", {}):
        base_multiplier = float(margin_params["age_groups"][age_key]["margin_mult"])
    elif age_key and age_key in age_group_params:
        base_multiplier = float(age_group_params[age_key]["margin_mult"])

    power_gap_scaling = 1.0
    if abs_power_diff > 0.15:
        power_gap_scaling = 2.0
    elif abs_power_diff > 0.10:
        transition_progress = (abs_power_diff - 0.10) / (0.15 - 0.10)
        power_gap_scaling = 1.5 + 0.5 * transition_progress
    elif abs_power_diff > 0.05:
        transition_progress = (abs_power_diff - 0.05) / (0.10 - 0.05)
        power_gap_scaling = 1.0 + 0.5 * transition_progress

    base_margin_scale = float(margin_params.get("margin_scale", 1.0))
    power_based_reduction = min(abs_power_diff / 0.12, 1.0)
    mismatch_based_reduction = min(mismatch_score / 0.7, 1.0)
    gap_dampening_reduction = max(power_based_reduction, mismatch_based_reduction)
    margin_scale = base_margin_scale + (1.0 - base_margin_scale) * gap_dampening_reduction

    return base_multiplier * power_gap_scaling * margin_scale


def calculate_team_variance(team_id: str, all_games: List[Game]) -> float:
    team_games = [
        game for game in all_games if game.home_team_master_id == team_id or game.away_team_master_id == team_id
    ]
    if len(team_games) < 2:
        return 1.0

    goals_for: List[int] = []
    goals_against: List[int] = []

    for game in team_games:
        is_home = game.home_team_master_id == team_id
        team_score = game.home_score if is_home else game.away_score
        opp_score = game.away_score if is_home else game.home_score

        if team_score is None or opp_score is None:
            continue

        goals_for.append(team_score)
        goals_against.append(opp_score)

    if len(goals_for) < 2 or len(goals_against) < 2:
        return 1.0

    def _variance(values: List[int]) -> float:
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / len(values)

    return _variance(goals_for) + _variance(goals_against)


def normalize_historical_uncertainty(variance_a: float, variance_b: float) -> float:
    return min(1.0, math.sqrt(variance_a + variance_b) / 4.0)


def calculate_glicko_uncertainty(team_a: TeamRanking, team_b: TeamRanking) -> Optional[float]:
    if team_a.glicko_rd is None or team_b.glicko_rd is None:
        return None

    normalized = math.sqrt(team_a.glicko_rd**2 + team_b.glicko_rd**2) / (math.sqrt(2.0) * 350.0)
    return max(0.0, min(1.0, normalized))


def compute_confidence(team_a: TeamRanking, team_b: TeamRanking, composite_diff: float, all_games: List[Game]) -> Dict[str, float | str]:
    variance_a = calculate_team_variance(team_a.team_id_master, all_games)
    variance_b = calculate_team_variance(team_b.team_id_master, all_games)

    historical_uncertainty = normalize_historical_uncertainty(variance_a, variance_b)
    glicko_uncertainty = calculate_glicko_uncertainty(team_a, team_b)
    combined_uncertainty = (
        historical_uncertainty
        if glicko_uncertainty is None
        else glicko_uncertainty * 0.7 + historical_uncertainty * 0.3
    )

    min_games_played = min(team_a.games_played or 0, team_b.games_played or 0)
    sample_strength = min(1.0, min_games_played / 30.0)

    confidence_params = _load_calibration_payload()["confidence_v2"]
    weights = confidence_params.get("weights", {})
    intercept = float(confidence_params.get("intercept", 0.0))

    if weights:
        raw_score = (
            float(weights.get("composite_diff", 16.58)) * abs(composite_diff)
            + float(weights.get("variance", -0.1)) * combined_uncertainty
            + float(weights.get("sample_strength", 0.4)) * sample_strength
            + intercept
        )
        confidence_score = _sigmoid(raw_score)
    else:
        confidence_score = _sigmoid(1.6 * abs(composite_diff) - 1.0 * combined_uncertainty + 0.6 * sample_strength)

    thresholds = confidence_params.get("thresholds", DEFAULT_CONFIDENCE_THRESHOLDS)
    high_threshold = float(thresholds.get("high", DEFAULT_CONFIDENCE_THRESHOLDS["high"]))
    medium_threshold = float(thresholds.get("medium", DEFAULT_CONFIDENCE_THRESHOLDS["medium"]))

    if confidence_score >= high_threshold:
        confidence = "high"
    elif confidence_score >= medium_threshold:
        confidence = "medium"
    else:
        confidence = "low"

    return {"confidence": confidence, "confidence_score": confidence_score}


def calculate_glicko_strength(team_a: TeamRanking, team_b: TeamRanking) -> Optional[Dict[str, float]]:
    if team_a.glicko_rating is None or team_b.glicko_rating is None:
        return None

    rating_diff = team_a.glicko_rating - team_b.glicko_rating
    win_probability_a = 1.0 / (1.0 + math.pow(10.0, -rating_diff / GLICKO_ELO_DIVISOR))

    rd_a = team_a.glicko_rd if team_a.glicko_rd is not None else 350.0
    rd_b = team_b.glicko_rd if team_b.glicko_rd is not None else 350.0
    normalized_rd = min(1.0, math.sqrt(rd_a * rd_a + rd_b * rd_b) / (math.sqrt(2.0) * 350.0))
    reliability = 0.45 + 0.55 * (1.0 - normalized_rd)

    return {
        "ratingDiff": rating_diff,
        "winProbabilityA": win_probability_a,
        "reliability": reliability,
        "signal": (win_probability_a - 0.5) * reliability,
    }


def predict_match(team_a: TeamRanking, team_b: TeamRanking, all_games: List[Game]) -> MatchPrediction:
    power_diff = (team_a.power_score_final or 0.5) - (team_b.power_score_final or 0.5)
    glicko_strength = calculate_glicko_strength(team_a, team_b)
    strength_signal = glicko_strength["signal"] * 0.75 + power_diff * 0.25 if glicko_strength else power_diff

    offense_a = team_a.offense_norm or 0.5
    defense_a = team_a.defense_norm or 0.5
    offense_b = team_b.offense_norm or 0.5
    defense_b = team_b.defense_norm or 0.5

    adaptive = get_adaptive_weights(power_diff, offense_a, offense_b, defense_a, defense_b)
    weights = adaptive["weights"]
    mismatch_score = float(adaptive["mismatchScore"])

    sos_diff = (team_a.sos_norm or 0.5) - (team_b.sos_norm or 0.5)

    form_a = calculate_recent_form(team_a.team_id_master, all_games)
    form_b = calculate_recent_form(team_b.team_id_master, all_games)
    form_diff_raw = form_a - form_b
    form_diff_norm = normalize_recent_form(form_diff_raw) - 0.5

    matchup_advantage = offense_a - defense_b - (offense_b - defense_a)

    h2h = calculate_head_to_head(team_a.team_id_master, team_b.team_id_master, all_games)
    h2h_games_played = int(h2h["gamesPlayed"])
    h2h_weight = min(0.05 * h2h_games_played, 0.15) if h2h_games_played > 0 else 0.0
    h2h_adjustment = 1.0 - h2h_weight

    composite_diff = (
        float(weights["POWER_SCORE"]) * strength_signal * h2h_adjustment
        + float(weights["SOS"]) * sos_diff * h2h_adjustment
        + float(weights["RECENT_FORM"]) * form_diff_norm * h2h_adjustment
        + float(weights["MATCHUP"]) * matchup_advantage * h2h_adjustment
        + h2h_weight * float(h2h["advantage"]) * 3.0
    )

    if mismatch_score > 0.4:
        amplification = 1.0 + (mismatch_score - 0.4) * 1.33
        composite_diff *= amplification

    raw_win_prob_a = _sigmoid(_get_sensitivity() * composite_diff)
    win_prob_a = calibrate_probability(raw_win_prob_a)
    win_prob_b = 1.0 - win_prob_a

    effective_age = (
        extract_age_from_team_name(team_a.team_name)
        or extract_age_from_team_name(team_b.team_name)
        or team_a.age
        or team_b.age
    )

    abs_power_diff = abs(power_diff)
    margin_multiplier = get_age_specific_margin_multiplier(effective_age, abs_power_diff, mismatch_score)
    expected_margin = composite_diff * MARGIN_COEFFICIENT * margin_multiplier

    league_avg_goals = get_league_average_goals(effective_age)
    abs_expected_margin = abs(expected_margin)

    if mismatch_score > 0.5:
        underdog_score = max(0.0, 1.5 - (mismatch_score - 0.5) * 2.5)
        if expected_margin >= 0:
            raw_score_b = underdog_score
            raw_score_a = underdog_score + abs_expected_margin
        else:
            raw_score_a = underdog_score
            raw_score_b = underdog_score + abs_expected_margin
    else:
        if expected_margin >= 0:
            raw_score_b = league_avg_goals - abs_expected_margin / 2.0
            raw_score_a = league_avg_goals + abs_expected_margin / 2.0
        else:
            raw_score_a = league_avg_goals - abs_expected_margin / 2.0
            raw_score_b = league_avg_goals + abs_expected_margin / 2.0

    rounded_margin = round(abs_expected_margin)

    if rounded_margin == 0:
        avg_score = round(league_avg_goals)
        expected_score_a = avg_score
        expected_score_b = avg_score
    elif expected_margin >= 0:
        expected_score_b = max(0, round(raw_score_b))
        expected_score_a = min(MAX_TEAM_SCORE, max(0, expected_score_b + rounded_margin))
        if expected_score_a == MAX_TEAM_SCORE and expected_score_b > MAX_TEAM_SCORE - rounded_margin:
            expected_score_b = max(0, MAX_TEAM_SCORE - rounded_margin)
    else:
        expected_score_a = max(0, round(raw_score_a))
        expected_score_b = min(MAX_TEAM_SCORE, max(0, expected_score_a + rounded_margin))
        if expected_score_b == MAX_TEAM_SCORE and expected_score_a > MAX_TEAM_SCORE - rounded_margin:
            expected_score_a = max(0, MAX_TEAM_SCORE - rounded_margin)

    if abs(win_prob_a - 0.5) < DRAW_THRESHOLD:
        predicted_winner = "draw"
    else:
        predicted_winner = "team_a" if win_prob_a >= 0.5 else "team_b"

    confidence_result = compute_confidence(team_a, team_b, composite_diff, all_games)

    components: Dict[str, float] = {
        "powerDiff": power_diff,
        "strengthSignal": strength_signal,
        "sosDiff": sos_diff,
        "formDiffRaw": form_diff_raw,
        "formDiffNorm": form_diff_norm,
        "matchupAdvantage": matchup_advantage,
        "compositeDiff": composite_diff,
        "mismatchScore": mismatch_score,
    }
    if glicko_strength:
        components.update(
            {
                "glickoRatingDiff": glicko_strength["ratingDiff"],
                "glickoWinProbabilityA": glicko_strength["winProbabilityA"],
                "glickoReliability": glicko_strength["reliability"],
            }
        )

    return MatchPrediction(
        predicted_winner=predicted_winner,
        win_probability_a=win_prob_a,
        win_probability_b=win_prob_b,
        expected_score={"teamA": expected_score_a, "teamB": expected_score_b},
        expected_margin=expected_margin,
        confidence=str(confidence_result["confidence"]),
        confidence_score=float(confidence_result["confidence_score"]),
        components=components,
        form_a=form_a,
        form_b=form_b,
        h2h={"gamesPlayed": float(h2h_games_played), "avgMargin": float(h2h["avgMargin"])} if h2h_games_played > 0 else None,
    )
