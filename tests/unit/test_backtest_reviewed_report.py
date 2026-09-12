from src.tournaments.backtest_reviewed_report import (
    model_comparison_rows,
    movement_rows,
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
