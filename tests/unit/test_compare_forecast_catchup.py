"""Exercise the actual catch-up sequencing without contacting GitHub or Supabase."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts import catch_up_compare_forecasts as job


def test_capped_queue_runs_again_and_captures_children_created_during_intake():
    states = iter([
        {"intake": (501, 0)}, {"intake": (1, 500), "live": (500, 0)},
        {"intake": (1, 500), "winner": (500, 0), "score": (500, 0)},
        {"intake": (1, 500), "score": (500, 0)}, {"intake": (1, 500)},
        {"live": (1, 500)}, {"winner": (1, 500), "score": (1, 500)}, {"score": (1, 500)}, {},
    ])
    collect = Mock(return_value=True)
    job.catch_up(lambda: next(states), collect, execute=True, deadline=float("inf"))
    assert [call.args[0] for call in collect.call_args_list] == ["intake", "live", "winner", "score"] * 2


def test_failed_or_stalled_stage_does_not_starve_independent_study():
    state = {"winner": (2, 10), "score": (1, 7)}
    def collect(stage, deadline):
        if stage == "score":
            state.pop(stage)
        return True
    with pytest.raises(RuntimeError, match="Unresolved"):
        job.catch_up(lambda: deepcopy(state), collect, execute=True, deadline=float("inf"))
    assert state == {"winner": (2, 10)}


def test_existing_run_finishes_before_retry_and_other_dates_can_make_progress():
    states = iter([{"live": (20, 70)}, {"live": (20, 70)}, {"live": (20, 570)}, {}])
    collect = Mock(side_effect=[False, True, True])
    job.catch_up(lambda: next(states), collect, execute=True, deadline=float("inf"))
    assert collect.call_count == 3


@pytest.mark.parametrize("execute,deadline", [(False, float("inf")), (True, 0)])
def test_preview_and_time_limit_cannot_dispatch(execute, deadline):
    collect = Mock()
    job.catch_up(lambda: {"score": (20, 0)}, collect, execute=execute, deadline=deadline)
    collect.assert_not_called()


def test_dispatch_protocol_and_existing_run(monkeypatch):
    api = Mock(side_effect=[{"workflow_runs": []}, {"workflow_run_id": 42},
                            {"status": "completed", "conclusion": "success"}])
    monkeypatch.setattr(job, "github", api)
    assert job.run_collector("winner", float("inf"))
    inputs = {"mode": "capture", "execute": "true", "limit": "500"}
    assert api.call_args_list[1].args == ("workflows/compare-winner-study.yml/dispatches",
                                          {"ref": "main", "inputs": inputs})
    assert api.call_args_list[2].args == ("runs/42",)
    api.reset_mock()
    api.side_effect = [{"workflow_runs": [{"status": "queued", "id": 7}]},
                       {"status": "completed", "conclusion": "success"}]
    assert not job.run_collector("intake", float("inf"))
    assert api.call_count == 2
    assert api.call_args.args == ("runs/7",)


def test_failed_originals_dispatch_pinned_error_queue_then_fill_children(monkeypatch):
    api = Mock(side_effect=[{"workflow_runs": []}, {"workflow_run_id": 42},
                            {"status": "completed", "conclusion": "success"}] * 4)
    monkeypatch.setattr(job, "github", api)
    states = iter([{"original_errors": (1, 200)}, {"live": (1, 150)},
                   {"winner": (1, 100), "score": (1, 100)}, {"score": (1, 100)}, {}])
    job.catch_up(lambda: next(states), job.run_collector, execute=True, deadline=float("inf"))
    dispatches = [c.args for c in api.call_args_list if len(c.args) == 2]
    assert dispatches[0] == ("workflows/weekly-prospective-refresh.yml/dispatches",
                             {"ref": "main", "inputs": {"execute": "true", "retry_errors": "true", "limit": "500"}})
    assert [path for path, _ in dispatches[1:]] == [
        "workflows/compare-live-monitoring.yml/dispatches", "workflows/compare-winner-study.yml/dispatches",
        "workflows/compare-score-study.yml/dispatches"]


@pytest.mark.parametrize("payload", [None, {"ref": "main"}])
def test_only_reads_retry_after_transport_failure(monkeypatch, payload):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    run = Mock(side_effect=[job.subprocess.CalledProcessError(1, "gh"), Mock(stdout='{"status":"queued"}')])
    monkeypatch.setattr(job.subprocess, "run", run)
    monkeypatch.setattr(job.time, "sleep", Mock())
    if payload is None:
        assert job.github("runs/42") == {"status": "queued"}
        assert run.call_count == 2
    else:
        with pytest.raises(job.subprocess.CalledProcessError):
            job.github("workflows/example/dispatches", payload)
        run.assert_called_once()


@pytest.mark.parametrize("archive_receipt", ["success", "failure", "skipped"])
def test_only_archived_partial_batches_are_rechecked_for_progress(monkeypatch, archive_receipt):
    steps = [{"name": "Freeze current Compare forecasts", "conclusion": "failure"},
             {"name": "Verify partial capture was archived", "conclusion": archive_receipt}]
    api = Mock(side_effect=[{"workflow_runs": []}, {"workflow_run_id": 42},
                            {"status": "completed", "conclusion": "failure"}, {"jobs": [{"steps": steps}]}])
    monkeypatch.setattr(job, "github", api)
    if archive_receipt == "success":
        assert job.run_collector("original_errors", float("inf"))
    else:
        with pytest.raises(RuntimeError, match="run 42: failure"):
            job.run_collector("original_errors", float("inf"))


def test_existing_writer_publication_failure_is_visible_even_after_queues_clear(monkeypatch):
    steps = [{"name": "Publish frozen forecast inputs privately", "conclusion": "failure"}]
    api = Mock(side_effect=[{"workflow_runs": [{"status": "in_progress", "id": 9}]},
                            {"status": "completed", "conclusion": "failure"}, {"jobs": [{"steps": steps}]}])
    monkeypatch.setattr(job, "github", api)
    states = iter([{"intake": (1, 10)}, {}])
    with pytest.raises(RuntimeError, match="queues are clear, but child workflows failed: intake"):
        job.catch_up(lambda: next(states), job.run_collector, execute=True, deadline=float("inf"))
    assert api.call_count == 3


def test_worker_activation_and_writes():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/compare-forecast-catchup.yml"
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert doc["on"]["schedule"] == [{"cron": "37 */4 * * *"}]
    assert doc["on"]["workflow_dispatch"]["inputs"]["execute"]["default"] == "false"
    runner = doc["jobs"]["catch-up"]
    assert runner["runs-on"] == "ubuntu-latest"
    assert "github.ref == 'refs/heads/main'" in runner["if"]
    assert runner["steps"][-1]["env"]["EXECUTE"] == "${{ github.event_name == 'schedule' || inputs.execute }}"


def test_closed_study_avoids_reading_fixture_or_outcome_tables(monkeypatch):
    monkeypatch.setenv("COMPARE_WINNER_STUDY_SIGNATURE", "a" * 64)
    monkeypatch.delenv("COMPARE_SCORE_STUDY_SIGNATURE", raising=False)
    client = Mock()
    query = client.table.return_value.select.return_value.eq.return_value.single.return_value
    query.execute.return_value.data = {"capture_start": "2020-01-01", "capture_end": "2020-01-28",
                                       "monitor_signature": "m"}
    assert job.coverage(client) == {}
    client.table.assert_called_once_with("compare_winner_studies")
    client.rpc.assert_not_called()


def test_open_study_uses_registered_parents_and_database_origins(monkeypatch):
    day = (job.datetime.now(job.timezone.utc).date() + timedelta(days=1)).isoformat()
    monkeypatch.setenv("COMPARE_WINNER_STUDY_SIGNATURE", "w")
    monkeypatch.delenv("COMPARE_SCORE_STUDY_SIGNATURE", raising=False)
    monkeypatch.setenv("COMPARE_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("COMPARE_MONITOR_ENABLED", "true")
    monkeypatch.setenv("COMPARE_MONITOR_REVISION", "rev")
    tables = {name: Mock() for name in ("compare_winner_studies", "compare_monitoring_models",
                                       "compare_monitoring_forecasts", "prospective_match_predictions")}
    client = Mock()
    client.table.side_effect = tables.__getitem__
    def single(table, signature, record):
        q = tables[table].select.return_value
        q.eq.side_effect = lambda key, value: q if (key, value) == ("signature", signature) else pytest.fail()
        q.single.return_value.execute.return_value.data = record
    single("compare_winner_studies", "w", {"capture_start": day, "capture_end": day, "monitor_signature": "m"})
    single("compare_monitoring_models", "m", {"manifest": {"code_revision": "rev"}})
    client.rpc.return_value.execute.return_value.data = [
        {"day": day, "missing_winner": 2, "paired": 9, "missing_current": 999},
        {"day": date.min.isoformat(), "missing_winner": 33, "paired": 7}]
    originals = tables["prospective_match_predictions"].select.return_value
    for method in ("eq", "gte", "lte", "order", "range"):
        getattr(originals, method).return_value = originals
    originals.execute.return_value.data = [{"id": i, "game_date": day} for i in ("a", "b")]
    saved = tables["compare_monitoring_forecasts"].select.return_value
    saved.eq.return_value.in_.return_value.execute.return_value.count = 1
    saved.in_.return_value.execute.return_value.count = 700
    inventory = Mock(return_value=([("g", {"game_date": day})], {}, [
        {"game_date": match_day, "source_system": source, "heuristic_prediction_status": status}
        for match_day, source, status in ((day, "database_games", "pending"), (day, "event_jsonl", "pending"),
                                          (day, "database_games", "error"), (day, "event_jsonl", "error"),
                                          (date.min.isoformat(), "database_games", "error"))]))
    monkeypatch.setattr(job, "database_fixture_inventory", inventory)
    assert job.coverage(client) == {"winner": (2, 9), "live": (1, 700), "intake": (2, 5), "original_errors": (1, 0)}
    originals.eq.assert_any_call("source_system", "database_games")
    originals.eq.assert_any_call("heuristic_prediction_status", "completed")
    saved.eq.assert_called_once_with("monitor_signature", "m")
    saved.eq.return_value.in_.assert_called_once_with("baseline_forecast_id", ["a", "b"])
    assert inventory.call_args.kwargs["include_predictions"] is False


def test_child_failure_still_attempts_other_due_collectors():
    state = {"winner": (2, 0), "score": (1, 0)}
    def collect(stage, deadline):
        if stage == "winner":
            raise RuntimeError("child failed")
        del state[stage]
        return True
    with pytest.raises(RuntimeError, match="Unresolved"):
        job.catch_up(lambda: state.copy(), collect, execute=True, deadline=float("inf"))
    assert list(state) == ["winner"]


def test_utc_rollover_replans_instead_of_blocking_a_productive_collector(monkeypatch):
    clock = Mock()
    clock.now.side_effect = [job.datetime(2026, 11, d, tzinfo=job.timezone.utc) for d in (20, 21, 21)]
    monkeypatch.setattr(job, "datetime", clock)
    states = iter([{"intake": (10, 2000)}, {"intake": (100, 1500)}, {}])
    collect = Mock(return_value=True)
    job.catch_up(lambda: next(states), collect, execute=True, deadline=float("inf"))
    assert collect.call_count == 2
