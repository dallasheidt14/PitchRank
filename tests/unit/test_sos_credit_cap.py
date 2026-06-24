"""Invariants of apply_sos_credit_cap (the record-gated SOS-credit cap).

The cap is a pure within-cohort transform on powerscore_core. These pin its load-bearing
properties without a DB: it is one-sided (never raises a score), it leaves record-justified
teams untouched, it relaxes for thin-sample teams, and it snapshots the pre-cap score into
power_presos for a pre/post audit.
"""

import pandas as pd

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import apply_sos_credit_cap


def _cfg():
    cfg = GlickoConfig()
    cfg.SOS_CREDIT_MAX = 0.15
    cfg.SOS_CREDIT_RECORD_WIN_WEIGHT = 0.6
    cfg.SOS_CREDIT_RECORD_GD_WEIGHT = 0.4
    cfg.SOS_CREDIT_MIN_GAMES_FULL = 12
    return cfg


def _cohort():
    # Two strong-record teams (modest published score) and two SOS-inflated teams
    # (mediocre record, top published score) that differ only in sample size.
    return pd.DataFrame(
        [
            {"team_id": "strong1", "wins": 11, "games_played": 12, "goals_for": 36, "goals_against": 12,
             "powerscore_core": 0.72},
            {"team_id": "strong2", "wins": 10, "games_played": 12, "goals_for": 30, "goals_against": 12,
             "powerscore_core": 0.68},
            {"team_id": "inflate_full", "wins": 6, "games_played": 12, "goals_for": 18, "goals_against": 18,
             "powerscore_core": 0.95},
            {"team_id": "inflate_low", "wins": 2, "games_played": 4, "goals_for": 6, "goals_against": 6,
             "powerscore_core": 0.95},
        ]
    )


def test_cap_is_one_sided_and_snapshots_pre_cap():
    df = _cohort()
    out = apply_sos_credit_cap(df, _cfg())
    # Never raises a score.
    assert (out["powerscore_core"] <= df["powerscore_core"] + 1e-9).all()
    # power_presos preserves the pre-cap value for every team.
    assert (out["power_presos"].to_numpy() == df["powerscore_core"].to_numpy()).all()


def test_strong_record_teams_are_uncapped():
    df = _cohort()
    out = apply_sos_credit_cap(df, _cfg()).set_index("team_id")
    base = df.set_index("team_id")
    for tid in ("strong1", "strong2"):
        assert out.loc[tid, "powerscore_core"] == base.loc[tid, "powerscore_core"]


def test_inflated_team_is_pulled_down():
    df = _cohort()
    out = apply_sos_credit_cap(df, _cfg()).set_index("team_id")
    assert out.loc["inflate_full", "powerscore_core"] < 0.95


def test_low_sample_team_is_less_capped():
    df = _cohort()
    out = apply_sos_credit_cap(df, _cfg()).set_index("team_id")
    # Identical record rates, but the 4-game team keeps more of its score than the
    # 12-game team (the cap ramps in with sample size — thin-sample teams aren't whipsawed).
    assert out.loc["inflate_low", "powerscore_core"] > out.loc["inflate_full", "powerscore_core"]
