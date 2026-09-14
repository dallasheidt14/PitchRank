"""Local evidence-quality report for Backtest historical ratings."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from src.tournaments.backtest_rating_fallback import (
    MISSING_HISTORY_FALLBACK_POLICY,
)


def _coverage_band(games_played: int) -> str:
    if games_played <= 2:
        return "0-2"
    if games_played <= 5:
        return "3-5"
    if games_played <= 10:
        return "6-10"
    if games_played <= 20:
        return "11-20"
    return "21+"


def _evidence_quality(check: Any) -> str:
    if not bool(check.eligible):
        return "ineligible"
    if str(check.rating_basis) != "historical_snapshot":
        if str(check.rating_fallback) == MISSING_HISTORY_FALLBACK_POLICY:
            return "missing_history_average"
        return "not_found_average"
    games_played = int(check.games_played or 0)
    if games_played >= 11:
        return "established_history"
    if games_played >= 6:
        return "moderate_history"
    return "limited_history"


def build_historical_coverage_report(preflight: Any) -> dict[str, Any]:
    """Summarize exactly which entrants depend on weak or average evidence."""

    entrants: list[dict[str, Any]] = []
    cohort_rows: list[dict[str, Any]] = []
    for cohort in preflight.cohorts:
        cohort_counts: Counter[str] = Counter()
        for check in cohort.entrants:
            quality = _evidence_quality(check)
            cohort_counts[quality] += 1
            entrants.append(
                {
                    **asdict(check),
                    "age_group": str(cohort.age_group),
                    "gender": str(cohort.gender),
                    "history_coverage_band": _coverage_band(int(check.games_played or 0)),
                    "evidence_quality": quality,
                    "needs_evidence_recovery": quality
                    in {
                        "ineligible",
                        "missing_history_average",
                        "not_found_average",
                        "limited_history",
                    },
                }
            )
        cohort_rows.append(
            {
                "age_group": str(cohort.age_group),
                "gender": str(cohort.gender),
                "total": int(cohort.total),
                "eligible": int(cohort.eligible),
                **dict(sorted(cohort_counts.items())),
            }
        )
    counts = Counter(row["evidence_quality"] for row in entrants)
    total = len(entrants)
    average_count = counts["missing_history_average"] + counts["not_found_average"]
    recovery_count = sum(bool(row["needs_evidence_recovery"]) for row in entrants)
    return {
        "schema_version": "matchbalance-historical-coverage-v1",
        "checked_at": str(preflight.checked_at),
        "cutoff_exclusive": str(preflight.cutoff_exclusive),
        "model_artifact_sha256": str(preflight.model_artifact_sha256),
        "summary": {
            "total_entrants": total,
            "eligible_entrants": sum(bool(row["eligible"]) for row in entrants),
            "average_estimate_entrants": average_count,
            "average_estimate_rate": average_count / total if total else 0.0,
            "evidence_recovery_entrants": recovery_count,
            "evidence_recovery_rate": recovery_count / total if total else 0.0,
            "counts_by_quality": dict(sorted(counts.items())),
        },
        "cohorts": cohort_rows,
        "entrants": entrants,
    }


def write_historical_coverage_report(preflight: Any, output_dir: str | Path) -> dict[str, str]:
    """Atomically write JSON and review-queue CSV beside the saved preflight."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    report = build_historical_coverage_report(preflight)
    json_path = destination / "historical_coverage.json"
    json_temporary = json_path.with_suffix(".json.tmp")
    json_temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    json_temporary.replace(json_path)

    csv_path = destination / "historical_coverage.csv"
    csv_temporary = csv_path.with_suffix(".csv.tmp")
    pd.DataFrame(report["entrants"]).sort_values(
        ["needs_evidence_recovery", "age_group", "gender", "event_team_name"],
        ascending=[False, True, True, True],
    ).to_csv(csv_temporary, index=False)
    csv_temporary.replace(csv_path)
    return {"json": str(json_path), "csv": str(csv_path)}
