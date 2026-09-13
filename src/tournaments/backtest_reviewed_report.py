"""Director-facing summary helpers for strict reviewed Backtest runs."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any


def observed_result_values(summary: dict[str, Any]) -> dict[str, int | float | None]:
    """Return observed aggregates without treating missing scores as zero-margin games."""

    actual = summary.get("actual_results") or {}
    game_count = int(actual.get("actual_game_count") or 0)
    return {
        "game_count": game_count,
        "average_goal_differential": (
            float(actual.get("average_goal_differential") or 0) if game_count else None
        ),
        "blowout_4plus_count": int(actual.get("blowout_4plus_count") or 0),
        "blowout_4plus_rate": (
            float(actual.get("blowout_4plus_rate") or 0) if game_count else None
        ),
    }


def actual_vs_matchbalance_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare captured results with the proposed MatchBalance projection."""

    observed = observed_result_values(summary)
    proposed = summary.get("proposed_model_projection") or {}
    specs = (
        (
            "Average goal margin",
            observed["average_goal_differential"],
            proposed.get("average_goal_differential"),
            "goals",
        ),
        (
            "4+ goal blowout rate",
            observed["blowout_4plus_rate"],
            proposed.get("blowout_4plus_probability"),
            "rate",
        ),
    )
    return [
        {
            "Metric": label,
            "Actual tournament": actual,
            "MatchBalance projection": matchbalance,
            "Estimated reduction": (
                float(actual) - float(matchbalance)
                if actual is not None and matchbalance is not None
                else None
            ),
            "Unit": unit,
        }
        for label, actual, matchbalance, unit in specs
    ]


def movement_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {"move_up": "Moved up", "move_down": "Moved down", "stay": "Stayed"}
    rows: list[dict[str, Any]] = []
    for item in summary.get("division_recommendations") or ():
        rows.append(
            {
                "Team": str(item.get("event_team_name") or item.get("canonical_team_name") or ""),
                "Original division": str(item.get("actual_division") or ""),
                "MatchBalance division": str(item.get("recommended_division") or ""),
                "Decision": labels.get(str(item.get("move") or ""), str(item.get("move") or "")),
                "Historical PowerScore": item.get("power_score"),
                "Rating evidence": _rating_evidence_label(item),
            }
        )
    return rows


def _rating_evidence_label(item: dict[str, Any]) -> str:
    basis = str(item.get("rating_basis") or "historical_snapshot")
    if basis == "original_division_median_surrogate":
        return "Division median fallback (team not found)"
    if basis == "cohort_median_surrogate":
        return "Cohort median fallback (team not found)"
    return "PitchRank pre-event rating"


def _format(value: Any, unit: str) -> str:
    if value is None:
        return "Unavailable"
    number = float(value)
    return f"{number * 100:.1f}%" if unit == "rate" else f"{number:.2f}"


def _format_reduction(value: Any, unit: str) -> str:
    if value is None:
        return "Unavailable"
    number = float(value)
    direction = "lower" if number >= 0 else "higher"
    return f"{_format(abs(number), unit)} {direction}"


def render_reviewed_backtest_html(
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """Create a self-contained sales-review report without changing evidence."""

    event_name = html.escape(str(summary.get("event_name") or metadata.get("event_name") or "Tournament"))
    cohort = summary.get("cohort") or {}
    cohort_label = html.escape(
        " ".join(
            part
            for part in (str(cohort.get("gender") or ""), str(cohort.get("age_group") or "").upper())
            if part
        )
    )
    observed = observed_result_values(summary)
    model_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['Metric']))}</td>"
        f"<td>{_format(row['Actual tournament'], str(row['Unit']))}</td>"
        f"<td>{_format(row['MatchBalance projection'], str(row['Unit']))}</td>"
        f"<td>{_format_reduction(row['Estimated reduction'], str(row['Unit']))}</td>"
        "</tr>"
        for row in actual_vs_matchbalance_rows(summary)
    )
    moves = movement_rows(summary)
    movement_rows_html = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['Team']))}</td>"
        f"<td>{html.escape(str(row['Original division']))}</td>"
        f"<td>{html.escape(str(row['MatchBalance division']))}</td>"
        f"<td>{html.escape(str(row['Decision']))}</td>"
        f"<td>{html.escape(str(row['Rating evidence']))}</td>"
        "</tr>"
        for row in moves
    )
    predictor = summary.get("predictor") or {}
    cutoff = html.escape(str(predictor.get("prediction_date") or metadata.get("prediction_date") or ""))
    artifact_hash = html.escape(str((summary.get("historical_inputs") or {}).get("model_artifact_sha256") or ""))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{event_name} Backtest</title>
<style>
body{{font-family:Arial,sans-serif;color:#17212b;max-width:1100px;margin:32px auto;padding:0 20px}}
h1{{margin-bottom:4px}} .muted{{color:#667085}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}}
.card{{border:1px solid #d0d5dd;border-radius:10px;padding:16px}}
.value{{font-size:28px;font-weight:700;margin-top:6px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}
th,td{{border-bottom:1px solid #eaecf0;padding:9px;text-align:left}}
th{{background:#f9fafb}} code{{font-size:11px;word-break:break-all}}
@media(max-width:760px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<p class="muted">MatchBalance completed-tournament Backtest</p><h1>{event_name}</h1>
<p>{cohort_label}</p>
<div class="cards">
<div class="card">Observed games<div class="value">{observed['game_count']}</div></div>
<div class="card">Observed average margin
<div class="value">{_format(observed['average_goal_differential'], 'goals')}</div></div>
<div class="card">Observed 4+ blowouts<div class="value">{observed['blowout_4plus_count']}</div></div>
<div class="card">Observed blowout rate
<div class="value">{_format(observed['blowout_4plus_rate'], 'rate')}</div></div>
<div class="card">Teams reseeded<div class="value">{sum(1 for row in moves if row['Decision'] != 'Stayed')}</div></div>
</div>
<p class="muted">The tournament column comes directly from captured results. The MatchBalance
column estimates the reseeded pool assignments using only pre-event evidence.</p>
<h2>Actual tournament versus MatchBalance</h2>
<table><thead><tr><th>Metric</th><th>Actual tournament</th><th>MatchBalance projection</th>
<th>Estimated reduction</th></tr></thead><tbody>{model_rows}</tbody></table>
<h2>Team placement</h2>
<table><thead><tr><th>Team</th><th>Original division</th><th>MatchBalance division</th>
<th>Decision</th><th>Rating evidence</th></tr></thead><tbody>{movement_rows_html}</tbody></table>
<h2>Historical evidence</h2><p>Exclusive event cutoff: <strong>{cutoff or 'Unavailable'}</strong></p>
<p>Model artifact SHA-256: <code>{artifact_hash or 'Unavailable'}</code></p>
</body></html>"""


def write_reviewed_backtest_html(
    path: Path,
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> Path:
    """Write the self-contained report atomically inside a staging run."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = render_reviewed_backtest_html(summary, metadata).encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path
