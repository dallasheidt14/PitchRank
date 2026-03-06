import pandas as pd

from src.etl.v53e import V53EConfig, compute_rankings


def _build_competitive_cluster_games():
    rows = []
    today = pd.Timestamp("2026-02-01")

    def add_game(game_id: str, date: pd.Timestamp, home: str, away: str, home_goals: int, away_goals: int):
        rows.append({
            "game_id": game_id,
            "date": date,
            "team_id": home,
            "opp_id": away,
            "age": "14",
            "gender": "male",
            "opp_age": "14",
            "opp_gender": "male",
            "gf": home_goals,
            "ga": away_goals,
        })
        rows.append({
            "game_id": game_id,
            "date": date,
            "team_id": away,
            "opp_id": home,
            "age": "14",
            "gender": "male",
            "opp_age": "14",
            "opp_gender": "male",
            "gf": away_goals,
            "ga": home_goals,
        })

    # Tight, highly-competitive mini cluster
    elite_schedule = [
        ("A", "B", 1, 0),
        ("A", "C", 2, 1),
        ("A", "D", 1, 0),
        ("B", "C", 1, 0),
        ("B", "D", 2, 1),
        ("C", "D", 1, 0),
        ("B", "A", 0, 1),
        ("C", "A", 1, 2),
        ("D", "A", 0, 1),
        ("C", "B", 0, 1),
        ("D", "B", 1, 2),
        ("D", "C", 0, 1),
    ]
    for idx, (home, away, home_goals, away_goals) in enumerate(elite_schedule, start=1):
        add_game(f"elite_{idx}", today - pd.Timedelta(days=idx), home, away, home_goals, away_goals)

    # Stat-padding team vs weak opponents
    weak_teams = ["W1", "W2", "W3", "W4", "W5", "W6"]
    for idx, weak in enumerate(weak_teams, start=1):
        add_game(f"pad_{idx}", today - pd.Timedelta(days=20 + idx), "X", weak, 8, 0)

    # Weak teams also play each other
    counter = 100
    for i, weak_a in enumerate(weak_teams):
        for weak_b in weak_teams[i + 1:]:
            counter += 1
            add_game(f"weak_{counter}", today - pd.Timedelta(days=40 + counter), weak_a, weak_b, 2, 1)

    # Bridge games show elite cluster can beat the stat-padding team in tight results
    add_game("bridge_1", today - pd.Timedelta(days=5), "A", "X", 1, 0)
    add_game("bridge_2", today - pd.Timedelta(days=6), "B", "X", 1, 0)
    add_game("bridge_3", today - pd.Timedelta(days=7), "C", "X", 2, 1)
    add_game("bridge_4", today - pd.Timedelta(days=8), "D", "X", 1, 0)

    return pd.DataFrame(rows), today


def test_competitive_cluster_uses_stronger_opponent_adjustment_signal():
    games_df, today = _build_competitive_cluster_games()

    # Legacy-like behavior: single strength map + percentile re-normalization.
    legacy_cfg = V53EConfig(
        OPPONENT_ADJUST_EXPONENT=1.0,
        OPPONENT_ADJUST_USE_COMPONENT_STRENGTH=False,
        OPPONENT_ADJUST_RENORM_MODE="percentile",
    )

    improved_cfg = V53EConfig()

    legacy = compute_rankings(games_df=games_df, today=today, cfg=legacy_cfg)["teams"].set_index("team_id")
    improved = compute_rankings(games_df=games_df, today=today, cfg=improved_cfg)["teams"].set_index("team_id")

    # Elite cluster offense should recover, while weak-opponent padding should lose credit.
    assert improved.loc["A", "off_norm"] > legacy.loc["A", "off_norm"]
    assert improved.loc["X", "off_norm"] < legacy.loc["X", "off_norm"]

    # Gap between stat-padding team and elite team should shrink.
    legacy_gap = float(legacy.loc["X", "powerscore_adj"] - legacy.loc["A", "powerscore_adj"])
    improved_gap = float(improved.loc["X", "powerscore_adj"] - improved.loc["A", "powerscore_adj"])
    assert improved_gap < legacy_gap
