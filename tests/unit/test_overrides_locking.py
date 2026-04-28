"""Concurrency tests for ``src.tournaments.storage.overrides.append_override``.

Pins Shell 09 Step 0's writer-tier scenario-lock fix: two concurrent
processes appending overrides for the same ``(event_key, scenario)``
must serialize through ``acquire_scenario_lock`` so every record lands
intact (no interleaved bytes, no lost writes).

Uses ``multiprocessing.Process`` rather than ``threading.Thread`` because
the underlying advisory locks (``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows) are per-fd; threads share the fd table
and can't faithfully simulate "two browser tabs hitting the same
Streamlit process pool".
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from src.tournaments.storage import (
    append_override,
    ensure_scenario,
)
from src.tournaments.storage.event_key import scenario_dir

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def _writer(base_dir: str, worker_id: int, iterations: int) -> None:
    """Append ``iterations`` overrides under the scenario lock.

    Each record carries ``worker_id`` and a per-worker ``seq`` so the
    parent test can verify per-process insertion order is preserved.
    """
    base_path = Path(base_dir)
    for seq in range(iterations):
        append_override(
            EVENT_KEY,
            SCENARIO,
            {
                "ts": "2026-04-26T12:00:00+00:00",
                "actor": "ops@example.com",
                "scope": "team",
                "type": "accept_match",
                "team_ref": f"pid-{worker_id}-{seq}",
                "before": {},
                "after": {"team_id_master": f"tim-{worker_id}-{seq}"},
                "reason": f"worker {worker_id} seq {seq}",
                "worker_id": worker_id,
                "seq": seq,
            },
            base_dir=base_path,
            timeout=10.0,
        )


def test_concurrent_writers_serialize_via_scenario_lock(tmp_path: Path) -> None:
    """Two child processes each append 100 overrides; the resulting JSONL
    must contain exactly 200 records, every line valid JSON, and per-worker
    insertion order preserved within each worker's ``seq`` stream."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    iterations = 100

    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(tmp_path), worker_id, iterations)) for worker_id in (1, 2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0, f"writer exited with {p.exitcode}"

    overrides_path = scenario_dir(EVENT_KEY, SCENARIO, base_dir=tmp_path) / "overrides.jsonl"
    text = overrides_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 2 * iterations, f"expected {2 * iterations} records, got {len(lines)}"

    by_worker: dict[int, list[int]] = {}
    for line in lines:
        # Every line must parse as valid JSON — no interleaved bytes.
        record = json.loads(line)
        worker_id = record["worker_id"]
        by_worker.setdefault(worker_id, []).append(record["seq"])

    # Per-worker insertion order is preserved within each worker's records.
    for worker_id, seqs in by_worker.items():
        assert seqs == list(range(iterations)), f"worker {worker_id} seq order broken: {seqs[:5]}..."
