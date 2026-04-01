from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.etl.glicko_config import GlickoConfig

logger = logging.getLogger(__name__)


# =========================================================
# Constants
# =========================================================
GLICKO2_SCALE = 173.7178  # Glickman's scaling factor


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
    cutoff = today - pd.Timedelta(days=window_days)
    dates = games_df["date"]
    if hasattr(dates.dtype, "tz") and dates.dtype.tz is not None:
        dates = dates.dt.tz_localize(None)
    mask = (games_df["team_id"] == team_id) & (dates >= cutoff)
    filtered = games_df.loc[mask].sort_values("date", ascending=False)
    return filtered.head(max_games)


def compute_recency_weights(game_dates: pd.Series, today: pd.Timestamp, lambda_: float = 1.0) -> np.ndarray:
    """Compute exponential-decay recency weights.

    Args:
        game_dates: Series of game dates.
        today: Reference date.
        lambda_: Decay rate (higher = faster decay).

    Returns:
        Numpy array of weights that sum to 1.0.
    """
    gd = game_dates.dt.tz_localize(None) if hasattr(game_dates.dtype, "tz") and game_dates.dtype.tz is not None else game_dates
    today_naive = today.tz_localize(None) if today.tzinfo is not None else today
    days_ago = (today_naive - gd).dt.days
    weights = np.exp(-lambda_ * days_ago / 365.0)
    return weights / weights.sum()


# =========================================================
# Cross-age scaling
# =========================================================
def get_anchor(age, gender: str, cfg: GlickoConfig) -> float:
    """Look up the calibrated anchor for a given age and gender.

    Args:
        age: Age as an int (14) or string like 'U14' / 'u14'.
        gender: Gender string — anything starting with 'M' (case-insensitive)
                or equal to 'Male' is treated as male; all others as female.
        cfg: GlickoConfig containing MALE_ANCHORS and FEMALE_ANCHORS.

    Returns:
        Anchor float from the config, or 1.0 for unknown ages.
    """
    # Normalise age to int
    if isinstance(age, str):
        age = int(age.lstrip("Uu"))

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
        tg = (
            team_games[team_id] if team_games and team_id in team_games
            else select_games(games_df, team_id, cfg.MAX_GAMES, cfg.WINDOW_DAYS, today)
        )
        if len(tg) == 0:
            results.append({"team_id": team_id, "off_raw": 0.0, "def_raw": 0.0})
            continue

        # Vectorized: lookup opponent mus
        opp_mus = np.array([team_ratings.get(o, (cfg.INITIAL_MU,))[0] for o in tg["opp_id"].values])
        e_team = 1.0 / (1.0 + 10.0 ** ((opp_mus - team_mu) / 400.0))
        off_residuals = tg["gf"].values.astype(float) - cohort_avg_gpg * e_team
        def_residuals = cohort_avg_gpg * (1.0 - e_team) - tg["ga"].values.astype(float)

        weights = compute_recency_weights(tg["date"], today, cfg.RECENCY_LAMBDA)
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

    Returns:
        DataFrame with columns: team_id, sos_raw.
    """
    results = []
    for team_id in team_ratings:
        tg = (
            team_games[team_id] if team_games and team_id in team_games
            else select_games(games_df, team_id, cfg.MAX_GAMES, cfg.WINDOW_DAYS, today)
        )
        if len(tg) == 0:
            results.append({"team_id": team_id, "sos_raw": cfg.INITIAL_MU})
            continue

        # Vectorized opponent mu lookup
        opp_ids = tg["opp_id"].values
        opp_mus_all = np.array([team_ratings.get(o, (cfg.INITIAL_MU,))[0] for o in opp_ids])

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
) -> Dict[str, Dict]:
    """Compute Schedule Connectivity Factor for each team.

    Detects teams playing in isolated regional bubbles (e.g., 3 Idaho teams
    only playing each other inflate each other's ratings) and assigns a
    diversity score that can dampen their SOS toward neutral.

    Args:
        games_df: DataFrame with columns team_id, opp_id plus standard game cols.
        team_state_map: Dict mapping team_id -> state abbreviation (e.g. 'ID').
        team_ratings: Dict of {team_id: (mu, sigma, volatility)}.
        cfg: GlickoConfig with SCF_ENABLED, SCF_DIVERSITY_DIVISOR, SCF_FLOOR,
             MIN_BRIDGE_GAMES, SCF_MIN_UNIQUE_STATES.
        team_games: Optional pre-filtered games dict from run_glicko2_cohort.

    Returns:
        Dict[team_id, {scf, unique_states, bridge_games, is_isolated, quality_boosted}]
    """
    result: Dict[str, Dict] = {}

    for team_id in team_ratings:
        if not cfg.SCF_ENABLED:
            result[team_id] = {
                "scf": 1.0,
                "unique_states": 0,
                "bridge_games": 0,
                "is_isolated": False,
                "quality_boosted": False,
            }
            continue

        team_state = team_state_map.get(team_id, "")
        if team_games and team_id in team_games:
            tg = team_games[team_id]
        else:
            tg = games_df[games_df["team_id"] == team_id]

        # Vectorized state lookup
        opp_ids = tg["opp_id"].values
        opp_states = [team_state_map.get(o, "") for o in opp_ids]
        bridge_count = sum(1 for s in opp_states if s and s != team_state)
        unique_states = len(set(s for s in opp_states if s))

        # SCF score: diversity of opponent states
        scf_raw = min(unique_states / cfg.SCF_DIVERSITY_DIVISOR, 1.0)
        scf = max(cfg.SCF_FLOOR, scf_raw)

        is_isolated = bridge_count < cfg.MIN_BRIDGE_GAMES or unique_states < cfg.SCF_MIN_UNIQUE_STATES

        result[team_id] = {
            "scf": scf,
            "unique_states": unique_states,
            "bridge_games": bridge_count,
            "is_isolated": is_isolated,
            "quality_boosted": False,
        }

    return result


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

    # Cap isolated teams' SOS before dampening
    max_sos = df["sos_raw"].max()
    isolated_mask = df["is_isolated"]
    sos_cap = neutral + cfg.ISOLATION_SOS_CAP * (max_sos - neutral)
    df.loc[isolated_mask, "sos_raw"] = df.loc[isolated_mask, "sos_raw"].clip(upper=sos_cap)

    # Dampen SOS toward neutral: sos_dampened = neutral + scf * (sos_raw - neutral)
    df["sos_raw"] = neutral + df["scf"] * (df["sos_raw"] - neutral)

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
            t: initial_ratings.get(t, (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY))
            for t in all_teams
        }
    else:
        ratings = {
            t: (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY) for t in all_teams
        }

    # 3. Clip outlier goals
    df = clip_outlier_goals(games_df, cfg.OUTLIER_GUARD_ZSCORE)

    # 4. Select games per team
    team_games: Dict[str, pd.DataFrame] = {}
    for t in all_teams:
        team_games[t] = select_games(df, t, cfg.MAX_GAMES, cfg.WINDOW_DAYS, today)

    # 5. Determine cohort age/gender for cross-age detection
    # Use the first row's age/gender as the cohort identity
    cohort_age = df["age"].iloc[0] if len(df) > 0 else None
    cohort_gender = df["gender"].iloc[0] if len(df) > 0 else None

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
            "weights": compute_recency_weights(tg["date"], today, cfg.RECENCY_LAMBDA).tolist(),
            "outcomes": [
                game_outcome(int(gf), int(ga), cfg.MAX_GD)
                for gf, ga in zip(tg["gf"].values, tg["ga"].values)
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
                        str(arr["opp_genders"][i]) if arr["opp_genders"] is not None else str(cohort_gender),
                        str(cohort_age), str(cohort_gender), cfg,
                    )
                elif opp_id in ratings:
                    opp_mu, opp_sigma, _ = ratings[opp_id]
                else:
                    opp_mu = cfg.INITIAL_MU
                    opp_sigma = cfg.INITIAL_SIGMA
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
# Main entry point — drop-in replacement for v53e.compute_rankings
# =========================================================
def compute_rankings_v2(
    games_df: pd.DataFrame,
    today: Optional[pd.Timestamp] = None,
    cfg: Optional[GlickoConfig] = None,
    global_rating_map: Optional[Dict[str, float]] = None,
    team_state_map: Optional[Dict[str, str]] = None,
    pass_label: Optional[str] = None,
    initial_ratings: Optional[Dict[str, Tuple[float, float, float]]] = None,
) -> Dict[str, pd.DataFrame]:
    """Drop-in replacement for v53e.compute_rankings.

    Runs the full Glicko-2 pipeline:
    1. Run Glicko-2 convergence for the cohort
    2. Derive offense/defense from game residuals
    3. Compute SOS with repeat cap and trim
    4. Apply SCF bubble detection (if team_state_map provided)
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
        {"teams": DataFrame with all rankings_full columns, "games_used": DataFrame of games used}
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

    # 2. Run Glicko-2 convergence
    team_df, team_games = run_glicko2_cohort(
        games_df, cfg, today, global_rating_map, initial_ratings=initial_ratings
    )

    # 3. Build ratings dict for derived metrics
    team_ratings: Dict[str, Tuple[float, float, float]] = dict(zip(
        team_df["team_id"],
        zip(team_df["mu"], team_df["sigma"], team_df["volatility"])
    ))

    # 4. Derive offense/defense
    off_def = derive_offense_defense(games_df, team_ratings, cfg, today, team_games=team_games)
    team_df = team_df.merge(off_def, on="team_id", how="left")

    # 5. Compute SOS
    sos = compute_sos(games_df, team_ratings, cfg, today, team_games=team_games)
    team_df = team_df.merge(sos, on="team_id", how="left")

    # 6. Apply SCF (if team_state_map provided and SCF_ENABLED)
    if cfg.SCF_ENABLED and team_state_map:
        scf_data = compute_scf(games_df, team_state_map, team_ratings, cfg, team_games=team_games)
        team_df = apply_scf_dampening(team_df, scf_data, cfg)

    # 7. Normalize to 0-1 via sigmoid z-score
    team_df["off_norm"] = sigmoid_zscore_normalize(team_df["off_raw"].fillna(0))
    team_df["def_norm"] = sigmoid_zscore_normalize(team_df["def_raw"].fillna(0))
    team_df["sos_norm"] = sigmoid_zscore_normalize(team_df["sos_raw"].fillna(1500))
    team_df["powerscore_adj"] = sigmoid_zscore_normalize(team_df["mu"])

    # 8. Provisional multiplier from sigma
    team_df["provisional_mult"] = np.clip(1.0 - (team_df["sigma"] / cfg.INITIAL_SIGMA) ** 2, 0.0, 1.0)

    # 9. Status and rankings
    cutoff = today - pd.Timedelta(days=cfg.INACTIVE_DAYS)
    last_game_ser = pd.to_datetime(team_df["last_game"])
    if hasattr(last_game_ser.dtype, "tz") and last_game_ser.dtype.tz is not None:
        last_game_ser = last_game_ser.dt.tz_localize(None)
    team_df["status"] = np.where(last_game_ser >= cutoff, "Active", "Inactive")

    team_df["sample_flag"] = np.where(team_df["games_played"] < cfg.MIN_GAMES_PROVISIONAL, "LOW_SAMPLE", "OK")

    active_mask = team_df["status"] == "Active"
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
    team_df["age_group"] = team_df.get("age", games_df["age"].iloc[0] if len(games_df) > 0 else "U15")
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

    # Power scores
    team_df["power_presos"] = team_df["powerscore_adj"]
    team_df["powerscore_core"] = team_df["powerscore_adj"]
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
    team_df["games_last_180_days"] = team_df["games_played"]  # approximation

    # State code
    if team_state_map:
        team_df["state_code"] = team_df["team_id"].map(lambda t: team_state_map.get(str(t), None))
    else:
        team_df["state_code"] = None

    # 11. Return
    if "sos_raw_col" in team_df.columns:
        team_df["sos_raw"] = team_df["sos_raw_col"]

    logger.info(f"Glicko-2 engine complete{label}: {len(team_df)} teams ranked")

    return {
        "teams": team_df,
        "games_used": games_df,
    }
