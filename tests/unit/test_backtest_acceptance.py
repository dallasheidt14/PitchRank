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
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"model")
    preflight = SimpleNamespace(
        input_sha256="preflight-sha",
        cutoff_exclusive="2025-05-10",
        ready=True,
        cohorts=(SimpleNamespace(eligible=2, total=2),),
    )
    monkeypatch.setattr(acceptance, "read_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(acceptance, "load_links", lambda *_args, **_kwargs: links)
    monkeypatch.setattr(acceptance, "build_reviewed_cohort_readiness", lambda *_args: readiness)
    monkeypatch.setattr(acceptance, "model_artifact_sha256", lambda *_args: "model-sha")
    monkeypatch.setattr(acceptance, "_model_data_end", lambda *_args: "2025-05-09")
    monkeypatch.setattr(acceptance, "preflight_input_sha256", lambda *_args: "preflight-sha")
    monkeypatch.setattr(acceptance, "load_historical_preflight", lambda *_args, **_kwargs: preflight)
    monkeypatch.setattr(acceptance, "list_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(acceptance, "list_failed_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        acceptance,
        "build_event_rollup",
        lambda *_args, **_kwargs: {
            "coverage": {"total_cohorts": 1, "completed": 1},
            "team_movements": {"evaluated": 2, "duplicate_entry_ids_skipped": []},
            "modelled_pool_matchups": {
                "original_count": 1,
                "matchbalance_count": 1,
                "original_blowout_4plus_rate": 0.2,
                "matchbalance_blowout_4plus_rate": 0.1,
            },
        },
    )

    report = acceptance.validate_backtest_acceptance(
        "gotsport__51783__unknown",
        profile,
        model_artifact=model_path,
        base_dir=tmp_path,
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
    monkeypatch.setattr(acceptance, "build_reviewed_cohort_readiness", lambda *_args: ())
    monkeypatch.setattr(acceptance, "load_historical_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(acceptance, "list_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(acceptance, "list_failed_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        acceptance,
        "build_event_rollup",
        lambda *_args, **_kwargs: {
            "coverage": {"total_cohorts": 1, "completed": 0},
            "team_movements": {"evaluated": 0, "duplicate_entry_ids_skipped": []},
            "modelled_pool_matchups": {
                "original_count": 0,
                "matchbalance_count": 0,
                "original_blowout_4plus_rate": None,
                "matchbalance_blowout_4plus_rate": None,
            },
        },
    )

    report = acceptance.validate_backtest_acceptance(
        "gotsport__51783__unknown",
        profile,
        model_artifact=tmp_path / "missing.pkl",
        base_dir=tmp_path,
    )

    failed_names = {check["name"] for check in report["checks"] if check["status"] == "fail"}
    assert report["status"] == "incomplete"
    assert "teams" in failed_names
    assert "historical model artifact" in failed_names
    assert "historical rating preflight" in failed_names
    assert "completed cohort outputs" in failed_names
    assert "tournament team movements" in failed_names
    assert "tournament rollup reconciliation" in failed_names
