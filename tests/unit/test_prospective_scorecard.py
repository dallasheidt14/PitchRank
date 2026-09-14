from __future__ import annotations

from src.predictions.prospective_scorecard import build_prospective_scorecard


def _prediction(
    *,
    version: str,
    game_date: str,
    accurate: bool,
) -> dict[str, object]:
    return {
        "model_version": version,
        "game_date": game_date,
        "actual_outcome": "team_a",
        "actual_score_a": 2,
        "actual_score_b": 1,
        "actual_margin": 1,
        "predicted_outcome": "team_a" if accurate else "team_b",
        "prob_team_a_win": 0.72 if accurate else 0.25,
        "prob_draw": 0.18 if accurate else 0.20,
        "prob_team_b_win": 0.10 if accurate else 0.55,
        "predicted_score_a": 2 if accurate else 1,
        "predicted_score_b": 1 if accurate else 3,
        "predicted_margin": 1 if accurate else -2,
        "predicted_absolute_margin": 1 if accurate else 2,
        "blowout_4plus_probability": 0.03 if accurate else 0.30,
    }


def test_long_run_scorecard_requires_coverage_and_repeated_monthly_wins():
    pairs = []
    for month in ("01", "02", "03"):
        for day in ("05", "12"):
            date = f"2026-{month}-{day}"
            pairs.append(
                (
                    _prediction(version="heuristic-v1", game_date=date, accurate=False),
                    _prediction(version="offline-v2", game_date=date, accurate=True),
                )
            )

    scorecard, monthly, report = build_prospective_scorecard(
        pairs,
        minimum_games=6,
        minimum_months=3,
    )

    assert scorecard.loc[0, "decision"] == "eligible_for_review"
    assert len(monthly) == 3
    assert report["version_pairs"][0]["automatic_activation"] is False
    assert report["version_pairs"][0]["consistent_monthly_wins"]
    assert report["report_sha256"]


def test_long_run_scorecard_holds_sparse_version_pair():
    pair = (
        _prediction(version="heuristic-v1", game_date="2026-01-05", accurate=False),
        _prediction(version="offline-v2", game_date="2026-01-05", accurate=True),
    )

    scorecard, _monthly, report = build_prospective_scorecard(
        [pair],
        minimum_games=10,
        minimum_months=3,
    )

    assert scorecard.loc[0, "decision"] == "hold"
    assert any("coverage" in reason.lower() for reason in report["version_pairs"][0]["reasons"])
