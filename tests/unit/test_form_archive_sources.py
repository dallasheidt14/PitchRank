from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.predictions.archive_inputs import authenticate_archive
from src.predictions.form_archive_sources import FrozenSourceIndex
from src.predictions.form_policy import CALIBRATION_SNAPSHOT_FILES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_research import prediction_input_error, residual_form, timestamp, valid_expectation
from src.rankings import input_archive
from src.rankings.archive_storage import publish_archive
from src.rankings.input_archive import InputArchive
from tests.unit.test_ranking_archive_storage import FakeServer

ROOT = Path(__file__).resolve().parents[2]


def forecast(source, day, captured_at, margin, games=None):
    return {
        "id": "forecast-" + source, "source_game_id": source, "fixture_key": "database:" + source,
        "game_date": day, "home_team_master_id": "a", "away_team_master_id": "b",
        "heuristic_predicted_at": captured_at,
        "heuristic_prediction": {
            "response": {"prediction": {"expectedMargin": margin}},
            "shadowContext": {
                "teamAInput": {"team_id_master": "a", "ratings_as_of": captured_at[:10] + "T00:00:00Z"},
                "teamBInput": {"team_id_master": "b", "ratings_as_of": captured_at[:10] + "T00:00:00Z"},
                "calibration": {key: {} for key in CALIBRATION_SNAPSHOT_FILES},
                "frozenEvidence": {"as_of": captured_at[:10], "games": games or []},
            },
        },
    }


@pytest.fixture
def archive_factory(tmp_path, monkeypatch):
    sequence = 0

    def capture(row, recorded_at):
        nonlocal sequence
        sequence += 1
        monkeypatch.setattr(input_archive, "utc_now", lambda: recorded_at)
        archive = InputArchive(tmp_path / str(sequence), ROOT, {"capture_kind": "frozen_compare_forecasts"})
        archive.query("prospective_match_predictions", [["select", ["*"], {}]],
                      SimpleNamespace(data=[row]), recorded_at, "select")
        archive.finish(True)
        server = FakeServer(recorded_at=recorded_at)
        publish_archive(server, archive.directory, dry_run=False)
        return authenticate_archive(server, archive.directory)

    # Real JS verification is covered by the integration chain. Isolate member/cutoff logic here.
    def checked(rows, root):
        return [{"verified": True, "id": row["id"], "model_signature": PINNED_MODEL_SIGNATURE,
                 "reference_time": timestamp(row["heuristic_predicted_at"]).isoformat(timespec="milliseconds")}
                for row in rows]

    monkeypatch.setattr("src.predictions.form_archive_sources._source_checks", checked)
    return capture


@pytest.fixture
def history_game():
    return {"id": "history", "game_date": "2026-11-12", "home_team_master_id": "a", "away_team_master_id": "b",
            "home_score": 2, "away_score": 0, "ml_overperformance": .4}


@pytest.fixture
def source_case(archive_factory, history_game):
    prior = archive_factory(forecast("history", "2026-11-12", "2026-11-11T12:00:00.123456Z", 4),
                            "2026-11-11T13:00:00Z")
    target_row = forecast("target", "2026-11-14", "2026-11-13T12:00:00.123456Z", 1, [history_game])
    target = archive_factory(target_row, "2026-11-13T13:00:00Z")
    sources = FrozenSourceIndex([prior, target], ROOT)
    binding = target.frozen_rows()[0]["binding"]
    case = {**sources.case_inputs(binding), "predictor_revision": PINNED_REVISION,
            "fixture": {key: target_row[key] for key in (
                "source_game_id", "game_date", "home_team_master_id", "away_team_master_id")}}
    return sources, case


def test_complete_frozen_inputs_need_live_authenticated_sources_and_keep_training_dates_unknown(
    source_case, history_game
):
    sources, case = source_case
    assert prediction_input_error(case, "2026-11-14") == "unverified_archive_witness"
    assert prediction_input_error(case, "2026-11-14", sources) is None
    assert "input_provenance" not in case
    assert case["reference_time"] == "2026-11-13T12:00:00.123+00:00"
    expected = case["expectations"]["history"]
    assert expected["expected_home_margin"] == 4 and "provenance" not in expected
    assert valid_expectation(expected, history_game, sources) is True
    assert valid_expectation(expected, history_game) is False
    form = residual_form("a", case["games"], case["expectations"], "2026-11-14", "residual_sequence", sources)
    assert form["value"] == -.25 and form["usable"] == 1 and form["provenance"] == {"frozen": 1}


@pytest.mark.parametrize("change", ["team", "game", "calibration", "prediction", "clock", "binding", "mix", "omit"])
def test_edited_frozen_inputs_and_cherry_picked_expectations_cannot_pass_the_archive_gate(source_case, change):
    sources, original = source_case
    case = deepcopy(original)
    if change == "team":
        case["teamA"]["power_score_final"] = .99
    elif change == "game":
        case["games"][0]["home_score"] = 9
    elif change == "calibration":
        case["calibrations"]["heuristic_outcome_calibration.json"] = {"alpha": 1}
    elif change == "prediction":
        case["frozenPrediction"]["expectedMargin"] = 99
    elif change == "clock":
        case["reference_time"] = "2026-11-13T12:00:00.124Z"
    elif change == "binding":
        case["source_witness"]["row_number"] = True
    elif change == "mix":
        case["input_provenance"] = []
    else:
        case["expectations"] = {}
    assert prediction_input_error(case, "2026-11-14", sources) is not None
    assert prediction_input_error(original, "2026-11-14", sources) is None


def test_later_archives_cannot_backdate_expectations(archive_factory, history_game):
    row = forecast("history", "2026-11-12", "2026-11-11T12:00:00Z", 4)
    late = archive_factory(row, "2026-11-15T12:00:00Z")
    sources = FrozenSourceIndex([late], ROOT)
    assert sources.expectation_for_game(history_game) is None


def test_future_conflicting_values_do_not_change_an_earlier_frozen_expectation(archive_factory, history_game):
    row = forecast("history", "2026-11-12", "2026-11-11T12:00:00Z", 4)
    early = archive_factory(row, "2026-11-11T13:00:00Z")
    sources = FrozenSourceIndex([early], ROOT)
    expected = sources.expectation_for_game(history_game)
    row["heuristic_prediction"]["response"]["prediction"]["expectedMargin"] = -99
    late = archive_factory(row, "2026-11-15T12:00:00Z")
    extended = FrozenSourceIndex([early, late], ROOT)
    assert extended.expectation_for_game(history_game) == expected


def test_conflicting_pre_game_records_are_unavailable(archive_factory, history_game):
    row = forecast("history", "2026-11-12", "2026-11-11T12:00:00Z", 4)
    early = archive_factory(row, "2026-11-11T13:00:00Z")
    row["heuristic_prediction"]["response"]["prediction"]["expectedMargin"] = -99
    other = archive_factory(row, "2026-11-11T14:00:00Z")
    sources = FrozenSourceIndex([early, other], ROOT)
    assert sources.expectation_for_game(history_game) is None
    assert sources.exclusions["conflicting_completed_forecast"] == 1


def test_forging_an_expected_margin_is_missing_evidence_and_cannot_fall_back_to_raw_form(source_case, history_game):
    sources, case = source_case
    case["expectations"]["history"]["expected_home_margin"] = -4
    assert valid_expectation(case["expectations"]["history"], history_game, sources) is False
    form = residual_form("a", case["games"], case["expectations"], "2026-11-14", "residual_sequence", sources)
    assert form["value"] == 0 and form["usable"] == 0 and form["missing"] == 1


def test_reused_response_page_does_not_share_mutable_row_payloads(source_case):
    sources, case = source_case
    original = sources.record(case["source_witness"])
    original["heuristic_prediction"]["response"]["prediction"]["expectedMargin"] = 99
    unchanged = sources.record(case["source_witness"])
    assert unchanged["heuristic_prediction"]["response"]["prediction"]["expectedMargin"] == 1
    assert prediction_input_error(case, "2026-11-14", sources) is None
