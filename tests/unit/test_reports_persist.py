"""Unit tests for ``compute_and_persist_report_card``.

End-to-end: build a fixture run dir, call the persist wrapper, verify
all six artifacts land in the run dir with the sentinel written last.
A partial-failure test monkeypatches the renderer to confirm cleanup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tournaments.reports import compute as reports_compute
from src.tournaments.reports.compute import (
    compute_and_persist_report_card,
    read_comparison_json,
)
from src.tournaments.storage._io import append_jsonl
from src.tournaments.storage.schema_version import stamp_schema_version
from tests.unit.test_reports_compute import (
    EVENT_KEY,
    RUN_ID,
    SCENARIO,
    _bootstrap,
    _write_division_recommendations,
    _write_summary,
)


def _seed_run_overrides_audit(run_path: Path) -> None:
    """Seed ``run_overrides_audit.jsonl`` with one schema-stamped row.

    Mirrors what ``run_orchestrator._write_run_overrides_audit`` produces:
    the source override dict spread plus ``run_id`` / ``applied_at`` /
    ``delta_balance_score=None``, schema-stamped before append.
    """
    record = {
        "ts": "2026-04-30T11:00:00+00:00",
        "actor": "ops@pitchrank.io",
        "type": "accept_match",
        "team_ref": "pid-1",
        "reason": "manual review",
        "before": {},
        "after": {},
        "run_id": RUN_ID,
        "applied_at": "2026-04-30T12:00:00+00:00",
        "delta_balance_score": None,
    }
    append_jsonl(run_path / "run_overrides_audit.jsonl", stamp_schema_version(record))


_ARTIFACTS: tuple[str, ...] = (
    "comparison.json",
    "comparison_metrics.csv",
    "comparison_risk_flags.csv",
    "comparison_team_movements.csv",
    "comparison.html",
    "report_card.done",
)


def test_compute_and_persist_writes_all_six_artifacts(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    for name in _ARTIFACTS:
        assert (run_path / name).exists(), f"missing artifact: {name}"
    # Round-trip the JSON canonical form back into a ReportCard.
    restored = read_comparison_json(run_path / "comparison.json")
    assert restored.balance_score.optimized == pytest.approx(rc.balance_score.optimized)
    assert restored.event_key == rc.event_key
    assert restored.run_id == rc.run_id


def test_sentinel_written_last(tmp_path: Path):
    """``report_card.done``'s mtime must be >= every other artifact."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    sentinel_mtime = (run_path / "report_card.done").stat().st_mtime
    for name in _ARTIFACTS:
        if name == "report_card.done":
            continue
        other = (run_path / name).stat().st_mtime
        # `>=` rather than strict `>`: filesystem mtime granularity on some
        # platforms (notably Windows NTFS at ~16 ms) can collapse adjacent
        # writes to the same value. The contract is "not earlier than", and
        # `>=` honors that without flaking on coarse timers.
        assert sentinel_mtime >= other, f"sentinel mtime older than {name}"


def test_partial_failure_cleans_up_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If ``write_html`` raises, no artifacts must survive on disk."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    # Patch the import target inside compute_and_persist_report_card.
    def _exploding_write_html(*args, **kwargs):
        raise RuntimeError("disk full")

    # ``src.tournaments.reports.render_html`` is shadowed in the package
    # namespace by the ``render_html`` function re-exported from
    # ``__init__.py`` (classic Python ``from package.foo import foo`` name
    # collision). Pull the actual module from ``sys.modules``.
    import importlib

    render_html_module = importlib.import_module("src.tournaments.reports.render_html")
    monkeypatch.setattr(render_html_module, "write_html", _exploding_write_html)

    with pytest.raises(RuntimeError, match="disk full"):
        compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    # All six artifacts must be absent — the cleanup loop ran.
    for name in _ARTIFACTS:
        assert not (run_path / name).exists(), f"leftover artifact after failure: {name}"


def test_compute_report_card_pure_does_not_write(tmp_path: Path):
    """``compute_report_card`` is the pure variant — no side effects."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    reports_compute.compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    for name in _ARTIFACTS:
        assert not (run_path / name).exists(), f"compute_report_card leaked artifact: {name}"


def test_comparison_html_retains_audit_details_block(tmp_path: Path):
    """``compute_and_persist_report_card → write_html → render_html →
    template`` chain must preserve the override-audit ``<details>`` block
    when ``card.override_audit`` is non-empty.

    Guards against accidental kwarg drops (Step 1b's ``show_override_audit``
    would silently suppress the block on a regression because Jinja's
    default Undefined is falsy)."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    _seed_run_overrides_audit(run_path)

    rc = compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert len(rc.override_audit) >= 1

    text = (run_path / "comparison.html").read_text(encoding="utf-8")
    assert text.count("rc-audit") >= 1
