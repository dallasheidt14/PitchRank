from src.tournaments.backtest_rating_fallback import (
    DIVISION_AVERAGE_BASIS,
    DIVISION_MISSING_HISTORY_AVERAGE_BASIS,
)
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
            "Original pool": "",
            "MatchBalance pool": "",
            "Decision": "Stayed",
            "Historical PowerScore": 0.6,
            "Rating evidence": "PitchRank pre-event rating",
        }
    ]


def test_movement_rows_disclose_not_found_rating_fallback():
    summary = _summary()
    summary["division_recommendations"][0]["rating_basis"] = DIVISION_AVERAGE_BASIS

    rows = movement_rows(summary)
    rendered = render_reviewed_backtest_html(summary, {})

    assert rows[0]["Rating evidence"] == "Division average estimate (team not found)"
    assert "Division average estimate (team not found)" in rendered


def test_movement_rows_disclose_missing_history_without_erasing_identity():
    summary = _summary()
    summary["division_recommendations"][0][
        "rating_basis"
    ] = DIVISION_MISSING_HISTORY_AVERAGE_BASIS

    rows = movement_rows(summary)
    rendered = render_reviewed_backtest_html(summary, {})

    assert rows[0]["Rating evidence"] == "Division average estimate (no pre-event history)"
    assert "Division average estimate (no pre-event history)" in rendered


def test_legacy_run_without_calibration_never_renders_a_sales_comparison():
    summary = _summary()
    summary.pop("model_validation")

    rows = actual_vs_matchbalance_rows(summary)

    assert all(row["MatchBalance projection"] is None for row in rows)
    assert all(row["Estimated reduction"] is None for row in rows)


def test_failed_calibration_withholds_team_placement_recommendations():
    summary = _summary()
    summary["model_validation"] = {"status": "failed", "blockers": ["Margin mismatch"]}

    rendered = render_reviewed_backtest_html(summary, {})

    assert movement_rows(summary) == []
    assert "Placement recommendations withheld" in rendered
    assert "<td>Alpha</td>" not in rendered


def test_operator_can_inspect_a_completed_cohort_that_needs_model_review():
    summary = _summary()
    summary["model_validation"] = {"status": "failed", "blockers": ["Margin mismatch"]}

    comparison = actual_vs_matchbalance_rows(
        summary,
        require_validated_model=False,
    )
    placements = movement_rows(summary, require_validated_model=False)

    assert comparison[0]["MatchBalance projection"] == 1.5
    assert comparison[0]["Estimated reduction"] == -0.5
    assert placements[0]["Team"] == "Alpha"


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
