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
