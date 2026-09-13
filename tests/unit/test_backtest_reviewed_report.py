from src.tournaments.backtest_reviewed_report import (
    actual_vs_matchbalance_rows,
    movement_rows,
    observed_result_values,
    render_reviewed_backtest_html,
)
from tests.unit.test_backtest_reviewed_run import _summary


def test_sales_comparison_uses_captured_results_and_matchbalance_projection():
    rows = actual_vs_matchbalance_rows(_summary())

    assert rows == [
        {
            "Metric": "Average goal margin",
            "Actual tournament": 1.0,
            "MatchBalance projection": 1.5,
            "Estimated reduction": -0.5,
            "Unit": "goals",
        },
        {
            "Metric": "4+ goal blowout rate",
            "Actual tournament": 0.0,
            "MatchBalance projection": 0.1,
            "Estimated reduction": -0.1,
            "Unit": "rate",
        },
    ]


def test_movement_rows_include_staying_teams():
    assert movement_rows(_summary()) == [
        {
            "Team": "Alpha",
            "Original division": "Gold",
            "MatchBalance division": "Gold",
            "Decision": "Stayed",
            "Historical PowerScore": 0.6,
            "Rating evidence": "PitchRank pre-event rating",
        }
    ]


def test_movement_rows_disclose_not_found_rating_fallback():
    summary = _summary()
    summary["division_recommendations"][0]["rating_basis"] = (
        "original_division_median_surrogate"
    )

    rows = movement_rows(summary)
    rendered = render_reviewed_backtest_html(summary, {})

    assert rows[0]["Rating evidence"] == "Division median fallback (team not found)"
    assert "Division median fallback (team not found)" in rendered


def test_director_report_escapes_tournament_and_team_names():
    summary = _summary()
    summary["event_name"] = "<script>alert(1)</script>"
    summary["division_recommendations"][0]["event_team_name"] = "<b>Alpha</b>"

    rendered = render_reviewed_backtest_html(summary, {})

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;b&gt;Alpha&lt;/b&gt;" in rendered
    assert "Actual tournament versus MatchBalance" in rendered
    assert "Modeled original" not in rendered


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
