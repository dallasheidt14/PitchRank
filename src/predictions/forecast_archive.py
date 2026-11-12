"""Preserve the ledger's complete frozen inputs without changing its forecasts."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE, InputArchive

FORECAST_FIELDS = (
    "id,fixture_key,source_game_id,provider_code,source_system,game_date,home_team_master_id,away_team_master_id,"
    "evaluation_group_kind,evaluation_group_key,source_event_id,fixture_payload,"
    "heuristic_prediction_status,heuristic_model_version,heuristic_predicted_at,heuristic_prediction"
)


def archive_forecasts(
    client, source_root: Path, output: Path | None = None, *, dry_run: bool = True, today: date | None = None
):
    if not dry_run and output is None:
        raise ValueError("Local archive capture requires a new output directory")
    day = today or datetime.now(timezone.utc).date()
    first, last = [(day + timedelta(days=n)).isoformat() for n in (1, 7)]
    archive = None if dry_run else InputArchive(output, source_root, {
        "capture_kind": FORECAST_ARCHIVE_KIND, "window_start": first, "window_end": last,
        "database_writes_enabled": False,
    })
    observed_client = archive.wrap(client) if archive else client
    total, offset, coverage = 0, 0, Counter()
    success = False
    try:
        while True:
            rows = (observed_client.table(FORECAST_TABLE).select(FORECAST_FIELDS)
                    .eq("heuristic_prediction_status", "completed").gte("game_date", first).lte("game_date", last)
                    .order("id").range(offset, offset + 999).execute().data or [])
            for row in rows:
                if not first <= row["game_date"] <= last or row["heuristic_prediction_status"] != "completed":
                    raise ValueError("Forecast read returned a row outside the requested frozen window")
                cohort = (row.get("fixture_payload") or {}).get("cohort", "unknown")
                coverage[f"{row['provider_code']}|{cohort}"] += 1
            total += len(rows)
            if len(rows) < 1000:
                break
            offset += 1000
        success = True
    finally:
        if archive:
            archive.finish(success)
    return {
        "dry_run": dry_run, "window_start": first, "window_end": last, "archived_rows": total,
        "coverage": dict(sorted(coverage.items())), "published": False, "eligibility_certified": False,
    }
