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
    provenance_error,
    residual_form,
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


def test_dry_run_writes_nothing_and_saved_bundle_cannot_be_overwritten(tmp_path):
    out = tmp_path / "run"
    write_bundle(out, {}, {}, dry_run=True)
    assert not out.exists()
    write_bundle(out, {}, {}, dry_run=False)
    assert (out / "manifest.json").exists()
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
