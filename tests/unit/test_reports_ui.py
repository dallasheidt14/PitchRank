"""Unit tests for ``src.tournaments.reports.ui``.

Covers the lazy compute-or-load gate (``ensure_report_card``), the
per-run lock contention path, the export-bundle helper (``zip_run_csvs``),
the audit-row projector, and the small label / format / filename helpers.

Reuses the fixture builders from ``test_reports_compute`` so the run-dir
scaffold matches the rest of the report-card suite.
"""

from __future__ import annotations

import contextlib
import io
import zipfile
from pathlib import Path

import pytest

from src.tournaments.reports.compute import (
    ReportCardError,
    compute_and_persist_report_card,
)
from src.tournaments.reports.schema import (
    BalanceScore,
    Metric,
    OverrideAuditRow,
    ReportCard,
)
from src.tournaments.reports.ui import (
    DISPLAY_COLS,
    derive_export_filenames,
    ensure_report_card,
    format_run_label,
    format_run_timestamp,
    project_audit_row,
    safe_read_comparison_json,
    zip_run_csvs,
)
from src.tournaments.storage.run_layout import RunLockError, acquire_run_lock
from tests.unit.test_reports_compute import (
    EVENT_KEY,
    RUN_ID,
    SCENARIO,
    _bootstrap,
    _write_division_recommendations,
    _write_summary,
)

# ---------------------------------------------------------------------------
# ensure_report_card
# ---------------------------------------------------------------------------


def test_ensure_report_card_loads_when_sentinel_exists(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    expected = compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert (run_path / "report_card.done").exists()

    rc = ensure_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert rc.run_id == expected.run_id
    assert rc.balance_score.optimized == pytest.approx(expected.balance_score.optimized)


def test_ensure_report_card_triggers_compute_when_sentinel_absent(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    assert not (run_path / "report_card.done").exists()

    rc = ensure_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    # Sentinel is now present and the returned card matches what's on disk.
    assert (run_path / "report_card.done").exists()
    assert (run_path / "comparison.json").exists()
    assert rc.run_id == RUN_ID


def test_ensure_report_card_raises_run_lock_error_on_contention(tmp_path: Path):
    """Holding ``runs/<run_id>/.report.lock`` externally makes the lazy
    trigger fail fast with ``RunLockError`` rather than blocking the UI."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    # Sentinel absent so the lock branch runs.
    assert not (run_path / "report_card.done").exists()

    with acquire_run_lock(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path, timeout=0.0):
        with pytest.raises(RunLockError):
            ensure_report_card(
                EVENT_KEY,
                SCENARIO,
                RUN_ID,
                base_dir=tmp_path,
                lock_timeout=0.05,
            )


def test_ensure_report_card_lost_update_guard_skips_recompute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When the sentinel appears between the outer check and the lock
    acquire, the inside-lock re-check loads via ``read_comparison_json``
    without re-running ``compute_and_persist_report_card``."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    # Persist a valid Report Card, then delete the sentinel so the outer
    # check at the top of ensure_report_card sees it absent.
    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    sentinel = run_path / "report_card.done"
    sentinel_bytes = sentinel.read_bytes()
    sentinel.unlink()

    # Replace acquire_run_lock with a stub that materializes the sentinel
    # mid-flight — simulates a sibling tab finishing compute between the
    # outer sentinel check and our lock acquire.
    @contextlib.contextmanager
    def _restoring_lock(*_args, **_kwargs):
        sentinel.write_bytes(sentinel_bytes)
        yield

    monkeypatch.setattr("src.tournaments.reports.ui.acquire_run_lock", _restoring_lock)

    # And make compute_and_persist_report_card raise so any leak through
    # the lost-update guard surfaces loudly.
    def _exploding_compute(*_args, **_kwargs):
        raise RuntimeError("compute_and_persist_report_card should not be called")

    monkeypatch.setattr(
        "src.tournaments.reports.ui.compute_and_persist_report_card",
        _exploding_compute,
    )

    rc = ensure_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert rc.run_id == RUN_ID


def test_ensure_report_card_normalizes_corrupt_json_to_report_card_error(tmp_path: Path):
    """A corrupt persisted ``comparison.json`` raises ``ReportCardError``,
    not the underlying ``json.JSONDecodeError`` / ``OSError``. Lets the
    UI catch a single typed exception."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    (run_path / "comparison.json").write_text("not json", encoding="utf-8")

    with pytest.raises(ReportCardError):
        ensure_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)


def test_ensure_report_card_normalizes_shape_invalid_json_to_report_card_error(tmp_path: Path):
    """JSON-valid but shape-invalid ``comparison.json`` (e.g. ``{}``,
    missing required keys) must surface as ``ReportCardError`` — not a
    raw ``KeyError`` from ``ReportCard.from_dict``'s bracket access.
    Guards the ``_LOAD_ERRORS`` swallow against the codex-flagged regression."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    # Empty object: ``schema_version`` defaults to 1 (lenient), but every
    # required field (event_key, run_id, balance_score, ...) is missing
    # so ``ReportCard.from_dict`` raises ``KeyError``.
    (run_path / "comparison.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReportCardError):
        ensure_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)


# ---------------------------------------------------------------------------
# safe_read_comparison_json
# ---------------------------------------------------------------------------


def test_safe_read_comparison_json_returns_card_when_well_formed(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    card = safe_read_comparison_json(run_path / "comparison.json")
    assert card is not None
    assert card.run_id == RUN_ID


def test_safe_read_comparison_json_returns_none_for_missing_file(tmp_path: Path):
    assert safe_read_comparison_json(tmp_path / "nonexistent.json") is None


def test_safe_read_comparison_json_returns_none_for_corrupt_json(tmp_path: Path):
    path = tmp_path / "comparison.json"
    path.write_text("not json", encoding="utf-8")
    assert safe_read_comparison_json(path) is None


def test_safe_read_comparison_json_returns_none_for_shape_invalid_json(tmp_path: Path):
    """JSON-valid but missing required keys must produce ``None``, not
    raise ``KeyError`` upward into the dropdown render."""
    path = tmp_path / "comparison.json"
    path.write_text("{}", encoding="utf-8")
    assert safe_read_comparison_json(path) is None


# ---------------------------------------------------------------------------
# zip_run_csvs
# ---------------------------------------------------------------------------


def test_zip_run_csvs_bundles_three_expected_files(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    blob = zip_run_csvs(run_path)
    assert isinstance(blob, bytes)

    with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
        names = sorted(archive.namelist())
        assert names == [
            "comparison_metrics.csv",
            "comparison_risk_flags.csv",
            "comparison_team_movements.csv",
        ]
        # Each entry round-trips verbatim against the on-disk file.
        for name in names:
            assert archive.read(name) == (run_path / name).read_bytes()


def test_zip_run_csvs_raises_when_csv_missing(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    compute_and_persist_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    (run_path / "comparison_risk_flags.csv").unlink()

    with pytest.raises(FileNotFoundError):
        zip_run_csvs(run_path)


# ---------------------------------------------------------------------------
# project_audit_row
# ---------------------------------------------------------------------------


def test_project_audit_row_picks_only_display_cols_and_drops_nested_fields():
    record = {
        "schema_version": 1,
        "ts": "2026-04-30T12:00:00+00:00",
        "actor": "ops@pitchrank.io",
        "type": "accept_match",
        "team_ref": "pid-1",
        "reason": "manual review",
        "delta_balance_score": None,
        "before": {"some": "nested"},
        "after": {"more": "nested"},
        "run_id": "u14_boys_test",
        "applied_at": "2026-04-30T12:00:00+00:00",
    }
    projected = project_audit_row(record)

    assert set(projected) == set(DISPLAY_COLS)
    assert "before" not in projected
    assert "after" not in projected
    assert "schema_version" not in projected
    assert projected["ts"] == "2026-04-30T12:00:00+00:00"
    assert projected["delta_balance_score"] == "n/a"


def test_project_audit_row_maps_none_delta_to_n_a():
    record = {"ts": "x", "actor": "y", "type": "z", "team_ref": "p", "reason": "r", "delta_balance_score": None}
    assert project_audit_row(record)["delta_balance_score"] == "n/a"


def test_project_audit_row_maps_empty_string_delta_to_n_a():
    record = {"ts": "x", "actor": "y", "type": "z", "team_ref": "p", "reason": "r", "delta_balance_score": ""}
    assert project_audit_row(record)["delta_balance_score"] == "n/a"


def test_project_audit_row_maps_missing_delta_to_n_a():
    """Scenario-level overrides (raw ``load_overrides`` records) lack the
    field entirely. The (None, "") predicate must still produce "n/a"."""
    record = {"ts": "x", "actor": "y", "type": "external", "team_ref": "p", "reason": "r"}
    assert project_audit_row(record)["delta_balance_score"] == "n/a"


def test_project_audit_row_preserves_numeric_delta():
    record = {"ts": "x", "actor": "y", "type": "z", "team_ref": "p", "reason": "r", "delta_balance_score": 1.5}
    assert project_audit_row(record)["delta_balance_score"] == 1.5


# ---------------------------------------------------------------------------
# format_run_label / format_run_timestamp
# ---------------------------------------------------------------------------


def test_format_run_timestamp_returns_unknown_for_none():
    assert format_run_timestamp(None) == "unknown"


def test_format_run_timestamp_returns_unknown_for_malformed():
    assert format_run_timestamp("not-a-date") == "unknown"
    assert format_run_timestamp("") == "unknown"


def test_format_run_timestamp_truncates_to_minute():
    assert format_run_timestamp("2026-04-30T12:34:56+00:00") == "2026-04-30 12:34"


def test_format_run_label_includes_truncated_timestamp_and_score():
    label = format_run_label("u14_boys_x", "2026-04-30T12:34:56+00:00", 78.4)
    assert label == "2026-04-30 12:34 · BS 78"


def test_format_run_label_renders_n_a_when_score_missing():
    label = format_run_label("u14_boys_x", "2026-04-30T12:34:56+00:00", None)
    assert label == "2026-04-30 12:34 · BS n/a"


def test_format_run_label_renders_unknown_timestamp_with_score():
    label = format_run_label("u14_boys_x", None, 81.0)
    assert label == "unknown · BS 81"


def test_format_run_label_renders_unknown_and_n_a_when_both_missing():
    assert format_run_label("u14_boys_x", None, None) == "unknown · BS n/a"


# ---------------------------------------------------------------------------
# derive_export_filenames
# ---------------------------------------------------------------------------


def _hand_card(*, event_name: str, gender: str, age_group: str, run_id: str) -> ReportCard:
    return ReportCard(
        event_key=EVENT_KEY,
        scenario=SCENARIO,
        run_id=run_id,
        age_group=age_group,
        gender=gender,
        event_name=event_name,
        computed_at="2026-04-30T12:00:00+00:00",
        balance_score=BalanceScore(actual=None, optimized=70.0, delta=None, preset_id="default"),
        metrics=(Metric(label="x", actual=None, optimized=0, delta=None, unit="count"),),
        risk_flags=(),
        top_reasons=(),
        team_movements=(),
        override_audit=(),
    )


def test_derive_export_filenames_produces_expected_keys():
    card = _hand_card(
        event_name="Phoenix Cup 2026",
        gender="Boys",
        age_group="u14",
        run_id="u14_boys_20260430T120000_aaaaaaaaaaaa",
    )
    names = derive_export_filenames(card)

    assert set(names) == {"html", "json", "zip"}
    assert names["html"].endswith(".html")
    assert names["zip"].endswith(".zip")
    assert names["json"].endswith(".json")


def test_derive_export_filenames_slugifies_spaces_and_unicode():
    card = _hand_card(
        event_name="Phoenix · Cup / 2026",  # contains separators + unicode dot
        gender="Boys",
        age_group="u14",
        run_id="u14_boys_x",
    )
    names = derive_export_filenames(card)

    # Slug collapses every non-alphanumeric run to a single underscore.
    assert "/" not in names["html"]
    assert " " not in names["html"]
    assert "·" not in names["html"]
    assert names["html"].startswith("report_card_Phoenix_Cup_2026_Boys_u14_")


def test_derive_export_filenames_no_path_traversal_chars():
    """All free-form fields slugify safely — no ``..`` / ``/`` / ``\\``
    can land in the on-disk filename a browser will write."""
    card = _hand_card(
        event_name="../../etc/passwd",
        gender="Boys/Girls",
        age_group="u14",
        run_id="u14_boys_x",
    )
    names = derive_export_filenames(card)

    for value in names.values():
        assert ".." not in value
        assert "/" not in value
        assert "\\" not in value


def test_derive_export_filenames_handles_all_blank_fields():
    """Empty/blank fields fall back to literal placeholders rather than
    producing ``report_card____.html``."""
    card = _hand_card(event_name="", gender="", age_group="", run_id="")
    names = derive_export_filenames(card)

    # ``card.run_id`` empty would slugify to "" — the helper substitutes
    # "run" so the filename remains parseable.
    assert "report_card_event_cohort_cohort_run" in names["html"]


# ---------------------------------------------------------------------------
# OverrideAuditRow integration with project_audit_row
# ---------------------------------------------------------------------------


def test_project_audit_row_works_on_override_audit_row_record():
    """Regression: OverrideAuditRow.record dicts survive projection
    untouched and the delta mapping fires for the orchestrator's
    hardcoded None."""
    row = OverrideAuditRow.from_dict(
        {
            "schema_version": 1,
            "ts": "2026-04-30T11:00:00+00:00",
            "actor": "ops",
            "type": "accept_match",
            "team_ref": "pid-1",
            "reason": "ok",
            "before": {"x": 1},
            "after": {"y": 2},
            "delta_balance_score": None,
        }
    )
    projected = project_audit_row(row.record)
    assert projected["type"] == "accept_match"
    assert projected["delta_balance_score"] == "n/a"
    assert "before" not in projected
