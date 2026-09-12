from src.tournaments.backtest_reviewed_report import (
    model_comparison_rows,
    movement_rows,
    observed_result_values,
    render_reviewed_backtest_html,
)
from tests.unit.test_backtest_reviewed_run import _summary


def test_model_comparison_uses_better_direction_for_each_metric():
    rows = model_comparison_rows(_summary())

    assert rows[0]["Improvement"] == 0.5
    assert round(rows[2]["Improvement"], 6) == 0.2
    assert round(rows[3]["Improvement"], 6) == 0.1


def test_movement_rows_include_staying_teams():
    assert movement_rows(_summary()) == [
        {
            "Team": "Alpha",
            "Original division": "Gold",
            "MatchBalance division": "Gold",
            "Decision": "Stayed",
            "Historical PowerScore": 0.6,
        }
    ]


def test_director_report_escapes_tournament_and_team_names():
    summary = _summary()
    summary["event_name"] = "<script>alert(1)</script>"
    summary["division_recommendations"][0]["event_team_name"] = "<b>Alpha</b>"

    rendered = render_reviewed_backtest_html(summary, {})

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;b&gt;Alpha&lt;/b&gt;" in rendered


def test_observed_aggregates_are_unavailable_without_scored_games():
    summary = _summary()
    summary["actual_results"] = {
        "actual_game_count": 0,
        "average_goal_differential": 0.0,
        "blowout_4plus_count": 0,
        "blowout_4plus_rate": 0.0,
    }

    observed = observed_result_values(summary)
    rendered = render_reviewed_backtest_html(summary, {})

    assert observed["game_count"] == 0
    assert observed["average_goal_differential"] is None
    assert observed["blowout_4plus_rate"] is None
    assert rendered.count("Unavailable") >= 2
