"""Tests for cross-age opponent adjustment in v53e Layer 9."""

import pytest
import pandas as pd
import numpy as np

from src.etl.v53e import V53EConfig, compute_rankings


def _make_game_pair(gid, date, home, away, hs, as_, age="12", gender="male",
                    opp_age=None, opp_gender=None):
    """Create home + away perspective rows for a single game."""
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    return [
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": opp_age,
            "opp_gender": opp_gender,
            "gf": hs,
            "ga": as_,
        },
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": opp_age,
            "gender": opp_gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": as_,
            "ga": hs,
        },
    ]


def _build_same_age_league(today=None):
    """Build a league where all teams are the same age group (U12M).

    8 teams, each playing 8 games. One dominant team (team_A) that
    wins all games with high GF. Used as baseline to confirm same-age
    adjustment is unchanged.
    """
    if today is None:
        today = pd.Timestamp("2026-03-01")

    teams = [f"team_{chr(65 + i)}" for i in range(8)]  # team_A through team_H
    rows = []
    gid = 0

    # Round-robin: each team plays each other once
    for i, home in enumerate(teams):
        for away in teams[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            # team_A dominates (5-0), others are average (2-1 or 1-2)
            if home == "team_A":
                hs, as_ = 5, 0
            elif away == "team_A":
                hs, as_ = 0, 5
            else:
                hs, as_ = 2, 1
            rows.extend(_make_game_pair(str(gid), date, home, away, hs, as_))

    return pd.DataFrame(rows)


class TestSameAgeBaseline:
    """Confirm same-age opponent adjustment produces expected rankings."""

    def test_dominant_team_has_highest_off_norm(self):
        """team_A scores 5 goals every game and should have the highest off_norm."""
        cfg = V53EConfig()
        games = _build_same_age_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_a = teams[teams["team_id"] == "team_A"].iloc[0]
        other_off_norms = teams[teams["team_id"] != "team_A"]["off_norm"]

        assert team_a["off_norm"] > other_off_norms.max(), (
            f"team_A off_norm ({team_a['off_norm']:.3f}) should be highest, "
            f"but max other is {other_off_norms.max():.3f}"
        )


def _build_cross_age_league(today=None):
    """Build a league with cross-age matchups to expose the bias.

    Two strong U12 teams:
    - team_same: plays 8 games vs U12 opponents, scores 4 GF per game
    - team_cross: plays 8 games vs U13 (scores 2 GF) — 100% cross-age schedule

    Both teams are equally dominant against their age-appropriate competition.
    team_cross scores fewer goals because U13 opponents are harder, not because
    they are worse at offense.

    Additional U12 and U13 teams fill out the league so normalization works.
    """
    if today is None:
        today = pd.Timestamp("2026-03-01")

    rows = []
    gid = 0

    u12_fillers = [f"u12_filler_{i}" for i in range(8)]
    u13_fillers = [f"u13_filler_{i}" for i in range(8)]

    # team_same: 8 games vs U12 opponents, all 4-1 wins
    for i, opp in enumerate(u12_fillers):
        gid += 1
        date = today - pd.Timedelta(days=gid)
        rows.extend(_make_game_pair(str(gid), date, "team_same", opp, 4, 1,
                                    age="12", gender="male"))

    # team_cross: 8 games vs U13 (2-1 wins) — 100% cross-age schedule
    for i in range(8):
        gid += 1
        date = today - pd.Timedelta(days=gid)
        rows.extend(_make_game_pair(str(gid), date, "team_cross", u13_fillers[i], 2, 1,
                                    age="12", gender="male",
                                    opp_age="13", opp_gender="male"))

    # U12 fillers play each other (so they have enough games for normalization)
    for i, home in enumerate(u12_fillers):
        for away in u12_fillers[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1))

    # U13 fillers play each other (so they have strength in global_strength_map)
    for i, home in enumerate(u13_fillers):
        for away in u13_fillers[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1,
                                        age="13", gender="male"))

    return pd.DataFrame(rows)


class TestCrossAgeAdjustment:
    """Test that cross-age opponent adjustment properly credits offense."""

    def test_cross_age_team_off_norm_not_suppressed(self):
        """team_cross plays mostly U13 opponents and should NOT have dramatically
        lower off_norm than team_same, because the opponent adjustment should
        account for the age gap.

        Acceptance criterion: team_cross off_norm must be within 0.05 of
        team_same off_norm. Without the fix, the gap is typically > 0.30.
        """
        cfg = V53EConfig()
        games = _build_cross_age_league()

        # Build global_strength_map from U13 cohort (simulating Pass 2)
        # First run U13 cohort to get their strengths
        u13_games = games[
            (games["age"] == "13") & (games["gender"] == "male")
        ].copy()
        if not u13_games.empty:
            u13_result = compute_rankings(
                u13_games, today=pd.Timestamp("2026-03-01"), cfg=cfg
            )
            u13_teams = u13_result["teams"]
            global_strength_map = dict(
                zip(u13_teams["team_id"].astype(str), u13_teams["abs_strength"].astype(float))
            )
        else:
            global_strength_map = {}

        # Now run U12 cohort with global_strength_map (Pass 2 behavior)
        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()
        result = compute_rankings(
            u12_games,
            today=pd.Timestamp("2026-03-01"),
            cfg=cfg,
            global_strength_map=global_strength_map,
        )
        teams = result["teams"]

        same = teams[teams["team_id"] == "team_same"].iloc[0]
        cross = teams[teams["team_id"] == "team_cross"].iloc[0]

        gap = same["off_norm"] - cross["off_norm"]
        assert gap < 0.05, (
            f"Cross-age off_norm gap too large: team_same={same['off_norm']:.3f}, "
            f"team_cross={cross['off_norm']:.3f}, gap={gap:.3f}. "
            f"Opponent adjustment should compensate for age difficulty."
        )
