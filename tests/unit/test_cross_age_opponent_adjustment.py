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
