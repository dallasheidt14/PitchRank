"""Drain private pregame queues through the registered collectors on main."""
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

from scripts.settle_prospective_match_predictions import _supabase_client
from src.predictions.prospective_fixtures import database_fixture_inventory, paged

WORKFLOWS = {
    "intake": "weekly-prospective-refresh.yml",
    "original_errors": "weekly-prospective-refresh.yml",
    "live": "compare-live-monitoring.yml",
    "winner": "compare-winner-study.yml",
    "score": "compare-score-study.yml",
}


def coverage(client):
    """Return (work due in study windows, completed work in the worker's full queue)."""
    today = datetime.now(timezone.utc).date()
    first, last = ((today + timedelta(days=n)).isoformat() for n in (1, 7))
    windows, monitor_windows, state = [], {}, {}
    for kind in ("winner", "score"):
        signature = os.getenv(f"COMPARE_{kind.upper()}_STUDY_SIGNATURE")
        if not signature:
            continue
        study = (client.table(f"compare_{kind}_studies").select("capture_start,capture_end,monitor_signature")
                 .eq("signature", signature).single().execute().data)
        start, end = max(first, study["capture_start"]), min(last, study["capture_end"])
        if start > end:
            continue
        windows.append((start, end))
        monitor_windows.setdefault(study["monitor_signature"], []).append((start, end))
        rows = client.rpc(f"compare_{kind}_coverage", {"p_signature": signature}).execute().data
        rows = [row for row in rows if start <= row["day"] <= end]
        state[kind] = (sum(r[f"missing_{kind}"] for r in rows), sum(r["paired"] for r in rows))

    if not windows:
        return state
    if os.getenv("COMPARE_MONITOR_ENABLED") == "true":
        # Only database-origin originals enter the registered monitor queue.
        originals = list(paged(lambda: client.table("prospective_match_predictions").select("id,game_date")
                               .eq("source_system", "database_games").eq("heuristic_prediction_status", "completed")
                               .gte("game_date", first).lte("game_date", last).order("id")))
        missing_live = 0
        for signature, spans in monitor_windows.items():
            model = (client.table("compare_monitoring_models").select("manifest").eq("signature", signature)
                     .single().execute().data)
            compatible = model["manifest"]["code_revision"] == os.environ["COMPARE_MONITOR_REVISION"]
            ids = [r["id"] for r in originals if any(lo <= r["game_date"] <= hi for lo, hi in spans)]
            for offset in range(0, len(ids), 100):
                batch = ids[offset:offset + 100]
                saved = (client.table("compare_monitoring_forecasts").select("baseline_forecast_id",
                         count="exact", head=True).eq("monitor_signature", signature)
                         .in_("baseline_forecast_id", batch).execute().count)
                missing = len(batch) - saved
                if compatible:
                    missing_live += missing
                elif missing:
                    state["incompatible_monitor"] = (missing + state.get("incompatible_monitor", (0, 0))[0], 0)
        # The monitor works oldest-first, including games before the study opens.
        count = (client.table("compare_monitoring_forecasts").select("baseline_forecast_id", count="exact", head=True)
                 .in_("monitor_signature", sorted(monitor_windows)).execute().count)
        state["live"] = (missing_live, count)
    if os.getenv("COMPARE_CAPTURE_ENABLED") == "true":
        candidates, _, originals = database_fixture_inventory(client, today=today, include_predictions=False)

        def in_study(day):
            return any(start <= day <= end for start, end in windows)

        pending = sum(in_study(row["game_date"]) for row in originals
                      if row["source_system"] == "database_games" and row["heuristic_prediction_status"] == "pending")
        new = sum(in_study(row["game_date"]) for _, row in candidates)
        completed = sum(row["heuristic_prediction_status"] in ("completed", "skipped")
                        for row in originals if row["source_system"] == "database_games")
        state["intake"] = (new + pending, len(originals) + completed)
        errors = sum(in_study(row["game_date"]) for row in originals
                     if row["source_system"] == "database_games" and row["heuristic_prediction_status"] == "error")
        if errors:
            state["original_errors"] = (errors, completed)
    return state


def github(path, payload=None):
    command = ["gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10",
               f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/{path}"]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    # GitHub sometimes returns an error on the first status read for a newly dispatched run.
    # POST is never retried: a lost response can still mean the collector started.
    for attempt in range(3):
        try:
            result = subprocess.run(command, input=json.dumps(payload) if payload else None, capture_output=True,
                                    text=True, check=True, timeout=60)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if payload is not None or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def run_collector(stage, deadline):
    workflow = WORKFLOWS[stage]
    runs = github(f"workflows/{workflow}/runs?branch=main&per_page=100")["workflow_runs"]
    busy = [r for r in runs if r["status"] != "completed"]
    if busy:
        run_id = busy[0]["id"]
        print(f"Waiting for existing {stage} run {run_id}")
        # Revisit a busy collector after giving independent queues their turn.
        deadline = min(deadline, time.monotonic() + 60)
    else:
        inputs = {"execute": "true", "limit": "500"}
        if stage == "original_errors":
            inputs["retry_errors"] = "true"
        elif stage != "intake":
            inputs["mode"] = "capture"
        run_id = github(f"workflows/{workflow}/dispatches", {"ref": "main", "inputs": inputs})["workflow_run_id"]
        print(f"Started {stage} run {run_id}")
    while time.monotonic() < deadline:
        run = github(f"runs/{run_id}")
        if run["status"] == "completed":
            if run["conclusion"] != "success" and (not busy or run["conclusion"] == "failure"):
                if stage in ("intake", "original_errors") and run["conclusion"] == "failure":
                    jobs = github(f"runs/{run_id}/jobs")["jobs"]
                    if len(jobs) == 1:
                        steps = {s["name"]: s["conclusion"] for s in jobs[0]["steps"]}
                        failures = [name for name, result in steps.items() if result == "failure"]
                        if (failures == ["Freeze current Compare forecasts"]
                                and steps.get("Verify partial capture was archived") == "success"):
                            print(f"Run {run_id} archived a partial batch; checking remaining forecast work.")
                            return not busy
                raise RuntimeError(f"{stage} run {run_id}: {run['conclusion']}")
            return not busy
        time.sleep(30)
    print(f"Run {run_id} is still active; coverage will be checked again.")
    return False


def catch_up(snapshot, collect, *, execute, deadline):
    observed_day = datetime.now(timezone.utc).date()
    state = snapshot()
    blocked, failed = set(), set()
    while True:
        print("Remaining:", {stage: counts[0] for stage, counts in state.items()})
        due = [s for s in WORKFLOWS if state.get(s, (0, 0))[0] and s not in blocked]
        if not execute or not due or time.monotonic() >= deadline:
            break
        for stage in WORKFLOWS:
            if stage in blocked or not state.get(stage, (0, 0))[0] or time.monotonic() >= deadline:
                continue
            before = state[stage]
            try:
                dispatched = collect(stage, deadline)
            except (RuntimeError, subprocess.SubprocessError) as error:
                print(f"Collector failed: {error}")
                blocked.add(stage)
                failed.add(stage)
                dispatched = False
            next_day = datetime.now(timezone.utc).date()
            state = snapshot()
            if next_day != observed_day:
                # The rolling seven-day queue has a different denominator after UTC midnight.
                observed_day = next_day
                blocked = failed.copy()
                continue
            remaining, completed = state.get(stage, (0, 0))
            if dispatched and remaining >= before[0] and completed <= before[1]:
                print(f"{stage} made no progress; inspect the collector run.")
                blocked.add(stage)
    unresolved = blocked | {"original_errors", "incompatible_monitor"}
    if execute and failed and not any(due_count for due_count, _ in state.values()):
        raise RuntimeError(f"Forecast queues are clear, but child workflows failed: {', '.join(sorted(failed))}. "
                           "Check their logs and archive publication.")
    if execute and (failed or any(state.get(s, (0, 0))[0] for s in unresolved)):
        raise RuntimeError("Unresolved collector errors; see counts and run IDs above")
    if due and execute:
        print("Time budget reached; the next scheduled check will resume.")


if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = _supabase_client()
    catch_up(lambda: coverage(client), run_collector, execute=os.getenv("EXECUTE") == "true",
             deadline=time.monotonic() + 120 * 60)
