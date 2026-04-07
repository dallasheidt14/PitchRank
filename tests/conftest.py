"""Shared test helpers auto-discovered by pytest."""

from __future__ import annotations

import pandas as pd


def make_game_pair(
    gid,
    date,
    home,
    away,
    hs,
    as_,
    age="14",
    gender="male",
    opp_age=None,
    opp_gender=None,
):
    """Create home + away perspective rows for a single game.

    Returns a list of two dicts (one per perspective) suitable for building
    a games DataFrame via ``pd.DataFrame(rows)``.
    """
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
