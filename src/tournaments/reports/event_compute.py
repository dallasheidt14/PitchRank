"""Event-wide rollup across all completed cohort runs in a scenario.

Loads one ``ReportCard`` per cohort (latest completed run wins), aggregates
them into an ``EventReportCard`` for the tournament-level view a TD wants
("how did Presidents Day go overall?" not "how did U13 Boys go?").

Pure compute — ``compute_event_report_card`` returns the dataclass;
``write_event_report_card`` is the side-effecting wrapper that persists it
to ``reports/<event_key>/scenarios/<scenario>/event_report.json``.

Per-cohort run resolution:
- Walks ``list_runs(event_key, scenario, completed_only=True)`` (excludes
  .failed / .cancelled / .tmp).
- For each cohort key ``(age, gender)``, picks the latest run id
  (alphabetic last == chronological last; the run-id timestamp is UTC
  ISO-compact format, so lexical sort == time sort).
- Loads ``comparison.json`` if the report-card sentinel exists; falls back
  to ``compute_report_card(...)`` on the fly otherwise (read-only — does
  not persist).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.tournaments.reports.compute import compute_report_card, read_comparison_json
from src.tournaments.reports.schema import (
    BetterExperienceRow,
    CohortScorecardRow,
    EarlyMeetingConcern,
    EventReportCard,
    ReportCard,
)
from src.tournaments.storage import (
    list_runs,
    read_event_metadata,
    stamp_schema_version,
)
from src.tournaments.storage._io import utc_now_iso, write_json
from src.tournaments.storage.event_key import run_dir as _run_dir

__all__ = [
    "compute_event_report_card",
    "write_event_report_card",
    "event_report_path",
]

# Top N teams per event-wide leaderboard. 10 is the user-stated cut.
EVENT_LEADERBOARD_TOP_N: int = 10


def event_report_path(event_key: str, scenario: str, *, base_dir: Path | str = "reports") -> Path:
    return Path(base_dir) / event_key / "scenarios" / scenario / "event_report.json"


def _parse_cohort_from_run_id(run_id: str) -> tuple[str, str] | None:
    """``"u13_male_20260502T193917_b3208167eed1"`` -> ``("u13", "male")``.

    Returns ``None`` if the prefix doesn't match the expected shape so
    legacy run-id formats don't crash the rollup.
    """
    parts = run_id.split("_")
    if len(parts) < 4:
        return None
    age, gender = parts[0], parts[1]
    if not age.startswith("u") or gender not in ("male", "female"):
        return None
    return age, gender


def _latest_run_per_cohort(
    event_key: str, scenario: str, *, base_dir: Path | str
) -> list[tuple[tuple[str, str], str]]:
    """Pick the latest completed run per ``(age, gender)`` cohort.

    ``list_runs(..., completed_only=True)`` returns runs with ``done.json``
    present, sorted ascending by name. Run-id timestamps embed UTC in
    ``YYYYMMDDTHHMMSS`` form, so the last entry per cohort is the most
    recent in time. Returns ``[((age, gender), run_id), ...]`` in cohort
    age-then-gender order.
    """
    runs = list_runs(event_key, scenario, completed_only=True, base_dir=base_dir)
    latest: dict[tuple[str, str], str] = {}
    for run_id in runs:
        cohort = _parse_cohort_from_run_id(run_id)
        if cohort is None:
            continue
        latest[cohort] = run_id  # asc sort means later iteration wins
    return sorted(latest.items(), key=lambda kv: (kv[0][0], kv[0][1]))


def _load_or_compute_report_card(
    event_key: str, scenario: str, run_id: str, *, base_dir: Path | str
) -> ReportCard:
    """Prefer the persisted ``comparison.json``; fall back to in-process compute.

    Recomputes when the persisted card is missing the new fields
    (headline_summary / division_balance / etc.), so legacy reports
    written before those fields existed don't poison the rollup with
    zero-team / zero-balance rows.
    """
    run_path = _run_dir(event_key, scenario, run_id, base_dir=base_dir)
    sentinel = run_path / "report_card.done"
    comparison = run_path / "comparison.json"
    if sentinel.exists() and comparison.exists():
        card = read_comparison_json(comparison)
        if card.headline_summary is not None:
            return card
        # Legacy card pre-dates headline_summary; recompute fresh so the
        # event rollup gets accurate per-cohort numbers.
    return compute_report_card(event_key, scenario, run_id, base_dir=base_dir)


def _safe_weighted_avg(values: list[tuple[float, int]]) -> float | None:
    """Weighted average over ``[(value, weight), ...]`` pairs.

    Returns ``None`` when total weight is zero. Skips ``None`` value
    entries upstream — caller filters before passing in.
    """
    total_weight = sum(w for _, w in values)
    if total_weight == 0:
        return None
    return sum(v * w for v, w in values) / total_weight


def _aggregate_metric(
    cards: list[ReportCard], pick: str, weight: str
) -> float | None:
    """Compute the weighted average of ``headline_summary.<pick>`` across
    cohorts, weighted by each cohort's ``headline_summary.<weight>``-derived
    proxy. ``weight`` here is always team_count or match_count (proxies for
    cohort size).
    """
    pairs: list[tuple[float, int]] = []
    for card in cards:
        if card.headline_summary is None:
            continue
        value = getattr(card.headline_summary, pick, None)
        weight_value = getattr(card.headline_summary, weight, 0)
        if value is None or not weight_value:
            continue
        pairs.append((float(value), int(weight_value)))
    return _safe_weighted_avg(pairs)


def _build_cohort_scorecard(card: ReportCard) -> CohortScorecardRow:
    """One ReportCard -> one row in the event-level scorecard table."""
    hs = card.headline_summary
    optimized_match_count = sum(d.optimized_match_count for d in card.division_balance)
    return CohortScorecardRow(
        age_group=card.age_group,
        gender=card.gender,
        run_id=card.run_id,
        team_count=hs.team_count if hs else 0,
        division_count=len(card.division_balance),
        balance_score_optimized=card.balance_score.optimized,
        data_quality_penalty=card.balance_score.data_quality_penalty,
        better_experience_count=hs.better_experience_count if hs else 0,
        asked_to_step_up_count=hs.asked_to_step_up_count if hs else 0,
        actual_avg_gd=hs.actual_avg_gd if hs else None,
        optimized_avg_gd=hs.optimized_avg_gd if hs else None,
        actual_blowout_5plus_rate=hs.actual_blowout_5plus_rate if hs else None,
        optimized_blowout_5plus_rate=hs.optimized_blowout_5plus_rate if hs else None,
        optimized_match_count=optimized_match_count,
        concerns_count=len(card.early_meeting_concerns),
    )


def _aggregate_event_leaderboards(
    cards: list[ReportCard], *, top_n: int = EVENT_LEADERBOARD_TOP_N
) -> tuple[tuple[BetterExperienceRow, ...], tuple[BetterExperienceRow, ...]]:
    """Combine all cohorts' better/worse leaderboards into event-wide top N."""
    all_better: list[BetterExperienceRow] = []
    all_worse: list[BetterExperienceRow] = []
    for card in cards:
        all_better.extend(card.better_experience)
        all_worse.extend(card.worse_experience)
    all_better.sort(key=lambda r: (-r.pain_reduction, r.team_name))
    all_worse.sort(key=lambda r: (-r.pain_reduction, r.team_name))
    return tuple(all_better[:top_n]), tuple(all_worse[:top_n])


def _aggregate_event_concerns(cards: list[ReportCard]) -> tuple[EarlyMeetingConcern, ...]:
    """Concatenate per-cohort concerns; sort kind, division, home_team_name."""
    all_concerns: list[EarlyMeetingConcern] = []
    for card in cards:
        all_concerns.extend(card.early_meeting_concerns)
    all_concerns.sort(key=lambda c: (c.kind, c.division_name, c.home_team_name))
    return tuple(all_concerns)


def compute_event_report_card(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> EventReportCard:
    """Build the event-wide rollup. Raises ``ValueError`` if no completed
    cohorts are present (no runs to aggregate)."""
    pairs = _latest_run_per_cohort(event_key, scenario, base_dir=base_dir)
    if not pairs:
        raise ValueError(
            f"No completed runs found in {event_key}/{scenario}. "
            "Run at least one cohort backtest before generating the event report."
        )

    cards: list[ReportCard] = []
    for _cohort, run_id in pairs:
        cards.append(
            _load_or_compute_report_card(event_key, scenario, run_id, base_dir=base_dir)
        )

    meta = read_event_metadata(event_key, base_dir=base_dir)
    event_name = meta.event_name

    cohort_scorecards = tuple(sorted(
        (_build_cohort_scorecard(card) for card in cards),
        key=lambda r: (r.age_group, r.gender),
    ))

    balance_scores = [card.balance_score.optimized for card in cards]
    avg_balance = sum(balance_scores) / len(balance_scores) if balance_scores else 0.0

    total_team_count = sum(
        (card.headline_summary.team_count if card.headline_summary else 0) for card in cards
    )

    event_better, event_worse = _aggregate_event_leaderboards(cards)
    event_concerns = _aggregate_event_concerns(cards)

    # Per-cohort champion roll-up: one row per (cohort, division) with both
    # actual and projected winners side by side. Stored as plain dicts (not
    # Champion dataclasses) so the event template can render them in a single
    # table without a complex zip; also lets the JSON consumer walk this
    # without importing the Champion class.
    cohort_champions: list[dict[str, Any]] = []
    for card in cards:
        actual_by_div = {c.division_name: c for c in card.actual_champions}
        proj_by_div = {c.division_name: c for c in card.projected_champions}
        for division in sorted(set(actual_by_div) | set(proj_by_div)):
            ac = actual_by_div.get(division)
            pc = proj_by_div.get(division)
            cohort_champions.append({
                "age_group": card.age_group,
                "gender": card.gender,
                "division_name": division,
                "actual_team_name": ac.team_name if ac else None,
                "actual_record": f"{ac.wins}-{ac.losses}-{ac.ties}" if ac else None,
                "actual_goal_differential": ac.goal_differential if ac else None,
                "projected_team_name": pc.team_name if pc else None,
                "projected_record": f"{pc.wins}-{pc.losses}-{pc.ties}" if pc else None,
                "projected_goal_differential": pc.goal_differential if pc else None,
                "same_team": bool(ac and pc and ac.canonical_team_id == pc.canonical_team_id),
            })

    return EventReportCard(
        event_key=event_key,
        scenario=scenario,
        event_name=event_name,
        computed_at=utc_now_iso(),
        cohort_count=len(cards),
        total_team_count=total_team_count,
        avg_balance_score_optimized=avg_balance,
        min_balance_score_optimized=min(balance_scores),
        max_balance_score_optimized=max(balance_scores),
        aggregate_actual_avg_gd=_aggregate_metric(cards, "actual_avg_gd", "team_count"),
        aggregate_optimized_avg_gd=_aggregate_metric(cards, "optimized_avg_gd", "team_count"),
        aggregate_actual_close_game_rate=_aggregate_metric(cards, "actual_close_game_rate", "team_count"),
        aggregate_optimized_close_game_rate=_aggregate_metric(cards, "optimized_close_game_rate", "team_count"),
        aggregate_actual_blowout_5plus_rate=_aggregate_metric(cards, "actual_blowout_5plus_rate", "team_count"),
        aggregate_optimized_blowout_5plus_rate=_aggregate_metric(cards, "optimized_blowout_5plus_rate", "team_count"),
        cohort_scorecards=cohort_scorecards,
        event_better_experience=event_better,
        event_worse_experience=event_worse,
        event_concerns=event_concerns,
        cohort_champions=tuple(cohort_champions),
    )


def write_event_report_card(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> tuple[EventReportCard, Path]:
    """Side-effecting wrapper: compute + persist to ``event_report.json``.

    Returns ``(event_card, written_path)``. Atomic via ``write_json``'s
    tmp+rename. Stamps schema_version. Overwrites any existing file.
    """
    card = compute_event_report_card(event_key, scenario, base_dir=base_dir)
    out_path = event_report_path(event_key, scenario, base_dir=base_dir)
    payload = stamp_schema_version(card.to_dict(), version=card.schema_version)
    write_json(out_path, payload)
    return card, out_path
