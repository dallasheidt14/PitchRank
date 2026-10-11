"""Tests for the team-cleanup status command, driven through main()."""

import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import run_store as rs  # noqa: E402
from scripts.team_cleanup import status  # noqa: E402

RUN = "2026-10-14-nv"


def _run(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["status.py", *argv])
    code = status.main()
    return code, capsys.readouterr().out


def _mark(store, stage, *markers):
    folder = rs.stage_dir(store, RUN, stage)
    folder.mkdir(parents=True, exist_ok=True)
    for marker in markers:
        (folder / marker).write_text("{}", encoding="utf-8")
    return folder


def test_the_open_run_shows_each_stage_s_next_step(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    rs.write_run(store, {"run_id": "2026-10-07-ut", "scope": {}, "status": "done"})
    rs.write_run(
        store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "reviewing", "stages": {"clubs": "skill_stale"}}
    )
    _mark(store, "reconcile", "preflight.json", "propose_done", "page.json", "collected.json", "RECORD.md")
    _mark(store, "states", "preflight.json")
    merges = _mark(store, "merges", "preflight.json", "propose_done")
    (merges / "review").mkdir()
    pair = {"merge_id": "m1", "keep_id": "k1", "merge_name": "A", "keep_name": "B"}
    (merges / "review" / "prop01.json").write_text(json.dumps([pair]), encoding="utf-8")
    (merges / "review" / "prop01_review.json").write_text(json.dumps([{**pair, "keep_id": "k9"}]), encoding="utf-8")
    (merges / "review" / "prop02.json").write_text(json.dumps([pair]), encoding="utf-8")

    code, out = _run(monkeypatch, capsys, "--store", str(store))

    assert code == 0
    assert out.splitlines() == [
        f"Run {RUN} (reviewing), scope {{'states': ['NV']}}",
        "  reconcile  finished",
        "  clubs      skill_stale",
        "  states     next: write the stage's proposals",
        "  ages       next: run the stage's skill self-check",
        "  merges     next: review the queued proposals (2 queued: prop01, prop02)",
        "             set aside merges/review/prop01_review.json.bad",
    ]


def test_with_no_open_run_it_names_the_latest(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    rs.write_run(store, {"run_id": "2026-10-07-ut", "scope": {}, "status": "done"})

    code, out = _run(monkeypatch, capsys, "--store", str(store))

    assert (code, out.strip()) == (0, f"No open run in {store}; the latest is 2026-10-07-ut (done).")


def test_the_store_comes_from_the_environment(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(rs.STORE_ENV, str(tmp_path / "env-store"))

    _, out = _run(monkeypatch, capsys)

    assert out.strip() == f"No open run in {(tmp_path / 'env-store').resolve()}."


def test_a_closed_run_can_be_shown_by_name(monkeypatch, capsys, tmp_path):
    store = tmp_path / "store"
    rs.write_run(store, {"run_id": "2026-10-07-ut", "scope": {}, "status": "done"})

    _, out = _run(monkeypatch, capsys, "--store", str(store), "--run", "2026-10-07-ut")

    assert out.splitlines()[0] == "Run 2026-10-07-ut (done), scope {}"


@pytest.mark.parametrize(
    "run_id, message",
    [
        ("2026-10-21-ks", "No run 2026-10-21-ks in"),
        ("../ks", "Cannot read run ../ks"),
        ("2026-10-22-wi", "Cannot read run 2026-10-22-wi"),
    ],
    ids=["unknown", "malformed", "another-run-s-file"],
)
def test_an_unknown_or_unreadable_run_exits_with_a_message(monkeypatch, capsys, tmp_path, run_id, message):
    (tmp_path / "runs" / "2026-10-22-wi").mkdir(parents=True)
    (tmp_path / "runs" / "2026-10-22-wi" / rs.RUN_FILE).write_text(
        json.dumps({"run_id": RUN, "status": "reviewing"}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as stopped:
        _run(monkeypatch, capsys, "--store", str(tmp_path), "--run", run_id)
    assert str(stopped.value.code).startswith(message)


def test_a_relative_store_exits_with_a_message(monkeypatch, capsys):
    monkeypatch.setenv(rs.STORE_ENV, "cleanup-runs")

    with pytest.raises(SystemExit) as stopped:
        _run(monkeypatch, capsys)
    assert str(stopped.value.code) == "the run store must be an absolute path, not 'cleanup-runs'"


def test_a_relative_store_flag_exits_with_a_message(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stopped:
        _run(monkeypatch, capsys, "--store", "cleanup-runs")
    assert str(stopped.value.code) == "the run store must be an absolute path, not 'cleanup-runs'"
