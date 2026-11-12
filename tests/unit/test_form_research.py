import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.predictions.form_research import (
    CALIBRATION_ROLES,
    FORM_CANDIDATES,
    INPUT_ROLES,
    AttackDefenseModel,
    ResearchPolicy,
    audit_cases,
    compare_outputs,
    digest,
    expectation_payload,
    pinned_source_identity,
    prediction_input_error,
    provenance_error,
    reconstruct_expectations,
    reconstruction_error,
    replay_reference_time,
    residual_form,
    valid_expectation,
    write_bundle,
)


@pytest.mark.parametrize("columns", [[], ["training_run_id", "training_cutoff", "calibration_signature"]])
def test_inventory_volume_or_schema_alone_cannot_establish_eligibility(columns):
    from scripts.benchmark_compare_form import inventory_report

    inventory = {
        "snapshot_columns": columns,
        "development_snapshots": 2_900_000,
        "evaluation_snapshots": 2_400_000,
        "target_coverage": [
            {"provider": "gotsport", "recorded_age_group": "u12", "snapshot_history_band": "8+", "target_rows": 10_000}
        ],
    }
    report = inventory_report(inventory)
    assert report["historical_selection"] == "not_performed"
    assert report["production_promotion"] is False
    assert report["verified_eligible"] == {
        "development": {"matches": 0, "groups": 0},
        "evaluation": {"matches": 0, "groups": 0},
    }
    assert report["inventory"]["target_coverage"] == inventory["target_coverage"]
    assert report["coverage_unit"] == "database_rows_before_source_deduplication"


def test_audit_batches_cover_both_periods_once_without_crossing_the_boundary():
    from datetime import date, timedelta

    from scripts.benchmark_compare_form import coverage_windows

    windows = coverage_windows()
    days = [
        date.fromisoformat(start) + timedelta(days=offset)
        for start, end in windows
        for offset in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    ]
    assert len(days) == len(set(days)) == 84
    assert days[0].isoformat() == "2026-08-17" and days[-1].isoformat() == "2026-11-08"
    assert all((date.fromisoformat(end) - date.fromisoformat(start)).days <= 6 for start, end in windows)
    assert all(not (start <= "2026-10-11" < end) for start, end in windows)


def provenance(day="2026-08-01"):
    return {
        "sha256": "a" * 64,
        "code_revision": "revision",
        "created_at": day + "T01:00:00Z",
        "last_calculated": day + "T00:30:00Z",
        "snapshot_date": day,
        "trained_at": "2026-07-01T00:00:00Z",
        "training_cutoff": "2026-06-30",
    }


def game(i="g1", day="2026-08-10", home=2, away=0, opponent="b"):
    return {
        "id": i,
        "game_date": day,
        "home_team_master_id": "a",
        "away_team_master_id": opponent,
        "home_score": home,
        "away_score": away,
    }


def expectation(margin=4, match=None):
    g = match or game()
    result = {
        "source": "frozen",
        "expected_home_margin": margin,
        "provenance": provenance(),
        "source_game_id": g["id"],
        "game_date": g["game_date"],
        "home_team_master_id": g["home_team_master_id"],
        "away_team_master_id": g["away_team_master_id"],
        "model_signature": "signature",
    }
    result["provenance"]["sha256"] = digest(expectation_payload(result))
    return result


@pytest.mark.parametrize("home,away,expected,sign", [(2, 0, 4, -1), (1, 2, -3, 1)])
def test_form_rewards_performance_relative_to_expectation(home, away, expected, sign):
    result = residual_form(
        "a", [game(home=home, away=away)], {"g1": expectation(expected)}, "2026-08-20", "residual_sequence"
    )
    assert result["value"] * sign > 0
    assert result["value"] == pytest.approx((home - away - expected) / 8)


def test_swapping_team_perspective_reverses_form():
    args = ([game()], {"g1": expectation()}, "2026-08-20", "residual_sequence")
    assert residual_form("a", *args)["value"] == -residual_form("b", *args)["value"]


def test_missing_expectation_does_not_use_raw_margin():
    result = residual_form("a", [game()], {}, "2026-08-20", "residual_sequence")
    assert result["value"] == 0 and result["missing"] == 1 and result["usable"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", None),
        ("last_calculated", None),
        ("trained_at", None),
        ("training_cutoff", None),
        ("snapshot_date", "2026-08-10"),
        ("created_at", "2026-08-10T00:00:00Z"),
        ("trained_at", "2026-09-01T00:00:00Z"),
    ],
)
def test_provenance_rejects_each_missing_or_late_input(field, value):
    p = provenance()
    p[field] = value
    assert provenance_error(p, "2026-08-10") is not None


def test_calendar_weights_depend_on_elapsed_days():
    games = [game("new", "2026-08-19", 4, 0, "b"), game("old", "2026-08-02", 0, 4, "c")]
    expectations = {g["id"]: expectation(0, g) for g in games}
    a = residual_form("a", games, expectations, "2026-08-20", "residual_30")
    b = residual_form("a", games, expectations, "2026-08-20", "residual_60")
    assert a["value"] > b["value"] > 0


def test_repeat_cap_and_distinct_opponent_shrinkage():
    games = [game(str(i), f"2026-08-{10 + i:02}", 4, 0) for i in range(8)]
    expectations = {g["id"]: expectation(0, g) for g in games}
    capped = residual_form("a", games, expectations, "2026-08-20", "residual_30_capped")
    assert capped["effective_weight"] == pytest.approx(1)
    assert capped["opponents"] == 1 and capped["value"] == pytest.approx(0.5)


def test_future_games_and_expectations_cannot_change_form():
    original = residual_form("a", [game()], {"g1": expectation()}, "2026-08-20", "residual_sequence")
    changed = residual_form(
        "a",
        [game(), game("future", "2026-09-01", 20, 0)],
        {"g1": expectation(), "future": expectation(-20)},
        "2026-08-20",
        "residual_sequence",
    )
    assert changed == original


def case(i, day, group):
    a, b = {"team_id_master": "a"}, {"team_id_master": "b"}
    calibrations = {file: {"version": 1} for file in CALIBRATION_ROLES.values()}
    payloads = {
        "team_a_snapshot": a,
        "team_b_snapshot": b,
        **{role: calibrations[file] for role, file in CALIBRATION_ROLES.items()},
    }
    return {
        "fixture": {
            "source_game_id": str(i),
            "game_date": day,
            "event_group": group,
            "home_score": 2,
            "away_score": 0,
            "home_team_master_id": "a",
            "away_team_master_id": "b",
        },
        "teamA": a,
        "teamB": b,
        "calibrations": calibrations,
        "predictor_revision": ResearchPolicy().predictor_revision,
        "input_provenance": [{**provenance(), "role": role, "sha256": digest(payloads[role])} for role in INPUT_ROLES],
        "games": [],
    }


def reconstructed_fixture():
    c = case("g1", "2026-08-10", "test")
    identity = pinned_source_identity()
    keys = {
        "ageGroups": "age_group_parameters.json", "probability": "probability_parameters.json",
        "margin": "margin_parameters_v2.json", "outcome": "heuristic_outcome_calibration.json",
        "confidence": "confidence_parameters_v2.json",
    }
    payload = json.dumps({
        "algorithm": identity["algorithm_hash"],
        "calibration": {key: c["calibrations"][file] for key, file in keys.items()},
    })
    runner = {
        **identity, "predictor_revision": ResearchPolicy().predictor_revision, "aa_parity": True,
        "model_signature_payload": payload, "model_signature": hashlib.sha256(payload.encode()).hexdigest(),
        "outputs": {"baseline": [{
            "id": "g1", "prediction": {"expectedMargin": 4}, "reference_time": "2026-08-09T23:59:59.999Z",
        }]},
    }
    return c, runner


def rebind_reconstruction(expected):
    receipt = expected["reconstruction"]
    receipt["inputs_sha256"] = digest(receipt["inputs"])
    receipt["prediction_sha256"] = digest(receipt["prediction"])
    expected["reconstruction_sha256"] = digest(receipt)
    expected["provenance"]["sha256"] = digest(expectation_payload(expected))


def test_truthful_later_reconstruction_uses_verified_earlier_dependencies():
    c, runner = reconstructed_fixture()
    captured = "2026-11-11T12:00:00Z"
    expected = reconstruct_expectations([c], runner, captured)["g1"]
    assert valid_expectation(expected, game())
    assert expected["provenance"]["created_at"] == captured
    assert reconstruct_expectations([c], runner, captured)["g1"] == expected
    assert "home_score" not in expected["reconstruction"]["inputs"]["fixture"]
    result = residual_form("a", [game()], {"g1": expected}, "2026-08-20", "residual_sequence")
    assert result["value"] == -0.25 and result["provenance"] == {"reconstructed": 1}
    c["teamA"]["power_score_final"] = 100
    runner["outputs"]["baseline"][0]["prediction"]["expectedMargin"] = -100
    assert valid_expectation(expected, game()) and expected["expected_home_margin"] == 4
    frozen = expectation()
    frozen["provenance"]["created_at"] = captured
    assert not valid_expectation(frozen, game())


@pytest.mark.parametrize("mutation", [
    "later_snapshot", "later_training", "prediction", "source", "identity", "timestamp", "signature",
    "computed_before_inputs",
])
def test_reconstruction_receipt_rejects_semantic_changes_even_with_rebound_hashes(mutation):
    c, runner = reconstructed_fixture()
    expected = reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")["g1"]
    receipt = expected["reconstruction"]
    if mutation in {"later_snapshot", "later_training"}:
        descriptor = receipt["inputs"]["input_provenance"][0]
        descriptor["last_calculated" if mutation == "later_snapshot" else "trained_at"] = "2026-11-01T00:00:00Z"
    elif mutation == "prediction":
        receipt["prediction"]["expectedMargin"] = -4
    elif mutation == "source":
        receipt["source_hashes"]["matchPredictor.ts"] = "0" * 64
    elif mutation == "identity":
        receipt["inputs"]["fixture"]["source_game_id"] = "another"
    elif mutation == "timestamp":
        expected["provenance"]["created_at"] = "2026-08-01T00:00:00Z"
    elif mutation == "computed_before_inputs":
        receipt["computed_at"] = "2026-07-01T00:00:00Z"
        expected["provenance"]["created_at"] = receipt["computed_at"]
        expected["provenance"]["last_calculated"] = receipt["computed_at"]
    else:
        receipt["model_signature"] = "0" * 64
        expected["model_signature"] = "0" * 64
    rebind_reconstruction(expected)
    assert reconstruction_error(expected) is not None
    assert not valid_expectation(expected, game())


def test_reconstruction_refuses_candidates_or_missing_training_provenance():
    c, runner = reconstructed_fixture()
    runner["outputs"]["candidate"] = runner["outputs"]["baseline"]
    with pytest.raises(ValueError, match="parity"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")
    del runner["outputs"]["candidate"]
    c["input_provenance"][0].pop("trained_at")
    with pytest.raises(ValueError, match="provenance"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")


def test_reconstruction_binds_pre_match_reference_time_to_actual_runner_output():
    c, runner = reconstructed_fixture()
    runner["outputs"]["baseline"][0]["reference_time"] = "2026-09-01T00:00:00Z"
    with pytest.raises(ValueError, match="reference time"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")
    c["reference_time"] = "2026-08-10T00:00:00Z"
    runner["outputs"]["baseline"][0]["reference_time"] = c["reference_time"]
    with pytest.raises(ValueError, match="provenance"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")


def test_reference_time_normalizes_server_precision_and_cannot_precede_inputs():
    assert replay_reference_time({"reference_time": "2026-11-11 18:15:27.993225+00"}) == "2026-11-11T18:15:27.993+00:00"
    c, runner = reconstructed_fixture()
    c["reference_time"] = "2026-07-31T23:59:59.999Z"
    runner["outputs"]["baseline"][0]["reference_time"] = c["reference_time"]
    with pytest.raises(ValueError, match="provenance"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")


@pytest.mark.parametrize("field", ["created_at", "last_calculated", "trained_at"])
def test_each_snapshot_availability_field_must_precede_the_replay_clock(field):
    c = case("g1", "2026-08-10", "test")
    c["reference_time"] = "2026-08-05T12:00:00Z"
    c["input_provenance"][0][field] = "2026-08-06T00:00:00Z"
    assert prediction_input_error(c, "2026-08-10") == "input_after_reference_time"


@pytest.mark.parametrize("field", ["result_available_at", "created_at", "last_calculated", "trained_at"])
def test_history_availability_between_replay_and_match_day_is_rejected_independently(field):
    c = case("g1", "2026-08-10", "test")
    c["reference_time"] = "2026-08-05T12:00:00Z"
    history = game("earlier", "2026-08-02")
    history.update(result_available_at="2026-08-03T00:00:00Z", ml_overperformance=0.2)
    history["ml_provenance"] = {**provenance(), "sha256": digest({"id": "earlier", "ml_overperformance": 0.2})}
    if field == "result_available_at":
        history[field] = "2026-08-06T00:00:00Z"
    else:
        history["ml_provenance"][field] = "2026-08-06T00:00:00Z"
    history["result_sha256"] = digest({key: history.get(key) for key in (
        "id", "game_date", "home_team_master_id", "away_team_master_id", "home_score", "away_score",
        "result_available_at",
    )})
    c["games"] = [history]
    reason = ("history_result_after_reference_time" if field == "result_available_at"
              else "history_learned_value_after_reference_time")
    assert prediction_input_error(c, "2026-08-10") == reason


@pytest.mark.parametrize("parity", [False, True])
def test_saved_forecast_replay_requires_explicit_capture_time_in_every_mode(tmp_path, monkeypatch, parity):
    import sys

    from scripts.benchmark_compare_form import main

    c = case("g1", "2026-08-10", "test")
    c["frozenPrediction"] = {"expectedMargin": 4}
    payload = dict(schema_version=1, predictor_revision=ResearchPolicy().predictor_revision,
                   calibrations=c["calibrations"], cases=[c])
    source, out = tmp_path / "frozen.json", tmp_path / "output"
    source.write_text(json.dumps(payload), encoding="utf-8")
    args = ["benchmark_compare_form.py", "--input", str(source), "--output-dir", str(out)]
    if parity:
        args.extend(["--parity-only", "--execute"])
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(ValueError, match="original capture reference_time"):
        main()
    assert not out.exists()


@pytest.mark.parametrize("key", ["g1", "local-row-uuid"])
def test_reconstructed_expectations_match_distinct_source_and_local_history_ids(key):
    c, runner = reconstructed_fixture()
    expected = reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")["g1"]
    history = {**game("local-row-uuid"), "source_game_id": "g1"}
    result = residual_form("a", [history], {key: expected}, "2026-08-20", "residual_sequence")
    assert result["usable"] == 1 and result["missing"] == 0 and result["value"] == -0.25


@pytest.mark.parametrize("field", ["inputs_sha256", "prediction_sha256", "reconstruction_sha256", "outer_sha256"])
def test_each_reconstruction_hash_guard_independently_rejects_a_stale_digest(field):
    c, runner = reconstructed_fixture()
    expected = reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")["g1"]
    if field in {"inputs_sha256", "prediction_sha256"}:
        expected["reconstruction"][field] = "0" * 64
        expected["reconstruction_sha256"] = digest(expected["reconstruction"])
        expected["provenance"]["sha256"] = digest(expectation_payload(expected))
    elif field == "reconstruction_sha256":
        expected[field] = "0" * 64
        expected["provenance"]["sha256"] = digest(expectation_payload(expected))
    else:
        expected["provenance"]["sha256"] = "0" * 64
    assert not valid_expectation(expected, game())


def test_full_prediction_binding_covers_non_margin_outputs():
    c, runner = reconstructed_fixture()
    expected = reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")["g1"]
    expected["reconstruction"]["prediction"]["blowout4PlusProbability"] = 0.99
    assert not valid_expectation(expected, game())


def test_missing_reconstruction_outer_digest_reduces_coverage_without_crashing():
    c, runner = reconstructed_fixture()
    expected = reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")["g1"]
    del expected["provenance"]["sha256"]
    result = residual_form("a", [game()], {"g1": expected}, "2026-08-20", "residual_sequence")
    assert result["usable"] == 0 and result["missing"] == 1 and result["value"] == 0


@pytest.mark.parametrize("mutation", ["duplicate", "extra", "missing", "wrong_identity"])
def test_reconstruction_requires_exactly_one_output_per_input_fixture(mutation):
    c, runner = reconstructed_fixture()
    rows = runner["outputs"]["baseline"]
    if mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "extra":
        rows.append({**rows[0], "id": "extra"})
    elif mutation == "missing":
        rows.clear()
    else:
        rows[0]["id"] = "another"
    with pytest.raises(ValueError, match="fixtures"):
        reconstruct_expectations([c], runner, "2026-11-11T12:00:00Z")


def test_provenance_is_bound_to_actual_team_and_calibration_payloads():
    for mutate in ("teamA", "calibration"):
        c = case("a", "2026-09-01", "dev")
        if mutate == "teamA":
            c["teamA"]["power_score_final"] = 0.99
        else:
            c["calibrations"]["heuristic_outcome_calibration.json"]["version"] = 2
        eligible, audit = audit_cases([c], ResearchPolicy())
        assert not eligible and audit["exclusions"]["input_hash_mismatch"] == 1


def test_self_matches_and_wrong_target_orientation_are_rejected():
    for identity in ("a", "wrong"):
        c = case("a", "2026-09-01", "dev")
        c["fixture"]["away_team_master_id"] = identity
        eligible, audit = audit_cases([c], ResearchPolicy())
        assert not eligible and audit["exclusions"]["invalid_target_orientation"] == 1


def test_sequence_keeps_pinned_input_order_for_same_day_games():
    games = [game("z", "2026-08-10", 4, 0, "b"), game("a", "2026-08-10", 0, 4, "c")]
    expectations = {g["id"]: expectation(0, g) for g in games}
    result = residual_form("a", games, expectations, "2026-08-20", "residual_sequence")
    assert result["value"] > 0


def test_audit_keeps_orientations_together_and_excludes_crossing_groups():
    cases = [
        case("a", "2026-09-01", "cross"),
        case("b", "2026-10-20", "cross"),
        case("c", "2026-09-01", "dev"),
        case("d", "2026-10-20", "eval"),
    ]
    cases.append(deepcopy(cases[-1]))
    eligible, audit = audit_cases(cases, replace(ResearchPolicy(), minimum_games=1, minimum_groups=1))
    assert [c["fixture"]["source_game_id"] for c in eligible] == ["c", "d"]
    assert audit["exclusions"]["crossing_group"] == 2
    assert audit["exclusions"]["missing_or_duplicate_source_identity"] == 1
    assert audit["status"] == "eligible"


def test_insufficient_data_does_not_inspect_candidate_outputs():
    report = compare_outputs([case("a", "2026-09-01", "dev")], {}, ResearchPolicy())
    assert report["status"] == "insufficient_data"
    assert "selected_candidate" not in report


def test_streamed_audit_can_keep_only_metadata_without_skipping_input_verification():
    good = case("good", "2026-09-01", "dev")
    bad = case("bad", "2026-09-01", "dev")
    bad["input_provenance"][0]["trained_at"] = "2026-10-01T00:00:00Z"
    retained, original_report = audit_cases([good, bad], ResearchPolicy())
    projected, projected_report = audit_cases((item for item in [good, bad]), ResearchPolicy(), retain_inputs=False)
    assert projected_report == original_report and len(retained) == len(projected) == 1
    assert projected_report["exclusions"]["trained_after_cutoff"] == 1
    assert projected[0] == {"fixture": good["fixture"], "period": "development"}
    projected[0]["fixture"]["home_score"] = 99
    assert good["fixture"]["home_score"] == 2


def test_dry_run_writes_nothing_and_saved_bundle_cannot_be_overwritten(tmp_path):
    out = tmp_path / "run"
    write_bundle(out, {}, {}, dry_run=True)
    assert not out.exists()
    write_bundle(out, {}, {}, dry_run=False)
    assert (out / "manifest.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert "src/predictions/form_policy.py" in manifest["research_source_hashes"]
    assert "src/predictions/form_study_contract.py" in manifest["research_source_hashes"]
    with pytest.raises(FileExistsError):
        write_bundle(out, {}, {}, dry_run=False)


def test_attack_defense_fit_is_pre_match_and_swaps_symmetrically():
    games = [game(str(i), "2026-08-01", 4, 0) for i in range(8)]
    model = AttackDefenseModel().fit(games, "2026-08-10")
    a, b = model.expected_goals("a", "b", "2026-08-11")
    rb, ra = model.expected_goals("b", "a", "2026-08-11")
    assert a > b and (a, b) == pytest.approx((ra, rb))
    neutral = model.expected_goals("unseen_a", "unseen_b", "2026-08-11")
    assert neutral[0] == neutral[1]
    with pytest.raises(ValueError):
        model.expected_goals("a", "b", "2026-08-09")
    later = games + [game("later", "2026-09-01", 0, 20)]
    assert AttackDefenseModel().fit(later, "2026-08-10").expected_goals("a", "b", "2026-08-11") == pytest.approx((a, b))


def test_expectation_margin_and_identity_must_match_the_frozen_digest():
    for key, value in [("expected_home_margin", -20), ("source_game_id", "another"), ("home_team_master_id", "b")]:
        e = expectation()
        e[key] = value
        result = residual_form("a", [game()], {"g1": e}, "2026-08-20", "residual_sequence")
        assert result["value"] == 0 and result["missing"] == 1


def test_later_learned_residual_is_rejected_even_with_an_earlier_result():
    c = case("a", "2026-09-01", "dev")
    g = game()
    g["result_available_at"] = "2026-08-11T00:00:00Z"
    g["ml_overperformance"] = 0.5
    g["result_sha256"] = digest(
        {
            k: g.get(k)
            for k in (
                "id",
                "game_date",
                "home_team_master_id",
                "away_team_master_id",
                "home_score",
                "away_score",
                "result_available_at",
            )
        }
    )
    g["ml_provenance"] = provenance()
    g["ml_provenance"]["trained_at"] = "2026-10-01T00:00:00Z"
    c["games"] = [g]
    eligible, audit = audit_cases([c], ResearchPolicy())
    assert not eligible and audit["exclusions"]["trained_after_cutoff"] == 1


def test_eligible_selection_uses_development_and_reports_ablation_and_holdout():
    cases = [case(str(i), "2026-09-01" if i < 4 else "2026-10-20", str(i // 2)) for i in range(8)]
    policy = replace(ResearchPolicy(), minimum_games=4, minimum_groups=2)

    def output(i, prob):
        return {
            "id": str(i),
            "prediction": {
                "winProbabilityA": prob,
                "drawProbability": 0.1,
                "winProbabilityB": 0.9 - prob,
                "blowout4PlusProbability": 0.2,
                "predictedWinner": "team_a",
                "expectedMargin": 1,
                "expectedScore": {"teamA": 2, "teamB": 1},
            },
        }

    outputs = {name: [output(i, 0.5 if name == "baseline" else 0.6) for i in range(8)] for name in FORM_CANDIDATES}
    outputs["residual_sequence"] = [output(i, 0.85 if i < 4 else 0.8) for i in range(8)]
    outputs["form_off"] = [output(i, 0.6 if i < 4 else 0.89) for i in range(8)]
    for name in FORM_CANDIDATES[1:]:
        outputs[name + "_ml_off"] = [output(i, 0.65) for i in range(4)]
    report = compare_outputs(cases, outputs, policy)
    assert report["selected_candidate"] == "residual_sequence"
    assert report["status"] == "qualifies_for_confirmation"
    assert report["production_promotion"] is False
    assert report["development_ml_ablations"]["form_off_ml_off"]["games"] == 4
    assert report["evaluation"]["candidate"]["games"] == 4
    assert report["log_loss_delta_95"][1] < 0
    assert "cohort" in report["slices"]
    outputs["residual_sequence"] = [output(i, 0.85 if i < 4 else 0.2) for i in range(8)]
    worse = compare_outputs(cases, outputs, policy)
    assert worse["selected_candidate"] == "residual_sequence" and worse["status"] == "no_advancement"
