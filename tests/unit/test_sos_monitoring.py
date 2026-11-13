"""Frozen paired forecasts, sealed labels, complete risk outputs and selection policy."""

from copy import deepcopy

import pytest

from src.predictions.sos_monitoring import collect_review, evaluate_sos, frame_for, validate_prediction, weekly_report


def case(i=0, day="2030-01-10", scores=(2, 0)):
    prediction = {
        "winProbabilityA": 0.6,
        "drawProbability": 0.2,
        "winProbabilityB": 0.2,
        "blowout4PlusProbability": 0.1,
        "expectedMargin": 1.0,
        "expectedScore": {"teamA": 2, "teamB": 1},
        "formA": 1.0,
        "formB": 0.0,
    }
    variants = {arm: deepcopy(prediction) for arm in ("0", "0.5", "1", "1.5")}
    variants["0.5"].update(winProbabilityA=0.7, drawProbability=0.15, winProbabilityB=0.15)
    return {
        "baseline_forecast_id": str(i),
        "actual_game_id": str(i),
        "captured_at": "2030-01-01T00:00:00Z",
        "game_date": day,
        "group": f"event-{i % 20}",
        "group_kind": "event",
        "provider": "test",
        "scores": list(scores),
        "open": True,
        "fixture": {},
        "payload": {
            "variants": variants,
            "context": {
                "teamAInput": {
                    "team_id_master": "a",
                    "sos_norm": 0.8,
                    "power_score_final": 0.5,
                    "age": 12,
                    "gender": "M",
                },
                "teamBInput": {
                    "team_id_master": "b",
                    "sos_norm": 0.3,
                    "power_score_final": 0.49,
                    "age": 12,
                    "gender": "M",
                },
                "frozenEvidence": {"games": []},
            },
        },
    }


def model():
    return {"signature": "a" * 64, "development_start": "2030-01-01", "development_end": "2030-01-28"}


def test_wins_misses_draws_and_missing_sos_are_all_reported():
    rows = [case(0), case(1, scores=(0, 1)), case(2, scores=(1, 1))]
    rows[2]["payload"]["context"]["teamAInput"]["sos_norm"] = None
    report = weekly_report(rows, {}, "2030-01-15T00:00:00Z")
    assert report["cumulative"]["games"] == 3
    assert report["cumulative"]["winner_accuracy"] == pytest.approx(1 / 3)
    assert report["cumulative"]["actual_draw_rate"] == pytest.approx(1 / 3)
    assert report["cumulative"]["expected_draw_rate"] == pytest.approx(0.2)
    assert {c["correct"] for c in report["case_review"]} == {False, True}
    assert frame_for(rows).iloc[2].sos_gap == "unknown"
    assert report["production_promotion"] is False


def test_duplicate_result_counts_once():
    row = case()
    reverse = deepcopy(row)
    reverse["baseline_forecast_id"] = "other"
    report = weekly_report([row, reverse], {}, "2030-01-15T00:00:00Z")
    assert report["cumulative"]["games"] == 1
    assert report["duplicate_results"] == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("drawProbability", None),
        ("winProbabilityA", 1.2),
        ("blowout4PlusProbability", float("nan")),
        ("expectedMargin", None),
    ],
)
def test_incomplete_risk_or_probabilities_refuse_comparison(key, value):
    p = case()["payload"]["variants"]["1"]
    p[key] = value
    with pytest.raises(ValueError):
        validate_prediction(p)


def test_server_seal_never_reaches_result_resolver_or_tables():
    class Client:
        def rpc(self, name, parameters):
            assert name == "compare_monitor_review"
            self.data = [
                {"game_date": "2030-01-10", "provider": "test", "open": False, "fixture": None, "payload": None}
            ]
            return self

        def execute(self):
            return self

        def table(self, name):
            pytest.fail("A sealed cohort must never query source results")

    records, coverage, _ = collect_review(Client(), "a" * 64, dry_run=False)
    assert records == []
    assert coverage["counts"]["sealed_or_future"] == 1


def test_development_selection_requires_1000_matches_and_20_groups():
    rows = [case(i) for i in range(1000)]
    report = evaluate_sos(rows, rows, model(), None, "2030-02-01T00:00:00Z")
    assert report["status"] == "selected_for_confirmation"
    assert report["selected"] == "0.5"
    assert report["production_promotion"] is False
    assert evaluate_sos(rows[:999], rows, model(), None, "2030-02-01T00:00:00Z")["status"] == "insufficient_development"


def test_open_development_and_confirmation_never_report_adoption():
    rows = [case(i) for i in range(5)]
    assert evaluate_sos(rows, rows, model(), None, "2030-01-20T00:00:00Z")["status"] == "collecting_development"


def test_crossing_event_excluded_from_development():
    rows = [case(i) for i in range(1000)]
    metadata = rows + [case(1000, day="2030-02-01")]
    report = evaluate_sos(rows, metadata, model(), None, "2030-02-02T00:00:00Z")
    assert report["excluded_crossing_groups"] == 1
    assert report["games"] == 950
    assert report["status"] == "insufficient_development"
