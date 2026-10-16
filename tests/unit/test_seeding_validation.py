import hashlib
import json
from copy import deepcopy

import pytest

from src.tournaments.compare_predictor_bridge import PREDICTOR_IDENTITY_FILES
from src.tournaments.seeding_validation import _cluster_intervals, frozen_validation_inputs, scorecard
from src.tournaments.seeding_validation_inputs import TEAM_NUMERIC_FIELDS


def team(key):
    return {**dict.fromkeys(TEAM_NUMERIC_FIELDS), "team_id_master": key, "team_name": key,
            **dict.fromkeys(("club_name", "league", "distinction", "state", "last_scraped_at")),
            "age": 14, "gender": "F", "has_modular11_alias": False, "ratings_as_of": "2026-05-01",
            "power_score_final": 0.5, "games_played": 0, "wins": 0, "losses": 0, "draws": 0}


def pack(a="a", b="b"):
    cohort = f"cohort-{a}-{b}"
    evidence = {"schema_version": 1, "model": "cohort", "model_parameters": None,
                "as_of": "2026-05-01", "window_start": "2025-05-01",
                "teams": {"0": team(a), "1": team(b)}, "opponents": {"external": team("external")},
                "games": [{"id": "prior", "game_date": "2026-04-30", "home_team_master_id": a,
                           "away_team_master_id": b, "home_score": 2, "away_score": 1,
                           "ml_overperformance": None, "is_excluded": False,
                           "event_name": None, "competition": None}]}
    prediction = {"entrant_a": "0", "entrant_b": "1", "win_probability_a": 0.5,
                  "draw_probability": 0.25, "win_probability_b": 0.25, "expected_margin": 1,
                  "blowout_4plus_probability": 0.1}
    return {"generated_at": "2026-05-01T12:00:00Z", "predictor_sha256": "a"*64,
            "calibration_inputs": {path.name: json.loads(path.read_text())
                                   for path in PREDICTOR_IDENTITY_FILES if path.suffix == ".json"},
            "input_evidence": {cohort: {"canonical_json": json.dumps(evidence)}},
            "ordering": {cohort: {"suggested_order": ["0", "1"]}},
            "predictions": {cohort: [prediction, {**prediction, "entrant_a": "1", "entrant_b": "0",
                                                  "win_probability_a": 0.25, "win_probability_b": 0.5,
                                                  "expected_margin": -1}]}}


def record(a="a", b="b"):
    saved = pack(a, b)
    frozen, manifest = frozen_validation_inputs(saved, f"cohort-{a}-{b}",
                                                candidate_packs={"baseline": saved, "candidate": deepcopy(saved)})
    prediction = {"probabilities": [0.5, 0.25, 0.25], "margin": 1, "blowout_probability": 0.1,
                  "seed_a": 1, "seed_b": 2}
    return {"game_id": "one", "event_id": "cup", "team_a": a, "team_b": b,
            "game_date": "2026-05-03", "cutoff": "2026-05-01", "previously_examined": False,
            "input_manifest": manifest, "frozen_inputs_json": frozen, "actual_margin": 1,
            "predictions": {"baseline": prediction, "candidate": deepcopy(prediction)}}


def replace_payload(row, inputs):
    row["frozen_inputs_json"] = json.dumps(inputs)
    row["input_manifest"]["sha256"] = hashlib.sha256(row["frozen_inputs_json"].encode()).hexdigest()


def freeze_test_forecasts(row):
    """Construct a synthetic pre-event candidate; tampering tests never call this."""
    inputs = json.loads(row["frozen_inputs_json"])
    for model, prediction in row["predictions"].items():
        candidate = inputs["candidates"].setdefault(model, deepcopy(inputs["candidates"]["baseline"]))
        candidate["order"] = ([row["team_a"], row["team_b"]] if prediction["seed_a"] == 1
                              else [row["team_b"], row["team_a"]])
        forecast = next(item for item in candidate["forecasts"]
                        if item["team_a"] == row["team_a"] and item["team_b"] == row["team_b"])
        forecast.update({key: prediction[key] for key in ("probabilities", "margin", "blowout_probability")})
    replace_payload(row, inputs)


def clustered_records():
    rows = []
    for index in range(60):
        row = record(f"t{index%20}", f"t{(index+1)%20}")
        row.update(game_id=str(index), event_id=f"cup-{index%6}")
        rows.append(row)
    return rows


def test_a_a_has_zero_difference_and_tiny_sample_is_not_confirmed():
    result = scorecard([record()], baseline="baseline")
    assert result["comparisons"]["candidate"]["brier_delta"] == 0
    assert result["comparisons"]["candidate"]["cluster_interval"]["status"] == "insufficient_clusters"
    assert result["models"]["baseline"]["margin_mae"] == 0
    assert result["models"]["baseline"]["brier"] == 0.375
    assert result["status"] == "measured_screening"


@pytest.mark.parametrize("field", ["ratings_available_date", "history_max_date", "calibration_available_date"])
def test_future_inputs_cannot_be_used_as_pre_event_validation(field):
    row = record()
    row["input_manifest"][field] = "2026-05-02"
    with pytest.raises(ValueError, match="Post-cutoff"):
        scorecard([row], baseline="baseline")


def test_confirmation_rejects_examined_events_and_hash_tampering():
    row = record()
    row["previously_examined"] = True
    with pytest.raises(ValueError, match="untouched"):
        scorecard([row], baseline="baseline", confirmation=True)
    row["frozen_inputs_json"] += " "
    with pytest.raises(ValueError, match="hash mismatch"):
        scorecard([row], baseline="baseline")


def test_tied_predictions_get_half_direction_credit_and_duplicates_fail():
    row = record()
    row["predictions"]["candidate"]["margin"] = 0
    freeze_test_forecasts(row)
    assert scorecard([row], baseline="baseline")["models"]["candidate"]["direction_agreement_half_credit_ties"] == 0.5
    with pytest.raises(ValueError, match="Duplicate"):
        scorecard([row, row], baseline="baseline")


@pytest.mark.parametrize("missing", ["participants", "rating", "game", "calibration", "named_calibration"])
def test_confirmation_rejects_non_replayable_inputs(missing):
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    candidate = inputs["candidates"]["candidate"]
    if missing == "participants":
        candidate["evidence"]["teams"] = {}
    elif missing == "rating":
        del candidate["evidence"]["teams"]["0"]["glicko_rating"]
    elif missing == "game":
        candidate["evidence"]["games"] = [{"game_date": "2026-04-30"}]
    elif missing == "calibration":
        candidate["calibration_inputs"] = {"version": 1}
    else:
        candidate["calibration_inputs"] = {name: {"version": 1} for name in candidate["calibration_inputs"]}
    replace_payload(row, inputs)
    with pytest.raises(ValueError):
        scorecard([row], baseline="baseline", confirmation=True)


@pytest.mark.parametrize("changed", [None, "opponent", "game", "capture"])
def test_exported_freeze_checks_content_dates_not_just_manifest(changed):
    row = record()
    captured = json.loads(row["frozen_inputs_json"])
    candidate = captured["candidates"]["candidate"]
    assert set(candidate["evidence"]["opponents"]) == {"external"}
    if changed == "opponent":
        candidate["evidence"]["opponents"]["external"]["ratings_as_of"] = "2026-05-02"
    elif changed == "game":
        candidate["evidence"]["games"][0]["game_date"] = "2026-05-02"
    elif changed == "capture":
        candidate["captured_at"] = "2026-05-02T01:00:00Z"
    replace_payload(row, captured)
    if changed:
        with pytest.raises(ValueError, match="future|post-cutoff|not frozen"):
            scorecard([row], baseline="baseline")
    else:
        assert scorecard([row], baseline="baseline")["status"] == "measured_screening"


def test_empty_history_and_explicitly_missing_optional_ratings_are_valid():
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    for candidate in inputs["candidates"].values():
        candidate["evidence"]["games"] = []
        assert candidate["evidence"]["teams"]["0"]["glicko_rating"] is None
    replace_payload(row, inputs)
    assert scorecard([row], baseline="baseline")["status"] == "measured_screening"


@pytest.mark.parametrize("value", [None, -0.01, 1.01, float("nan"), float("inf")])
def test_seeded_participants_require_eligible_power_scores(value):
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    inputs["candidates"]["candidate"]["evidence"]["teams"]["0"]["power_score_final"] = value
    replace_payload(row, inputs)
    with pytest.raises(ValueError, match="rating|PowerScore"):
        scorecard([row], baseline="baseline", confirmation=True)


@pytest.mark.parametrize("field,value", [("ml_overperformance", "bad"), ("ml_overperformance", True),
                                         ("ml_overperformance", float("nan")), ("ml_overperformance", float("inf")),
                                         ("is_excluded", True), ("event_name", 12), ("competition", [])])
def test_consumed_game_features_must_be_replayable(field, value):
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    inputs["candidates"]["candidate"]["evidence"]["games"][0][field] = value
    replace_payload(row, inputs)
    with pytest.raises(ValueError, match="game|history"):
        scorecard([row], baseline="baseline", confirmation=True)


def test_frozen_games_record_missing_form_explicitly_and_accept_finite_form():
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    game = inputs["candidates"]["candidate"]["evidence"]["games"][0]
    game["ml_overperformance"] = 0.3
    replace_payload(row, inputs)
    assert scorecard([row], baseline="baseline")["status"] == "measured_screening"
    del game["ml_overperformance"]
    replace_payload(row, inputs)
    with pytest.raises(ValueError, match="Incomplete"):
        scorecard([row], baseline="baseline")


def test_frozen_seed_order_cannot_include_an_external_history_opponent():
    row = record()
    inputs = json.loads(row["frozen_inputs_json"])
    inputs["candidates"]["candidate"]["order"].append("external")
    replace_payload(row, inputs)
    with pytest.raises(ValueError, match="candidate order"):
        scorecard([row], baseline="baseline")


@pytest.mark.parametrize("invalid", [None, "version", "missing", "zero_half_life", "season_weight"])
def test_results_model_parameters_share_export_and_scorecard_validation(invalid):
    saved = pack()
    evidence = json.loads(saved["input_evidence"]["cohort-a-b"]["canonical_json"])
    parameters = {"version": "opponent_adjusted_results_v1", "halfLifeDays": 90, "marginCap": 4,
                  "priorWeight": 5, "previousSeasonWeight": 0.5}
    evidence.update(model="results", model_parameters=parameters)
    if invalid == "version":
        parameters["version"] = "unsupported"
    elif invalid == "missing":
        del parameters["marginCap"]
    elif invalid == "zero_half_life":
        parameters["halfLifeDays"] = 0
    elif invalid == "season_weight":
        parameters["previousSeasonWeight"] = 1.1
    saved["input_evidence"]["cohort-a-b"]["canonical_json"] = json.dumps(evidence)
    candidates = {"baseline": pack(), "candidate": saved}
    if invalid:
        with pytest.raises(ValueError):
            frozen_validation_inputs(saved, "cohort-a-b", candidate_packs=candidates)
        row = record()
        inputs = json.loads(row["frozen_inputs_json"])
        inputs["candidates"]["candidate"]["evidence"] = evidence
        replace_payload(row, inputs)
        with pytest.raises(ValueError):
            scorecard([row], baseline="baseline", confirmation=True)
    else:
        row = record()
        row["frozen_inputs_json"], row["input_manifest"] = frozen_validation_inputs(
            saved, "cohort-a-b", candidate_packs=candidates)
        assert scorecard([row], baseline="baseline", confirmation=True)["status"] == "measured_confirmation"


@pytest.mark.parametrize("change", [{"seed_a": 2, "seed_b": 1}, {"margin": -1},
                                    {"probabilities": [0.25, 0.25, 0.5]}])
def test_reported_seeds_and_forecasts_must_match_the_frozen_candidate(change):
    row = record()
    row["predictions"]["candidate"].update(change)
    with pytest.raises(ValueError, match="differ from the frozen"):
        scorecard([row], baseline="baseline", confirmation=True)


def test_one_event_cohort_cannot_change_its_freeze_between_observed_games():
    first, second = record(), record()
    second["game_id"] = "two"
    second["predictions"]["candidate"].update(seed_a=2, seed_b=1)
    freeze_test_forecasts(second)
    with pytest.raises(ValueError, match="consistent frozen candidate"):
        scorecard([first, second], baseline="baseline")


def test_clustered_confirmation_is_deterministic_and_distinguishes_order_from_pair_prediction():
    rows = clustered_records()
    aa = scorecard(rows, baseline="baseline", confirmation=True)
    assert aa["comparisons"]["candidate"]["cluster_interval"]["interval_95"] == [0, 0]
    for index, row in enumerate(rows):
        row["predictions"]["candidate"].update(probabilities=[0.7 + 0.1*(index%2), 0.1, 0.2 - 0.1*(index%2)],
                                                 seed_a=2, seed_b=1)
        freeze_test_forecasts(row)
    result = scorecard(rows, baseline="baseline", confirmation=True)
    assert result == scorecard(rows, baseline="baseline", confirmation=True)
    comparison = result["comparisons"]["candidate"]
    assert comparison["cluster_interval"]["interval_95"][1] < 0
    assert comparison["seed_order_agreement_half_credit_ties"]["delta"] == -1


def test_three_candidates_use_wider_family_adjusted_intervals():
    rows = clustered_records()
    for index, row in enumerate(rows):
        for number, name in enumerate(("candidate", "second", "third")):
            probability = 0.35 + 0.05*((index+number)%9)
            row["predictions"][name] = {**row["predictions"]["baseline"],
                                         "probabilities": [probability, 0.1, 0.9-probability]}
        freeze_test_forecasts(row)
    result = scorecard(rows, baseline="baseline")
    for comparison in result["comparisons"].values():
        interval = comparison["cluster_interval"]
        ordinary, adjusted = interval["interval_95"], interval["family_adjusted_interval"]
        assert interval["candidate_comparisons"] == 3
        assert adjusted[0] < ordinary[0] < ordinary[1] < adjusted[1]


def test_batched_bootstrap_preserves_the_pre_refactor_oracle():
    rows = [{"event_id": f"e{i%6}", "team_a": f"t{i%20}", "team_b": f"t{(i+1)%20}"} for i in range(60)]
    values = [((i%7)-3)/10 for i in range(60)]
    result = _cluster_intervals(rows, {"first": values, "same": values}, comparisons=3)
    assert result["first"] == result["same"]
    assert result["first"]["resamples"] == 1999
    assert result["first"]["interval_95"] == pytest.approx([-0.13333333333333333, 0.12000000000000001])
    assert result["first"]["family_adjusted_interval"] == pytest.approx([-0.1625, 0.14705882352941177])
