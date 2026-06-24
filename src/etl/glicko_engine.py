from __future__ import annotations

import logging
import math
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.etl.glicko_config import GlickoConfig

logger = logging.getLogger(__name__)


# =========================================================
# Constants
# =========================================================
GLICKO2_SCALE = 173.7178  # Glickman's scaling factor

_EXPLAIN_COLUMNS = [
    "team_id",
    "opp_id",
    "game_date",
    "gf",
    "ga",
    "game_id",
    "id",
    "team_mu",
    "team_sigma",
    "opp_mu",
    "opp_sigma",
    "expected_outcome",
    "actual_outcome",
    "outcome_surprise",
    "g_factor",
    "recency_weight",
    "rating_contribution",
    "off_residual",
    "def_residual",
]


# =========================================================
# Scale conversion helpers
# =========================================================
def _to_glicko2_scale(mu: float, sigma: float) -> Tuple[float, float]:
    """Convert from rating scale (1500-centered) to Glicko-2 internal scale."""
    mu_g2 = (mu - 1500.0) / GLICKO2_SCALE
    sigma_g2 = sigma / GLICKO2_SCALE
    return mu_g2, sigma_g2


def _from_glicko2_scale(mu_g2: float, sigma_g2: float) -> Tuple[float, float]:
    """Convert from Glicko-2 internal scale back to rating scale."""
    mu = mu_g2 * GLICKO2_SCALE + 1500.0
    sigma = sigma_g2 * GLICKO2_SCALE
    return mu, sigma


# =========================================================
# Core Glicko-2 functions (Glickman paper, Section 5)
# =========================================================
def glicko2_g(phi: float) -> float:
    """Compute g(phi) = 1 / sqrt(1 + 3 * phi^2 / pi^2).

    Reduces the impact of games against opponents with high rating deviation.
    """
    return 1.0 / math.sqrt(1.0 + 3.0 * phi**2 / (math.pi**2))


def glicko2_E(mu: float, mu_j: float, phi_j: float) -> float:
    """Compute expected outcome E(mu, mu_j, phi_j).

    Returns the probability of the player beating opponent j,
    given their ratings on the Glicko-2 internal scale.
    """
    g_val = glicko2_g(phi_j)
    return 1.0 / (1.0 + math.exp(-g_val * (mu - mu_j)))


# =========================================================
# Volatility update (Illinois algorithm — Section 5.4)
# =========================================================
def _update_volatility(
    sigma_vol: float,
    delta: float,
    phi: float,
    v: float,
    tau: float,
) -> float:
    """Update volatility using the iterative algorithm from Glickman's paper.

    Uses the Illinois variant of the regula falsi method to find the root
    of the function f(x) described in Step 5.4 of the paper.

    Args:
        sigma_vol: Current volatility.
        delta: Estimated improvement.
        phi: Current rating deviation on Glicko-2 scale.
        v: Estimated variance of the player's rating.
        tau: System constant controlling volatility change.

    Returns:
        Updated volatility.
    """
    a = math.log(sigma_vol**2)
    phi2 = phi**2
    delta2 = delta**2

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta2 - phi2 - v - ex)
        denom = 2.0 * (phi2 + v + ex) ** 2
        return num / denom - (x - a) / (tau**2)

    # Step 5.4.2: Set initial values of iterative algorithm
    A = a
    if delta2 > phi2 + v:
        B = math.log(delta2 - phi2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    # Step 5.4.3: Iterative algorithm
    f_A = f(A)
    f_B = f(B)
    EPSILON = 1e-6
    MAX_ITERATIONS = 100

    iteration = 0
    while abs(B - A) > EPSILON:
        if iteration >= MAX_ITERATIONS:
            logger.warning(
                "glicko2 volatility update did not converge after %d iterations "
                "(sigma_vol=%.6f, delta=%.6f, phi=%.6f, v=%.6f, tau=%.6f)",
                MAX_ITERATIONS,
                sigma_vol,
                delta,
                phi,
                v,
                tau,
            )
            break
        C = A + (A - B) * f_A / (f_B - f_A)
        f_C = f(C)
        if f_C * f_B <= 0:
            A = B
            f_A = f_B
        else:
            f_A = f_A / 2.0
        B = C
        f_B = f_C
        iteration += 1

    return math.exp(A / 2.0)


# =========================================================
# Full Glicko-2 update
# =========================================================
def glicko2_update(
    mu: float,
    rd: float,
    sigma: float,
    opponents: List[Tuple[float, float]],
    outcomes: List[float],
    weights: List[float],
    tau: float,
) -> Tuple[float, float, float]:
    """Perform a full Glicko-2 rating update for one team.

    Implements the complete algorithm from Glickman's paper:
    1. Convert to Glicko-2 scale
    2. Compute estimated variance (v)
    3. Compute estimated improvement (delta)
    4. Update volatility
    5. Update rating deviation (phi)
    6. Update rating (mu)

    Args:
        mu: Current rating on the original scale (1500-centered).
        rd: Current rating deviation on the original 1500-scale (e.g. 350.0).
            Not to be confused with the Glicko-2 internal phi; the conversion
            happens inside this function.
        sigma: Current volatility.
        opponents: List of (mu_j, sigma_j) tuples on the original scale.
        outcomes: List of game outcomes (0.0 to 1.0).
        weights: List of recency weights for each game.
        tau: System constant controlling volatility change.

    Returns:
        Tuple of (new_mu, new_rd, new_sigma) on the original scale.
    """
    # Step 2: Convert to Glicko-2 scale
    mu_g2, phi_g2 = _to_glicko2_scale(mu, rd)

    # No games played: widen uncertainty, leave mu and sigma unchanged
    if not opponents:
        phi_star = math.sqrt(phi_g2**2 + sigma**2)
        new_mu, new_phi = _from_glicko2_scale(mu_g2, phi_star)
        return new_mu, new_phi, sigma

    opp_g2 = [_to_glicko2_scale(m, s) for m, s in opponents]

    # Step 3: Compute v (estimated variance) and delta
    v_inv = 0.0
    delta_sum = 0.0

    for (mu_j, phi_j), s_j, w_j in zip(opp_g2, outcomes, weights):
        g_j = glicko2_g(phi_j)
        E_j = glicko2_E(mu_g2, mu_j, phi_j)
        v_inv += w_j * g_j**2 * E_j * (1.0 - E_j)
        delta_sum += w_j * g_j * (s_j - E_j)

    if v_inv == 0.0:
        # All opponents have extreme expected outcomes — treat as no-info period
        phi_star = math.sqrt(phi_g2**2 + sigma**2)
        new_mu, new_phi = _from_glicko2_scale(mu_g2, phi_star)
        return new_mu, new_phi, sigma

    v = 1.0 / v_inv
    delta = v * delta_sum

    # Step 4: Update volatility
    new_sigma = _update_volatility(sigma, delta, phi_g2, v, tau)

    # Step 5: Update phi (pre-rating period value)
    phi_star = math.sqrt(phi_g2**2 + new_sigma**2)

    # Step 6: Update phi and mu
    new_phi_g2 = 1.0 / math.sqrt(1.0 / phi_star**2 + 1.0 / v)
    new_mu_g2 = mu_g2 + new_phi_g2**2 * delta_sum

    # Step 7: Convert back to original scale
    new_mu, new_phi = _from_glicko2_scale(new_mu_g2, new_phi_g2)

    return new_mu, new_phi, new_sigma


# =========================================================
# Game outcome scoring (log-margin)
# =========================================================
def game_outcome(gf: int, ga: int, max_gd: int) -> float:
    """Compute a game outcome score using log-margin scoring.

    Maps goal differential to a continuous outcome between 0 and 1,
    using a logarithmic scale that compresses large margins.

    Args:
        gf: Goals for (scored by the team).
        ga: Goals against (conceded by the team).
        max_gd: Maximum goal differential (cap).

    Returns:
        Score between 0.0 and 1.0:
        - 0.5 for a draw
        - >0.5 for a win (higher with larger margin)
        - <0.5 for a loss (lower with larger margin)
    """
    if gf == ga:
        return 0.5

    gd = abs(gf - ga)
    capped_gd = min(gd, max_gd)
    margin = 0.5 * math.log(1.0 + capped_gd) / math.log(1.0 + max_gd)

    if gf > ga:
        return 0.5 + margin
    else:
        return 0.5 - margin


# =========================================================
# Game preprocessing
# =========================================================
def clip_outlier_goals(games_df: pd.DataFrame, zscore_threshold: float = 2.5) -> pd.DataFrame:
    """Clip GF/GA per (age, gender) cohort to mean +/- zscore_threshold * std.

    Args:
        games_df: DataFrame with columns gf, ga, age, gender.
        zscore_threshold: Number of standard deviations for the clip boundary.

    Returns:
        A new DataFrame with gf and ga clipped and rounded to integers.
    """
    df = games_df.copy()

    for _, idx in df.groupby(["age", "gender"]).groups.items():
        group = df.loc[idx]
        for col in ("gf", "ga"):
            mean = group[col].mean()
            std = group[col].std()
            if std == 0 or pd.isna(std):
                continue
            lo = mean - zscore_threshold * std
            hi = mean + zscore_threshold * std
            df.loc[idx, col] = group[col].clip(lower=lo, upper=hi).round().astype(int)

    return df


def select_games(
    games_df: pd.DataFrame,
    team_id: str,
    max_games: int,
    window_days: int,
    today: pd.Timestamp,
    grace_days: int = 0,
) -> pd.DataFrame:
    """Select the most recent *max_games* games within *window_days* for a team.

    Args:
        games_df: DataFrame with columns team_id and date.
        team_id: The team to filter for.
        max_games: Maximum number of games to return.
        window_days: Only include games within this many days of *today*.
        today: Reference date for the window and recency sort.

    Returns:
        Filtered DataFrame sorted by date descending, at most *max_games* rows.
    """
    cutoff = today - pd.Timedelta(days=window_days + max(int(grace_days), 0))
    dates = games_df["date"]
    if hasattr(dates.dtype, "tz") and dates.dtype.tz is not None:
        dates = dates.dt.tz_localize(None)
    mask = (games_df["team_id"] == team_id) & (dates >= cutoff)
    sort_cols = [col for col in ["date", "game_id", "id", "opp_id"] if col in games_df.columns]
    ascending = [False] + [True] * (len(sort_cols) - 1)
    filtered = games_df.loc[mask].sort_values(sort_cols, ascending=ascending, kind="mergesort")
    return filtered.head(max_games)


def _parse_age_number(age_value) -> Optional[int]:
    if age_value is None or (isinstance(age_value, float) and math.isnan(age_value)):
        return None
    digits = "".join(ch for ch in str(age_value) if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _selection_quality_weight(opp_mu: float, cfg: GlickoConfig) -> float:
    centered = (float(opp_mu) - cfg.SCF_BRIDGE_QUALITY_MIDPOINT) / max(cfg.SCF_BRIDGE_QUALITY_SCALE, 1e-6)
    logistic = 1.0 / (1.0 + math.exp(-centered))
    scaled = 0.35 + 0.65 * float(logistic)
    return max(cfg.SCF_BRIDGE_QUALITY_FLOOR, scaled)


def _apply_tier_mult(opp_mu: float, mult: float, cfg: GlickoConfig) -> float:
    if mult == 1.0:
        return opp_mu
    if cfg.TIER_MULT_CENTERED:
        return cfg.INITIAL_MU + (opp_mu - cfg.INITIAL_MU) * mult
    return opp_mu * mult


def _effective_selection_opponent_mu(
    row: pd.Series,
    rating_lookup: Dict[str, Tuple[float, float, float]],
    cfg: GlickoConfig,
    cohort_age,
    cohort_gender,
    global_rating_map: Optional[Dict[str, float]] = None,
    tier_mult_fn=None,
) -> float:
    opp_id = str(row.get("opp_id"))
    opp_age = row.get("opp_age")
    opp_gender = row.get("opp_gender")
    is_cross_age = False
    if opp_age is not None and opp_gender is not None:
        is_cross_age = str(opp_age) != str(cohort_age) or str(opp_gender) != str(cohort_gender)

    if is_cross_age and global_rating_map is not None:
        opp_mu = float(global_rating_map.get(opp_id, cfg.INITIAL_MU))
        opp_mu = scale_cross_age_rating(
            opp_mu,
            str(opp_age) if opp_age is not None else str(cohort_age),
            str(opp_gender) if opp_gender is not None else str(cohort_gender),
            str(cohort_age),
            str(cohort_gender),
            cfg,
        )
    elif opp_id in rating_lookup:
        opp_mu = float(rating_lookup[opp_id][0])
    elif global_rating_map is not None and opp_id in global_rating_map:
        opp_mu = float(global_rating_map[opp_id])
    else:
        opp_mu = cfg.INITIAL_MU

    if tier_mult_fn is not None:
        opp_mu = _apply_tier_mult(opp_mu, float(tier_mult_fn(opp_id)), cfg)
    return opp_mu


def select_games_balanced(
    games_df: pd.DataFrame,
    team_id: str,
    cfg: GlickoConfig,
    today: pd.Timestamp,
    rating_lookup: Optional[Dict[str, Tuple[float, float, float]]] = None,
    global_rating_map: Optional[Dict[str, float]] = None,
    team_state_map: Optional[Dict[str, str]] = None,
    tier_mult_fn=None,
) -> pd.DataFrame:
    """Select a balanced evidence window: recent + same-age quality + bridge quality.

    The output keeps the engine mostly recency-driven while reserving slots for
    quality same-age evidence and meaningful connectivity games.
    """
    filtered = select_games(
        games_df,
        team_id,
        max_games=len(games_df),
        window_days=cfg.WINDOW_DAYS,
        today=today,
        grace_days=getattr(cfg, "WINDOW_GRACE_DAYS", 0),
    )
    if filtered.empty:
        return filtered
    if not getattr(cfg, "BALANCED_SELECTION_ENABLED", False) or len(filtered) <= cfg.MAX_GAMES:
        return filtered.head(cfg.MAX_GAMES)

    work = filtered.copy()
    work["team_id"] = work["team_id"].astype(str)
    work["opp_id"] = work["opp_id"].astype(str)
    cohort_age = work["age"].iloc[0] if "age" in work.columns else None
    cohort_gender = work["gender"].iloc[0] if "gender" in work.columns else None
    rating_lookup = rating_lookup or {}

    work["is_same_age"] = False
    if {"opp_age", "opp_gender"}.issubset(work.columns):
        work["is_same_age"] = (work["opp_age"].astype(str) == str(cohort_age)) & (
            work["opp_gender"].astype(str) == str(cohort_gender)
        )

    work["is_non_loss"] = False
    if {"gf", "ga"}.issubset(work.columns):
        work["is_non_loss"] = work["gf"].fillna(-999) >= work["ga"].fillna(999)

    team_state = team_state_map.get(str(team_id), "") if team_state_map else ""
    if team_state_map:
        opp_states = work["opp_id"].map(lambda opp_id: team_state_map.get(str(opp_id), ""))
        work["is_bridge_game"] = opp_states.ne("") & opp_states.ne("UNKNOWN") & opp_states.ne(team_state)
    else:
        work["is_bridge_game"] = False

    work["opp_mu_selection"] = work.apply(
        lambda row: _effective_selection_opponent_mu(
            row,
            rating_lookup,
            cfg,
            cohort_age,
            cohort_gender,
            global_rating_map=global_rating_map,
            tier_mult_fn=tier_mult_fn,
        ),
        axis=1,
    )
    work["bridge_quality"] = work["opp_mu_selection"].map(lambda mu: _selection_quality_weight(mu, cfg))
    work.loc[~work["is_same_age"], "bridge_quality"] *= float(cfg.BALANCED_SELECTION_CROSS_AGE_BRIDGE_MULT)
    work["selection_bucket"] = "recent_backfill"

    selected_parts: List[pd.DataFrame] = []
    selected_idx: set = set()

    def _take(bucket_name: str, candidates: pd.DataFrame, count: int) -> None:
        if count <= 0 or candidates.empty:
            return
        chosen = candidates.head(count).copy()
        if chosen.empty:
            return
        chosen["selection_bucket"] = bucket_name
        selected_parts.append(chosen)
        selected_idx.update(chosen.index.tolist())

    recent_cols = [col for col in ["date", "game_id", "id", "opp_id"] if col in work.columns]
    recent = work.sort_values(
        recent_cols,
        ascending=[False, True, True, True][: len(recent_cols)],
        kind="mergesort",
    )
    _take("recent", recent, int(cfg.BALANCED_SELECTION_RECENT_GAMES))

    remaining = work.loc[~work.index.isin(selected_idx)].copy()
    same_age_cols = [
        col
        for col in ["is_non_loss", "opp_mu_selection", "date", "game_id", "id", "opp_id"]
        if col in remaining.columns
    ]
    same_age_quality = remaining[remaining["is_same_age"]].sort_values(
        same_age_cols,
        ascending=[False, False, False, True, True, True][: len(same_age_cols)],
        kind="mergesort",
    )
    _take("same_age_quality", same_age_quality, int(cfg.BALANCED_SELECTION_SAME_AGE_QUALITY_GAMES))

    remaining = work.loc[~work.index.isin(selected_idx)].copy()
    bridge_cols = [
        col
        for col in [
            "is_same_age",
            "is_non_loss",
            "bridge_quality",
            "opp_mu_selection",
            "date",
            "game_id",
            "id",
            "opp_id",
        ]
        if col in remaining.columns
    ]
    bridge_quality = remaining[remaining["is_bridge_game"]].sort_values(
        bridge_cols,
        ascending=[False, False, False, False, False, True, True, True][: len(bridge_cols)],
        kind="mergesort",
    )
    _take("bridge_quality", bridge_quality, int(cfg.BALANCED_SELECTION_BRIDGE_GAMES))

    backfill_cols = [
        col
        for col in ["date", "is_non_loss", "opp_mu_selection", "game_id", "id", "opp_id"]
        if col in work.columns
    ]
    remaining = work.loc[~work.index.isin(selected_idx)].sort_values(
        backfill_cols,
        ascending=[False, False, False, True, True, True][: len(backfill_cols)],
        kind="mergesort",
    )
    _take("recent_backfill", remaining, max(0, int(cfg.MAX_GAMES) - len(selected_idx)))

    if not selected_parts:
        fallback_cols = [col for col in ["date", "game_id", "id", "opp_id"] if col in work.columns]
        fallback_asc = [False] + [True] * (len(fallback_cols) - 1)
        return work.sort_values(fallback_cols, ascending=fallback_asc, kind="mergesort").head(cfg.MAX_GAMES)

    selected = pd.concat(selected_parts, ignore_index=False)
    selected_cols = [col for col in ["date", "game_id", "id", "opp_id"] if col in selected.columns]
    selected_asc = [False] + [True] * (len(selected_cols) - 1)
    selected = selected.sort_values(selected_cols, ascending=selected_asc, kind="mergesort")
    selected = selected[~selected.index.duplicated(keep="first")]
    if len(selected) > cfg.MAX_GAMES:
        selected = selected.head(cfg.MAX_GAMES)
    return selected


def _get_team_games(
    team_id: str,
    team_games: Optional[Dict[str, pd.DataFrame]],
    games_df: pd.DataFrame,
    cfg: GlickoConfig,
    today: pd.Timestamp,
) -> pd.DataFrame:
    """Return pre-filtered games for a team, falling back to select_games()."""
    if team_games and team_id in team_games:
        return team_games[team_id]
    return select_games(
        games_df,
        team_id,
        cfg.MAX_GAMES,
        cfg.WINDOW_DAYS,
        today,
        grace_days=getattr(cfg, "WINDOW_GRACE_DAYS", 0),
    )


def compute_recency_weights(
    game_dates: pd.Series,
    today: pd.Timestamp,
    lambda_: float = 1.0,
    window_days: Optional[int] = None,
    grace_days: int = 0,
) -> np.ndarray:
    """Compute exponential-decay recency weights.

    Args:
        game_dates: Series of game dates.
        today: Reference date.
        lambda_: Decay rate (higher = faster decay).

    Returns:
        Numpy array of weights that sum to 1.0.
    """
    gd = (
        game_dates.dt.tz_localize(None)
        if hasattr(game_dates.dtype, "tz") and game_dates.dtype.tz is not None
        else game_dates
    )
    today_naive = today.tz_localize(None) if today.tzinfo is not None else today
    days_ago = (today_naive - gd).dt.days
    weights = np.exp(-lambda_ * days_ago / 365.0)
    if window_days is not None and grace_days > 0:
        tail_days = (days_ago - int(window_days)).clip(lower=0)
        taper = 1.0 - (tail_days / float(int(grace_days) + 1))
        weights = weights * np.clip(taper, 0.0, 1.0)
    return weights / weights.sum()


def compute_repeat_opponent_weights(opp_ids, cfg: GlickoConfig) -> np.ndarray:
    """Return per-game repeat-opponent multipliers in encounter order.

    The input order is expected to match the selected ranking window order
    (most recent first). The first meeting with an opponent gets full weight,
    then repeated meetings decay according to cfg.REPEAT_OPPONENT_WEIGHTS.
    """
    opp_list = [str(opp_id) for opp_id in opp_ids]
    if not opp_list:
        return np.array([], dtype=float)
    if not getattr(cfg, "REPEAT_OPPONENT_DECAY_ENABLED", False):
        return np.ones(len(opp_list), dtype=float)

    schedule = list(getattr(cfg, "REPEAT_OPPONENT_WEIGHTS", []) or [1.0])
    counts: Dict[str, int] = {}
    multipliers = []
    for opp_id in opp_list:
        counts[opp_id] = counts.get(opp_id, 0) + 1
        idx = min(counts[opp_id] - 1, len(schedule) - 1)
        multipliers.append(float(schedule[idx]))
    return np.asarray(multipliers, dtype=float)


# =========================================================
# Cross-age scaling
# =========================================================
def get_anchor(age, gender: str, cfg: GlickoConfig) -> float:
    """Look up the calibrated anchor for a given age and gender.

    Args:
        age: Age as an int (14) or string like 'U14' / 'u14' / '14.0'.
        gender: Gender string — anything starting with 'M' (case-insensitive)
                or equal to 'Male' is treated as male; all others as female.
        cfg: GlickoConfig containing MALE_ANCHORS and FEMALE_ANCHORS.

    Returns:
        Anchor float from the config, or 1.0 for unknown ages.
    """
    # Normalise age to int. Parse via float so stringified floats ('14.0')
    # resolve instead of crashing; unparseable ages take the unknown-age anchor.
    if isinstance(age, str):
        try:
            age = int(float(age.lstrip("Uu")))
        except ValueError:
            return 1.0

    # Choose anchor dict by gender
    if gender.upper().startswith("M"):
        anchors = cfg.MALE_ANCHORS
    else:
        anchors = cfg.FEMALE_ANCHORS

    return anchors.get(age, 1.0)


def scale_cross_age_rating(
    opp_mu: float,
    opp_age,
    opp_gender: str,
    team_age,
    team_gender: str,
    cfg: GlickoConfig,
) -> float:
    """Apply additive cross-age scaling on the Glicko-2 scale.

    Adjusts an opponent's effective rating based on the age/gender anchor
    difference between the two cohorts.  A younger team facing an older
    opponent sees that opponent as effectively stronger, and vice-versa.

    Formula:
        scaled_mu = opp_mu + (opp_anchor - team_anchor) * ANCHOR_SCALE_FACTOR

    Example — U14M team (anchor=0.928) vs U19M opponent (anchor=1.000) rated 1500:
        scaled = 1500 + (1.000 - 0.928) * 400 = 1528.8

    Args:
        opp_mu: Opponent's current Glicko-2 rating on the original scale.
        opp_age: Opponent's age (int or string like 'U19').
        opp_gender: Opponent's gender string.
        team_age: This team's age (int or string like 'U14').
        team_gender: This team's gender string.
        cfg: GlickoConfig with MALE_ANCHORS, FEMALE_ANCHORS, ANCHOR_SCALE_FACTOR.

    Returns:
        Scaled opponent mu (float), unchanged when anchors are equal.
    """
    opp_anchor = get_anchor(opp_age, opp_gender, cfg)
    team_anchor = get_anchor(team_age, team_gender, cfg)

    if opp_anchor == team_anchor:
        return opp_mu

    return opp_mu + (opp_anchor - team_anchor) * cfg.ANCHOR_SCALE_FACTOR


# =========================================================
# Offense / Defense / SOS derivation
# =========================================================
def expected_score(mu_a: float, mu_b: float) -> float:
    """Standard expected score on the 1500-scale (NOT Glicko-2 internal scale).

    Args:
        mu_a: Rating of player A on the original scale.
        mu_b: Rating of player B on the original scale.

    Returns:
        Expected score for player A, between 0.0 and 1.0.
    """
    return 1.0 / (1.0 + 10.0 ** ((mu_b - mu_a) / 400.0))


def derive_offense_defense(
    games_df: pd.DataFrame,
    team_ratings: Dict[str, Tuple[float, float, float]],
    cfg: GlickoConfig,
    today: pd.Timestamp,
    team_games: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Compute off_raw and def_raw per team using expected goals formula.

    For each team, compares actual goals scored/conceded against expected
    values derived from rating differences.  Positive off_raw means the
    team scores more than its rating predicts; positive def_raw means
    the team concedes fewer goals than expected (good defense).

    Args:
        games_df: DataFrame with columns team_id, opp_id, gf, ga, date, age, gender.
        team_ratings: Dict of {team_id: (mu, sigma, volatility)}.
        cfg: GlickoConfig with MAX_GAMES, WINDOW_DAYS, RECENCY_LAMBDA.
        today: Reference date for window and recency.
        team_games: Optional pre-filtered games dict from run_glicko2_cohort.

    Returns:
        DataFrame with columns: team_id, off_raw, def_raw.
    """
    cohort_avg_gpg = games_df["gf"].mean()

    results = []
    for team_id, (team_mu, _, _) in team_ratings.items():
        tg = _get_team_games(team_id, team_games, games_df, cfg, today)
        if len(tg) == 0:
            results.append({"team_id": team_id, "off_raw": 0.0, "def_raw": 0.0})
            continue

        # Vectorized: lookup opponent mus
        opp_mus = np.array([team_ratings.get(o, (cfg.INITIAL_MU,))[0] for o in tg["opp_id"].values])
        e_team = 1.0 / (1.0 + 10.0 ** ((opp_mus - team_mu) / 400.0))
        off_residuals = tg["gf"].values.astype(float) - cohort_avg_gpg * e_team
        def_residuals = cohort_avg_gpg * (1.0 - e_team) - tg["ga"].values.astype(float)

        weights = compute_recency_weights(
            tg["date"],
            today,
            cfg.RECENCY_LAMBDA,
            window_days=cfg.WINDOW_DAYS,
            grace_days=getattr(cfg, "WINDOW_GRACE_DAYS", 0),
        )
        off_raw = float(np.average(off_residuals, weights=weights))
        def_raw = float(np.average(def_residuals, weights=weights))

        results.append({"team_id": team_id, "off_raw": off_raw, "def_raw": def_raw})

    return pd.DataFrame(results)


def compute_sos(
    games_df: pd.DataFrame,
    team_ratings: Dict[str, Tuple[float, float, float]],
    cfg: GlickoConfig,
    today: pd.Timestamp,
    team_games: Optional[Dict[str, pd.DataFrame]] = None,
    tier_league_map: Optional[Dict[str, str]] = None,
    cohort_gender: str = "Male",
) -> pd.DataFrame:
    """Compute schedule strength as average opponent Glicko-2 mu.

    Applies a repeat cap per opponent and symmetric trim of the weakest
    and strongest opponents before averaging.

    Args:
        games_df: DataFrame with columns team_id, opp_id, gf, ga, date, age, gender.
        team_ratings: Dict of {team_id: (mu, sigma, volatility)}.
        cfg: GlickoConfig with MAX_GAMES, WINDOW_DAYS, SOS_REPEAT_CAP,
             SOS_TRIM_BOTTOM_PCT, SOS_TRIM_TOP_PCT.
        today: Reference date for window filtering.
        team_games: Optional pre-filtered games dict from run_glicko2_cohort.
        tier_league_map: Optional mapping of team_id -> league string for tier lookup.
        cohort_gender: Gender cohort for tier multiplier lookup (default "Male").

    Returns:
        DataFrame with columns: team_id, sos_raw.
    """
    from src.rankings.constants import get_tier_multiplier

    # Extract cohort age for tier multiplier age guard (U13+ only)
    _cohort_age = None
    if "age" in games_df.columns and len(games_df) > 0:
        try:
            _cohort_age = int(games_df["age"].iloc[0])
        except (ValueError, TypeError):
            pass

    _tier_cache: Dict[str, float] = {}

    def _tier_mult(opp_id: str) -> float:
        if tier_league_map is None:
            return 1.0
        if opp_id not in _tier_cache:
            _tier_cache[opp_id] = get_tier_multiplier(tier_league_map.get(str(opp_id)), cohort_gender, age=_cohort_age)
        return _tier_cache[opp_id]

    results = []
    for team_id in team_ratings:
        tg = _get_team_games(team_id, team_games, games_df, cfg, today)
        if len(tg) == 0:
            results.append({"team_id": team_id, "sos_raw": cfg.INITIAL_MU})
            continue

        # Vectorized opponent mu lookup
        opp_ids = tg["opp_id"].values
        opp_mus_all = np.array(
            [_apply_tier_mult(team_ratings.get(o, (cfg.INITIAL_MU,))[0], _tier_mult(o), cfg) for o in opp_ids]
        )

        # Apply repeat cap
        opp_counts: Dict[str, int] = {}
        keep_mask = []
        for o in opp_ids:
            opp_counts[o] = opp_counts.get(o, 0) + 1
            keep_mask.append(opp_counts[o] <= cfg.SOS_REPEAT_CAP)
        opp_mus = opp_mus_all[keep_mask]

        if len(opp_mus) == 0:
            results.append({"team_id": team_id, "sos_raw": cfg.INITIAL_MU})
            continue

        # Symmetric trim: sort, remove bottom and top percentiles
        opp_mus_sorted = np.sort(opp_mus)
        n = len(opp_mus_sorted)
        trim_bottom = int(n * cfg.SOS_TRIM_BOTTOM_PCT)
        trim_top = int(n * cfg.SOS_TRIM_TOP_PCT)

        if trim_bottom + trim_top >= n:
            # If trimming would remove everything, keep all
            trimmed = opp_mus_sorted
        else:
            end = n - trim_top if trim_top > 0 else n
            trimmed = opp_mus_sorted[trim_bottom:end]

        if len(trimmed) == 0:
            trimmed = opp_mus_sorted  # fallback: keep all

        results.append({"team_id": team_id, "sos_raw": float(np.mean(trimmed))})

    return pd.DataFrame(results)


def sigmoid_zscore_normalize(values: pd.Series) -> pd.Series:
    """Normalize values to [0, 1] using sigmoid of z-score.

    Maps the mean to 0.5, with values above/below the mean approaching
    1.0/0.0 asymptotically.  No min-max rescaling is applied.

    Args:
        values: Series of numeric values to normalize.

    Returns:
        Series of normalized values in (0, 1).
    """
    mean = values.mean()
    std = values.std(ddof=0)
    if std < 1e-10:
        return pd.Series(0.5, index=values.index)
    z = (values - mean) / std
    return 1.0 / (1.0 + np.exp(-z))


# =========================================================
# SCF: Schedule Connectivity Factor (regional bubble detection)
# =========================================================
def compute_scf(
    games_df: pd.DataFrame,
    team_state_map: Dict[str, str],
    team_ratings: Dict[str, Tuple[float, float, float]],
    cfg: GlickoConfig,
    team_games: Optional[Dict[str, pd.DataFrame]] = None,
    tier_league_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict]:
    """Compute Schedule Connectivity Factor for each team.

    Detects teams playing in isolated bubbles — either regional (state-based)
    or league-based (e.g., cross-state ECNL_RL play). Assigns a diversity
    score that can dampen SOS and mu toward neutral.

    Args:
        games_df: DataFrame with columns team_id, opp_id plus standard game cols.
        team_state_map: Dict mapping team_id -> state abbreviation (e.g. 'ID').
        team_ratings: Dict of {team_id: (mu, sigma, volatility)}.
        cfg: GlickoConfig with SCF and league-SCF settings.
        team_games: Optional pre-filtered games dict from run_glicko2_cohort.
        tier_league_map: Optional dict of team_id -> league string for league diversity.

    Returns:
        Dict[team_id, {scf, unique_states, bridge_games, is_isolated, quality_boosted,
                        unique_leagues, league_scf, dominant_opp_league, dominant_opp_league_share}]
    """
    from collections import Counter

    result: Dict[str, Dict] = {}
    cohort_age_num = None
    if "age" in games_df.columns and len(games_df) > 0:
        cohort_age_num = _parse_age_number(games_df["age"].iloc[0])
    use_league_scf = (
        tier_league_map is not None
        and (cohort_age_num is None or cohort_age_num >= int(cfg.SCF_DISABLE_LEAGUE_BELOW_AGE))
    )

    for team_id in team_ratings:
        if not cfg.SCF_ENABLED:
            result[team_id] = {
                "scf": 1.0,
                "unique_states": 0,
                "bridge_games": 0,
                "is_isolated": False,
                "quality_boosted": False,
                "unique_leagues": 0,
                "league_scf": 1.0,
                "dominant_opp_league": None,
                "dominant_opp_league_share": 0.0,
            }
            continue

        team_state = team_state_map.get(team_id, "")
        if team_games and team_id in team_games:
            tg = team_games[team_id]
        else:
            tg = games_df[games_df["team_id"] == team_id]

        # State diversity (filter unknown states)
        opp_ids = tg["opp_id"].values
        opp_states = [team_state_map.get(o, "") for o in opp_ids]
        valid_states = [s for s in opp_states if s and s != "UNKNOWN"]
        bridge_count = sum(1 for s in valid_states if s != team_state)
        unique_states = len(set(valid_states))
        weighted_bridge_games = float(bridge_count)
        weighted_unique_states = float(unique_states)

        if cfg.SCF_QUALITY_WEIGHT_ENABLED and len(tg) > 0:
            team_age = tg["age"].iloc[0] if "age" in tg.columns else None
            team_gender = tg["gender"].iloc[0] if "gender" in tg.columns else None
            state_best_weight: Dict[str, float] = {}
            weighted_bridge_games = 0.0
            for idx, opp_id in enumerate(opp_ids):
                opp_state = opp_states[idx] if idx < len(opp_states) else ""
                if not opp_state or opp_state == "UNKNOWN" or opp_state == team_state:
                    continue
                opp_mu = team_ratings.get(opp_id, (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY))[0]
                bridge_weight = _selection_quality_weight(float(opp_mu), cfg)
                is_same_age = True
                if {"opp_age", "opp_gender", "age", "gender"}.issubset(tg.columns):
                    is_same_age = (
                        str(tg["opp_age"].iloc[idx]) == str(team_age)
                        and str(tg["opp_gender"].iloc[idx]) == str(team_gender)
                    )
                if not is_same_age:
                    bridge_weight *= float(cfg.SCF_CROSS_AGE_BRIDGE_MULT)
                weighted_bridge_games += bridge_weight
                state_best_weight[opp_state] = max(state_best_weight.get(opp_state, 0.0), bridge_weight)
            weighted_unique_states = float(sum(state_best_weight.values()))

        # SCF score: diversity of opponent states, quality-weighted when enabled.
        # True zero-bridge bubbles should dampen harder than partially bridged
        # schedules, so ramp the floor up only as bridge volume approaches the
        # minimum evidence threshold.
        scf_raw = min(weighted_unique_states / cfg.SCF_DIVERSITY_DIVISOR, 1.0)
        scf_floor = cfg.SCF_FLOOR
        if cfg.MIN_BRIDGE_GAMES > 0 and weighted_bridge_games < cfg.MIN_BRIDGE_GAMES:
            bridge_progress = max(0.0, float(weighted_bridge_games) / float(cfg.MIN_BRIDGE_GAMES))
            scf_floor = cfg.SCF_ZERO_BRIDGE_FLOOR + (
                (cfg.SCF_FLOOR - cfg.SCF_ZERO_BRIDGE_FLOOR) * bridge_progress
            )
        scf = max(scf_floor, scf_raw)

        is_isolated = (
            weighted_bridge_games < cfg.MIN_BRIDGE_GAMES or weighted_unique_states < cfg.SCF_MIN_UNIQUE_STATES
        )

        # League diversity (only when tier_league_map provided)
        # Uses league FAMILIES, not exact league strings. Top-tier leagues
        # (ECNL, GA, MLS_NEXT_HD) are one family; all others are "lower".
        # Playing across ASPIRE + ECNL_RL + DPL is NOT meaningful diversity.
        unique_leagues = 0
        dominant_league = None
        dominant_share = 0.0
        league_scf = 1.0

        if use_league_scf:
            _TOP_TIER = {"ECNL", "GA", "MLS_NEXT_HD"}
            opp_leagues_known = [tier_league_map[str(o)] for o in opp_ids if str(o) in tier_league_map]

            if opp_leagues_known:
                # Map to families for diversity measurement
                opp_families = ["top" if lg in _TOP_TIER else "lower" for lg in opp_leagues_known]
                unique_families = len(set(opp_families))
                unique_leagues = unique_families  # report family count, not raw league count

                # Concentration penalty only applies when dominant family is "lower".
                # Being concentrated in top-tier competition is NOT a bubble — it's
                # the strongest possible schedule. Only penalize lower-tier bubbles.
                family_counts = Counter(opp_families)
                dominant_league, dominant_count = family_counts.most_common(1)[0]
                dominant_share = dominant_count / len(opp_families)

                if dominant_league == "lower":
                    # Count-based: need opponents from 2+ families
                    league_count_scf = min(unique_families / cfg.SCF_LEAGUE_DIVERSITY_DIVISOR, 1.0)

                    # Concentration-based: penalty if dominant lower family > threshold
                    if dominant_share > cfg.SCF_LEAGUE_CONCENTRATION_THRESHOLD:
                        excess = dominant_share - cfg.SCF_LEAGUE_CONCENTRATION_THRESHOLD
                        concentration_penalty = max(0.0, 1.0 - cfg.SCF_LEAGUE_CONCENTRATION_SCALE * excess)
                    else:
                        concentration_penalty = 1.0

                    league_scf_raw = min(league_count_scf, concentration_penalty)
                    league_scf = max(cfg.SCF_LEAGUE_FLOOR, league_scf_raw)
                # else: dominant family is "top" → no league penalty (league_scf stays 1.0)

            # Final SCF: most restrictive dimension wins
            scf = min(scf, league_scf)
            # Only flag league-isolated when dominant family is lower-tier
            if dominant_league == "lower":
                is_isolated = is_isolated or unique_leagues < cfg.SCF_MIN_UNIQUE_LEAGUES

        result[team_id] = {
            "scf": scf,
            "unique_states": weighted_unique_states,
            "bridge_games": weighted_bridge_games,
            "is_isolated": is_isolated,
            "quality_boosted": bool(cfg.SCF_QUALITY_WEIGHT_ENABLED),
            "unique_leagues": unique_leagues,
            "league_scf": league_scf,
            "dominant_opp_league": dominant_league,
            "dominant_opp_league_share": round(dominant_share, 3),
        }

    return result


def _summarize_team_recent_activity(tg: Optional[pd.DataFrame], today: pd.Timestamp) -> Dict[str, int | None]:
    if tg is None or tg.empty or "date" not in tg.columns:
        return {
            "games_last_60_days": 0,
            "games_last_120_days": 0,
            "games_last_180_days": 0,
            "days_since_last": None,
        }

    dates = pd.to_datetime(tg["date"], errors="coerce")
    if hasattr(dates.dtype, "tz") and dates.dtype.tz is not None:
        dates = dates.dt.tz_localize(None)
    valid_dates = dates.dropna()
    if valid_dates.empty:
        return {
            "games_last_60_days": 0,
            "games_last_120_days": 0,
            "games_last_180_days": 0,
            "days_since_last": None,
        }

    last_game = valid_dates.max()
    return {
        "games_last_60_days": int((valid_dates >= (today - pd.Timedelta(days=60))).sum()),
        "games_last_120_days": int((valid_dates >= (today - pd.Timedelta(days=120))).sum()),
        "games_last_180_days": int((valid_dates >= (today - pd.Timedelta(days=180))).sum()),
        "days_since_last": int((today - last_game).days),
    }


def _compute_base_evidence_scale(
    team_df: pd.DataFrame,
    team_games: Dict[str, pd.DataFrame],
    scf_data: Optional[Dict[str, Dict]],
    cfg: GlickoConfig,
    today: Optional[pd.Timestamp] = None,
    recent_activity: Optional[Dict[str, Dict[str, int | None]]] = None,
) -> pd.Series:
    """Return multiplicative evidence scales for published base scores."""
    if team_df.empty or not cfg.BASE_EVIDENCE_SHRINK_ENABLED:
        return pd.Series(1.0, index=team_df.index if not team_df.empty else pd.Index([]), dtype=float)

    if today is not None and today.tzinfo is not None:
        today = today.tz_localize(None)

    ranked = team_df.sort_values(["mu", "team_id"], ascending=[False, True]).reset_index(drop=True)
    rank_lookup = {str(row.team_id): idx + 1 for idx, row in enumerate(ranked.itertuples(index=False))}
    scale_lookup: Dict[str, float] = {}

    for row in team_df.itertuples(index=False):
        team_id = str(row.team_id)
        tg = team_games.get(team_id)
        if tg is None or tg.empty:
            scale_lookup[team_id] = 1.0
            continue

        same_age = tg
        if {"opp_age", "opp_gender", "age", "gender"}.issubset(tg.columns):
            same_age = tg[
                (tg["opp_age"].astype(str) == str(tg["age"].iloc[0]))
                & (tg["opp_gender"].astype(str) == str(tg["gender"].iloc[0]))
            ]
        unique_same_age = same_age["opp_id"].dropna().astype(str).unique().tolist()
        if {"gf", "ga"}.issubset(same_age.columns):
            non_loss_same_age = same_age[same_age["gf"].fillna(-999) >= same_age["ga"].fillna(999)]
        else:
            non_loss_same_age = same_age.iloc[0:0]
        unique_non_loss = non_loss_same_age["opp_id"].dropna().astype(str).unique().tolist()

        opp_ranks = [rank_lookup.get(opp_id) for opp_id in unique_same_age if rank_lookup.get(opp_id) is not None]
        non_loss_ranks = [rank_lookup.get(opp_id) for opp_id in unique_non_loss if rank_lookup.get(opp_id) is not None]

        top100 = sum(1 for rank in opp_ranks if rank <= 100)
        top500 = sum(1 for rank in opp_ranks if rank <= 500)
        top500_non_loss = sum(1 for rank in non_loss_ranks if rank <= 500)
        top1000_non_loss = sum(1 for rank in non_loss_ranks if rank <= 1000)
        avg_rank = float(sum(opp_ranks) / len(opp_ranks)) if opp_ranks else float("inf")

        counts = tg["opp_id"].astype(str).value_counts()
        repeat_share = float(counts[counts >= 2].sum() / len(tg)) if len(tg) else 0.0
        scf = float((scf_data or {}).get(team_id, {}).get("scf", 1.0))
        activity = (recent_activity or {}).get(team_id)
        if activity is None and today is not None:
            activity = _summarize_team_recent_activity(tg, today)
        days_since_last = activity.get("days_since_last") if activity is not None else None
        games_last_60 = int(activity.get("games_last_60_days", 0)) if activity is not None else 0
        games_last_120 = int(activity.get("games_last_120_days", 0)) if activity is not None else 0

        shrink = 0.0
        if (
            top100 == 0
            and top500 <= cfg.BASE_EVIDENCE_SHRINK_STRONG_MAX_TOP500
            and top1000_non_loss <= cfg.BASE_EVIDENCE_SHRINK_MAX_TOP1000_NON_LOSS
            and avg_rank >= cfg.BASE_EVIDENCE_SHRINK_AVG_RANK_STRONG
        ):
            shrink = cfg.BASE_EVIDENCE_SHRINK_STRONG
        elif (
            top100 == 0
            and top500 <= cfg.BASE_EVIDENCE_SHRINK_MODERATE_MAX_TOP500
            and avg_rank >= cfg.BASE_EVIDENCE_SHRINK_AVG_RANK_MODERATE
        ):
            shrink = cfg.BASE_EVIDENCE_SHRINK_MODERATE
        elif (
            top100 <= 1
            and top500 <= cfg.BASE_EVIDENCE_SHRINK_LIGHT_MAX_TOP500
            and avg_rank >= cfg.BASE_EVIDENCE_SHRINK_AVG_RANK_LIGHT
        ):
            shrink = cfg.BASE_EVIDENCE_SHRINK_LIGHT
        elif (
            top100 == 0
            and top500 <= cfg.BASE_EVIDENCE_SHRINK_QUALITY_MAX_TOP500
            and top500_non_loss <= cfg.BASE_EVIDENCE_SHRINK_QUALITY_MAX_TOP500_NON_LOSS
            and avg_rank >= cfg.BASE_EVIDENCE_SHRINK_AVG_RANK_QUALITY
        ):
            shrink = cfg.BASE_EVIDENCE_SHRINK_QUALITY

        if scf <= cfg.BASE_EVIDENCE_SHRINK_LOW_SCF:
            shrink += cfg.BASE_EVIDENCE_SHRINK_LOW_CONNECTIVITY_BONUS
        if repeat_share >= cfg.BASE_EVIDENCE_SHRINK_REPEAT_SHARE:
            shrink += cfg.BASE_EVIDENCE_SHRINK_REPEAT_BONUS
        if (
            days_since_last is not None
            and days_since_last >= cfg.BASE_EVIDENCE_STALE_NO_RECENT_DAYS
            and games_last_60 <= cfg.BASE_EVIDENCE_STALE_MAX_GAMES_LAST_60
        ):
            shrink += cfg.BASE_EVIDENCE_STALE_NO_RECENT_BONUS
        if (
            days_since_last is not None
            and days_since_last >= cfg.BASE_EVIDENCE_STALE_LOW_ACTIVITY_DAYS
            and games_last_120 <= cfg.BASE_EVIDENCE_STALE_MAX_GAMES_LAST_120
        ):
            shrink += cfg.BASE_EVIDENCE_STALE_LOW_ACTIVITY_BONUS

        shrink = min(float(cfg.BASE_EVIDENCE_SHRINK_MAX), max(0.0, shrink))
        scale_lookup[team_id] = 1.0 - shrink

    return team_df["team_id"].astype(str).map(scale_lookup).fillna(1.0).astype(float)


def compute_game_explainability(
    games_df: pd.DataFrame,
    team_ratings: Dict[str, Tuple[float, float, float]],
    cfg: GlickoConfig,
    today: pd.Timestamp,
    team_games: Optional[Dict[str, pd.DataFrame]] = None,
    global_rating_map: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Compute per-game explainability breakdown using final converged ratings.

    For each team's perspective of each game, re-derives the intermediate
    Glicko-2 values that were aggregated during convergence: expected outcome,
    actual outcome, surprise factor, rating contribution, and off/def residuals.

    Runs once as a post-hoc pass — does NOT modify the convergence loop.

    Args:
        games_df: DataFrame with columns team_id, opp_id, date, gf, ga, age, gender,
                  opp_age, opp_gender.  Optional columns game_id and id are passed
                  through to the output when present (from data_adapter).
        team_ratings: Dict of {team_id: (mu, sigma, volatility)} from final convergence.
        cfg: GlickoConfig with MAX_GAMES, WINDOW_DAYS, RECENCY_LAMBDA, MAX_GD.
        today: Reference date for window and recency.
        team_games: Optional pre-filtered games dict from run_glicko2_cohort.
        global_rating_map: Cross-age opponent ratings from Pass 1. None for Pass 1.

    Returns:
        DataFrame with one row per (team, game) perspective.  Columns are defined
        by _EXPLAIN_COLUMNS: team_id, opp_id, game_date, gf, ga, game_id, id,
        team_mu, team_sigma, opp_mu, opp_sigma, expected_outcome, actual_outcome,
        outcome_surprise, g_factor, recency_weight, rating_contribution,
        off_residual, def_residual.
    """
    cohort_avg_gpg = games_df["gf"].mean() if len(games_df) > 0 else 0.0

    # Determine cohort age/gender for cross-age detection
    cohort_age = games_df["age"].iloc[0] if len(games_df) > 0 else None
    cohort_gender = games_df["gender"].iloc[0] if len(games_df) > 0 else None

    rows = []
    for team_id, (team_mu, team_sigma, _) in team_ratings.items():
        tg = _get_team_games(team_id, team_games, games_df, cfg, today)
        if len(tg) == 0:
            continue

        # Recency weights are additionally decayed for repeated opponents.
        weights = np.asarray(compute_recency_weights(tg["date"], today, cfg.RECENCY_LAMBDA))
        weights = weights * compute_repeat_opponent_weights(tg["opp_id"].values, cfg)

        # Convert team rating to Glicko-2 scale
        team_mu_g2, _ = _to_glicko2_scale(team_mu, team_sigma)

        # Per-game breakdown
        opp_ids = tg["opp_id"].values
        gf_vals = tg["gf"].values.astype(int)
        ga_vals = tg["ga"].values.astype(int)
        dates = tg["date"].values

        has_cross_age = "opp_age" in tg.columns and "opp_gender" in tg.columns
        opp_ages = tg["opp_age"].values if has_cross_age else None
        opp_genders = tg["opp_gender"].values if has_cross_age else None

        # Optional ID columns from data_adapter
        game_ids = tg["game_id"].values if "game_id" in tg.columns else [None] * len(tg)
        row_ids = tg["id"].values if "id" in tg.columns else [None] * len(tg)

        for i, opp_id in enumerate(opp_ids):
            # Resolve opponent rating (mirroring run_glicko2_cohort cross-age logic)
            is_cross_age = False
            if has_cross_age and opp_ages is not None and opp_genders is not None:
                is_cross_age = (opp_ages[i] != cohort_age) or (opp_genders[i] != cohort_gender)

            if is_cross_age and global_rating_map is not None:
                opp_mu = global_rating_map.get(opp_id, cfg.INITIAL_MU)
                opp_sigma = cfg.INITIAL_SIGMA
                opp_mu = scale_cross_age_rating(
                    opp_mu,
                    str(opp_ages[i]),
                    str(opp_genders[i]),
                    str(cohort_age),
                    str(cohort_gender),
                    cfg,
                )
            elif opp_id in team_ratings:
                opp_mu, opp_sigma, _ = team_ratings[opp_id]
            else:
                opp_mu = cfg.INITIAL_MU
                opp_sigma = cfg.INITIAL_SIGMA

            # Glicko-2 per-game values
            opp_mu_g2, opp_phi_g2 = _to_glicko2_scale(opp_mu, opp_sigma)
            g_j = glicko2_g(opp_phi_g2)
            E_j = glicko2_E(team_mu_g2, opp_mu_g2, opp_phi_g2)
            s_j = game_outcome(int(gf_vals[i]), int(ga_vals[i]), cfg.MAX_GD)
            w_j = float(weights[i])

            # Off/def residuals use Elo scale, not Glicko-2 scale
            e_team = expected_score(team_mu, opp_mu)
            off_res = float(gf_vals[i]) - cohort_avg_gpg * e_team
            def_res = cohort_avg_gpg * (1.0 - e_team) - float(ga_vals[i])

            rows.append(
                {
                    "team_id": team_id,
                    "opp_id": opp_id,
                    "game_date": dates[i],
                    "gf": int(gf_vals[i]),
                    "ga": int(ga_vals[i]),
                    "game_id": game_ids[i],
                    "id": row_ids[i],
                    "team_mu": team_mu,
                    "team_sigma": team_sigma,
                    "opp_mu": opp_mu,
                    "opp_sigma": opp_sigma,
                    "expected_outcome": E_j,
                    "actual_outcome": s_j,
                    "outcome_surprise": s_j - E_j,
                    "g_factor": g_j,
                    "recency_weight": w_j,
                    "rating_contribution": w_j * g_j * (s_j - E_j),
                    "off_residual": off_res,
                    "def_residual": def_res,
                }
            )

    if not rows:
        return pd.DataFrame(columns=_EXPLAIN_COLUMNS)

    return pd.DataFrame(rows)


def apply_scf_dampening(
    team_df: pd.DataFrame,
    scf_data: Dict[str, Dict],
    cfg: GlickoConfig,
) -> pd.DataFrame:
    """Apply SCF dampening to SOS values.

    Dampens sos_raw toward the Glicko-2 neutral rating (1500.0) based on
    each team's SCF score. Isolated teams also get their SOS capped.

    Args:
        team_df: DataFrame with columns team_id, sos_raw.
        scf_data: Output of compute_scf().
        cfg: GlickoConfig with ISOLATION_SOS_CAP.

    Returns:
        Modified DataFrame with SCF columns added and sos_raw dampened.
    """
    df = team_df.copy()
    neutral = cfg.INITIAL_MU  # 1500.0

    # Map SCF fields onto the DataFrame
    df["scf"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("scf", 1.0))
    df["bridge_games"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("bridge_games", 0))
    df["is_isolated"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("is_isolated", False))
    df["unique_opp_states"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("unique_states", 0))
    df["quality_boosted"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("quality_boosted", False))
    df["unique_opp_leagues"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("unique_leagues", 0))
    df["dominant_opp_league"] = df["team_id"].map(lambda t: scf_data.get(t, {}).get("dominant_opp_league"))
    df["dominant_opp_league_share"] = df["team_id"].map(
        lambda t: scf_data.get(t, {}).get("dominant_opp_league_share", 0.0)
    )

    # Cap isolated teams' SOS before dampening
    max_sos = df["sos_raw"].max()
    isolated_mask = df["is_isolated"]
    sos_cap = neutral + cfg.ISOLATION_SOS_CAP * (max_sos - neutral)
    df.loc[isolated_mask, "sos_raw"] = df.loc[isolated_mask, "sos_raw"].clip(upper=sos_cap)

    # Dampen SOS toward neutral: sos_dampened = neutral + scf * (sos_raw - neutral)
    df["sos_raw"] = neutral + df["scf"] * (df["sos_raw"] - neutral)

    # Dampen mu toward neutral for isolated teams (Shelopugin & Sirotkin 2023:
    # Glicko-2 ratings inflate in isolated ecosystems without cross-references).
    # Under SCF_PUBLISH_ONLY, mu stays pure for prediction/SOS/cross-age use and
    # only the published score is dampened.
    if "mu" in df.columns and not cfg.SCF_PUBLISH_ONLY:
        df["mu"] = neutral + df["scf"] * (df["mu"] - neutral)

    return df


def apply_sos_credit_cap(team_df: pd.DataFrame, cfg: GlickoConfig) -> pd.DataFrame:
    """Cap each team's SOS-credit — the portion of its published score above what its
    own record justifies — gated on record so only SOS-inflated teams (mediocre record
    on a hard schedule) are pulled down, never record-justified ones.

    Runs within the cohort, on the normalized powerscore_core scale. record_score is
    produced by the same sigmoid_zscore_normalize used for powerscore_core, so the two
    share one [0, 1] scale and powerscore_core - record_score is meaningful. The cap is
    one-sided (a min): it never raises a score and never touches mu, SOS, SCF, or ML.

    Args:
        team_df: DataFrame with team_id, wins, games_played, goals_for, goals_against,
                 and powerscore_core (post-normalization).
        cfg: GlickoConfig with SOS_CREDIT_* settings.

    Returns:
        Modified DataFrame with powerscore_core capped and power_presos holding the
        pre-cap value (for a pre/post audit).
    """
    df = team_df.copy()

    games = df["games_played"].astype(float)
    gp = games.clip(lower=1.0)
    win_rate = df["wins"].astype(float) / gp
    gd_per_game = (df["goals_for"].astype(float) - df["goals_against"].astype(float)) / gp

    # Standardize each component before blending: win-rate is [0, 1] while goal
    # differential spans several goals, so a raw blend would let goal-diff dominate
    # regardless of the configured weights.
    def _zscore(series: pd.Series) -> pd.Series:
        std = series.std(ddof=0)
        if std < 1e-10:
            return pd.Series(0.0, index=series.index)
        return (series - series.mean()) / std

    record_raw = cfg.SOS_CREDIT_RECORD_WIN_WEIGHT * _zscore(win_rate) + cfg.SOS_CREDIT_RECORD_GD_WEIGHT * _zscore(
        gd_per_game
    )
    record_score = sigmoid_zscore_normalize(record_raw)

    # Record-gated ceiling: a strong record keeps ~full credit (ceiling >= 1 → never
    # binds); a mediocre record allows only SOS_CREDIT_MAX above its record level.
    ceiling = record_score * (1.0 + cfg.SOS_CREDIT_MAX)
    core = df["powerscore_core"].astype(float)
    capped_full = core.clip(upper=ceiling)

    # Ramp the cap in with sample size: fully applied at SOS_CREDIT_MIN_GAMES_FULL
    # games, relaxed toward uncapped below it so thin-sample teams aren't whipsawed by
    # a noisy record estimate. The blend stays continuous, so there is no rank cliff.
    games_ramp = (games / max(float(cfg.SOS_CREDIT_MIN_GAMES_FULL), 1.0)).clip(lower=0.0, upper=1.0)
    capped_core = core + games_ramp * (capped_full - core)

    df["power_presos"] = df["powerscore_core"]
    df["powerscore_core"] = capped_core
    return df


# =========================================================
# Batch convergence engine
# =========================================================
def run_glicko2_cohort(
    games_df: pd.DataFrame,
    cfg: GlickoConfig,
    today: pd.Timestamp,
    global_rating_map: Optional[Dict[str, float]] = None,
    initial_ratings: Optional[Dict[str, Tuple[float, float, float]]] = None,
    tier_league_map: Optional[Dict[str, str]] = None,
    cohort_gender: str = "Male",
    team_state_map: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Run Glicko-2 for a single (age, gender) cohort.

    Processes games iteratively until ratings converge. Each iteration:
    1. For each team, collect opponents + outcomes + recency weights
    2. Apply glicko2_update to compute new mu/sigma/volatility
    3. Check convergence (mean |delta_mu| < threshold)
    4. Stop if converged or max iterations reached

    Args:
        games_df: DataFrame with columns: team_id, opp_id, date, gf, ga, age, gender.
                  Should be pre-filtered to a single (age, gender) cohort.
                  Each row is one team's perspective of one game.
        cfg: GlickoConfig with all parameters.
        today: Reference date for recency weighting and window filtering.
        global_rating_map: Optional dict of {team_id: mu} for cross-age opponent lookup.
                          When provided (Pass 2), cross-age opponents use this rating.
        initial_ratings: Optional dict of {team_id: (mu, sigma, volatility)} for warm-start.
                        When provided, use these as starting ratings instead of defaults.
        tier_league_map: Optional dict of {team_id: league} for tier-based opponent
                        strength discounting during convergence.
        cohort_gender: "Male" or "Female" for tier lookup.
        team_state_map: Optional dict of {team_id: state_code} for balanced window
                        bridge selection.

    Returns:
        Tuple of (DataFrame, team_games dict):
        - DataFrame with columns: team_id, mu, sigma, volatility,
          games_played, wins, losses, draws, last_game, goals_for, goals_against
        - Dict mapping team_id -> filtered games DataFrame for reuse downstream
    """
    # 1. Identify all teams
    all_teams = games_df["team_id"].unique().tolist()

    # 2. Initialize ratings (warm-start if provided)
    if initial_ratings is not None:
        ratings: Dict[str, Tuple[float, float, float]] = {
            t: initial_ratings.get(t, (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY)) for t in all_teams
        }
    else:
        ratings = {t: (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY) for t in all_teams}

    # 3. Clip outlier goals
    df = clip_outlier_goals(games_df, cfg.OUTLIER_GUARD_ZSCORE)

    # 4. Determine cohort age/gender for cross-age detection
    # Use the first row's age/gender as the cohort identity
    cohort_age = df["age"].iloc[0] if len(df) > 0 else None
    _cohort_gender_detected = df["gender"].iloc[0] if len(df) > 0 else None

    # Tier multiplier for opponent mu during convergence
    from src.rankings.constants import get_tier_multiplier as _get_tier_mult_fn

    _tier_cache: Dict[str, float] = {}
    _cohort_age_int: Optional[int] = None
    if cohort_age is not None:
        try:
            _cohort_age_int = int(cohort_age)
        except (ValueError, TypeError):
            # Handle "U15" / "u15" format
            age_str = str(cohort_age).lower().lstrip("u")
            try:
                _cohort_age_int = int(age_str)
            except (ValueError, TypeError):
                _cohort_age_int = None

    def _tier_mult_conv(opp_id) -> float:
        if tier_league_map is None:
            return 1.0
        opp_key = str(opp_id)
        if opp_key not in _tier_cache:
            _tier_cache[opp_key] = _get_tier_mult_fn(tier_league_map.get(opp_key), cohort_gender, age=_cohort_age_int)
        return _tier_cache[opp_key]

    # 5. Select games per team
    team_games: Dict[str, pd.DataFrame] = {}
    for t in all_teams:
        team_games[t] = select_games_balanced(
            df,
            t,
            cfg,
            today,
            rating_lookup=ratings,
            global_rating_map=global_rating_map,
            team_state_map=team_state_map,
            tier_mult_fn=_tier_mult_conv,
        )

    # 6. Pre-convert team games to arrays (avoid iterrows in the hot loop)
    team_arrays: Dict[str, Optional[Dict]] = {}
    for t in all_teams:
        tg = team_games[t]
        if len(tg) == 0:
            team_arrays[t] = None
            continue
        opp_ages = tg["opp_age"].values if "opp_age" in tg.columns else None
        opp_genders = tg["opp_gender"].values if "opp_gender" in tg.columns else None
        cross_age_mask = None
        if opp_ages is not None and opp_genders is not None:
            cross_age_mask = (opp_ages != cohort_age) | (opp_genders != cohort_gender)
        team_arrays[t] = {
            "opp_ids": tg["opp_id"].values,
            "gf": tg["gf"].values.astype(int),
            "ga": tg["ga"].values.astype(int),
            "opp_ages": opp_ages,
            "opp_genders": opp_genders,
            "cross_age_mask": cross_age_mask,
            "weights": (
                compute_recency_weights(
                    tg["date"],
                    today,
                    cfg.RECENCY_LAMBDA,
                    window_days=cfg.WINDOW_DAYS,
                    grace_days=getattr(cfg, "WINDOW_GRACE_DAYS", 0),
                )
                * compute_repeat_opponent_weights(tg["opp_id"].values, cfg)
            ).tolist(),
            "outcomes": [
                game_outcome(int(gf), int(ga), cfg.MAX_GD) for gf, ga in zip(tg["gf"].values, tg["ga"].values)
            ],
        }

    # 7. Iterate until convergence (Jacobi iteration)
    for iteration in range(cfg.MAX_ITERATIONS):
        new_ratings: Dict[str, Tuple[float, float, float]] = {}

        for t in all_teams:
            arr = team_arrays[t]
            if arr is None:
                new_ratings[t] = ratings[t]
                continue

            # Collect opponents using pre-computed arrays
            opp_ids = arr["opp_ids"]
            cross_age_mask = arr["cross_age_mask"]
            opponents_list: List[Tuple[float, float]] = []
            for i, opp_id in enumerate(opp_ids):
                is_cross_age = cross_age_mask[i] if cross_age_mask is not None else False
                if is_cross_age and global_rating_map is not None:
                    opp_mu = global_rating_map.get(opp_id, cfg.INITIAL_MU)
                    opp_sigma = cfg.INITIAL_SIGMA
                    opp_mu = scale_cross_age_rating(
                        opp_mu,
                        str(arr["opp_ages"][i]) if arr["opp_ages"] is not None else str(cohort_age),
                        str(arr["opp_genders"][i]) if arr["opp_genders"] is not None else str(_cohort_gender_detected),
                        str(cohort_age),
                        str(_cohort_gender_detected),
                        cfg,
                    )
                elif opp_id in ratings:
                    opp_mu, opp_sigma, _ = ratings[opp_id]
                else:
                    opp_mu = cfg.INITIAL_MU
                    opp_sigma = cfg.INITIAL_SIGMA
                # Apply tier discount: beating a Tier 2 opponent = beating a weaker opponent
                opp_mu = _apply_tier_mult(opp_mu, _tier_mult_conv(opp_id), cfg)
                opponents_list.append((opp_mu, opp_sigma))

            # Update rating
            mu, sigma, vol = ratings[t]
            new_mu, new_sigma, new_vol = glicko2_update(
                mu, sigma, vol, opponents_list, arr["outcomes"], arr["weights"], cfg.TAU
            )
            new_ratings[t] = (new_mu, new_sigma, new_vol)

        # Compute convergence metrics
        max_delta = 0.0
        delta_sum = 0.0
        for t in all_teams:
            delta = abs(new_ratings[t][0] - ratings[t][0])
            max_delta = max(max_delta, delta)
            delta_sum += delta
        mean_delta = delta_sum / len(all_teams) if all_teams else 0.0

        # Batch-update all ratings (Jacobi)
        ratings = new_ratings

        logger.info(
            "Glicko-2 iteration %d: max_delta=%.4f, mean_delta=%.4f",
            iteration + 1,
            max_delta,
            mean_delta,
        )

        if mean_delta < cfg.CONVERGENCE_THRESHOLD:
            logger.info(
                "Glicko-2 converged after %d iterations (max_delta=%.4f, mean_delta=%.4f)",
                iteration + 1,
                max_delta,
                mean_delta,
            )
            break
    else:
        logger.warning(
            "Glicko-2 did not converge after %d iterations (max_delta=%.4f, mean_delta=%.4f)",
            cfg.MAX_ITERATIONS,
            max_delta,
            mean_delta,
        )

    # 7. Compute aggregate stats per team
    results = []
    for t in all_teams:
        tg = team_games[t]
        mu, sigma, vol = ratings[t]

        gp = len(tg)
        wins = int((tg["gf"] > tg["ga"]).sum()) if gp > 0 else 0
        losses = int((tg["gf"] < tg["ga"]).sum()) if gp > 0 else 0
        draws = int((tg["gf"] == tg["ga"]).sum()) if gp > 0 else 0
        last_game = tg["date"].max() if gp > 0 else pd.NaT
        goals_for = int(tg["gf"].sum()) if gp > 0 else 0
        goals_against = int(tg["ga"].sum()) if gp > 0 else 0

        results.append(
            {
                "team_id": t,
                "mu": mu,
                "sigma": sigma,
                "volatility": vol,
                "games_played": gp,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "last_game": last_game,
                "goals_for": goals_for,
                "goals_against": goals_against,
            }
        )

    return pd.DataFrame(results), team_games


# =========================================================
# Main Glicko-2 ranking entry point
# =========================================================
def compute_rankings_v2(
    games_df: pd.DataFrame,
    today: Optional[pd.Timestamp] = None,
    cfg: Optional[GlickoConfig] = None,
    global_rating_map: Optional[Dict[str, float]] = None,
    team_state_map: Optional[Dict[str, str]] = None,
    pass_label: Optional[str] = None,
    initial_ratings: Optional[Dict[str, Tuple[float, float, float]]] = None,
    tier_league_map: Optional[Dict[str, str]] = None,
) -> Dict[str, pd.DataFrame]:
    """Run the full Glicko-2 ranking pipeline.

    Runs the full Glicko-2 pipeline:
    1. Run Glicko-2 convergence for the cohort
    2. Derive offense/defense from game residuals
    3. Compute SOS with repeat cap and trim
    4. Apply post-convergence SCF dampening to SOS and published mu (if team_state_map provided)
    5. Normalize all metrics via sigmoid z-score
    6. Compute rankings and status
    7. Map to full rankings_full schema

    Args:
        games_df: DataFrame with game data (team_id, opp_id, date, gf, ga, age, gender, opp_age, opp_gender).
        today: Reference date. Defaults to now.
        cfg: GlickoConfig. Defaults to GlickoConfig().
        global_rating_map: Cross-age opponent ratings from Pass 1. None for Pass 1.
        team_state_map: Team ID -> state code for SCF. None disables SCF.
        pass_label: "Pass1" or "Pass2" for logging.

    Returns:
        {"teams": DataFrame with all rankings_full columns,
         "games_used": DataFrame of games used,
         "game_explainability": DataFrame with per-game Glicko-2 breakdown
             (one row per team-game perspective)}
    """
    # 1. Setup
    if today is None:
        today = pd.Timestamp.now("UTC")
    # Strip timezone so all date comparisons are tz-naive (Supabase dates are naive)
    if today.tzinfo is not None:
        today = today.tz_localize(None)
    if cfg is None:
        cfg = GlickoConfig()
    label = f" [{pass_label}]" if pass_label else ""
    logger.info(f"Starting Glicko-2 ranking engine{label}")

    # Determine cohort gender early (needed for tier multiplier in convergence)
    _cohort_gender = "Male"
    if "gender" in games_df.columns and len(games_df) > 0:
        _cohort_gender = games_df["gender"].iloc[0].capitalize()

    # 2. Run Glicko-2 convergence
    team_df, team_games = run_glicko2_cohort(
        games_df,
        cfg,
        today,
        global_rating_map,
        initial_ratings=initial_ratings,
        tier_league_map=tier_league_map,
        cohort_gender=_cohort_gender,
        team_state_map=team_state_map,
    )

    # 3. Build the converged ratings dict for all downstream derived metrics
    team_ratings: Dict[str, Tuple[float, float, float]] = dict(
        zip(team_df["team_id"], zip(team_df["mu"], team_df["sigma"], team_df["volatility"]))
    )
    recent_activity = {
        str(team_id): _summarize_team_recent_activity(tg, today) for team_id, tg in team_games.items()
    }

    # 4. Derive offense/defense
    off_def = derive_offense_defense(games_df, team_ratings, cfg, today, team_games=team_games)
    team_df = team_df.merge(off_def, on="team_id", how="left")

    # 5. Compute SOS (reuses _cohort_gender from above)
    sos = compute_sos(
        games_df,
        team_ratings,
        cfg,
        today,
        team_games=team_games,
        tier_league_map=tier_league_map,
        cohort_gender=_cohort_gender,
    )
    team_df = team_df.merge(sos, on="team_id", how="left")

    # 5b. Compute per-game explainability breakdown
    game_explain_df = compute_game_explainability(
        games_df,
        team_ratings,
        cfg,
        today,
        team_games=team_games,
        global_rating_map=global_rating_map,
    )

    # 6. Apply SCF post-convergence dampening (if team_state_map provided and SCF_ENABLED)
    scf_data: Dict[str, Dict] = {}
    if cfg.SCF_ENABLED and team_state_map:
        scf_data = compute_scf(
            games_df,
            team_state_map,
            team_ratings,
            cfg,
            team_games=team_games,
            tier_league_map=tier_league_map,
        )
        team_df = apply_scf_dampening(team_df, scf_data, cfg)

    # 7. Normalize to 0-1 via sigmoid z-score
    team_df["off_norm"] = sigmoid_zscore_normalize(team_df["off_raw"].fillna(0))
    team_df["def_norm"] = sigmoid_zscore_normalize(team_df["def_raw"].fillna(0))
    team_df["sos_norm"] = sigmoid_zscore_normalize(team_df["sos_raw"].fillna(1500))
    if cfg.SOS_ADJ_ENABLED:
        weak = (cfg.SOS_ADJ_WEAK_THRESHOLD - team_df["sos_norm"]).clip(lower=0) / cfg.SOS_ADJ_WEAK_THRESHOLD
        strong = (team_df["sos_norm"] - cfg.SOS_ADJ_STRONG_THRESHOLD).clip(lower=0) / (
            1.0 - cfg.SOS_ADJ_STRONG_THRESHOLD
        )
        sos_scale = 1.0 + cfg.SOS_ADJ_STRONG_MAX * strong - cfg.SOS_ADJ_WEAK_MAX * weak
        sos_scale = sos_scale.clip(
            1.0 - cfg.SOS_ADJ_WEAK_MAX,
            1.0 + cfg.SOS_ADJ_STRONG_MAX,
        )
        mu_sos = cfg.INITIAL_MU + (team_df["mu"] - cfg.INITIAL_MU) * sos_scale
        if cfg.SCF_PUBLISH_ONLY and "scf" in team_df.columns:
            mu_sos = cfg.INITIAL_MU + (mu_sos - cfg.INITIAL_MU) * team_df["scf"]
        evidence_scale = _compute_base_evidence_scale(
            team_df,
            team_games,
            scf_data,
            cfg,
            today=today,
            recent_activity=recent_activity,
        )
        mu_sos = cfg.INITIAL_MU + (mu_sos - cfg.INITIAL_MU) * evidence_scale
        team_df["powerscore_core"] = sigmoid_zscore_normalize(mu_sos)
    else:
        mu_publish = team_df["mu"]
        if cfg.SCF_PUBLISH_ONLY and "scf" in team_df.columns:
            mu_publish = cfg.INITIAL_MU + (mu_publish - cfg.INITIAL_MU) * team_df["scf"]
        evidence_scale = _compute_base_evidence_scale(
            team_df,
            team_games,
            scf_data,
            cfg,
            today=today,
            recent_activity=recent_activity,
        )
        mu_publish = cfg.INITIAL_MU + (mu_publish - cfg.INITIAL_MU) * evidence_scale
        team_df["powerscore_core"] = sigmoid_zscore_normalize(mu_publish)

    # 7b. Record-gated SOS-credit cap (one block covers both powerscore_core branches).
    if cfg.SOS_CREDIT_CAP_ENABLED:
        team_df = apply_sos_credit_cap(team_df, cfg)

    # 8. Provisional multiplier from sigma
    team_df["provisional_mult"] = np.clip(1.0 - (team_df["sigma"] / cfg.INITIAL_SIGMA) ** 2, 0.0, 1.0)
    team_df["powerscore_adj"] = (team_df["powerscore_core"] * team_df["provisional_mult"]).clip(0.0, 1.0)

    # 9. Status and rankings
    cutoff = today - pd.Timedelta(days=cfg.INACTIVE_DAYS)
    last_game_ser = pd.to_datetime(team_df["last_game"])
    if hasattr(last_game_ser.dtype, "tz") and last_game_ser.dtype.tz is not None:
        last_game_ser = last_game_ser.dt.tz_localize(None)
    team_df["status"] = np.where(
        (last_game_ser < cutoff) | (team_df["last_game"].isna()),
        "Inactive",
        np.where(
            team_df["games_played"] < cfg.MIN_GAMES_PROVISIONAL,
            "Not Enough Ranked Games",
            "Active",
        ),
    )

    team_df["sample_flag"] = np.where(team_df["games_played"] < cfg.MIN_GAMES_PROVISIONAL, "LOW_SAMPLE", "OK")

    active_mask = team_df["status"] == "Active"
    # Mu-ordered intermediate only — under SCF_PUBLISH_ONLY it carries no isolation
    # dampening. The published rank (rank_in_cohort_final) is recomputed downstream
    # from power_score_true, which does.
    team_df["rank_in_cohort"] = np.nan
    team_df.loc[active_mask, "rank_in_cohort"] = team_df.loc[active_mask, "mu"].rank(ascending=False, method="min")
    team_df["national_rank"] = team_df["rank_in_cohort"]

    # 10. Map to all rankings_full columns

    # Win percentage
    team_df["win_percentage"] = np.where(
        team_df["games_played"] > 0,
        (team_df["wins"] / team_df["games_played"] * 100).round(1),
        0.0,
    )

    # Age group and gender from games
    _age_val = games_df["age"].iloc[0] if len(games_df) > 0 else "U15"
    if "age" not in team_df.columns:
        team_df["age"] = _age_val
    _age_digits_re = re.compile(r"\d+")

    def _to_age_group(x):
        if not pd.notna(x):
            return None
        s = str(x).strip()
        if not s:
            return None
        m = _age_digits_re.search(s)
        if not m:
            return None
        try:
            return f"u{int(m.group(0))}"
        except (ValueError, TypeError):
            return None

    team_df["age_group"] = team_df["age"].apply(_to_age_group)
    if "gender" not in team_df.columns:
        team_df["gender"] = games_df["gender"].iloc[0] if len(games_df) > 0 else "M"

    # SOS aliases and backward-compat columns
    team_df["sos"] = team_df["sos_raw"]
    team_df["sos_raw_col"] = team_df["sos_raw"]
    team_df["strength_of_schedule"] = team_df["sos_raw"]
    team_df["sos_norm_national"] = team_df["sos_norm"]
    team_df["sos_norm_state"] = team_df["sos_norm"]

    # SOS rankings
    team_df["sos_rank_national"] = np.nan
    team_df.loc[active_mask, "sos_rank_national"] = team_df.loc[active_mask, "sos_raw"].rank(
        ascending=False, method="min"
    )
    team_df["sos_rank_state"] = team_df["sos_rank_national"]

    # Raw/intermediate (backward compat)
    team_df["sad_raw"] = -team_df["def_raw"].fillna(0)
    team_df["off_shrunk"] = team_df["off_raw"]
    team_df["def_shrunk"] = team_df["def_raw"]
    team_df["sad_shrunk"] = team_df["sad_raw"]

    # Abs strength for two-pass
    team_df["abs_strength"] = sigmoid_zscore_normalize(team_df["mu"])

    # Power scores. The SOS-credit cap, when on, already set power_presos to the
    # pre-cap powerscore_core; only assign here when it left it unset.
    if "power_presos" not in team_df.columns:
        team_df["power_presos"] = team_df["powerscore_core"]
    team_df["anchor"] = 0.5

    # Performance residuals (placeholder -- ML layer computes these)
    team_df["perf_raw"] = 0.0
    team_df["perf_centered"] = 0.0

    # ML columns (placeholder -- Layer 13 fills these)
    team_df["ml_overperf"] = None
    team_df["ml_norm"] = None
    team_df["powerscore_ml"] = team_df["powerscore_adj"]
    team_df["rank_in_cohort_ml"] = team_df["rank_in_cohort"]

    # Final scores
    team_df["power_score_final"] = team_df["powerscore_adj"].clip(0.0, 1.0)
    team_df["national_power_score"] = team_df["power_score_final"]
    team_df["global_power_score"] = team_df["power_score_final"]
    team_df["power_score_true"] = team_df["power_score_final"]

    # State rank (same as national for now -- compute_all_cohorts adds state-level)
    team_df["state_rank"] = team_df["national_rank"]
    team_df["global_rank"] = team_df["national_rank"]

    # Rank changes (computed downstream by ranking_history comparison)
    team_df["rank_change_7d"] = None
    team_df["rank_change_30d"] = None
    team_df["rank_change_state_7d"] = None
    team_df["rank_change_state_30d"] = None

    # Timestamps
    team_df["last_calculated"] = pd.Timestamp.now("UTC")

    # Games in last 180 days
    team_df["games_last_180_days"] = (
        team_df["team_id"]
        .astype(str)
        .map(lambda team_id: recent_activity.get(team_id, {}).get("games_last_180_days", 0))
        .fillna(0)
        .astype(int)
    )

    # State code
    if team_state_map:
        team_df["state_code"] = team_df["team_id"].map(lambda t: team_state_map.get(str(t), None))
    else:
        team_df["state_code"] = None

    # 11. Return
    if "sos_raw_col" in team_df.columns:
        team_df["sos_raw"] = team_df["sos_raw_col"]

    logger.info(f"Glicko-2 engine complete{label}: {len(team_df)} teams ranked")

    # Collect the actual games used by Glicko-2, preserving per-team selection metadata.
    selected_frames = [tg.copy() for tg in team_games.values() if tg is not None and not tg.empty]
    games_used = pd.concat(selected_frames, ignore_index=False) if selected_frames else games_df.copy()

    return {
        "teams": team_df,
        "games_used": games_used,
        "game_explainability": game_explain_df,
    }
