from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import backtest_tournament_cohort as cohort
from scripts.predictor_python import Game as PredictorGame
from src.tournaments.seeding_optimizer import MatchupCost, SeedableTeam


def test_snapshot_as_of_date_returns_latest_prior_snapshot():
    snapshots = [
        {"snapshot_date": "2026-04-08", "snapshot_ts": pd.Timestamp("2026-04-08"), "power_score_final": 0.51},
        {"snapshot_date": "2026-04-10", "snapshot_ts": pd.Timestamp("2026-04-10"), "power_score_final": 0.63},
        {"snapshot_date": "2026-04-12", "snapshot_ts": pd.Timestamp("2026-04-12"), "power_score_final": 0.77},
    ]

    selected = cohort._snapshot_as_of_date(snapshots, "2026-04-11")

    assert selected is not None
    assert selected["snapshot_date"] == "2026-04-10"
    assert selected["power_score_final"] == 0.63


def test_resolve_prediction_snapshot_rejects_future_only_history():
    with pytest.raises(ValueError, match="before 2026-04-10"):
        cohort._resolve_prediction_snapshot(
            {"event_team_name": "Alpha", "ranking_source_team_id": "team-a"},
            [{"snapshot_date": "2026-04-11", "snapshot_ts": pd.Timestamp("2026-04-11")}],
            "2026-04-10",
        )


def test_historical_ranking_row_uses_frozen_prediction_features():
    row = cohort._historical_ranking_row(
        {
            "team_id": "team-a",
            "snapshot_date": "2026-04-09",
            "age_group": "u14",
            "gender": "Male",
            "status": "Active",
            "games_played": 8,
            "power_score_final": 0.61,
            "sos_norm": 0.52,
            "offense_norm": 0.55,
            "defense_norm": 0.49,
            "rank_in_cohort_final": 7,
        }
    )

    assert row["power_score_final"] == 0.61
    assert row["off_norm"] == 0.55
    assert row["def_norm"] == 0.49
    assert row["rank_in_cohort_final"] == 7


def test_historical_snapshot_provenance_rejects_reconstructed_inputs():
    with pytest.raises(ValueError, match="reconstructed input"):
        cohort._verify_snapshot_provenance(
            {"created_at": "2026-04-12T00:00:00+00:00"},
            prediction_date="2026-04-10",
            team_name="Alpha",
        )


def test_related_snapshot_index_excludes_same_day_and_late_backfills():
    filtered = cohort._filter_snapshot_index_for_cutoff(
        {
            "common-opponent": [
                {
                    "snapshot_date": "2026-04-07",
                    "snapshot_ts": pd.Timestamp("2026-04-07"),
                    "created_at": "2026-04-11T00:00:00+00:00",
                },
                {
                    "snapshot_date": "2026-04-08",
                    "snapshot_ts": pd.Timestamp("2026-04-08"),
                    "created_at": "2026-04-09T23:00:00+00:00",
                },
                {
                    "snapshot_date": "2026-04-09",
                    "snapshot_ts": pd.Timestamp("2026-04-09"),
                },
                {
                    "snapshot_date": "2026-04-10",
                    "snapshot_ts": pd.Timestamp("2026-04-10"),
                    "created_at": "2026-04-09T23:00:00+00:00",
                },
            ]
        },
        "2026-04-10",
    )

    assert [row["snapshot_date"] for row in filtered["common-opponent"]] == ["2026-04-08"]


def test_entrant_snapshot_resolution_falls_back_from_late_backfill():
    filtered = cohort._filter_snapshot_index_for_cutoff(
        {
            "team-a": [
                {
                    "snapshot_date": "2026-04-07",
                    "snapshot_ts": pd.Timestamp("2026-04-07"),
                    "created_at": "2026-04-08T12:00:00+00:00",
                    "power_score_final": 0.52,
                },
                {
                    "snapshot_date": "2026-04-09",
                    "snapshot_ts": pd.Timestamp("2026-04-09"),
                    "created_at": "2026-04-11T12:00:00+00:00",
                    "power_score_final": 0.68,
                },
            ]
        },
        "2026-04-10",
    )

    selected, mode = cohort._resolve_prediction_snapshot(
        {"event_team_name": "Alpha", "ranking_source_team_id": "team-a"},
        filtered["team-a"],
        "2026-04-10",
    )

    assert mode == "as_of"
    assert selected["snapshot_date"] == "2026-04-07"
    assert selected["power_score_final"] == 0.52


def test_freeze_historical_inputs_is_deterministic_and_records_cutoff():
    entrants = [
        {
            "entrant_id": "entry-b",
            "canonical_team_id": "canonical-b",
            "ranking_source_team_id": "source-b",
            "source_age_group": "u13",
            "source_gender": "Female",
            "age_group": "u13/u14",
            "gender": "Female",
            "power_score": 0.58,
            "rank_in_cohort": 4,
            "games_played": 9,
            "sos_norm": 0.51,
            "off_norm": 0.54,
            "def_norm": 0.48,
            "glicko_rating": None,
            "glicko_rd": None,
            "glicko_volatility": None,
        }
    ]
    snapshots = {
        "source-b": {
            "snapshot_date": "2026-04-09",
            "created_at": "2026-04-09T23:00:00+00:00",
        }
    }

    first = cohort._freeze_historical_inputs(
        entrants,
        snapshots,
        prediction_date="2026-04-10",
        history_start_date="2025-04-10",
        model_artifact=None,
        model_training_metadata={"train_examples": 100},
    )
    second = cohort._freeze_historical_inputs(
        list(reversed(entrants)),
        snapshots,
        prediction_date="2026-04-10",
        history_start_date="2025-04-10",
        model_artifact=None,
        model_training_metadata={"train_examples": 100},
    )

    assert first == second
    assert first["source"] == "prediction_feature_history"
    assert first["data_cutoff_exclusive"] == "2026-04-10"
    assert first["teams"][0]["snapshot_date"] == "2026-04-09"
    assert len(first["input_digest_sha256"]) == 64


def test_freeze_historical_inputs_covers_games_and_related_snapshots():
    entrant = {
        "entrant_id": "entry-a",
        "canonical_team_id": "canonical-a",
        "ranking_source_team_id": "source-a",
        "source_age_group": "u14",
        "source_gender": "Male",
        "age_group": "u14",
        "gender": "Male",
        "power_score": 0.61,
        "rank_in_cohort": 4,
        "games_played": 9,
        "sos_norm": 0.51,
        "off_norm": 0.54,
        "def_norm": 0.48,
        "glicko_rating": None,
        "glicko_rd": None,
        "glicko_volatility": None,
    }
    entrant_snapshot = {
        "snapshot_date": "2026-04-09",
        "created_at": "2026-04-09T23:00:00+00:00",
    }
    game = PredictorGame(
        id="game-1",
        home_team_master_id="source-a",
        away_team_master_id="opponent",
        home_score=2,
        away_score=1,
        game_date="2026-04-08",
        created_at="2026-04-08T12:00:00+00:00",
    )
    related = {
        "opponent": [
            {
                "team_id": "opponent",
                "snapshot_date": "2026-04-08",
                "snapshot_ts": pd.Timestamp("2026-04-08"),
                "created_at": "2026-04-09T12:00:00+00:00",
                "power_score_final": 0.55,
            }
        ]
    }

    frozen = cohort._freeze_historical_inputs(
        [entrant],
        {"source-a": entrant_snapshot},
        prediction_date="2026-04-10",
        history_start_date="2025-04-10",
        model_artifact=None,
        model_training_metadata={},
        recent_games=[game],
        related_snapshot_index=related,
    )

    assert frozen["recent_games"][0]["created_at"] == "2026-04-08T12:00:00+00:00"
    assert frozen["related_snapshots"][0]["team_id"] == "opponent"
    assert "snapshot_ts" not in frozen["related_snapshots"][0]
    changed = cohort._freeze_historical_inputs(
        [entrant],
        {"source-a": entrant_snapshot},
        prediction_date="2026-04-10",
        history_start_date="2025-04-10",
        model_artifact=None,
        model_training_metadata={},
        recent_games=[PredictorGame(**{**game.__dict__, "home_score": 3})],
        related_snapshot_index=related,
    )
    assert changed["input_digest_sha256"] != frozen["input_digest_sha256"]


def test_recent_games_require_import_before_prediction_cutoff():
    calls: list[tuple[str, str]] = []

    class Query:
        def __init__(self):
            self.page = 0

        def select(self, columns):
            calls.append(("select", columns))
            return self

        def gte(self, column, value):
            calls.append((f"gte:{column}", value))
            return self

        def lt(self, column, value):
            calls.append((f"lt:{column}", value))
            return self

        @property
        def not_(self):
            return self

        def is_(self, _column, _value):
            return self

        def eq(self, _column, _value):
            return self

        def or_(self, _filters):
            return self

        def range(self, _start, _end):
            return self

        def execute(self):
            self.page += 1
            if self.page > 1:
                return SimpleNamespace(data=[])
            return SimpleNamespace(
                data=[
                    {
                        "id": "game-1",
                        "home_team_master_id": "team-a",
                        "away_team_master_id": "team-b",
                        "home_score": 2,
                        "away_score": 1,
                        "game_date": "2026-04-08",
                        "created_at": "2026-04-09T12:00:00+00:00",
                    }
                ]
            )

    query = Query()

    class Client:
        def table(self, name):
            assert name == "games"
            return query

    games = cohort._fetch_recent_games_for_teams(
        Client(),
        ["team-a"],
        as_of_date="2026-04-10",
    )

    assert ("lt:game_date", "2026-04-10") in calls
    assert ("lt:created_at", "2026-04-10T00:00:00+00:00") in calls
    assert "created_at" in dict(calls)["select"]
    assert games[0].created_at == "2026-04-09T12:00:00+00:00"


def test_captured_fixture_count_does_not_shrink_to_scored_games():
    division = {
        "name": "Gold",
        "actual_division_name": "Gold",
        "captured_fixture_count": 614,
    }

    assert (
        cohort._captured_fixture_count(
            division,
            {"Gold": 613},
            fallback_division_name="Gold",
        )
        == 614
    )


def test_model_training_provenance_requires_pre_event_data():
    assert (
        cohort._verify_model_training_provenance(
            {"model_data_end_date": "2026-04-09"},
            prediction_date="2026-04-10",
        )
        == "2026-04-09"
    )
    with pytest.raises(ValueError, match="no model_data_end_date"):
        cohort._verify_model_training_provenance({}, prediction_date="2026-04-10")
    with pytest.raises(ValueError, match="not before the event cutoff"):
        cohort._verify_model_training_provenance(
            {"model_data_end_date": "2026-04-10"},
            prediction_date="2026-04-10",
        )


def test_build_point_in_time_prediction_and_cost_functions_uses_asof_snapshots(monkeypatch, tmp_path):
    entrant_rows = [
        {
            "entrant_id": "entrant-a",
            "ranking_source_team_id": "team-a-source",
            "event_team_name": "Alpha",
        },
        {
            "entrant_id": "entrant-b",
            "ranking_source_team_id": "team-b-source",
            "event_team_name": "Bravo",
        },
    ]
    snapshot_index = {
        "team-a-source": [
            {
                "snapshot_date": "2026-04-09",
                "snapshot_ts": pd.Timestamp("2026-04-09"),
                "created_at": "2026-04-09T23:00:00+00:00",
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.61,
            },
            {
                "snapshot_date": "2026-04-12",
                "snapshot_ts": pd.Timestamp("2026-04-12"),
                "created_at": "2026-04-12T00:00:00+00:00",
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.99,
            },
        ],
        "team-b-source": [
            {
                "snapshot_date": "2026-04-08",
                "snapshot_ts": pd.Timestamp("2026-04-08"),
                "created_at": "2026-04-09T23:00:00+00:00",
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.48,
            },
            {
                "snapshot_date": "2026-04-11",
                "snapshot_ts": pd.Timestamp("2026-04-11"),
                "created_at": "2026-04-11T00:00:00+00:00",
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.20,
            },
        ],
    }
    all_games = [
        PredictorGame(
            id="prior-game",
            home_team_master_id="team-a-source",
            away_team_master_id="common-opponent",
            home_score=2,
            away_score=1,
            game_date="2026-04-08",
        ),
        PredictorGame(
            id="same-day-game",
            home_team_master_id="team-b-source",
            away_team_master_id="common-opponent",
            home_score=1,
            away_score=0,
            game_date="2026-04-10",
        ),
        PredictorGame(
            id="future-game",
            home_team_master_id="team-a-source",
            away_team_master_id="team-b-source",
            home_score=0,
            away_score=3,
            game_date="2026-04-11",
        ),
    ]
    captured: dict[str, object] = {}

    def fake_build_point_in_time_matchup_row(**kwargs):
        captured["team_a_snapshot_date"] = kwargs["team_a_snapshot"]["snapshot_date"]
        captured["team_b_snapshot_date"] = kwargs["team_b_snapshot"]["snapshot_date"]
        captured["prior_game_ids"] = [game.id for game in kwargs["all_games"]]
        captured["game_date"] = kwargs["game_date"]
        return {"dummy_feature": 1.0}

    class FakeModel:
        probability_strategy = "poisson_draw_gate"
        selection_objective = "competitive_match_quality"

        def predict_frame(self, frame):
            captured["frame_columns"] = list(frame.columns)
            return pd.DataFrame(
                [
                    {
                        "predicted_outcome": "team_a_win",
                        "prob_team_a_win": 0.57,
                        "prob_draw": 0.21,
                        "prob_team_b_win": 0.22,
                        "expected_goals_a": 1.8,
                        "expected_goals_b": 0.9,
                        "predicted_margin": 0.9,
                        "blowout_3plus_probability": 0.18,
                        "blowout_5plus_probability": 0.04,
                        "probability_strategy": "poisson_draw_gate",
                    }
                ]
            )

        def relabel_evaluation_frame(self, frame):
            return frame

    monkeypatch.setattr(cohort, "build_point_in_time_matchup_row", fake_build_point_in_time_matchup_row)
    monkeypatch.setattr(cohort.PointInTimeMatchModel, "load", lambda artifact_path: FakeModel())

    artifact_path = tmp_path / "fake_point_in_time_match_model.pkl"
    artifact_path.write_text("placeholder", encoding="utf-8")
    predict_fn, matchup_cost_fn, loaded_model = cohort._build_point_in_time_prediction_and_cost_functions(
        entrant_rows,
        all_games,
        prediction_date="2026-04-10",
        snapshot_index=snapshot_index,
        model_artifact=artifact_path,
    )

    assert loaded_model.probability_strategy == "poisson_draw_gate"

    team_a = SeedableTeam(
        team_id="entrant-a",
        team_name="Alpha",
        age_group="u14",
        gender="Male",
        power_score=0.61,
    )
    team_b = SeedableTeam(
        team_id="entrant-b",
        team_name="Bravo",
        age_group="u14",
        gender="Male",
        power_score=0.48,
    )
    prediction = predict_fn(team_a, team_b)
    cost = matchup_cost_fn(team_a, team_b)

    assert captured["team_a_snapshot_date"] == "2026-04-09"
    assert captured["team_b_snapshot_date"] == "2026-04-08"
    assert captured["prior_game_ids"] == ["prior-game"]
    assert captured["game_date"] == "2026-04-10"
    assert captured["frame_columns"] == ["dummy_feature"]
    assert prediction.predicted_winner == "team_a"
    assert prediction.expected_score == {"teamA": 2, "teamB": 1}
    assert prediction.source == "point_in_time:fake_point_in_time_match_model"
    assert round(cost.projected_margin, 2) == 1.0
    assert round(cost.blowout_3plus_probability, 2) == 0.18
    assert round(cost.blowout_5plus_probability, 2) == 0.04


def test_override_point_in_time_probability_strategy_swaps_policy():
    class FakeModel:
        probability_strategy = "hybrid"
        requested_probability_strategy = "auto"
        draw_decision_policy = {
            "default": {"min_draw_probability": 0.16},
            "by_age": {14: {"min_draw_probability": 0.2}},
        }

        @staticmethod
        def _default_draw_decision_policy():
            return {
                "min_draw_probability": 0.25,
                "max_draw_gap": 0.02,
                "max_total_goals": 2.2,
                "min_stalemate_signal": 0.6,
            }

    model = FakeModel()

    overridden = cohort._override_point_in_time_probability_strategy(model, "poisson_draw_gate")

    assert overridden == "poisson_draw_gate"
    assert model.requested_probability_strategy == "poisson_draw_gate"
    assert model.probability_strategy == "poisson_draw_gate"
    assert model.draw_decision_policy == {
        "default": {
            "min_draw_probability": 0.25,
            "max_draw_gap": 0.02,
            "max_total_goals": 2.2,
            "min_stalemate_signal": 0.6,
        },
        "by_age": {},
    }


def test_resolve_point_in_time_probability_strategy_override_defaults_to_draw_gate():
    override = cohort._resolve_point_in_time_probability_strategy_override(None, None)

    assert override == "poisson_draw_gate"


def test_resolve_point_in_time_probability_strategy_override_prefers_cli_then_payload():
    assert (
        cohort._resolve_point_in_time_probability_strategy_override(
            "hybrid",
            "poisson_primary",
        )
        == "hybrid"
    )
    assert (
        cohort._resolve_point_in_time_probability_strategy_override(
            None,
            "poisson_primary",
        )
        == "poisson_primary"
    )


def test_build_division_specs_accepts_integer_strings():
    divisions = cohort._build_division_specs(
        {
            "divisions": [
                {"name": "Gold", "team_count": "7", "pool_sizes": ["4", "3"]},
            ]
        }
    )

    assert divisions == [cohort.DivisionSpec("Gold", 7, (4, 3))]


@pytest.mark.parametrize("invalid_count", [0, -1, 1.5, True, "1.5"])
def test_build_division_specs_rejects_invalid_capacities(invalid_count):
    with pytest.raises(ValueError, match="positive integer"):
        cohort._build_division_specs(
            {"divisions": [{"name": "Gold", "team_count": invalid_count}]}
        )


@pytest.mark.parametrize("invalid_name", [None, "", "  ", 42])
def test_build_division_specs_rejects_invalid_names(invalid_name):
    with pytest.raises(ValueError, match="non-empty string name"):
        cohort._build_division_specs(
            {"divisions": [{"name": invalid_name, "team_count": 2}]}
        )


def test_normalize_actual_games_override_filters_divisions_and_coerces_scores():
    rows = [
        {
            "id": "game-1",
            "division_name": "BU10 Premier",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-b",
            "home_score": "1",
            "away_score": 2,
        },
        {
            "id": "game-2",
            "division_name": "BU10 Super Elite",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-c",
            "away_team_master_id": "team-d",
            "home_score": 0,
            "away_score": 0,
        },
    ]

    normalized = cohort._normalize_actual_games_override(rows, {"BU10 Premier"})

    assert normalized == [
        {
            "id": "game-1",
            "division_name": "BU10 Premier",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-b",
            "home_score": 1,
            "away_score": 2,
        }
    ]


def test_build_entrant_row_keeps_event_cohort_for_play_up_team():
    notes: list[str] = []

    entrant_row = cohort._build_entrant_row(
        {
            "entrant_id": "entrant-1",
            "canonical_team_id": "canonical-team",
            "event_team_name": "Dynamos SC 2016 SC",
            "provider_team_id": "126693",
            "actual_division_name": "Platinum",
        },
        {
            "team_name": "Dynamos SC 2016 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "is_deprecated": False,
        },
        {
            "team_id": "canonical-team",
            "age_group": "u10",
            "gender": "Male",
            "status": "Active",
            "games_played": 14,
            "power_score_true": 0.61,
            "rank_in_cohort_final": 7,
        },
        cohort_age_group="u11",
        cohort_gender="Male",
        notes=notes,
    )

    assert entrant_row["age_group"] == "u11"
    assert entrant_row["gender"] == "Male"
    assert entrant_row["source_age_group"] == "u10"
    assert entrant_row["source_gender"] == "Male"
    assert any("playing up from u10 into u11" in note for note in notes)


def test_build_predictor_team_ranking_prefers_source_age_group():
    ranking = cohort._build_predictor_team_ranking(
        {
            "team_id": "source-team",
            "team_name": "Dynamos SC 2016 SC",
            "power_score": 0.61,
            "age_group": "u11",
            "source_age_group": "u10",
            "games_played": 12,
            "sos_norm": 0.52,
            "off_norm": 0.55,
            "def_norm": 0.50,
            "glicko_rating": None,
            "glicko_rd": None,
            "glicko_volatility": None,
        }
    )

    assert ranking.age == 10


def test_python_predictor_receives_source_age_for_combined_cohort(monkeypatch):
    captured: list[dict[str, object]] = []

    def fake_build(row):
        captured.append(row)
        return cohort.TeamRanking(team_id_master=str(row["team_id"]), age=10)

    monkeypatch.setattr(cohort, "_build_predictor_team_ranking", fake_build)
    cohort._build_python_prediction_and_cost_functions(
        [
            {
                "entrant_id": "entry-a",
                "ranking_source_team_id": "source-a",
                "event_team_name": "Alpha",
                "power_score": 0.6,
                "age_group": "u10/u11",
                "source_age_group": "u10",
                "games_played": 8,
                "sos_norm": 0.5,
                "off_norm": 0.5,
                "def_norm": 0.5,
                "glicko_rating": None,
                "glicko_rd": None,
                "glicko_volatility": None,
            }
        ],
        [],
    )

    assert captured[0]["age_group"] == "u10/u11"
    assert captured[0]["source_age_group"] == "u10"


def test_pool_arrangement_comparison_matches_optimizer_objective_exactly():
    teams = [
        SeedableTeam("a", "A", "u14", "Male", 0.9),
        SeedableTeam("b", "B", "u14", "Male", 0.8),
        SeedableTeam("c", "C", "u14", "Male", 0.7),
        SeedableTeam("d", "D", "u14", "Male", 0.6),
    ]
    costs = {
        frozenset(("a", "b")): 1.0,
        frozenset(("c", "d")): 1.0,
        frozenset(("a", "d")): 4.0,
        frozenset(("b", "c")): 3.0,
    }

    def matchup_cost(team_a, team_b):
        value = costs.get(frozenset((team_a.team_id, team_b.team_id)), 2.0)
        return MatchupCost(value, 0.5, 0.2, 0.1, value)

    result = cohort.optimize_tournament_format(
        teams,
        [cohort.DivisionSpec("Gold", 4, pool_sizes=(2, 2))],
        matchup_cost_fn=matchup_cost,
    )
    proposed = cohort._project_optimized_pool_arrangement(result, matchup_cost)

    assert proposed["projection_basis"] == "optimized_intra_pool_pairings"
    assert proposed["total_model_cost"] == pytest.approx(result.total_cost)


def test_original_pool_projection_requires_exact_membership():
    teams = [SeedableTeam("a", "A", "u14", "Male", 0.9)]

    projection, issues = cohort._project_original_pool_arrangement(
        [{"entrant_id": "a", "actual_division_name": "Gold", "actual_pool_name": ""}],
        teams,
        lambda _a, _b: MatchupCost(1.0, 0.5, 0.2, 0.1, 1.0),
    )

    assert projection is None
    assert issues == ("Entrant a is missing its captured original pool",)
