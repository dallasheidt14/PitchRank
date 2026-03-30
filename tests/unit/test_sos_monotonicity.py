"""Tests for SOS monotonicity fixes.

Fix A: COMPONENT_SOS_ENABLED = False eliminates pathological ceiling ties.
Fix B: MIN_GAMES_FOR_TOP_SOS = 6 aligns SOS trust with Active eligibility.
"""

import pytest
import pandas as pd
import numpy as np

from src.etl.v53e import V53EConfig, compute_rankings


def _make_game(gid, date, home, away, hs, as_, age="15", gender="male",
               opp_age=None, opp_gender=None):
    """Create home + away perspective rows for a single game."""
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    return [
        {
            "game_id": str(gid), "date": pd.Timestamp(date),
            "team_id": home, "opp_id": away,
            "age": age, "gender": gender,
            "opp_age": opp_age, "opp_gender": opp_gender,
            "gf": hs, "ga": as_,
        },
        {
            "game_id": str(gid), "date": pd.Timestamp(date),
            "team_id": away, "opp_id": home,
            "age": opp_age, "gender": opp_gender,
            "opp_age": age, "opp_gender": gender,
            "gf": as_, "ga": hs,
        },
    ]


def _build_multi_component_league():
    """Build a league with TWO disconnected components to expose ceiling ties.

    Component A: 10 teams in a round-robin (each plays 9 games).
      team_A0 dominates (5-0 every game), team_A1 is strong (3-1), rest average.

    Component B: 4 teams in a round-robin (each plays 3 games).
      team_B0 dominates (4-0 every game), rest lose.

    The components share no opponents — they are disconnected subgraphs.
    With COMPONENT_SOS_ENABLED=True, the top team in each component
    gets sos_norm_component=1.0, creating ceiling ties.
    With COMPONENT_SOS_ENABLED=False, all 14 teams are normalized in
    one pool, and the top of Component B gets a lower sos_norm
    (because its opponents are weaker globally).
    """
    today = pd.Timestamp("2026-03-01")
    rows = []
    gid = 0

    # Component A: 10 teams, round-robin
    comp_a = [f"team_A{i}" for i in range(10)]
    for i, home in enumerate(comp_a):
        for away in comp_a[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            if home == "team_A0":
                hs, as_ = 5, 0
            elif away == "team_A0":
                hs, as_ = 0, 5
            elif home == "team_A1":
                hs, as_ = 3, 1
            elif away == "team_A1":
                hs, as_ = 1, 3
            else:
                hs, as_ = 2, 1
            rows.extend(_make_game(gid, date, home, away, hs, as_))

    # Component B: 4 teams, round-robin (completely disconnected from A)
    comp_b = [f"team_B{i}" for i in range(4)]
    for i, home in enumerate(comp_b):
        for away in comp_b[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            if home == "team_B0":
                hs, as_ = 4, 0
            elif away == "team_B0":
                hs, as_ = 0, 4
            else:
                hs, as_ = 1, 1
            rows.extend(_make_game(gid, date, home, away, hs, as_))

    return pd.DataFrame(rows)


class TestFixA_ComponentNormalization:
    """Fix A: disabling component normalization eliminates ceiling ties.

    Terminology:
      "ceiling tie" — multiple teams from different disconnected components both
      receive elevated sos_norm values because each component is normalized to [0, 1]
      independently. The top team in each component hits its component ceiling even
      when one component has globally stronger opponents than the other.

    Observable pathology:
      Component A (10 teams, avg-quality opponents) → team_A9 hits component ceiling.
      Component B (4 teams, same-age avg opponents) → team_B0 hits component B ceiling.
      Both get inflated sos_norm relative to global quality, creating cross-component
      rank ties that do not reflect actual schedule strength.

    With COMPONENT_SOS_ENABLED=False: all teams are normalized in one global pool.
      Component A's top team gets sos_norm based on its place among all 14 teams,
      so its value is lower (no artificial component ceiling boost).
    """

    def test_component_enabled_inflates_component_top_teams(self):
        """With COMPONENT_SOS_ENABLED=True, the top team in Component A (team_A9)
        gets an inflated sos_norm relative to global-only normalization, because
        the component normalization boosts it to the per-component ceiling.

        team_A9 has raw SOS ~0.682, which ranks 4th globally (behind team_B1/B2/B3
        at ~0.712). Yet with component normalization, team_A9 gets the highest
        sos_norm in the cohort because it hits Component A's ceiling — a pathological
        ceiling tie driven by component isolation, not actual schedule quality.
        """
        cfg_enabled = V53EConfig()
        cfg_enabled.COMPONENT_SOS_ENABLED = True
        cfg_disabled = V53EConfig()
        cfg_disabled.COMPONENT_SOS_ENABLED = False

        games = _build_multi_component_league()
        res_enabled = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg_enabled)
        res_disabled = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg_disabled)

        teams_enabled = res_enabled["teams"].set_index("team_id")
        teams_disabled = res_disabled["teams"].set_index("team_id")

        # With component normalization, team_A9 is boosted to the Component A
        # ceiling (sos_norm ~0.86), well above the global-only value (~0.78).
        a9_with_component = teams_enabled.loc["team_A9", "sos_norm"]
        a9_without_component = teams_disabled.loc["team_A9", "sos_norm"]
        assert a9_with_component > a9_without_component, (
            f"team_A9: expected component sos_norm ({a9_with_component:.4f}) "
            f"> global-only sos_norm ({a9_without_component:.4f}), "
            f"indicating the component ceiling inflation is present"
        )

        # The inflation should be substantial (>= 0.05 difference)
        inflation = a9_with_component - a9_without_component
        assert inflation >= 0.05, (
            f"team_A9 component inflation too small: {inflation:.4f} (expected >= 0.05). "
            f"Component sos_norm={a9_with_component:.4f}, global={a9_without_component:.4f}"
        )

    def test_component_disabled_reduces_ceiling_inflation(self):
        """With COMPONENT_SOS_ENABLED=False (new default), the sos_norm of Component
        A's top team (team_A9) is pulled down toward its true global rank. Teams in
        Component B that have higher raw SOS are no longer penalized by being in a
        different normalization pool."""
        cfg_enabled = V53EConfig()
        cfg_enabled.COMPONENT_SOS_ENABLED = True
        cfg_disabled = V53EConfig()
        cfg_disabled.COMPONENT_SOS_ENABLED = False

        games = _build_multi_component_league()
        res_enabled = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg_enabled)
        res_disabled = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg_disabled)

        teams_enabled = res_enabled["teams"].set_index("team_id")
        teams_disabled = res_disabled["teams"].set_index("team_id")

        # With component disabled, the sos_norm gap between team_A9 (comp-A ceiling)
        # and team_B1/B2/B3 (globally higher SOS but comp-B mid-tier) should be
        # smaller than with component enabled. This reflects reduced ceiling inflation.
        a9_enabled = teams_enabled.loc["team_A9", "sos_norm"]
        b1_enabled = teams_enabled.loc["team_B1", "sos_norm"]
        gap_enabled = a9_enabled - b1_enabled

        a9_disabled = teams_disabled.loc["team_A9", "sos_norm"]
        b1_disabled = teams_disabled.loc["team_B1", "sos_norm"]
        gap_disabled = a9_disabled - b1_disabled

        assert gap_disabled < gap_enabled, (
            f"Expected smaller A9-B1 sos_norm gap without component normalization. "
            f"Gap with component={gap_enabled:.4f}, gap without={gap_disabled:.4f}"
        )

    def test_default_config_has_component_disabled(self):
        """The new default for COMPONENT_SOS_ENABLED should be False."""
        cfg = V53EConfig()
        assert cfg.COMPONENT_SOS_ENABLED is False, (
            f"Expected COMPONENT_SOS_ENABLED=False as new default, got {cfg.COMPONENT_SOS_ENABLED}"
        )


def _build_varied_gp_league():
    """Build a league where teams have varied games played (3 to 12).

    All test teams win 3-1 against the same single opponent (``anchor``), so
    their raw SOS is identical by construction — the only variable is GP count.
    The ``anchor`` team plays enough intra-pool games to establish a stable
    strength estimate.  Because every test team faces the exact same opponent,
    any sos_norm spread among 6+-GP teams is caused solely by shrinkage, not by
    opponent selection.
    """
    today = pd.Timestamp("2026-03-01")
    rows = []
    gid = 0

    # Establish the anchor's strength via a round-robin with 11 filler teams.
    # anchor wins ~half to produce a mid-tier SOS anchor.
    anchor = "anchor"
    fillers = [f"filler_{i}" for i in range(11)]
    all_pool = [anchor] + fillers
    for i, home in enumerate(all_pool):
        for away in all_pool[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game(gid, date, home, away, 2, 1))

    # Teams with varied GP, all beating anchor 3-1.
    # Same single opponent => identical raw SOS; only shrinkage differs.
    for gp_count in range(3, 13):
        team_name = f"team_{gp_count}gp"
        for _ in range(gp_count):
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game(gid, date, team_name, anchor, 3, 1))

    return pd.DataFrame(rows)


class TestFixB_ShrinkageThreshold:
    """Fix B: MIN_GAMES_FOR_TOP_SOS = 6 aligns with Active eligibility."""

    def test_default_threshold_is_6(self):
        """New default MIN_GAMES_FOR_TOP_SOS should be 6."""
        cfg = V53EConfig()
        assert cfg.MIN_GAMES_FOR_TOP_SOS == 6, (
            f"Expected MIN_GAMES_FOR_TOP_SOS=6, got {cfg.MIN_GAMES_FOR_TOP_SOS}"
        )

    def test_6gp_team_not_shrunk(self):
        """A team with exactly 6 GP should have no SOS shrinkage applied
        (sample_flag should be 'OK', not 'LOW_SAMPLE')."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        cfg.GP_SOS_DECORRELATION_ENABLED = False  # isolate shrinkage effect
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_6 = teams[teams["team_id"] == "team_6gp"]
        assert len(team_6) == 1, "team_6gp not found in results"
        assert team_6.iloc[0]["sample_flag"] == "OK", (
            f"team_6gp should have sample_flag='OK' with threshold=6, "
            f"got '{team_6.iloc[0]['sample_flag']}'"
        )

    def test_5gp_team_still_shrunk(self):
        """A team with 5 GP should still be shrunk (below the threshold)."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        cfg.GP_SOS_DECORRELATION_ENABLED = False  # isolate shrinkage effect
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_5 = teams[teams["team_id"] == "team_5gp"]
        assert len(team_5) == 1, "team_5gp not found in results"
        assert team_5.iloc[0]["sample_flag"] == "LOW_SAMPLE", (
            f"team_5gp should have sample_flag='LOW_SAMPLE' with threshold=6, "
            f"got '{team_5.iloc[0]['sample_flag']}'"
        )

    def test_6gp_to_12gp_sos_ordering_preserved(self):
        """Among teams with 6+ GP playing the same opponents and winning 3-1,
        sos_norm should be roughly similar (no large inversions from shrinkage).
        The max spread among these teams should be < 0.10."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        cfg.GP_SOS_DECORRELATION_ENABLED = False  # isolate shrinkage effect
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        # Get teams with 6+ GP
        ok_teams = teams[
            teams["team_id"].str.match(r"team_\d+gp")
            & (teams["gp"] >= 6)
        ].sort_values("gp")

        assert len(ok_teams) >= 5, f"Expected at least 5 OK teams, got {len(ok_teams)}"

        sos_spread = ok_teams["sos_norm"].max() - ok_teams["sos_norm"].min()
        assert sos_spread < 0.10, (
            f"SOS spread among 6+ GP teams playing same opponents should be < 0.10, "
            f"got {sos_spread:.4f}. Values:\n"
            f"{ok_teams[['team_id', 'gp', 'sos_norm', 'sample_flag']].to_string()}"
        )

    def test_old_threshold_creates_inversions(self):
        """With the old threshold of 10, teams with 6-9 GP should be noticeably
        shrunk compared to teams with 10+ GP, even when playing the same opponents.
        This confirms the old behavior creates the cliff we're fixing."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 10
        cfg.COMPONENT_SOS_ENABLED = False
        cfg.GP_SOS_DECORRELATION_ENABLED = False  # isolate shrinkage effect
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_6 = teams[teams["team_id"] == "team_6gp"].iloc[0]
        team_12 = teams[teams["team_id"] == "team_12gp"].iloc[0]

        # With threshold=10, team_6gp should be significantly shrunk vs team_12gp
        gap = team_12["sos_norm"] - team_6["sos_norm"]
        assert gap > 0.05, (
            f"With old threshold=10, expected significant gap between 6gp and 12gp teams. "
            f"6gp={team_6['sos_norm']:.4f}, 12gp={team_12['sos_norm']:.4f}, gap={gap:.4f}"
        )
