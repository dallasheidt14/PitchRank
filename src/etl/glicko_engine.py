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
    return 1.0 / math.sqrt(1.0 + 3.0 * phi ** 2 / (math.pi ** 2))


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
    a = math.log(sigma_vol ** 2)
    phi2 = phi ** 2
    delta2 = delta ** 2

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta2 - phi2 - v - ex)
        denom = 2.0 * (phi2 + v + ex) ** 2
        return num / denom - (x - a) / (tau ** 2)

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
                MAX_ITERATIONS, sigma_vol, delta, phi, v, tau,
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
        phi_star = math.sqrt(phi_g2 ** 2 + sigma ** 2)
        new_mu, new_phi = _from_glicko2_scale(mu_g2, phi_star)
        return new_mu, new_phi, sigma

    opp_g2 = [_to_glicko2_scale(m, s) for m, s in opponents]

    # Step 3: Compute v (estimated variance) and delta
    v_inv = 0.0
    delta_sum = 0.0

    for (mu_j, phi_j), s_j, w_j in zip(opp_g2, outcomes, weights):
        g_j = glicko2_g(phi_j)
        E_j = glicko2_E(mu_g2, mu_j, phi_j)
        v_inv += w_j * g_j ** 2 * E_j * (1.0 - E_j)
        delta_sum += w_j * g_j * (s_j - E_j)

    v = 1.0 / v_inv
    delta = v * delta_sum

    # Step 4: Update volatility
    new_sigma = _update_volatility(sigma, delta, phi_g2, v, tau)

    # Step 5: Update phi (pre-rating period value)
    phi_star = math.sqrt(phi_g2 ** 2 + new_sigma ** 2)

    # Step 6: Update phi and mu
    new_phi_g2 = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)
    new_mu_g2 = mu_g2 + new_phi_g2 ** 2 * delta_sum

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
def clip_outlier_goals(
    games_df: pd.DataFrame, zscore_threshold: float = 2.5
) -> pd.DataFrame:
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
    mask = (games_df["team_id"] == team_id) & (games_df["date"] >= cutoff)
    filtered = games_df.loc[mask].sort_values("date", ascending=False)
    return filtered.head(max_games)


def compute_recency_weights(
    game_dates: pd.Series, today: pd.Timestamp, lambda_: float = 1.0
) -> np.ndarray:
    """Compute exponential-decay recency weights.

    Args:
        game_dates: Series of game dates.
        today: Reference date.
        lambda_: Decay rate (higher = faster decay).

    Returns:
        Numpy array of weights that sum to 1.0.
    """
    days_ago = (today - game_dates).dt.days
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
        age = int(age.lstrip('Uu'))

    # Choose anchor dict by gender
    if gender.upper().startswith('M'):
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
# Batch convergence engine
# =========================================================
def run_glicko2_cohort(
    games_df: pd.DataFrame,
    cfg: GlickoConfig,
    today: pd.Timestamp,
    global_rating_map: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Run Glicko-2 for a single (age, gender) cohort.

    Processes games iteratively until ratings converge. Each iteration:
    1. For each team, collect opponents + outcomes + recency weights
    2. Apply glicko2_update to compute new mu/sigma/volatility
    3. Check convergence (max |delta_mu| < threshold)
    4. Stop if converged or max iterations reached

    Args:
        games_df: DataFrame with columns: team_id, opp_id, date, gf, ga, age, gender.
                  Should be pre-filtered to a single (age, gender) cohort.
                  Each row is one team's perspective of one game.
        cfg: GlickoConfig with all parameters.
        today: Reference date for recency weighting and window filtering.
        global_rating_map: Optional dict of {team_id: mu} for cross-age opponent lookup.
                          When provided (Pass 2), cross-age opponents use this rating.

    Returns:
        DataFrame with columns: team_id, mu, sigma, volatility,
        games_played, wins, losses, draws, last_game, goals_for, goals_against
    """
    # 1. Identify all teams
    all_teams = games_df["team_id"].unique().tolist()

    # 2. Initialize ratings
    ratings: Dict[str, Tuple[float, float, float]] = {
        t: (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY)
        for t in all_teams
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

    # 6. Iterate until convergence (Jacobi iteration)
    for iteration in range(cfg.MAX_ITERATIONS):
        new_ratings: Dict[str, Tuple[float, float, float]] = {}

        for t in all_teams:
            tg = team_games[t]
            if len(tg) == 0:
                new_ratings[t] = ratings[t]
                continue

            # Collect opponents, outcomes, and weights
            opponents_list: List[Tuple[float, float]] = []
            outcomes_list: List[float] = []

            for _, row in tg.iterrows():
                opp_id = row["opp_id"]

                # Check if opponent is cross-age
                is_cross_age = False
                if "opp_age" in row.index and "opp_gender" in row.index:
                    if row["opp_age"] != cohort_age or row["opp_gender"] != cohort_gender:
                        is_cross_age = True

                # Look up opponent rating
                if is_cross_age and global_rating_map is not None:
                    opp_mu = global_rating_map.get(opp_id, cfg.INITIAL_MU)
                    opp_sigma = cfg.INITIAL_SIGMA
                elif opp_id in ratings:
                    opp_mu, opp_sigma, _ = ratings[opp_id]
                else:
                    opp_mu = cfg.INITIAL_MU
                    opp_sigma = cfg.INITIAL_SIGMA

                opponents_list.append((opp_mu, opp_sigma))
                outcomes_list.append(
                    game_outcome(int(row["gf"]), int(row["ga"]), cfg.MAX_GD)
                )

            # Compute recency weights
            weights = compute_recency_weights(
                tg["date"], today, cfg.RECENCY_LAMBDA
            ).tolist()

            # Update rating
            mu, sigma, vol = ratings[t]
            new_mu, new_sigma, new_vol = glicko2_update(
                mu, sigma, vol, opponents_list, outcomes_list, weights, cfg.TAU
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
            iteration + 1, max_delta, mean_delta,
        )

        if max_delta < cfg.CONVERGENCE_THRESHOLD:
            logger.info(
                "Glicko-2 converged after %d iterations (max_delta=%.4f)",
                iteration + 1, max_delta,
            )
            break
    else:
        logger.warning(
            "Glicko-2 did not converge after %d iterations (max_delta=%.4f)",
            cfg.MAX_ITERATIONS, max_delta,
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

        results.append({
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
        })

    return pd.DataFrame(results)
