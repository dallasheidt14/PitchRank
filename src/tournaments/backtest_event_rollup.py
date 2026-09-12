"""Event-wide rollup for reviewed MatchBalance Backtest cohort runs."""

from __future__ import annotations

import html
import io
import json
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from src.tournaments.backtest_intake_state import (
    BacktestSnapshot,
    effective_roster,
    tournament_totals,
)
from src.tournaments.backtest_reviewed_run import (
    ReviewedCohortReadiness,
    ReviewedRunRecord,
    load_reviewed_run,
)


@dataclass(frozen=True)
class SelectedCohortRun:
    readiness: ReviewedCohortReadiness
    record: ReviewedRunRecord
    summary: dict[str, Any]
    metadata: dict[str, Any]


def _request_sha(request: dict[str, Any] | None) -> str:
    import hashlib

    if request is None:
        return ""
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _remaining_status(readiness: ReviewedCohortReadiness) -> str:
    blockers = " ".join(readiness.blockers).casefold()
    if "match" in blockers or "team" in blockers:
        return "awaiting_matches"
    if "histor" in blockers or "rating" in blockers or "model" in blockers:
        return "awaiting_history"
    if blockers:
        return "awaiting_review"
    return "ready"


def select_compatible_runs(
    snapshot: BacktestSnapshot,
    readiness: Iterable[ReviewedCohortReadiness],
    records: Iterable[ReviewedRunRecord],
    *,
    model_sha256: str | None,
) -> tuple[tuple[SelectedCohortRun, ...], tuple[dict[str, Any], ...]]:
    """Select the newest current run for each cohort without mixing evidence."""

    records_by_cohort: dict[tuple[str, str], list[ReviewedRunRecord]] = {}
    for record in records:
        records_by_cohort.setdefault((record.age_group, record.gender), []).append(record)
    for cohort_records in records_by_cohort.values():
        cohort_records.sort(key=lambda item: (item.ended_at, item.run_id), reverse=True)
    selected: list[SelectedCohortRun] = []
    coverage: list[dict[str, Any]] = []
    for item in readiness:
        match: SelectedCohortRun | None = None
        failed_reason = ""
        for record in records_by_cohort.get((item.age_group, item.gender), ()):
            try:
                metadata = json.loads((record.run_dir / "run_metadata.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if metadata.get("source_capture_generation") != snapshot.generation:
                continue
            if metadata.get("request_sha256") != _request_sha(item.request):
                continue
            if model_sha256 and metadata.get("model_artifact_sha256") != model_sha256:
                continue
            if record.state == "failed":
                failed_reason = record.error or "The latest compatible run failed"
                break
            try:
                summary, metadata = load_reviewed_run(record)
            except (OSError, ValueError, TypeError):
                continue
            if (summary.get("seeding_comparison") or {}).get("status") != "comparable":
                continue
            match = SelectedCohortRun(item, record, summary, metadata)
            break
        status = "completed" if match else ("failed" if failed_reason else _remaining_status(item))
        coverage.append(
            {
                "age_group": item.age_group,
                "gender": item.gender,
                "team_count": item.team_count,
                "division_count": item.division_count,
                "status": status,
                "run_id": match.record.run_id if match else None,
                "what_remains": "" if match else (failed_reason or "; ".join(item.blockers)),
            }
        )
        if match:
            selected.append(match)
    return tuple(selected), tuple(coverage)


def _weighted_projection(
    selected: Iterable[SelectedCohortRun],
    key: str,
) -> tuple[float | None, int]:
    total = 0.0
    matchups = 0
    for run in selected:
        projection = run.summary.get(key) or {}
        value = projection.get("average_goal_differential")
        count = int(projection.get("projected_matchup_count") or 0)
        if value is None or count <= 0:
            continue
        total += float(value) * count
        matchups += count
    return (total / matchups if matchups else None), matchups


def _weighted_probability(
    selected: Iterable[SelectedCohortRun],
    projection_key: str,
) -> tuple[float | None, int]:
    total = 0.0
    matchups = 0
    for run in selected:
        projection = run.summary.get(projection_key) or {}
        value = projection.get("blowout_4plus_probability")
        count = int(projection.get("projected_matchup_count") or 0)
        if value is None or count <= 0:
            continue
        total += float(value) * count
        matchups += count
    return (total / matchups if matchups else None), matchups


def build_event_rollup(
    snapshot: BacktestSnapshot,
    readiness: Iterable[ReviewedCohortReadiness],
    records: Iterable[ReviewedRunRecord],
    *,
    model_sha256: str | None = None,
) -> dict[str, Any]:
    """Combine compatible cohort outputs into one honest tournament summary."""

    selected, coverage = select_compatible_runs(
        snapshot,
        readiness,
        records,
        model_sha256=model_sha256,
    )
    original_margin, original_matchups = _weighted_projection(selected, "original_model_projection")
    proposed_margin, proposed_matchups = _weighted_projection(selected, "proposed_model_projection")
    original_blowout, original_blowout_matchups = _weighted_probability(
        selected, "original_model_projection"
    )
    proposed_blowout, proposed_blowout_matchups = _weighted_probability(
        selected, "proposed_model_projection"
    )
    movements: list[dict[str, Any]] = []
    seen_entries: set[str] = set()
    duplicate_entries: set[str] = set()
    for run in selected:
        for row in run.summary.get("division_recommendations") or ():
            entry_id = str(row.get("entrant_id") or "")
            identity = entry_id or f"{run.readiness.age_group}|{run.readiness.gender}|{row.get('event_team_name')}"
            if identity in seen_entries:
                duplicate_entries.add(identity)
                continue
            seen_entries.add(identity)
            movements.append(dict(row))
    move_counts = Counter(str(row.get("move") or "stay") for row in movements)
    coverage_counts = Counter(row["status"] for row in coverage)
    totals = tournament_totals(effective_roster(snapshot))
    actual = totals["results"]
    complete_4plus = (
        original_blowout_matchups == original_matchups
        and proposed_blowout_matchups == proposed_matchups
        and original_matchups > 0
    )
    return {
        "schema_version": 1,
        "event": {
            "event_id": snapshot.roster.event_id,
            "event_name": totals["event_name"],
            "event_start_date": getattr(snapshot.roster, "event_start_date", None),
            "event_end_date": getattr(snapshot.roster, "event_end_date", None),
            "capture_generation": snapshot.generation,
        },
        "actual_results": {
            "game_count": int(actual["scored_games"]),
            "total_goal_margin": int(actual["total_goal_margin"]),
            "average_goal_margin": actual["average_goal_margin"],
            "blowout_4plus_count": int(actual["blowout_games"]),
            "blowout_4plus_rate": (
                float(actual["blowout_percentage"]) / 100.0
                if actual["blowout_percentage"] is not None
                else None
            ),
        },
        "modelled_pool_matchups": {
            "original_count": original_matchups,
            "matchbalance_count": proposed_matchups,
            "original_average_goal_margin": original_margin,
            "matchbalance_average_goal_margin": proposed_margin,
            "goal_margin_improvement": (
                original_margin - proposed_margin
                if original_margin is not None and proposed_margin is not None
                else None
            ),
            "original_blowout_4plus_rate": original_blowout if complete_4plus else None,
            "matchbalance_blowout_4plus_rate": proposed_blowout if complete_4plus else None,
            "blowout_4plus_rate_improvement": (
                original_blowout - proposed_blowout
                if complete_4plus and original_blowout is not None and proposed_blowout is not None
                else None
            ),
            "scope_note": "Frozen-model projections for intra-pool matchups in completed cohorts",
        },
        "team_movements": {
            "evaluated": len(movements),
            "moved_up": move_counts["move_up"],
            "moved_down": move_counts["move_down"],
            "unchanged": move_counts["stay"],
            "duplicate_entry_ids_skipped": sorted(duplicate_entries),
            "rows": movements,
        },
        "coverage": {
            "total_cohorts": len(coverage),
            "completed": coverage_counts["completed"],
            "failed": coverage_counts["failed"],
            "awaiting_matches": coverage_counts["awaiting_matches"],
            "awaiting_review": coverage_counts["awaiting_review"],
            "awaiting_history": coverage_counts["awaiting_history"],
            "ready": coverage_counts["ready"],
            "rows": list(coverage),
        },
        "selected_runs": [run.record.run_id for run in selected],
        "model_artifact_sha256": model_sha256,
    }


def _format(value: Any, *, rate: bool = False) -> str:
    if value is None:
        return "Unavailable"
    return f"{float(value) * 100:.1f}%" if rate else f"{float(value):.2f}"


def render_event_rollup_html(rollup: dict[str, Any]) -> str:
    event = rollup["event"]
    actual = rollup["actual_results"]
    modelled = rollup["modelled_pool_matchups"]
    coverage = rollup["coverage"]
    movements = rollup["team_movements"]
    coverage_rows = "".join(
        f"<tr><td>{html.escape(str(row['gender']))} {html.escape(str(row['age_group']).upper())}</td>"
        f"<td>{row['team_count']}</td><td>{html.escape(str(row['status']).replace('_', ' ').title())}</td>"
        f"<td>{html.escape(str(row['what_remains']))}</td></tr>"
        for row in coverage["rows"]
    )
    movement_rows = "".join(
        f"<tr><td>{html.escape(str(row.get('event_team_name') or ''))}</td>"
        f"<td>{html.escape(str(row.get('actual_division') or ''))}</td>"
        f"<td>{html.escape(str(row.get('recommended_division') or ''))}</td>"
        f"<td>{html.escape(str(row.get('move') or '').replace('_', ' ').title())}</td></tr>"
        for row in movements["rows"]
    )
    original_margin = _format(modelled["original_average_goal_margin"])
    matchbalance_margin = _format(modelled["matchbalance_average_goal_margin"])
    margin_improvement = _format(modelled["goal_margin_improvement"])
    original_blowout = _format(modelled["original_blowout_4plus_rate"], rate=True)
    matchbalance_blowout = _format(modelled["matchbalance_blowout_4plus_rate"], rate=True)
    blowout_improvement = _format(modelled["blowout_4plus_rate_improvement"], rate=True)
    model_sha = html.escape(str(rollup.get("model_artifact_sha256") or "Unavailable"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(str(event['event_name']))} MatchBalance Backtest</title><style>
body{{font-family:Arial,sans-serif;color:#17212b;max-width:1120px;margin:32px auto;padding:0 20px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:20px 0}}
.card{{border:1px solid #d0d5dd;border-radius:10px;padding:15px}}.value{{font-size:26px;font-weight:700}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}
th,td{{border-bottom:1px solid #eaecf0;padding:9px;text-align:left}}
th{{background:#f9fafb}}.muted{{color:#667085}}</style></head><body>
<p class="muted">MatchBalance completed-tournament Backtest</p><h1>{html.escape(str(event['event_name']))}</h1>
<p>{html.escape(str(event.get('event_start_date') or ''))} to {html.escape(str(event.get('event_end_date') or ''))}</p>
<h2>Tournament results</h2><div class="cards">
<div class="card">Observed games<div class="value">{actual['game_count']}</div></div>
<div class="card">Observed average margin<div class="value">{_format(actual['average_goal_margin'])}</div></div>
<div class="card">Observed 4+ blowouts<div class="value">{actual['blowout_4plus_count']}</div></div>
<div class="card">Observed blowout rate
<div class="value">{_format(actual['blowout_4plus_rate'], rate=True)}</div></div></div>
<h2>Original projected versus MatchBalance</h2><p class="muted">{html.escape(modelled['scope_note'])}.</p>
<table><thead><tr><th>Metric</th><th>Original</th><th>MatchBalance</th><th>Improvement</th></tr></thead><tbody>
<tr><td>Average goal margin</td><td>{original_margin}</td><td>{matchbalance_margin}</td>
<td>{margin_improvement}</td></tr>
<tr><td>4+ blowout rate</td><td>{original_blowout}</td><td>{matchbalance_blowout}</td>
<td>{blowout_improvement}</td></tr></tbody></table>
<h2>Team movement</h2><div class="cards">
<div class="card">Moved up<div class="value">{movements['moved_up']}</div></div>
<div class="card">Moved down<div class="value">{movements['moved_down']}</div></div>
<div class="card">Unchanged<div class="value">{movements['unchanged']}</div></div></div>
<table><thead><tr><th>Team</th><th>Original division</th>
<th>MatchBalance division</th><th>Decision</th></tr></thead><tbody>{movement_rows}</tbody></table>
<h2>Cohort coverage</h2><p>{coverage['completed']} of {coverage['total_cohorts']} cohorts complete.</p>
<table><thead><tr><th>Cohort</th><th>Teams</th><th>Status</th><th>What remains</th></tr></thead>
<tbody>{coverage_rows}</tbody></table>
<p class="muted">Model SHA-256: {model_sha}</p>
</body></html>"""


def event_rollup_export(rollup: dict[str, Any]) -> bytes:
    """Return one portable director package with HTML and machine-readable JSON."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tournament-director-report.html", render_event_rollup_html(rollup))
        archive.writestr("tournament-backtest-rollup.json", json.dumps(rollup, indent=2, sort_keys=True))
    return buffer.getvalue()
