from scripts.predictor_python import Game, TeamRanking, calculate_common_opponent_signal, predict_match


def test_predict_match_prefers_team_with_higher_glicko_rating():
    team_a = TeamRanking(
        team_id_master="a",
        power_score_final=0.55,
        sos_norm=0.55,
        offense_norm=0.55,
        defense_norm=0.55,
        age=14,
        games_played=20,
        glicko_rating=1620,
        glicko_rd=70,
    )
    team_b = TeamRanking(
        team_id_master="b",
        power_score_final=0.56,
        sos_norm=0.55,
        offense_norm=0.55,
        defense_norm=0.55,
        age=14,
        games_played=20,
        glicko_rating=1500,
        glicko_rd=70,
    )

    prediction = predict_match(team_a, team_b, [])

    assert prediction.predicted_winner == "team_a"
    assert prediction.win_probability_a > 0.5
    assert prediction.components["glickoRatingDiff"] > 0


def test_predict_match_uses_draw_threshold_for_true_toss_up():
    team_a = TeamRanking(
        team_id_master="a",
        power_score_final=0.5,
        sos_norm=0.5,
        offense_norm=0.5,
        defense_norm=0.5,
        age=13,
        games_played=12,
        glicko_rating=1500,
        glicko_rd=120,
    )
    team_b = TeamRanking(
        team_id_master="b",
        power_score_final=0.5,
        sos_norm=0.5,
        offense_norm=0.5,
        defense_norm=0.5,
        age=13,
        games_played=12,
        glicko_rating=1500,
        glicko_rd=120,
    )

    prediction = predict_match(team_a, team_b, [])

    assert prediction.predicted_winner == "draw"
    assert abs(prediction.win_probability_a - 0.5) < 0.03


def test_predict_match_confidence_drops_with_high_glicko_rd():
    low_rd_team_a = TeamRanking(
        team_id_master="a",
        power_score_final=0.62,
        sos_norm=0.58,
        offense_norm=0.60,
        defense_norm=0.57,
        age=15,
        games_played=24,
        glicko_rating=1600,
        glicko_rd=60,
    )
    low_rd_team_b = TeamRanking(
        team_id_master="b",
        power_score_final=0.49,
        sos_norm=0.50,
        offense_norm=0.49,
        defense_norm=0.50,
        age=15,
        games_played=24,
        glicko_rating=1480,
        glicko_rd=65,
    )
    high_rd_team_a = TeamRanking(**{**low_rd_team_a.__dict__, "glicko_rd": 260})
    high_rd_team_b = TeamRanking(**{**low_rd_team_b.__dict__, "glicko_rd": 250})

    history = [
        Game("g1", "a", "x", 3, 1, "2026-01-10"),
        Game("g2", "a", "y", 2, 0, "2026-01-17"),
        Game("g3", "b", "z", 1, 0, "2026-01-09"),
        Game("g4", "b", "w", 0, 1, "2026-01-16"),
    ]

    low_rd_prediction = predict_match(low_rd_team_a, low_rd_team_b, history)
    high_rd_prediction = predict_match(high_rd_team_a, high_rd_team_b, history)

    assert low_rd_prediction.confidence_score is not None
    assert high_rd_prediction.confidence_score is not None
    assert low_rd_prediction.confidence_score > high_rd_prediction.confidence_score


def test_predict_match_uses_common_opponent_signal():
    team_a = TeamRanking(
        team_id_master="a",
        power_score_final=0.58,
        sos_norm=0.54,
        offense_norm=0.57,
        defense_norm=0.56,
        age=14,
        games_played=18,
        glicko_rating=1520,
        glicko_rd=85,
    )
    team_b = TeamRanking(
        team_id_master="b",
        power_score_final=0.58,
        sos_norm=0.54,
        offense_norm=0.57,
        defense_norm=0.56,
        age=14,
        games_played=18,
        glicko_rating=1520,
        glicko_rd=85,
    )

    history = [
        Game("g1", "a", "opp-1", 3, 0, "2026-03-20"),
        Game("g2", "a", "opp-2", 2, 0, "2026-03-13"),
        Game("g3", "opp-1", "b", 2, 1, "2026-03-06"),
        Game("g4", "opp-2", "b", 1, 1, "2026-02-27"),
    ]

    common_opponents = calculate_common_opponent_signal("a", "b", history)
    prediction = predict_match(team_a, team_b, history)

    assert common_opponents["sharedOpponents"] == 2.0
    assert common_opponents["advantage"] > 0.0
    assert prediction.predicted_winner == "team_a"
    assert prediction.components["commonOpponentSignal"] > 0.0
    assert prediction.common_opponents is not None
    assert prediction.common_opponents["sharedOpponents"] == 2.0
