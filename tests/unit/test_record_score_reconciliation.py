"""Invariants of apply_record_score_reconciliation (the down-side record reconciliation).

A pure within-cohort transform on powerscore_core that lowers only SOS-inflated teams
toward an absolute-anchored, windowed, draw-aware record level. These pin its load-bearing
properties without a DB: it is one-sided (never raises a score), it leaves record-justified
teams untouched, the record anchor is absolute (a strong record stays high regardless of the
cohort's record distribution — unlike the cohort-relative SOS-credit cap it supersedes), it
relaxes for thin-sample teams, and it snapshots the pre-reconciliation score into power_presos.
"""

import pandas as pd

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import (
    _record_expected_index,
    apply_record_score_reconciliation,
    derive_windowed_record,
)


def _cfg():
    cfg = GlickoConfig()
    cfg.RECORD_RECONCILE_WIN_WEIGHT = 0.7
    cfg.RECORD_RECONCILE_GD_WEIGHT = 0.3
    cfg.RECORD_RECONCILE_WIN_MIDPOINT = 0.5
    cfg.RECORD_RECONCILE_WIN_SCALE = 0.12
    cfg.RECORD_RECONCILE_GD_CLAMP = 3.0
    cfg.RECORD_RECONCILE_BETA = 0.8
    cfg.RECORD_RECONCILE_R0 = 0.5
    cfg.RECORD_RECONCILE_DOWNPULL_K = 0.5
    cfg.RECORD_RECONCILE_TOLERANCE_FLOOR = 0.05
    cfg.RECORD_RECONCILE_MIN_COHORT = 2
    cfg.RECORD_RECONCILE_MIN_GAMES_FULL = 12
    return cfg


def _cohort():
    # Two strong-record teams (modest published score) and two SOS-inflated teams
    # (mediocre record, top published score) that differ only in windowed sample size,
    # plus two mid teams so the cohort dispersion estimate runs on a real spread.
    return pd.DataFrame(
        [
            {"team_id": "strong1", "rec_window_wins": 17, "rec_window_draws": 1, "rec_window_games": 20,
             "rec_window_goals_for": 60, "rec_window_goals_against": 18, "powerscore_core": 0.72},
            {"team_id": "strong2", "rec_window_wins": 15, "rec_window_draws": 2, "rec_window_games": 20,
             "rec_window_goals_for": 50, "rec_window_goals_against": 20, "powerscore_core": 0.68},
            {"team_id": "mid1", "rec_window_wins": 10, "rec_window_draws": 4, "rec_window_games": 20,
             "rec_window_goals_for": 35, "rec_window_goals_against": 30, "powerscore_core": 0.55},
            {"team_id": "mid2", "rec_window_wins": 9, "rec_window_draws": 3, "rec_window_games": 20,
             "rec_window_goals_for": 32, "rec_window_goals_against": 32, "powerscore_core": 0.50},
            {"team_id": "inflate_full", "rec_window_wins": 9, "rec_window_draws": 2, "rec_window_games": 20,
             "rec_window_goals_for": 30, "rec_window_goals_against": 30, "powerscore_core": 0.95},
            {"team_id": "inflate_low", "rec_window_wins": 1, "rec_window_draws": 2, "rec_window_games": 4,
             "rec_window_goals_for": 8, "rec_window_goals_against": 8, "powerscore_core": 0.95},
        ]
    )


def test_reconciliation_is_one_sided_and_snapshots_pre_value():
    df = _cohort()
    out = apply_record_score_reconciliation(df, _cfg())
    # Never raises a score.
    assert (out["powerscore_core"] <= df["powerscore_core"] + 1e-9).all()
    # power_presos preserves the pre-reconciliation value for every team.
    assert (out["power_presos"].to_numpy() == df["powerscore_core"].to_numpy()).all()


def test_strong_record_teams_are_untouched():
    df = _cohort()
    out = apply_record_score_reconciliation(df, _cfg()).set_index("team_id")
    base = df.set_index("team_id")
    for tid in ("strong1", "strong2"):
        assert out.loc[tid, "powerscore_core"] == base.loc[tid, "powerscore_core"]


def test_inflated_team_is_pulled_down():
    df = _cohort()
    out = apply_record_score_reconciliation(df, _cfg()).set_index("team_id")
    assert out.loc["inflate_full", "powerscore_core"] < 0.95


def test_low_sample_team_is_less_pulled():
    df = _cohort()
    out = apply_record_score_reconciliation(df, _cfg()).set_index("team_id")
    # Identical record rates, but the 4-game team keeps more of its score than the
    # 20-game team (the pull ramps in with windowed sample size — thin-sample teams
    # aren't whipsawed by a noisy record estimate).
    assert out.loc["inflate_low", "powerscore_core"] > out.loc["inflate_full", "powerscore_core"]


def test_record_expected_is_absolute_anchored():
    cfg = _cfg()
    # A 90%-points, +2 gd/game team computed alone...
    solo = _record_expected_index(pd.Series([0.9]), pd.Series([2.0]), cfg).iloc[0]
    # ...and the same team embedded in a cohort of weak-record teams.
    in_weak_cohort = _record_expected_index(
        pd.Series([0.9, 0.2, 0.3, 0.25]),
        pd.Series([2.0, -1.0, -0.5, -1.5]),
        cfg,
    ).iloc[0]
    # The absolute anchor depends only on the team's own record — the surrounding
    # cohort cannot compress it (a cohort-relative z-score record would shift here).
    assert in_weak_cohort == solo
    assert solo >= 0.9


def test_strong_record_uncapped_regardless_of_peer_records():
    # The headline property at the FULL-transform level: a strong record keeps full credit even
    # in an elite cohort, because record_expected is absolute. The cohort-relative z-score cap this
    # supersedes would have compressed the strong team when its peers also had strong records.
    cfg = _cfg()

    def _target(core):
        return {"team_id": "target", "rec_window_wins": 17, "rec_window_draws": 1, "rec_window_games": 20,
                "rec_window_goals_for": 60, "rec_window_goals_against": 18, "powerscore_core": core}

    def _peer(tid, core, wins, gf, ga):
        return {"team_id": tid, "rec_window_wins": wins, "rec_window_draws": 0, "rec_window_games": 20,
                "rec_window_goals_for": gf, "rec_window_goals_against": ga, "powerscore_core": core}

    # Identical peer cores in both cohorts (so the cohort median is identical); only the peers'
    # RECORDS differ — weak in one cohort, strong in the other.
    peer_cores = [0.65, 0.55, 0.50, 0.45, 0.40]
    weak = pd.DataFrame([_target(0.70)] + [_peer(f"w{i}", c, 4, 15, 25) for i, c in enumerate(peer_cores)])
    strong = pd.DataFrame([_target(0.70)] + [_peer(f"s{i}", c, 16, 50, 15) for i, c in enumerate(peer_cores)])

    out_weak = apply_record_score_reconciliation(weak, cfg).set_index("team_id")
    out_strong = apply_record_score_reconciliation(strong, cfg).set_index("team_id")
    assert out_weak.loc["target", "powerscore_core"] == 0.70
    assert out_strong.loc["target", "powerscore_core"] == 0.70


def test_zero_windowed_games_team_is_untouched():
    # A team with a top published score but no games inside the window is left untouched: the
    # games-ramp is 0, so the record estimate (which would be near-floor) cannot pull it down.
    df = _cohort()
    extra = pd.DataFrame(
        [{"team_id": "no_window", "rec_window_wins": 0, "rec_window_draws": 0, "rec_window_games": 0,
          "rec_window_goals_for": 0, "rec_window_goals_against": 0, "powerscore_core": 0.95}]
    )
    out = apply_record_score_reconciliation(pd.concat([df, extra], ignore_index=True), _cfg()).set_index("team_id")
    assert out.loc["no_window", "powerscore_core"] == 0.95


def test_small_cohort_falls_back_to_tolerance_floor():
    # When the cohort is smaller than MIN_COHORT the dispersion estimate is unreliable, so the
    # tolerance falls back to the floor rather than a computed std — still one-sided, still pulling
    # the inflated team.
    cfg = _cfg()
    cfg.RECORD_RECONCILE_MIN_COHORT = 10  # the 6-row fixture now trips the small-cohort branch
    base = _cohort().set_index("team_id")
    out = apply_record_score_reconciliation(_cohort(), cfg).set_index("team_id")
    assert (out["powerscore_core"] <= base["powerscore_core"] + 1e-9).all()
    assert out.loc["inflate_full", "powerscore_core"] < 0.95


def test_derive_windowed_record_counts_wins_draws_within_window():
    cfg = GlickoConfig()
    today = pd.Timestamp("2026-06-24")
    games = pd.DataFrame(
        [
            {"team_id": "A", "gf": 3, "ga": 1, "date": today - pd.Timedelta(days=10)},    # win
            {"team_id": "A", "gf": 2, "ga": 2, "date": today - pd.Timedelta(days=20)},    # draw
            {"team_id": "A", "gf": 0, "ga": 1, "date": today - pd.Timedelta(days=30)},    # loss
            {"team_id": "A", "gf": 9, "ga": 0, "date": today - pd.Timedelta(days=5000)},  # outside window
            {"team_id": "B", "gf": 5, "ga": 0, "date": today - pd.Timedelta(days=10)},
        ]
    )
    out = derive_windowed_record(games, cfg, today).set_index("team_id")
    assert out.loc["A", "rec_window_games"] == 3
    assert out.loc["A", "rec_window_wins"] == 1
    assert out.loc["A", "rec_window_draws"] == 1
    assert out.loc["A", "rec_window_goals_for"] == 5
    assert out.loc["A", "rec_window_goals_against"] == 4
    assert out.loc["B", "rec_window_wins"] == 1


def test_derive_windowed_record_empty_when_all_out_of_window():
    cfg = GlickoConfig()
    today = pd.Timestamp("2026-06-24")
    games = pd.DataFrame([{"team_id": "A", "gf": 1, "ga": 0, "date": today - pd.Timedelta(days=5000)}])
    out = derive_windowed_record(games, cfg, today)
    assert out.empty
    assert "rec_window_games" in out.columns


def test_derive_windowed_record_handles_tz_aware_dates():
    cfg = GlickoConfig()
    today = pd.Timestamp("2026-06-24")
    games = pd.DataFrame([{"team_id": "A", "gf": 2, "ga": 0, "date": pd.Timestamp("2026-06-14", tz="UTC")}])
    out = derive_windowed_record(games, cfg, today).set_index("team_id")
    assert out.loc["A", "rec_window_games"] == 1
    assert out.loc["A", "rec_window_wins"] == 1
