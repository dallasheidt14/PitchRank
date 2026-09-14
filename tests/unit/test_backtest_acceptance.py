from dataclasses import replace
from types import SimpleNamespace

from src.tournaments import backtest_acceptance as acceptance
from src.tournaments.backtest_acceptance import AcceptanceProfile
from src.tournaments.backtest_intake_state import CaptureVerification, tournament_totals
from src.tournaments.backtest_reviewed_run import build_reviewed_cohort_readiness
from tests.unit.test_backtest_request import _links, _snapshot


def test_acceptance_passes_only_when_every_gate_is_current(monkeypatch, tmp_path):
    base = _snapshot()
    snapshot = replace(
        base,
        verification=CaptureVerification(
            ("group-1",),
            (1, 1),
            "2026-09-12T00:00:00+00:00",
            True,
        ),
    )
    links = _links()
    totals = tournament_totals(snapshot.roster)
    results = totals["results"]
    profile = AcceptanceProfile(
        name="fixture",
        event_id="51783",
        event_name="Spring Cup",
        cutoff_exclusive="2025-05-10",
        total_teams=2,
        divisions=1,
        pools=1,
        fixtures=1,
        scored_games=results["scored_games"],
        total_goal_margin=results["total_goal_margin"],
        blowout_games=results["blowout_games"],
    )
    readiness = build_reviewed_cohort_readiness(snapshot, links)
    preflight = SimpleNamespace(
        input_sha256="preflight-sha",
        cutoff_exclusive="2025-05-10",
        predictor_sha256="predictor-sha",
        calibration_available_date="2025-04-01",
        calibration_source_commit="source-commit",
        ready=True,
        merge_map_version="merge-v1",
        cohorts=(SimpleNamespace(eligible=2, total=2),),
    )
    monkeypatch.setattr(acceptance, "read_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(acceptance, "load_links", lambda *_args, **_kwargs: links)
    monkeypatch.setattr(
        acceptance, "build_reviewed_cohort_readiness", lambda *_args, **_kwargs: readiness
    )
    monkeypatch.setattr(acceptance, "canonical_predictor_sha256", lambda: "predictor-sha")
    monkeypatch.setattr(
        acceptance, "preflight_input_sha256", lambda *_args, **_kwargs: "preflight-sha"
    )
    monkeypatch.setattr(acceptance, "load_historical_preflight", lambda *_args, **_kwargs: preflight)
    monkeypatch.setattr(acceptance, "list_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(acceptance, "list_failed_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        acceptance,
        "build_event_rollup",
        lambda *_args, **_kwargs: {
            "coverage": {"total_cohorts": 1, "completed": 1},
            "model_validation": {
                "passed_cohorts": 1,
                "failures": [],
                "event_validation": {"status": "passed", "blockers": []},
            },
            "team_movements": {"evaluated": 2, "duplicate_entry_ids_skipped": []},
            "actual_vs_matchbalance": {
                "comparison_ready": True,
                "actual_game_count": 1,
                "matchbalance_projected_matchup_count": 1,
                "actual_blowout_4plus_rate": 0.2,
                "matchbalance_projected_blowout_4plus_rate": 0.1,
            },
        },
    )

    report = acceptance.validate_backtest_acceptance(
        "gotsport__51783__unknown",
        profile,
        base_dir=tmp_path,
        merge_map_version="merge-v1",
    )

    assert report["status"] == "pass"
    assert report["failed"] == 0
    assert len(report["report_sha256"]) == 64


def test_acceptance_exposes_baseline_and_completion_failures(monkeypatch, tmp_path):
    snapshot = _snapshot()
    links = _links()
    profile = replace(
        acceptance.SAN_ANTONIO_51783,
        total_teams=999,
    )
    monkeypatch.setattr(acceptance, "read_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(acceptance, "load_links", lambda *_args, **_kwargs: links)
    monkeypatch.setattr(
        acceptance, "build_reviewed_cohort_readiness", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(acceptance, "load_historical_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(acceptance, "list_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(acceptance, "list_failed_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        acceptance,
        "build_event_rollup",
        lambda *_args, **_kwargs: {
            "coverage": {"total_cohorts": 1, "completed": 0},
            "model_validation": {
                "passed_cohorts": 0,
                "failures": [],
                "event_validation": {
                    "status": "failed",
                    "blockers": ["No completed event replay"],
                },
            },
            "team_movements": {"evaluated": 0, "duplicate_entry_ids_skipped": []},
            "actual_vs_matchbalance": {
                "comparison_ready": False,
                "actual_game_count": 0,
                "matchbalance_projected_matchup_count": 0,
                "actual_blowout_4plus_rate": None,
                "matchbalance_projected_blowout_4plus_rate": None,
            },
        },
    )

    report = acceptance.validate_backtest_acceptance(
        "gotsport__51783__unknown",
        profile,
        base_dir=tmp_path,
    )

    failed_names = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert report["status"] == "incomplete"
    assert "teams" in failed_names
    assert "PitchRank prediction engine" not in failed_names
    assert "historical rating preflight" in failed_names
    assert "completed cohort outputs" in failed_names
    assert "tournament team movements" in failed_names
    assert "tournament rollup reconciliation" in failed_names


def test_movement_entry_count_keeps_one_registration_in_each_entered_division():
    snapshot = _snapshot()
    second_division = replace(
        snapshot.roster.divisions[0],
        group_id="group-2",
        division_label="Silver",
    )
    repeated_registration = replace(
        snapshot.roster.teams[0],
        source_index=2,
        group_id="group-2",
        division_label="Silver",
    )
    roster = replace(
        snapshot.roster,
        divisions=snapshot.roster.divisions + (second_division,),
        teams=snapshot.roster.teams + (repeated_registration,),
    )

    assert acceptance._scoped_entry_count(roster) == 3
