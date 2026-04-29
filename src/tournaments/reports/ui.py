"""Streamlit-free helpers for the Shell 08 Report Card UI surface.

Sibling to ``compute.py`` / ``render_html.py`` / ``render_csv.py``. Holds
the lazy compute-or-load gate (``ensure_report_card``), the export-bundle
helper (``zip_run_csvs``), the audit-row projector (``project_audit_row``),
and the small label/format/filename helpers consumed by ``tournament_intake.py``.

Streamlit MUST NOT be imported here so unit tests can exercise these
helpers without a Streamlit runtime.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.tournaments.reports.compute import (
    ReportCardError,
    compute_and_persist_report_card,
    read_comparison_json,
)
from src.tournaments.reports.render_csv import REPORT_CARD_CSV_NAMES
from src.tournaments.reports.schema import ReportCard
from src.tournaments.storage.event_key import run_dir as _run_dir
from src.tournaments.storage.run_layout import acquire_run_lock
from src.tournaments.storage.schema_version import SchemaVersionError

__all__ = [
    "DISPLAY_COLS",
    "derive_export_filenames",
    "ensure_report_card",
    "format_run_label",
    "format_run_timestamp",
    "project_audit_row",
    "safe_read_comparison_json",
    "zip_run_csvs",
]


DISPLAY_COLS: tuple[str, ...] = (
    "ts",
    "actor",
    "type",
    "team_ref",
    "reason",
    "delta_balance_score",
)
"""Columns surfaced in the Shell 08 override-audit panel.

Nested ``before`` / ``after`` / ``schema_version`` keys are deliberately
omitted — pandas would render them as object-repr cells and clutter the
display. ``project_audit_row`` projects each record down to this set
before the dataframe is built.
"""


_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")

_LOAD_ERRORS: tuple[type[BaseException], ...] = (
    SchemaVersionError,
    ValueError,
    json.JSONDecodeError,
    FileNotFoundError,
    OSError,
    KeyError,
    TypeError,
    AttributeError,
)
"""Exceptions ``read_comparison_json`` may raise that should normalize
to ``ReportCardError``. Covers the I/O layer (``OSError`` / ``FileNotFoundError``),
the JSON layer (``json.JSONDecodeError`` / ``ValueError``), the schema-version
gate (``SchemaVersionError``), AND the structural-shape layer (``KeyError`` /
``TypeError`` / ``AttributeError``) — the last group covers JSON-valid but
shape-invalid payloads (``[]``, ``{}``, missing nested keys) that would
otherwise bubble through ``ReportCard.from_dict``'s bracket-access reads.
"""


def _load_persisted_card(comparison_path: Path, run_id: str) -> ReportCard:
    """Read ``comparison.json``, normalizing failure modes to ``ReportCardError``.

    Used by both branches of ``ensure_report_card`` (outer sentinel-hit
    fast path and inside-lock lost-update guard) so the swallow-list and
    error-message format live in one place.
    """
    try:
        return read_comparison_json(comparison_path)
    except _LOAD_ERRORS as exc:
        raise ReportCardError(f"Cannot load Report Card for run {run_id!r}: {exc}") from exc


def safe_read_comparison_json(comparison_path: Path) -> ReportCard | None:
    """Best-effort read of ``comparison.json``; returns ``None`` on any failure.

    Used by render-time helpers that need the persisted Report Card for
    display labels (e.g. the previous-runs dropdown's optimized-score
    column) but must NOT explode the surrounding render when a single
    legacy / corrupt artifact exists. Catches the same exception family
    as ``_load_persisted_card`` plus ``ReportCardError`` itself, since the
    underlying ``read_comparison_json`` may raise it via the schema gate.
    """
    try:
        return read_comparison_json(comparison_path)
    except (ReportCardError, *_LOAD_ERRORS):
        return None


def ensure_report_card(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
    lock_timeout: float = 30.0,
) -> ReportCard:
    """Sentinel-gated lazy compute-or-load.

    If ``runs/<run_id>/report_card.done`` exists, read the cached
    ``comparison.json``. Otherwise acquire the per-run lock at
    ``runs/<run_id>/.report.lock`` (with ``lock_timeout`` to absorb
    concurrent-tab contention), re-check the sentinel inside the critical
    section (lost-update guard so a sibling tab that just finished
    computing isn't recomputed redundantly), then call
    ``compute_and_persist_report_card``.

    All non-lock failures (corrupt ``comparison.json``, schema mismatch,
    missing artifacts, OS errors) are normalized to ``ReportCardError`` so
    the caller's UI branch only needs to catch ``ReportCardError`` and
    ``RunLockError``.
    """
    run_dir_path = _run_dir(event_key, scenario, run_id, base_dir=base_dir)
    sentinel = run_dir_path / "report_card.done"
    comparison_path = run_dir_path / "comparison.json"

    if sentinel.exists():
        return _load_persisted_card(comparison_path, run_id)

    with acquire_run_lock(event_key, scenario, run_id, base_dir=base_dir, timeout=lock_timeout):
        # Lost-update guard: a sibling tab may have completed the compute
        # between our sentinel check above and the lock acquire here.
        if sentinel.exists():
            return _load_persisted_card(comparison_path, run_id)
        try:
            return compute_and_persist_report_card(event_key, scenario, run_id, base_dir=base_dir)
        except (ReportCardError, *_LOAD_ERRORS) as exc:
            raise ReportCardError(f"Cannot load Report Card for run {run_id!r}: {exc}") from exc


def zip_run_csvs(run_dir_path: Path) -> bytes:
    """Bundle the Report Card CSVs into an in-memory ZIP.

    Reads each entry of ``REPORT_CARD_CSV_NAMES`` from ``run_dir_path``
    (typically the promoted ``runs/<run_id>/`` directory) and bundles them
    with ``ZIP_DEFLATED``. Sourcing the filename list from ``render_csv``
    keeps the export bundle in sync if a fourth CSV ever lands.

    Raises ``FileNotFoundError`` if any expected CSV is missing — callers
    translate that to a user-visible warning. Post-
    ``compute_and_persist_report_card`` all three are written atomically
    by ``render_all_csv``, so this should not occur in normal operation.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in REPORT_CARD_CSV_NAMES:
            csv_path = run_dir_path / name
            archive.writestr(name, csv_path.read_bytes())
    return buffer.getvalue()


def project_audit_row(record: dict[str, Any]) -> dict[str, Any]:
    """Project an override-audit record to the display columns.

    Picks ``DISPLAY_COLS`` from ``record`` (defaulting missing keys to
    empty string), then maps both ``delta_balance_score=None`` (the per-run
    audit's hardcoded value at ``run_orchestrator.py:702``) and missing /
    empty values (scenario-level records read from ``load_overrides`` lack
    the field entirely) to the literal string ``"n/a"`` BEFORE pandas
    coerces ``None`` to NaN. The ``(None, "")`` predicate is required —
    ``is None`` alone would leave the missing-key path producing an empty
    cell, inconsistent with per-run rows.
    """
    projected = {key: record.get(key, "") for key in DISPLAY_COLS}
    if projected["delta_balance_score"] in (None, ""):
        projected["delta_balance_score"] = "n/a"
    return projected


def format_run_timestamp(iso_string: str | None) -> str:
    """Format an ISO-8601 timestamp as ``YYYY-MM-DD HH:MM`` (wall-clock, minute-truncated).

    Does NOT convert non-UTC offsets — the displayed wall-clock time is
    whatever the source string encodes. All current writers
    (``utc_now_iso`` and ``run_metadata.json``) emit ``+00:00``, so the
    label is effectively UTC today; legacy/external payloads with other
    offsets would render in their source timezone.

    Returns the literal ``"unknown"`` for ``None`` or unparseable input
    rather than raising — the dropdown's ``format_func`` calls this for
    every visible run, so a single legacy/corrupt ``run_metadata.json``
    must not explode the entire selectbox render.
    """
    if iso_string is None:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(iso_string)
    except (TypeError, ValueError):
        return "unknown"
    return parsed.strftime("%Y-%m-%d %H:%M")


def format_run_label(
    run_id: str,
    ended_at: str | None,
    balance_score_optimized: float | None,
) -> str:
    """Build a fixed-format label for the previous-runs ``selectbox``.

    Format: ``"{ts} · BS {score}"`` — ``ts`` from ``format_run_timestamp``
    (``"unknown"`` fallback) and ``score`` rounded to integer or ``"n/a"``
    when the run pre-dates the Report Card sentinel write.
    """
    ts_display = format_run_timestamp(ended_at)
    if balance_score_optimized is None:
        return f"{ts_display} · BS n/a"
    return f"{ts_display} · BS {balance_score_optimized:.0f}"


def derive_export_filenames(card: ReportCard) -> dict[str, str]:
    """Return ``{"html", "json", "zip"}`` filenames for the export buttons.

    Slug pattern: ``report_card_<event_slug>_<gender>_<age>_<run_id>.<ext>``.
    All free-form fields run through ``re.sub(r"[^a-zA-Z0-9]+", "_", ...)``
    so spaces, slashes, and Unicode characters are normalized into
    ASCII-safe segments — no path-traversal characters can land in
    ``file_name``.
    """
    event_slug = _SLUG_RE.sub("_", card.event_name).strip("_") or "event"
    gender_slug = _SLUG_RE.sub("_", card.gender).strip("_") or "cohort"
    age_slug = _SLUG_RE.sub("_", card.age_group).strip("_") or "cohort"
    run_slug = _SLUG_RE.sub("_", card.run_id).strip("_") or "run"
    stem = f"report_card_{event_slug}_{gender_slug}_{age_slug}_{run_slug}"
    return {
        "html": f"{stem}.html",
        "json": f"{stem}.json",
        "zip": f"{stem}.zip",
    }
