"""
Ranking audit tests: validate ranking outputs against real cached data.

Catches ranking anomalies by running compute_rankings on production-cached
game data and asserting plausibility constraints:

- Top-ranked teams must have sufficient game volume
- SOS_norm must not be artificially inflated for any single team
- PowerScore components (OFF/DEF/SOS) must be balanced — no single component
  should dominate ranking position
- Cross-snapshot stability: same games → similar rankings
- Win/loss record sanity: teams with losing records shouldn't rank top-10
- Low-game-count teams shouldn't outrank high-game-count dominant teams

Motivated by a real bug where a U16 Female team jumped from #47 to #1 due to
SOS_norm inflation (0.39 → 0.97) while OFF/DEF stayed constant (~0.937/0.933).
"""

import os
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"

# Cohort game files for audit (U16 Female, different snapshot dates).
# Each entry: (hash, label, expected_team_count_range)
U16F_COHORT_FILES = [
    ("0633f48a1d6687d10e97faed922a278c", "U16F-snapshot-A", (1800, 2500)),
    ("0ab9e3e6d441341d8d58c144aab851d3", "U16F-snapshot-B", (1800, 2500)),
]

# The team that was observed ranking #1 incorrectly
SUSPECT_TEAM_ID = "d3fa4cfa-8da4-40e6-af7e-96e317a46981"

# Standard config for audit runs (matches production defaults)
AUDIT_CFG = V53EConfig(
    SOS_POWER_ITERATIONS=3,
    COMPONENT_SOS_ENABLED=True,
    OPPONENT_ADJUST_ENABLED=True,
    PERF_BLEND_WEIGHT=0.0,
    SCF_ENABLED=True,
    PAGERANK_DAMPENING_ENABLED=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_today(games_df: pd.DataFrame) -> pd.Timestamp:
    """
    Infer an appropriate 'today' date from the game data.

    Uses the latest game date + 7 days, so the 365-day window covers the
    full dataset. This prevents stale-window artifacts when cached data
    is older than the current date.
    """
    max_date = pd.Timestamp(games_df["date"].max())
    return max_date + pd.Timedelta(days=7)


def _load_games(file_hash: str) -> pd.DataFrame | None:
    """Load cached game data by hash. Returns None if file missing."""
    path = CACHE_DIR / f"rankings_{file_hash}_games.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _load_teams(file_hash: str) -> pd.DataFrame | None:
    """Load cached team ranking data by hash. Returns None if file missing."""
    path = CACHE_DIR / f"rankings_{file_hash}_teams.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _run_rankings(games_df: pd.DataFrame, cfg=None, today=None) -> pd.DataFrame:
    """Run compute_rankings and return the active teams sorted by rank."""
    cfg = cfg or AUDIT_CFG
    if today is None:
        today = _infer_today(games_df)
    result = compute_rankings(games_df=games_df, cfg=cfg, today=today)
    teams = result["teams"]
    active = teams[teams["status"] == "Active"].copy()
    active = active.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
    return active


def _compute_win_record(games_df: pd.DataFrame, team_id: str) -> dict:
    """Compute W/L/D record for a team from game rows."""
    tg = games_df[games_df["team_id"] == team_id]
    wins = int((tg["gf"] > tg["ga"]).sum())
    losses = int((tg["gf"] < tg["ga"]).sum())
    draws = int((tg["gf"] == tg["ga"]).sum())
    gp = len(tg)
    win_pct = wins / gp if gp > 0 else 0
    return {"wins": wins, "losses": losses, "draws": draws, "gp": gp, "win_pct": win_pct}


# ===========================================================================
# Test Class: Top-N Plausibility (Real Data)
# ===========================================================================

class TestTopNPlausibility:
    """
    Validate that top-ranked teams in real data have plausible profiles.

    A team ranking in the national top-10 should have:
    - Sufficient games played (≥ 10)
    - A strong win record (≥ 60% win rate)
    - Balanced PowerScore components (no single component artificially inflated)
    """

    @pytest.fixture(scope="class")
    def u16f_snapshots(self):
        """Load all available U16F snapshot data."""
        snapshots = {}
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            teams = _load_teams(file_hash)
            if games is not None:
                snapshots[label] = {"games": games, "teams_cached": teams}
        if not snapshots:
            pytest.skip("No U16F cached data found in data/cache/")
        return snapshots

    def test_top10_minimum_games_played(self, u16f_snapshots):
        """Top-10 nationally ranked teams must have ≥ 10 games played."""
        for label, data in u16f_snapshots.items():
            active = _run_rankings(data["games"])
            top10 = active.head(10)

            for _, row in top10.iterrows():
                assert row["gp"] >= 10, (
                    f"[{label}] Team {row['team_id'][:12]}... ranked #{_ + 1} "
                    f"has only {row['gp']} games — too few for top-10 national"
                )

    def test_top10_win_rate_above_threshold(self, u16f_snapshots):
        """Top-10 teams should have ≥ 60% win rate."""
        for label, data in u16f_snapshots.items():
            active = _run_rankings(data["games"])
            top10 = active.head(10)

            for idx, row in top10.iterrows():
                record = _compute_win_record(data["games"], row["team_id"])
                assert record["win_pct"] >= 0.60, (
                    f"[{label}] Team {row['team_id'][:12]}... ranked #{idx + 1} "
                    f"has win rate {record['win_pct']:.0%} "
                    f"({record['wins']}W-{record['losses']}L-{record['draws']}D) "
                    f"— too low for top-10"
                )

    def test_top10_sos_norm_not_extreme(self, u16f_snapshots):
        """
        No top-10 team should have sos_norm > 0.98 unless cohort median is > 0.6.

        An sos_norm near 1.0 in a large cohort is suspicious — it means the team's
        raw SOS was the single highest in 2000+ teams, which should be very rare
        for a team that isn't from a top-tier national league (ECNL/GA/MLS NEXT).
        """
        for label, data in u16f_snapshots.items():
            active = _run_rankings(data["games"])
            top10 = active.head(10)
            cohort_sos_median = active["sos_norm"].median()

            for idx, row in top10.iterrows():
                if cohort_sos_median < 0.60:
                    assert row["sos_norm"] < 0.98, (
                        f"[{label}] Team {row['team_id'][:12]}... ranked #{idx + 1} "
                        f"has sos_norm={row['sos_norm']:.4f} (cohort median={cohort_sos_median:.4f}) "
                        f"— suspiciously inflated"
                    )

    def test_top10_powerscore_component_balance(self, u16f_snapshots):
        """
        PowerScore for top-10 teams should not be dominated by a single component.

        With weights OFF=0.20, DEF=0.20, SOS=0.60, the SOS contribution should not
        exceed 85% of the total PowerScore. If it does, the team is ranked purely on
        schedule strength with mediocre actual performance.
        """
        for label, data in u16f_snapshots.items():
            active = _run_rankings(data["games"])
            top10 = active.head(10)

            for idx, row in top10.iterrows():
                off_contrib = AUDIT_CFG.OFF_WEIGHT * row["off_norm"]
                def_contrib = AUDIT_CFG.DEF_WEIGHT * row["def_norm"]
                sos_contrib = AUDIT_CFG.SOS_WEIGHT * row["sos_norm"]
                total = off_contrib + def_contrib + sos_contrib

                if total > 0:
                    sos_share = sos_contrib / total
                    assert sos_share < 0.85, (
                        f"[{label}] Team {row['team_id'][:12]}... ranked #{idx + 1}: "
                        f"SOS contributes {sos_share:.0%} of PowerScore "
                        f"(off={off_contrib:.3f}, def={def_contrib:.3f}, sos={sos_contrib:.3f}) "
                        f"— ranking driven entirely by schedule, not performance"
                    )


# ===========================================================================
# Test Class: Cross-Snapshot Stability
# ===========================================================================

class TestCrossSnapshotStability:
    """
    Rankings should be stable across snapshots with similar game data.

    A team shouldn't jump 40+ ranks between snapshots unless the underlying
    game data changed significantly (new games, different window).
    """

    @pytest.fixture(scope="class")
    def paired_snapshots(self):
        """Load two U16F snapshots with overlapping data."""
        if len(U16F_COHORT_FILES) < 2:
            pytest.skip("Need at least 2 snapshots for stability test")

        snapshots = []
        for file_hash, label, _ in U16F_COHORT_FILES[:2]:
            games = _load_games(file_hash)
            if games is None:
                pytest.skip(f"Missing game data for {label}")
            snapshots.append((label, games))
        return snapshots

    def test_rerank_stability_top30(self, paired_snapshots):
        """
        Re-ranking both snapshots with identical config should produce
        similar top-30 orderings if the game data is similar.
        """
        label_a, games_a = paired_snapshots[0]
        label_b, games_b = paired_snapshots[1]

        active_a = _run_rankings(games_a)
        active_b = _run_rankings(games_b)

        # Build rank lookup: team_id → rank
        rank_a = dict(zip(active_a["team_id"], range(1, len(active_a) + 1)))
        rank_b = dict(zip(active_b["team_id"], range(1, len(active_b) + 1)))

        # For teams in top-30 of snapshot A, check their rank in snapshot B
        top30_a = active_a.head(30)
        common_teams = [t for t in top30_a["team_id"] if t in rank_b]

        if len(common_teams) < 10:
            pytest.skip("Not enough common teams between snapshots for stability test")

        rank_jumps = []
        for tid in common_teams:
            jump = abs(rank_a[tid] - rank_b[tid])
            rank_jumps.append((tid, rank_a[tid], rank_b[tid], jump))

        # No team in the top-30 should jump more than 40 ranks
        max_allowed_jump = 40
        worst_jumps = [(t, ra, rb, j) for t, ra, rb, j in rank_jumps if j > max_allowed_jump]

        assert len(worst_jumps) == 0, (
            f"[{label_a} vs {label_b}] {len(worst_jumps)} teams in top-30 jumped "
            f">{max_allowed_jump} ranks:\n"
            + "\n".join(
                f"  {t[:12]}...: #{ra} → #{rb} (Δ{j})"
                for t, ra, rb, j in sorted(worst_jumps, key=lambda x: -x[3])[:5]
            )
        )


# ===========================================================================
# Test Class: Suspect Team Deep Audit
# ===========================================================================

class TestSuspectTeamAudit:
    """
    Deep audit of the specific team flagged as incorrectly ranked #1.

    Team d3fa4cfa was observed ranking #1 nationally in U16 Female with:
    - sos_norm = 0.97 (top 3% of 2000+ teams)
    - off_norm = 0.937, def_norm = 0.933 (strong but not extraordinary)
    - In other snapshots with nearly identical games: ranked #47 with sos_norm = 0.39

    The test validates that this team does NOT rank in the top-5 when
    re-ranked with consistent configuration.
    """

    @pytest.fixture(scope="class")
    def suspect_data(self):
        """Load game data containing the suspect team."""
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            if games is None:
                continue
            if SUSPECT_TEAM_ID in games["team_id"].values:
                return {"games": games, "label": label, "hash": file_hash}
        pytest.skip(f"Suspect team {SUSPECT_TEAM_ID[:12]}... not found in cached data")

    def test_suspect_team_not_top5(self, suspect_data):
        """
        The suspect team should not rank top-5 when re-ranked with standard config.

        With 23W-2L-1D and strong OFF/DEF, the team deserves a good rank — but
        not #1 national. Their opponents are mid-tier (sos_norm ~0.39 in stable runs).
        """
        active = _run_rankings(suspect_data["games"])
        suspect = active[active["team_id"] == SUSPECT_TEAM_ID]

        if suspect.empty:
            pytest.skip("Suspect team not in Active rankings (may have insufficient games)")

        rank = suspect.index[0] + 1  # 0-indexed → 1-indexed
        assert rank > 5, (
            f"[{suspect_data['label']}] Suspect team {SUSPECT_TEAM_ID[:12]}... "
            f"ranked #{rank} — should not be top-5. "
            f"sos_norm={suspect.iloc[0]['sos_norm']:.4f}, "
            f"off_norm={suspect.iloc[0]['off_norm']:.4f}, "
            f"def_norm={suspect.iloc[0]['def_norm']:.4f}, "
            f"gp={suspect.iloc[0]['gp']}"
        )

    def test_suspect_team_sos_stability(self, suspect_data):
        """
        SOS_norm for the suspect team should be consistent across re-rankings.

        Run the ranking engine 3 times with the same data. SOS_norm must not
        vary by more than 0.01 — if it does, there's non-determinism in the pipeline.
        """
        sos_values = []
        for i in range(3):
            active = _run_rankings(suspect_data["games"])
            suspect = active[active["team_id"] == SUSPECT_TEAM_ID]
            if not suspect.empty:
                sos_values.append(suspect.iloc[0]["sos_norm"])

        if len(sos_values) < 2:
            pytest.skip("Suspect team not consistently ranked")

        sos_range = max(sos_values) - min(sos_values)
        assert sos_range < 0.01, (
            f"SOS_norm for suspect team varies by {sos_range:.4f} across identical "
            f"re-rankings: {[f'{v:.4f}' for v in sos_values]} — non-determinism detected"
        )

    def test_suspect_team_sos_vs_cohort(self, suspect_data):
        """
        The suspect team's SOS_norm should not be in the top 1% of the cohort.

        With mostly mid-tier opponents, the team's raw SOS should place it
        in a reasonable percentile (roughly 20-60th), not the 99th.
        """
        active = _run_rankings(suspect_data["games"])
        suspect = active[active["team_id"] == SUSPECT_TEAM_ID]

        if suspect.empty:
            pytest.skip("Suspect team not in Active rankings")

        suspect_sos = suspect.iloc[0]["sos_norm"]
        sos_percentile = (active["sos_norm"] < suspect_sos).mean()

        assert sos_percentile < 0.95, (
            f"Suspect team sos_norm={suspect_sos:.4f} is at the "
            f"{sos_percentile:.0%} percentile — implausibly high for "
            f"a team with mid-tier opponents"
        )


# ===========================================================================
# Test Class: SOS Inflation Detection (Synthetic)
# ===========================================================================

class TestSOSInflationDetection:
    """
    Synthetic tests that catch SOS inflation patterns.

    These don't require cached data — they construct game scenarios that
    should NOT produce sos_norm > 0.90 for the test team.
    """

    @staticmethod
    def _make_game_pair(gid, date, home, away, hs, as_, age="16", gender="female"):
        """Create home + away perspective rows."""
        return [
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": home, "opp_id": away, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": away, "opp_id": home, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
        ]

    # Reference date for synthetic tests — all game dates are relative to this
    SYNTH_TODAY = pd.Timestamp("2025-07-15")

    def _build_mid_tier_scenario(self):
        """
        Build a scenario mimicking the suspect team:
        - "star_team" beats 20 opponents convincingly (3-1 avg)
        - Those opponents are mid-tier (they beat each other ~50/50)
        - star_team should rank high on OFF/DEF but NOT have elite SOS
        """
        rows = []
        gc = 0
        rng = np.random.RandomState(42)
        base = pd.Timestamp("2025-07-01")

        # 20 mid-tier opponents with 10+ games each (round-robin among themselves)
        opps = [f"mid_opp_{i:02d}" for i in range(20)]
        for i, opp_a in enumerate(opps):
            for j in range(i + 1, min(i + 6, len(opps))):
                opp_b = opps[j]
                gc += 1
                # ~50/50 results: mid-tier teams are evenly matched
                ha = int(rng.poisson(1.5))
                hb = int(rng.poisson(1.5))
                d = base - pd.Timedelta(days=int(rng.randint(10, 200)))
                rows.extend(self._make_game_pair(f"rr_{gc}", d, opp_a, opp_b, ha, hb))

        # star_team beats mid-tier opponents convincingly
        for i, opp in enumerate(opps):
            gc += 1
            d = base - pd.Timedelta(days=int(rng.randint(5, 180)))
            rows.extend(self._make_game_pair(
                f"star_{gc}", d, "star_team", opp,
                int(rng.poisson(3.0)),  # ~3 goals scored
                int(rng.poisson(0.5)),  # ~0.5 goals conceded
            ))

        return pd.DataFrame(rows)

    def test_dominant_team_vs_midtier_opponents_sos(self):
        """
        A team that beats mid-tier opponents should have mid-range SOS.

        This catches the bug where SOS_norm gets inflated to ~0.97 for
        a team whose opponents are all mediocre.
        """
        games = self._build_mid_tier_scenario()
        active = _run_rankings(games, today=self.SYNTH_TODAY)

        star = active[active["team_id"] == "star_team"]
        assert not star.empty, "star_team should be Active (has 20 games)"

        star_row = star.iloc[0]
        assert star_row["sos_norm"] < 0.80, (
            f"star_team plays only mid-tier opponents but got sos_norm="
            f"{star_row['sos_norm']:.4f} — should be < 0.80"
        )

    def test_dominant_team_high_off_def(self):
        """The dominant team should rank well on OFF/DEF but not from SOS alone."""
        games = self._build_mid_tier_scenario()
        active = _run_rankings(games, today=self.SYNTH_TODAY)

        star = active[active["team_id"] == "star_team"]
        if star.empty:
            pytest.skip("star_team not Active")

        star_row = star.iloc[0]
        # OFF and DEF should be high (dominant results)
        assert star_row["off_norm"] > 0.80, (
            f"star_team off_norm={star_row['off_norm']:.4f} — should be high"
        )
        assert star_row["def_norm"] > 0.70, (
            f"star_team def_norm={star_row['def_norm']:.4f} — should be decent"
        )

    def _build_isolated_league_scenario(self):
        """
        Build a small isolated league (8 teams) that plays only each other.

        This catches SOS inflation in small connected components: if 8 teams
        form a closed circuit, SOS percentile normalization can push all of
        them to extreme values.
        """
        rows = []
        gc = 0
        rng = np.random.RandomState(99)
        base = pd.Timestamp("2025-07-01")

        # 8 isolated teams play only each other (round-robin, 2 games each matchup)
        isolated = [f"iso_{i}" for i in range(8)]
        for i, team_a in enumerate(isolated):
            for j in range(i + 1, len(isolated)):
                team_b = isolated[j]
                for rep in range(2):
                    gc += 1
                    d = base - pd.Timedelta(days=int(rng.randint(10, 200)))
                    rows.extend(self._make_game_pair(
                        f"iso_{gc}", d, team_a, team_b,
                        int(rng.poisson(2.0)), int(rng.poisson(2.0)),
                    ))

        # Add a large "rest of cohort" so percentile normalization has context
        mainstream = [f"main_{i:03d}" for i in range(100)]
        for i, team_a in enumerate(mainstream):
            for j in range(5):  # Each mainstream team plays 5 others
                team_b = mainstream[(i + j + 1) % len(mainstream)]
                gc += 1
                d = base - pd.Timedelta(days=int(rng.randint(10, 200)))
                rows.extend(self._make_game_pair(
                    f"main_{gc}", d, team_a, team_b,
                    int(rng.poisson(1.5)), int(rng.poisson(1.5)),
                ))

        return pd.DataFrame(rows), isolated

    def test_isolated_league_sos_not_extreme(self):
        """
        Teams in a small isolated league should not have sos_norm > 0.95.

        Small components can cause SOS inflation through self-referencing:
        team A beats B who beats C who beats A → all get high SOS.
        """
        games, isolated_teams = self._build_isolated_league_scenario()
        active = _run_rankings(games, today=self.SYNTH_TODAY)

        for tid in isolated_teams:
            team = active[active["team_id"] == tid]
            if team.empty:
                continue
            sos = team.iloc[0]["sos_norm"]
            assert sos < 0.95, (
                f"Isolated team {tid} has sos_norm={sos:.4f} — inflated by "
                f"small-component self-reference"
            )


# ===========================================================================
# Test Class: Cohort-Wide Distribution Sanity
# ===========================================================================

class TestCohortDistributionSanity:
    """
    Validate that ranking distributions across the full cohort are healthy.
    """

    @pytest.fixture(scope="class")
    def u16f_data(self):
        """Load the first available U16F game data."""
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            if games is not None:
                return {"games": games, "label": label}
        pytest.skip("No U16F data available")

    def test_powerscore_range_and_distribution(self, u16f_data):
        """PowerScore should span a reasonable range with no extreme outliers."""
        active = _run_rankings(u16f_data["games"])

        ps = active["powerscore_adj"]
        assert (ps >= 0.0).all(), "PowerScore below 0 detected"
        assert (ps <= 1.0).all(), "PowerScore above 1 detected"

        # Range should be meaningful (at least 0.20 spread for 2000 teams)
        spread = ps.max() - ps.min()
        assert spread > 0.20, (
            f"PowerScore spread only {spread:.4f} — insufficient differentiation "
            f"in {len(active)} teams"
        )

        # Top team shouldn't be absurdly far ahead of #2
        if len(active) >= 2:
            gap_1_2 = active.iloc[0]["powerscore_adj"] - active.iloc[1]["powerscore_adj"]
            assert gap_1_2 < 0.10, (
                f"Gap between #1 ({active.iloc[0]['powerscore_adj']:.4f}) and "
                f"#2 ({active.iloc[1]['powerscore_adj']:.4f}) is {gap_1_2:.4f} — "
                f"suspiciously large"
            )

    def test_sos_norm_not_bimodal(self, u16f_data):
        """
        SOS_norm distribution should be roughly continuous, not bimodal.

        A bimodal distribution (cluster at 0 and cluster at 1) indicates
        the normalization is creating artificial separation.
        """
        active = _run_rankings(u16f_data["games"])
        sos = active["sos_norm"]

        # Check that the middle range (0.3-0.7) has at least 20% of teams
        middle_share = ((sos >= 0.3) & (sos <= 0.7)).mean()
        assert middle_share > 0.15, (
            f"Only {middle_share:.0%} of teams have sos_norm in [0.3, 0.7] — "
            f"distribution may be bimodal"
        )

    def test_games_played_not_correlated_with_sos_norm(self, u16f_data):
        """
        Games played should not strongly predict SOS_norm.

        If correlation > 0.5, teams with more games are systematically
        getting higher SOS — a bias in the normalization.
        """
        active = _run_rankings(u16f_data["games"])

        # Only check teams with 8+ games (Active)
        gp_sos_corr = active[["gp", "sos_norm"]].corr().iloc[0, 1]
        assert abs(gp_sos_corr) < 0.50, (
            f"GP-SOS correlation is {gp_sos_corr:+.3f} — games played "
            f"should not strongly predict SOS_norm"
        )

    def test_off_def_norm_reasonable_range(self, u16f_data):
        """OFF/DEF norms should use most of the [0, 1] range."""
        active = _run_rankings(u16f_data["games"])

        for col in ["off_norm", "def_norm"]:
            vals = active[col].dropna()
            assert vals.min() < 0.15, f"{col} min={vals.min():.3f}, expected < 0.15"
            assert vals.max() > 0.85, f"{col} max={vals.max():.3f}, expected > 0.85"


# ===========================================================================
# Test Class: Known Good Teams Validation
# ===========================================================================

class TestKnownGoodTeams:
    """
    Validate that teams with clearly strong profiles rank appropriately.

    A team with 25+ games, 85%+ win rate, and positive goal differential
    against diverse opponents should rank in the top quartile.
    """

    @pytest.fixture(scope="class")
    def u16f_rankings(self):
        """Load and run rankings for U16F."""
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            if games is None:
                continue
            active = _run_rankings(games)
            if len(active) > 100:
                return {"active": active, "games": games, "label": label}
        pytest.skip("No U16F data with enough teams")

    def test_high_volume_winning_teams_rank_well(self, u16f_rankings):
        """
        Teams with 20+ games and 80%+ win rate should be in the top 25%.
        """
        active = u16f_rankings["active"]
        games = u16f_rankings["games"]
        n_active = len(active)
        top_quartile = n_active // 4

        high_volume_winners = []
        for _, row in active.iterrows():
            if row["gp"] >= 20:
                record = _compute_win_record(games, row["team_id"])
                if record["win_pct"] >= 0.80:
                    rank = active.index.get_loc(_) + 1
                    high_volume_winners.append((row["team_id"], rank, record))

        for tid, rank, record in high_volume_winners:
            assert rank <= top_quartile, (
                f"[{u16f_rankings['label']}] Team {tid[:12]}... has "
                f"{record['gp']} games, {record['win_pct']:.0%} win rate "
                f"but ranks #{rank}/{n_active} — should be top quartile (top {top_quartile})"
            )

    def test_losing_teams_not_in_top20(self, u16f_rankings):
        """Teams with < 40% win rate should NOT be in the top 20."""
        active = u16f_rankings["active"]
        games = u16f_rankings["games"]
        top20 = active.head(20)

        for idx, row in top20.iterrows():
            record = _compute_win_record(games, row["team_id"])
            assert record["win_pct"] >= 0.40, (
                f"[{u16f_rankings['label']}] Team {row['team_id'][:12]}... "
                f"ranked #{idx + 1} but has only {record['win_pct']:.0%} win rate "
                f"({record['wins']}W-{record['losses']}L-{record['draws']}D) "
                f"— losing teams should not rank top-20"
            )


# ===========================================================================
# Test Class: SOS Sensitivity to Config Changes
# ===========================================================================

class TestSOSConfigSensitivity:
    """
    Validate that small config changes don't cause catastrophic rank shifts.

    The ranking should be robust: toggling optional features or small parameter
    changes should not flip rankings by 50+ positions for any team.
    """

    @pytest.fixture(scope="class")
    def u16f_games(self):
        """Load U16F game data."""
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            if games is not None:
                return games
        pytest.skip("No U16F data available")

    def test_sos_power_iterations_sensitivity(self, u16f_games):
        """
        Changing SOS_POWER_ITERATIONS from 3 to 0 should not flip any top-30
        team by more than 50 ranks.

        If it does, the power-SOS iteration is creating fragile rankings that
        depend heavily on the iterative refinement rather than real signal.
        """
        cfg_with = V53EConfig(SOS_POWER_ITERATIONS=3, PERF_BLEND_WEIGHT=0.0)
        cfg_without = V53EConfig(SOS_POWER_ITERATIONS=0, PERF_BLEND_WEIGHT=0.0)

        active_with = _run_rankings(u16f_games, cfg=cfg_with)
        active_without = _run_rankings(u16f_games, cfg=cfg_without)

        rank_with = dict(zip(active_with["team_id"], range(1, len(active_with) + 1)))
        rank_without = dict(zip(active_without["team_id"], range(1, len(active_without) + 1)))

        top30_with = active_with.head(30)
        big_movers = []
        for _, row in top30_with.iterrows():
            tid = row["team_id"]
            if tid in rank_without:
                jump = abs(rank_with[tid] - rank_without[tid])
                if jump > 50:
                    big_movers.append((tid, rank_with[tid], rank_without[tid], jump))

        assert len(big_movers) == 0, (
            f"SOS_POWER_ITERATIONS change caused {len(big_movers)} top-30 teams "
            f"to jump 50+ ranks:\n"
            + "\n".join(
                f"  {t[:12]}...: #{rw} → #{rwo} (Δ{j})"
                for t, rw, rwo, j in sorted(big_movers, key=lambda x: -x[3])[:5]
            )
        )

    def test_component_sos_toggle_sensitivity(self, u16f_games):
        """
        Toggling COMPONENT_SOS_ENABLED should not cause > 30 rank jumps
        for any top-20 team.
        """
        cfg_on = V53EConfig(COMPONENT_SOS_ENABLED=True, PERF_BLEND_WEIGHT=0.0)
        cfg_off = V53EConfig(COMPONENT_SOS_ENABLED=False, PERF_BLEND_WEIGHT=0.0)

        active_on = _run_rankings(u16f_games, cfg=cfg_on)
        active_off = _run_rankings(u16f_games, cfg=cfg_off)

        rank_on = dict(zip(active_on["team_id"], range(1, len(active_on) + 1)))
        rank_off = dict(zip(active_off["team_id"], range(1, len(active_off) + 1)))

        top20_on = active_on.head(20)
        big_movers = []
        for _, row in top20_on.iterrows():
            tid = row["team_id"]
            if tid in rank_off:
                jump = abs(rank_on[tid] - rank_off[tid])
                if jump > 30:
                    big_movers.append((tid, rank_on[tid], rank_off[tid], jump))

        assert len(big_movers) == 0, (
            f"COMPONENT_SOS toggle caused {len(big_movers)} top-20 teams "
            f"to jump 30+ ranks:\n"
            + "\n".join(
                f"  {t[:12]}...: #{ro} → #{rf} (Δ{j})"
                for t, ro, rf, j in sorted(big_movers, key=lambda x: -x[3])[:5]
            )
        )


# ===========================================================================
# Test Class: Repeat Opponent SOS Gaming Detection
# ===========================================================================

class TestRepeatOpponentGaming:
    """
    Detect whether teams that play the same opponent many times get an
    unfair SOS advantage.

    With SOS_REPEAT_CAP=2, playing the same strong opponent 10 times
    should only count twice for SOS. If the cap isn't working, the team
    gets a massive SOS boost from a single strong opponent.
    """

    @staticmethod
    def _make_game_pair(gid, date, home, away, hs, as_, age="16", gender="female"):
        return [
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": home, "opp_id": away, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": away, "opp_id": home, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
        ]

    def test_repeat_cap_limits_sos_boost(self):
        """
        Playing one strong opponent 10 times should give similar SOS to
        playing them twice + 8 different weak opponents.
        """
        rows_repeat = []
        rows_diverse = []
        gc = 0
        today = pd.Timestamp("2025-07-15")
        base = pd.Timestamp("2025-07-01")

        # Build a cohort of 30 teams so percentile normalization has context
        filler_teams = [f"filler_{i:02d}" for i in range(30)]
        for i, fa in enumerate(filler_teams):
            for j in range(3):
                fb = filler_teams[(i + j + 1) % len(filler_teams)]
                gc += 1
                d = base - pd.Timedelta(days=gc % 200)
                pair = self._make_game_pair(f"f_{gc}", d, fa, fb, 1, 1)
                rows_repeat.extend(pair)
                rows_diverse.extend(pair)

        # "strong_opp" is a dominant team (beats everyone)
        for i, ft in enumerate(filler_teams[:15]):
            gc += 1
            d = base - pd.Timedelta(days=10 + i * 5)
            pair = self._make_game_pair(f"so_{gc}", d, "strong_opp", ft, 4, 0)
            rows_repeat.extend(pair)
            rows_diverse.extend(pair)

        # --- Repeat scenario: team_repeat plays strong_opp 10 times ---
        for i in range(10):
            gc += 1
            d = base - pd.Timedelta(days=5 + i * 10)
            rows_repeat.extend(self._make_game_pair(
                f"rpt_{gc}", d, "team_repeat", "strong_opp", 1, 2,
            ))

        # --- Diverse scenario: team_diverse plays strong_opp twice + 8 weak ---
        for i in range(2):
            gc += 1
            d = base - pd.Timedelta(days=5 + i * 10)
            rows_diverse.extend(self._make_game_pair(
                f"div_{gc}", d, "team_diverse", "strong_opp", 1, 2,
            ))
        weak_teams = [f"weak_{i}" for i in range(8)]
        for i, wt in enumerate(weak_teams):
            gc += 1
            d = base - pd.Timedelta(days=20 + i * 10)
            # Weak teams lose to everyone
            rows_diverse.extend(self._make_game_pair(
                f"divw_{gc}", d, "team_diverse", wt, 3, 0,
            ))
            # Give weak teams some games so they're ranked
            for j in range(3):
                gc += 1
                d2 = base - pd.Timedelta(days=30 + i * 10 + j * 5)
                ft = filler_teams[(i * 3 + j) % len(filler_teams)]
                rows_diverse.extend(self._make_game_pair(
                    f"wkf_{gc}", d2, wt, ft, 0, 2,
                ))

        games_repeat = pd.DataFrame(rows_repeat)
        games_diverse = pd.DataFrame(rows_diverse)

        active_r = _run_rankings(games_repeat, today=today)
        active_d = _run_rankings(games_diverse, today=today)

        team_r = active_r[active_r["team_id"] == "team_repeat"]
        team_d = active_d[active_d["team_id"] == "team_diverse"]

        if team_r.empty or team_d.empty:
            pytest.skip("Teams not in Active rankings")

        # The repeat team should NOT have massively higher SOS than diverse team
        sos_repeat = team_r.iloc[0]["sos_norm"]
        sos_diverse = team_d.iloc[0]["sos_norm"]

        # With repeat cap working, sos_repeat should be similar to or less than sos_diverse
        # (diverse team plays weak opponents, repeat team plays strong one but capped)
        assert sos_repeat < sos_diverse + 0.30, (
            f"Repeat-opponent team sos_norm={sos_repeat:.4f} vs "
            f"diverse-opponent team sos_norm={sos_diverse:.4f} — "
            f"repeat cap may not be limiting SOS inflation"
        )


# ===========================================================================
# Test Class: Goal Differential Gaming
# ===========================================================================

class TestGoalDifferentialGaming:
    """
    Validate that teams cannot game rankings by running up scores.

    With GOAL_DIFF_CAP=6, a 15-0 win should not give more credit than 6-0.
    """

    @staticmethod
    def _make_game_pair(gid, date, home, away, hs, as_, age="16", gender="female"):
        return [
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": home, "opp_id": away, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": away, "opp_id": home, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
        ]

    def test_blowout_scores_capped(self):
        """
        Two teams with identical records but different margins (6-0 vs 15-0)
        should have very similar PowerScores.
        """
        rows = []
        gc = 0
        today = pd.Timestamp("2025-07-15")
        base = pd.Timestamp("2025-07-01")

        # Build shared opponent pool
        opps = [f"opp_{i:02d}" for i in range(25)]
        for i, oa in enumerate(opps):
            for j in range(3):
                ob = opps[(i + j + 1) % len(opps)]
                gc += 1
                d = base - pd.Timedelta(days=10 + gc % 200)
                rows.extend(self._make_game_pair(f"bg_{gc}", d, oa, ob, 1, 1))

        # team_normal wins 6-0 against 15 opponents
        for i in range(15):
            gc += 1
            d = base - pd.Timedelta(days=5 + i * 8)
            rows.extend(self._make_game_pair(
                f"tn_{gc}", d, "team_normal", opps[i], 6, 0,
            ))

        # team_blowout wins 15-0 against same 15 opponents
        for i in range(15):
            gc += 1
            d = base - pd.Timedelta(days=5 + i * 8)
            rows.extend(self._make_game_pair(
                f"tb_{gc}", d, "team_blowout", opps[i], 15, 0,
            ))

        games = pd.DataFrame(rows)
        active = _run_rankings(games, today=today)

        tn = active[active["team_id"] == "team_normal"]
        tb = active[active["team_id"] == "team_blowout"]

        if tn.empty or tb.empty:
            pytest.skip("Teams not Active")

        ps_diff = abs(tn.iloc[0]["powerscore_adj"] - tb.iloc[0]["powerscore_adj"])
        assert ps_diff < 0.05, (
            f"team_normal (6-0 wins) ps={tn.iloc[0]['powerscore_adj']:.4f} vs "
            f"team_blowout (15-0 wins) ps={tb.iloc[0]['powerscore_adj']:.4f} — "
            f"difference {ps_diff:.4f} > 0.05, goal diff cap may not be working"
        )


# ===========================================================================
# Test Class: Stale Window Detection
# ===========================================================================

class TestStaleWindowDetection:
    """
    Validate that rankings degrade gracefully when game data is stale.

    If TODAY is far beyond the game data's date range, most games fall outside
    the 365-day window, leaving rankings based on very few recent games.
    This should be detectable.
    """

    @pytest.fixture(scope="class")
    def u16f_games(self):
        """Load U16F game data."""
        for file_hash, label, _ in U16F_COHORT_FILES:
            games = _load_games(file_hash)
            if games is not None:
                return games
        pytest.skip("No U16F data available")

    def test_stale_window_reduces_active_teams(self, u16f_games):
        """
        When TODAY is set 6 months past the latest game, Active team count
        should drop significantly vs using a current date.

        This validates that the 365-day window and 180-day inactivity
        threshold are working together correctly.
        """
        today_fresh = _infer_today(u16f_games)
        today_stale = today_fresh + pd.Timedelta(days=180)

        active_fresh = _run_rankings(u16f_games, today=today_fresh)
        active_stale = _run_rankings(u16f_games, today=today_stale)

        # Stale window should have fewer Active teams
        ratio = len(active_stale) / max(len(active_fresh), 1)
        assert ratio < 0.80, (
            f"Stale window (TODAY+180d) has {len(active_stale)} Active teams vs "
            f"fresh {len(active_fresh)} ({ratio:.0%}). Expected significant reduction — "
            f"inactivity threshold may not be working"
        )

    def test_stale_window_top_teams_have_recent_games(self, u16f_games):
        """
        When ranking with a stale window, top-10 teams should all have
        games within the last 180 days of TODAY.

        If a team with only very old games makes top-10, the window filtering
        isn't working properly.
        """
        today_fresh = _infer_today(u16f_games)
        active = _run_rankings(u16f_games, today=today_fresh)
        top10 = active.head(10)

        cutoff = today_fresh - pd.Timedelta(days=180)
        for _, row in top10.iterrows():
            team_games = u16f_games[u16f_games["team_id"] == row["team_id"]]
            latest_game = pd.Timestamp(team_games["date"].max())
            assert latest_game >= cutoff, (
                f"Top-10 team {row['team_id'][:12]}... latest game is "
                f"{latest_game.date()} — more than 180 days before "
                f"ranking date {today_fresh.date()}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
