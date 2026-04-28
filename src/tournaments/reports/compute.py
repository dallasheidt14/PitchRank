"""Build a ``ReportCard`` from a Shell 06 cohort run dir.

The Report Card is the commercial proof-of-value artifact — what
tournament directors see after a backtest run completes. ``compute.py``
reads ``summary.json`` (Shell 06's authoritative output), the run-dir
auxiliary JSONL files (``fallbacks.jsonl``, ``run_overrides_audit.jsonl``,
``division_recommendations.json``), and scenario-level metadata /
registry / overrides via the public storage facade — then computes every
metric, risk flag, top reason, and team movement that lands on the
Report Card.

No new backtest logic lives here; all numbers are derived from Shell 06
artifacts.

**Cohort identity vocab — deviation from spec.** The plan reads cohort
identity from ``summary.json["cohort"]`` but Shell 06 normalizes
``gender`` to ``"Male"/"Female"`` (cf.
``scripts/backtest_tournament_cohort.py:864`` ``normalize_gender_label``).
The registry CSV, override ledger, and ``run_orchestrator._override_in_cohort``
all use ``"Boys"/"Girls"``. This module reads ``run_metadata.json``
(orchestrator-emitted at ``run_orchestrator.py:594``) so ``cohort_gender``
matches the rest of the storage layer — required for the
``recompute_medians`` cohort-key check (``f"{age}_{gender}"`` is written
in registry vocab at ``tournament_intake.py:1930``).

**Frozen-median invariant** (spec §12) is enforced upstream by Shell 06's
CLI argv path; ``compute.py`` does not re-validate it.

**Concurrency** — ``compute_and_persist_report_card`` is NOT safe to run
concurrently for the same ``(event_key, scenario, run_id)``. Concurrent
calls race the per-file ``.tmp → final`` renames and the sentinel-write
order. Callers (Shell 06 orchestrator, Shell 08 UI) must serialize.
"""

from __future__ import annotations

import datetime as _datetime
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from src.tournaments.reports.schema import (
    BalanceScore,
    Metric,
    OverrideAuditRow,
    ReportCard,
    RiskFlag,
    TeamMovement,
    TopReason,
)
from src.tournaments.storage import (
    EventMetadata,
    SchemaVersionError,
    assert_supported_version,
    load_overrides,
    read_event_metadata,
    read_registry,
    stamp_schema_version,
)
from src.tournaments.storage._io import (
    read_json,
    read_jsonl,
    utc_now_iso,
    write_json,
)
from src.tournaments.storage.event_key import run_dir as _run_dir
from src.tournaments.triage import (
    ProjectedCohortState,
    ProjectedTeamState,
    _is_placeholder_team,
    project_overrides,
)

__all__ = [
    "EARLY_STAGES",
    "LOW_GAMES_THRESHOLD",
    "STALE_SNAPSHOT_DAYS",
    "TOP_REASON_TEMPLATES",
    "ReportCardError",
    "compute_and_persist_report_card",
    "compute_report_card",
    "read_comparison_json",
    "write_comparison_json",
]


LOW_GAMES_THRESHOLD: int = 6
"""Entrants with fewer than this many games trigger a ``low_games`` flag."""

STALE_SNAPSHOT_DAYS: int = 7
"""``ranking_snapshot_date`` older than this many days before
``event_start_date`` triggers a ``stale_ranking_snapshot`` warning. Strict
``>`` boundary — exactly 7 days is not flagged.
"""

EARLY_STAGES: frozenset[str] = frozenset({"Pool", "Semi Final A", "Semi Final B"})
"""Stages considered "early" for same-club + rematch counting. Sourced
from ``schedule_simulator.py:337, 362, 370`` — the only place ``stage``
literals are written. ``"Final"`` and ``"Third Place"`` are excluded.
"""

TOP_REASON_TEMPLATES: dict[str, str] = {
    "blowout_5plus": "Reduced 5+ goal mismatches from {actual_count} games to {optimized_count} ({pct_change:+.0%}).",
    "one_goal_rate": "Raised one-goal games from {actual_pct:.0%} to {optimized_pct:.0%} of the schedule.",
    "same_club_early": "Removed {removed_count} same-club early matchups.",
    "same_coach_early": "Removed {removed_count} same-coach pool conflicts.",
    "rematches": "Eliminated {removed_count} intra-event rematches.",
    "avg_gd": "Tightened average goal differential from {actual_avg:.2f} to {optimized_avg:.2f}.",
}
"""Top-reason templates keyed by metric. Insertion order is the stable
secondary sort key (Python 3.7+ dicts preserve it) so
``test_reports_compute.py`` can assert exact ordering on tied magnitudes.
"""


_ARTIFACT_NAMES: tuple[str, ...] = (
    "comparison.json",
    "comparison_metrics.csv",
    "comparison_risk_flags.csv",
    "comparison_team_movements.csv",
    "comparison.html",
    "report_card.done",
)


class ReportCardError(RuntimeError):
    """Raised when a run dir's invariants prevent Report Card computation.

    Examples: missing ``done.json`` (run not completed), missing
    ``run_metadata.json``, malformed ``summary.json``.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extras(meta: EventMetadata) -> dict[str, Any]:
    """Single-source the ``extras = meta.extras or {}`` guard.

    Convention anchor: ``run_orchestrator.py:345``. Centralizing this
    keeps the ``or {}`` default from drifting across the metric branches
    that read from ``extras``.
    """
    return meta.extras or {}


def _parse_iso_date(value: str | None) -> _datetime.date | None:
    if not value:
        return None
    try:
        return _datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _comparison_json_path(run_dir_path: Path) -> Path:
    return run_dir_path / "comparison.json"


def _iter_optimized_matches(optimized_proj: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every per-``SimulatedMatch`` row across all divisions."""
    for division in optimized_proj.get("divisions") or []:
        for match in division.get("matches") or []:
            yield match


def _capped_avg_gd(matches: list[dict[str, Any]], cap: int) -> float | None:
    """Mean of ``min(margin_i, cap)`` over per-match goal differentials."""
    if not matches:
        return None
    return float(sum(min(int(m["goal_differential"]), cap) for m in matches) / len(matches))


def _count_same_club_early(
    matches: list[dict[str, Any]],
    entrants_by_id: dict[str, dict[str, Any]],
) -> int:
    same_club = 0
    for m in matches:
        if m.get("stage") not in EARLY_STAGES:
            continue
        home = entrants_by_id.get(str(m.get("home_team_id") or ""))
        away = entrants_by_id.get(str(m.get("away_team_id") or ""))
        if home is None or away is None:
            continue
        home_club = home.get("club_name")
        away_club = away.get("club_name")
        if home_club and away_club and home_club == away_club:
            same_club += 1
    return same_club


def _count_intra_event_rematches(matches: list[dict[str, Any]]) -> int:
    """Count unordered ``(home, away)`` pairs that recur within EARLY_STAGES."""
    pair_counts: dict[frozenset[str], int] = {}
    for m in matches:
        if m.get("stage") not in EARLY_STAGES:
            continue
        home_id = str(m.get("home_team_id") or "")
        away_id = str(m.get("away_team_id") or "")
        if not home_id or not away_id:
            continue
        pair = frozenset({home_id, away_id})
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    return sum(1 for count in pair_counts.values() if count > 1)


def _count_total_early_meetings(matches: list[dict[str, Any]]) -> int:
    return sum(1 for m in matches if m.get("stage") in EARLY_STAGES)


def _read_run_metadata(run_dir_path: Path) -> dict[str, Any]:
    """Read ``run_metadata.json``; raise ``ReportCardError`` if missing.

    The orchestrator (``run_orchestrator.execute_run``) writes this file
    BEFORE Popen-spawn, so a promoted run dir always carries it.
    """
    path = run_dir_path / "run_metadata.json"
    if not path.exists():
        raise ReportCardError(
            f"run_metadata.json missing at {path}; cannot determine cohort identity"
        )
    payload = read_json(path)
    try:
        assert_supported_version(payload, source=str(path))
    except SchemaVersionError as exc:
        raise ReportCardError(str(exc)) from exc
    return payload


def _build_metrics(
    actual_results: dict[str, Any],
    optimized_proj: dict[str, Any],
    same_club_early_count: int,
    rematch_count: int,
    capped_gd_limit: int,
) -> tuple[Metric, ...]:
    """Eight-row metrics tuple. Sign convention for ``delta``:

    - GD / blowout / 3+ blowout / 5+ blowout: ``actual - optimized`` so a
      positive delta is improvement (lower is better).
    - One-goal rate: ``optimized - actual`` so positive delta is
      improvement (higher is better).
    """
    matches = list(_iter_optimized_matches(optimized_proj))
    capped_optimized = _capped_avg_gd(matches, capped_gd_limit)

    actual_avg_gd = float(actual_results["average_goal_differential"])
    opt_avg_gd = float(optimized_proj["average_goal_differential"])
    actual_close = float(actual_results["close_game_rate"])
    opt_close = float(optimized_proj["close_game_rate"])
    actual_3plus = float(actual_results["blowout_3plus_rate"])
    opt_3plus = float(optimized_proj["blowout_3plus_rate"])
    actual_5plus = float(actual_results["blowout_5plus_rate"])
    opt_5plus = float(optimized_proj["blowout_5plus_rate"])

    return (
        Metric(
            label="Expected avg GD (raw)",
            actual=actual_avg_gd,
            optimized=opt_avg_gd,
            delta=actual_avg_gd - opt_avg_gd,
            unit="gd",
        ),
        Metric(
            label=f"Expected avg GD (capped at {capped_gd_limit}; actual unavailable in v1)",
            actual=None,
            optimized=capped_optimized,
            delta=None,
            unit="gd",
        ),
        Metric(
            label="One-goal game rate",
            actual=actual_close,
            optimized=opt_close,
            delta=opt_close - actual_close,
            unit="rate",
        ),
        Metric(
            label="3+ goal blowout rate",
            actual=actual_3plus,
            optimized=opt_3plus,
            delta=actual_3plus - opt_3plus,
            unit="rate",
        ),
        Metric(
            label="5+ goal blowout rate",
            actual=actual_5plus,
            optimized=opt_5plus,
            delta=actual_5plus - opt_5plus,
            unit="rate",
        ),
        Metric(
            label="Same-club early meetings (actual unavailable in v1)",
            actual=None,
            optimized=int(same_club_early_count),
            delta=None,
            unit="count",
        ),
        Metric(
            label="Same-coach early meetings (coach data unavailable in v1)",
            actual=None,
            optimized=None,
            delta=None,
            unit="count",
        ),
        Metric(
            label="Intra-event rematches (actual unavailable in v1)",
            actual=None,
            optimized=int(rematch_count),
            delta=None,
            unit="count",
        ),
    )


def _compute_balance_score(
    optimized_proj: dict[str, Any],
    same_club_early_count: int,
    rematch_count: int,
    extras: dict[str, Any],
) -> tuple[BalanceScore, list[RiskFlag]]:
    """Compute the optimized-side Balance Score per spec §9 default formula.

    The actual side returns ``None`` in v1 — Shell 06's actual aggregates
    don't carry per-match rows, so ``same_club_early_rate`` and
    ``rematch_rate`` for actual are uncomputable. Substituting zero would
    bias the actual baseline upward by 20 points and compress the
    headline delta — see Step 4 metric notes.

    Returns ``(score, risk_flags)`` so the zero-denominator guard's
    ``no_early_meetings`` flag flows back into the ReportCard's flag list.
    """
    weights_dict = extras.get("balance_score_weights") or {}
    preset_id = str(weights_dict.get("preset_id") or "default")
    if preset_id != "default":
        raise ValueError(
            f"Unsupported balance_score_weights preset_id: {preset_id!r} "
            "(v1 only supports 'default')"
        )

    flags: list[RiskFlag] = []
    matches = list(_iter_optimized_matches(optimized_proj))
    total_early = _count_total_early_meetings(matches)

    one_goal_rate = float(optimized_proj["close_game_rate"])
    blowout_5plus_rate = float(optimized_proj["blowout_5plus_rate"])

    if total_early == 0:
        same_club_early_rate = 0.0
        rematch_rate = 0.0
        flags.append(
            RiskFlag(
                severity="info",
                category="no_early_meetings",
                message=(
                    "Cohort has no pool/semi early-meeting matches; "
                    "same-club and rematch rates forced to 0."
                ),
            )
        )
    else:
        same_club_early_rate = same_club_early_count / total_early
        rematch_rate = rematch_count / total_early

    optimized_score = (
        50 * one_goal_rate
        + 30 * (1 - blowout_5plus_rate)
        + 10 * (1 - same_club_early_rate)
        + 10 * (1 - rematch_rate)
    )
    return (
        BalanceScore(
            actual=None,
            optimized=float(optimized_score),
            delta=None,
            preset_id=preset_id,
        ),
        flags,
    )


def _build_top_reasons(
    actual_results: dict[str, Any],
    optimized_proj: dict[str, Any],
) -> tuple[TopReason, ...]:
    """Generate templated top-reason bullets ranked by improvement magnitude.

    Skips templates whose required inputs are ``None`` (covers the v1 gap
    where actual per-match rows are unavailable). Stable secondary sort
    key is ``TOP_REASON_TEMPLATES`` insertion order so tied deltas resolve
    deterministically.
    """
    template_order = list(TOP_REASON_TEMPLATES.keys())
    candidates: list[tuple[str, float, str]] = []  # (key, magnitude, text)

    actual_5plus = actual_results.get("blowout_5plus_rate")
    opt_5plus = optimized_proj.get("blowout_5plus_rate")
    if actual_5plus is not None and opt_5plus is not None:
        actual_count = int(round(float(actual_5plus) * int(actual_results.get("actual_game_count", 0) or 0)))
        opt_count = int(round(float(opt_5plus) * int(optimized_proj.get("match_count", 0) or 0)))
        if actual_5plus == 0:
            pct_change = 0.0 if opt_5plus == 0 else float(opt_5plus)
        else:
            pct_change = (float(opt_5plus) - float(actual_5plus)) / float(actual_5plus)
        text = TOP_REASON_TEMPLATES["blowout_5plus"].format(
            actual_count=actual_count,
            optimized_count=opt_count,
            pct_change=pct_change,
        )
        candidates.append(("blowout_5plus", abs(float(opt_5plus) - float(actual_5plus)), text))

    actual_one = actual_results.get("close_game_rate")
    opt_one = optimized_proj.get("close_game_rate")
    if actual_one is not None and opt_one is not None:
        text = TOP_REASON_TEMPLATES["one_goal_rate"].format(
            actual_pct=float(actual_one),
            optimized_pct=float(opt_one),
        )
        candidates.append(("one_goal_rate", abs(float(opt_one) - float(actual_one)), text))

    actual_avg = actual_results.get("average_goal_differential")
    opt_avg = optimized_proj.get("average_goal_differential")
    if actual_avg is not None and opt_avg is not None:
        text = TOP_REASON_TEMPLATES["avg_gd"].format(
            actual_avg=float(actual_avg),
            optimized_avg=float(opt_avg),
        )
        candidates.append(("avg_gd", abs(float(actual_avg) - float(opt_avg)), text))

    candidates.sort(key=lambda c: (-c[1], template_order.index(c[0])))

    n_significant = sum(1 for _, mag, _ in candidates if mag > 0.001)
    n_top = min(5, max(3, n_significant))
    n_to_take = min(n_top, len(candidates))
    return tuple(TopReason(text=text) for _, _, text in candidates[:n_to_take])


def _build_team_movements(run_dir_path: Path) -> tuple[TeamMovement, ...]:
    """Read ``division_recommendations.json`` and project to non-stay moves.

    Per the plan, the headline list filters ``move != "stay"`` because the
    UI surfaces "what changed" for the director. Missing file (e.g. an
    older run dir) yields an empty tuple rather than raising.
    """
    path = run_dir_path / "division_recommendations.json"
    if not path.exists():
        return ()
    rows = read_json(path)
    if not isinstance(rows, list):
        return ()
    movements: list[TeamMovement] = []
    for row in rows:
        if str(row.get("move") or "") == "stay":
            continue
        movements.append(
            TeamMovement(
                canonical_team_id=str(row.get("canonical_team_id") or ""),
                team_name=str(row.get("event_team_name") or ""),
                from_division=str(row.get("actual_division") or ""),
                to_division=str(row.get("recommended_division") or ""),
                move=str(row.get("move") or "stay"),
            )
        )
    return tuple(movements)


def _build_risk_flags(
    *,
    meta: EventMetadata,
    extras: dict[str, Any],
    entrants: list[dict[str, Any]],
    fallbacks: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
    registry_pids: set[str],
    team_state: Mapping[str, ProjectedTeamState],
    cohort_state: Mapping[str, ProjectedCohortState],
    age: str,
    gender: str,
    balance_score_flags: list[RiskFlag],
) -> tuple[RiskFlag, ...]:
    """Assemble the full risk-flag tuple from cohort-scoped inputs.

    Ordering is intentional: snapshot freshness → fallbacks → state-derived
    flags → low-games → orphans → no-early-meetings (carried in via
    ``balance_score_flags``) → coach-data. Same order each render so the
    HTML template can rely on stable groupings.
    """
    flags: list[RiskFlag] = []

    # Snapshot freshness
    snapshot_iso = extras.get("ranking_snapshot_date")
    snapshot_date = _parse_iso_date(snapshot_iso if isinstance(snapshot_iso, str) else None)
    event_start_date = _parse_iso_date(meta.event_start_date)
    if snapshot_date is None or event_start_date is None:
        flags.append(
            RiskFlag(
                severity="info",
                category="snapshot_freshness_unknown",
                message=(
                    "Snapshot date or event start date not recorded; "
                    "freshness cannot be computed."
                ),
            )
        )
    else:
        days_old = (event_start_date - snapshot_date).days
        if days_old > STALE_SNAPSHOT_DAYS:
            flags.append(
                RiskFlag(
                    severity="warning",
                    category="stale_ranking_snapshot",
                    message=(
                        f"Snapshot is {days_old} days old "
                        f"(threshold: > {STALE_SNAPSHOT_DAYS} days). "
                        f"event_start={event_start_date.isoformat()}, "
                        f"snapshot={snapshot_date.isoformat()}."
                    ),
                )
            )

    # Synthetic / future-snapshot fallbacks (Section 10 fold-in 21c)
    for row in fallbacks:
        team_name = str(row.get("team_name") or "")
        kind = str(row.get("fallback_kind") or "snapshot_fallback")
        flags.append(
            RiskFlag(
                severity="warning",
                category="snapshot_fallback",
                message=f"{team_name}: {kind}",
                affected_teams=(team_name,) if team_name else (),
            )
        )

    # External / placeholder team states — entrants are inherently
    # cohort-scoped (the cohort CLI processes one cohort per run).
    cohort_key = f"{age}_{gender}"
    has_cohort_recompute = cohort_key in cohort_state
    for entrant in entrants:
        pid = str(entrant.get("provider_team_id") or "")
        team_name = str(entrant.get("event_team_name") or pid)
        if not pid:
            continue
        projected = team_state.get(pid)
        if projected is not None and projected.state == "external":
            if has_cohort_recompute:
                flags.append(
                    RiskFlag(
                        severity="info",
                        category="external_with_assumed_median",
                        message=(
                            f"{team_name}: external team using cohort-recomputed "
                            "median power score."
                        ),
                        affected_teams=(team_name,),
                    )
                )
            else:
                flags.append(
                    RiskFlag(
                        severity="info",
                        category="external_no_override",
                        message=(
                            f"{team_name}: external team without a "
                            "recompute_medians cohort override."
                        ),
                        affected_teams=(team_name,),
                    )
                )
        if _is_placeholder_team(team_name=team_name, provider_team_id=pid):
            flags.append(
                RiskFlag(
                    severity="warning",
                    category="placeholder_match",
                    message=(
                        f"{team_name}: matched to ``unknown_<provider_id>`` "
                        "placeholder; resolve before publishing."
                    ),
                    affected_teams=(team_name,),
                )
            )

    # Low-games entrants
    for entrant in entrants:
        games = int(entrant.get("games_played") or 0)
        if games < LOW_GAMES_THRESHOLD:
            team_name = str(entrant.get("event_team_name") or entrant.get("provider_team_id") or "")
            flags.append(
                RiskFlag(
                    severity="info",
                    category="low_games",
                    message=(
                        f"{team_name}: only {games} games this season "
                        f"(threshold: < {LOW_GAMES_THRESHOLD})."
                    ),
                    affected_teams=(team_name,) if team_name else (),
                )
            )

    # Rescrape orphan overrides — scenario-scoped, not cohort-scoped.
    # Same orphan surfaces on every cohort's Report Card until resolved.
    seen_orphan_refs: set[str] = set()
    for record in overrides:
        if record.get("type") in {"manual_add", "recompute_medians"}:
            continue
        team_ref = str(record.get("team_ref") or "")
        if not team_ref or team_ref.startswith("manual_"):
            continue
        if team_ref in registry_pids:
            continue
        if team_ref in seen_orphan_refs:
            continue
        seen_orphan_refs.add(team_ref)
        affected_name = str((record.get("after") or {}).get("event_team_name") or team_ref)
        flags.append(
            RiskFlag(
                severity="warning",
                category="rescrape_orphan_override",
                message=(
                    f"Override targets provider_team_id {team_ref!r} "
                    "not present in current scenario registry; team may need rescrape."
                ),
                affected_teams=(affected_name,),
            )
        )

    # Balance-score zero-denominator flags (no early meetings)
    flags.extend(balance_score_flags)

    # Coach-data limitation — always emitted in v1 so the gap is loud
    flags.append(
        RiskFlag(
            severity="info",
            category="coach_data_unavailable",
            message=(
                "Coach data not yet collected; same-coach metric reserved for v2."
            ),
        )
    )

    return tuple(flags)


# ---------------------------------------------------------------------------
# Public API — pure compute
# ---------------------------------------------------------------------------


def compute_report_card(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> ReportCard:
    """Build a ``ReportCard`` from the run dir's artifacts.

    Pure — no side effects. ``compute_and_persist_report_card`` is the
    side-effecting wrapper that writes the comparison artifacts.

    Raises ``ReportCardError`` if the run is not completed (``done.json``
    missing) or if cohort identity cannot be determined
    (``run_metadata.json`` missing). Raises ``ValueError`` from
    ``_compute_balance_score`` if a non-default ``preset_id`` is set in
    ``meta.extras["balance_score_weights"]``.
    """
    run_dir_path = _run_dir(event_key, scenario, run_id, base_dir=base_dir)

    if not (run_dir_path / "done.json").exists():
        raise ReportCardError(
            f"Run {run_id!r} is not completed (no done.json marker at "
            f"{run_dir_path}). Failed/cancelled/in-flight runs cannot "
            "produce a Report Card."
        )

    summary_path = run_dir_path / "summary.json"
    if not summary_path.exists():
        raise ReportCardError(f"summary.json missing at {summary_path}")
    summary = read_json(summary_path)

    run_metadata = _read_run_metadata(run_dir_path)
    age = str(run_metadata["cohort_age_group"])
    gender = str(run_metadata["cohort_gender"])
    event_name = str(run_metadata.get("event_name") or summary.get("event_name") or "")

    actual_results = summary.get("actual_results") or {}
    optimized_proj = (summary.get("optimized_projection") or {}).get("simulated_schedule") or {}
    entrants = list(summary.get("entrants") or [])
    entrants_by_id = {str(e.get("entrant_id") or ""): e for e in entrants}

    fallbacks_path = run_dir_path / "fallbacks.jsonl"
    fallbacks = list(read_jsonl(fallbacks_path)) if fallbacks_path.exists() else []

    audit_path = run_dir_path / "run_overrides_audit.jsonl"
    audit_rows = list(read_jsonl(audit_path)) if audit_path.exists() else []

    meta = read_event_metadata(event_key, base_dir=base_dir)
    extras = _extras(meta)
    capped_gd_limit = int(extras.get("capped_gd_limit", 3) or 3)

    overrides = load_overrides(event_key, scenario, base_dir=base_dir)
    team_state, cohort_state = project_overrides(overrides)
    registry = read_registry(event_key, scenario, base_dir=base_dir)
    registry_pids = {
        entry.resolved_gotsport_provider_team_id
        for entry in registry
        if entry.resolved_gotsport_provider_team_id
    }

    matches = list(_iter_optimized_matches(optimized_proj))
    same_club_early_count = _count_same_club_early(matches, entrants_by_id)
    rematch_count = _count_intra_event_rematches(matches)

    metrics = _build_metrics(
        actual_results,
        optimized_proj,
        same_club_early_count,
        rematch_count,
        capped_gd_limit,
    )
    balance_score, balance_score_flags = _compute_balance_score(
        optimized_proj,
        same_club_early_count,
        rematch_count,
        extras,
    )
    risk_flags = _build_risk_flags(
        meta=meta,
        extras=extras,
        entrants=entrants,
        fallbacks=fallbacks,
        overrides=overrides,
        registry_pids=registry_pids,
        team_state=team_state,
        cohort_state=cohort_state,
        age=age,
        gender=gender,
        balance_score_flags=balance_score_flags,
    )
    top_reasons = _build_top_reasons(actual_results, optimized_proj)
    team_movements = _build_team_movements(run_dir_path)
    override_audit = tuple(OverrideAuditRow.from_dict(row) for row in audit_rows)

    return ReportCard(
        event_key=event_key,
        scenario=scenario,
        run_id=run_id,
        age_group=age,
        gender=gender,
        event_name=event_name,
        computed_at=utc_now_iso(),
        balance_score=balance_score,
        metrics=metrics,
        risk_flags=risk_flags,
        top_reasons=top_reasons,
        team_movements=team_movements,
        override_audit=override_audit,
    )


def write_comparison_json(report_card: ReportCard, run_dir_path: Path) -> Path:
    """Write the ReportCard as ``comparison.json`` with the schema stamp."""
    path = _comparison_json_path(run_dir_path)
    write_json(path, stamp_schema_version(report_card.to_dict()))
    return path


def read_comparison_json(path: Path) -> ReportCard:
    """Read ``comparison.json`` back into a ``ReportCard``.

    Strict on read: raises ``SchemaVersionError`` on a newer schema
    (mirrors ``frozen_medians.py:80``).
    """
    payload = read_json(path)
    assert_supported_version(payload, source=str(path))
    return ReportCard.from_dict(payload)


# ---------------------------------------------------------------------------
# Public API — compute + persist (Step 8)
# ---------------------------------------------------------------------------


def compute_and_persist_report_card(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> ReportCard:
    """Compute the ReportCard and write all six artifacts to the run dir.

    Order: ``comparison.json`` → three CSVs → ``comparison.html`` →
    ``report_card.done`` (sentinel, written LAST so readers gating on the
    sentinel never see partial state). Mirrors Shell 06's ``done.json``
    contract at ``run_layout.py:5-26``.

    On any exception, all six artifacts are unlinked (``missing_ok=True``)
    before re-raising — the run dir reverts to "no Report Card present"
    rather than a half-written state.

    NOT safe for concurrent invocation against the same ``(event_key,
    scenario, run_id)`` (per-file ``.tmp → final`` renames + sentinel
    ordering would race). Callers must serialize.
    """
    # Local imports avoid a circular dependency on the renderers at module load.
    from src.tournaments.reports.render_csv import render_all_csv
    from src.tournaments.reports.render_html import write_html

    rc = compute_report_card(event_key, scenario, run_id, base_dir=base_dir)
    run_dir_path = _run_dir(event_key, scenario, run_id, base_dir=base_dir)
    try:
        write_comparison_json(rc, run_dir_path)
        render_all_csv(rc, run_dir_path)
        write_html(rc, run_dir_path / "comparison.html", mode="standalone")
        write_json(
            run_dir_path / "report_card.done",
            stamp_schema_version({"completed_at": utc_now_iso()}),
        )
    except BaseException:
        for name in _ARTIFACT_NAMES:
            (run_dir_path / name).unlink(missing_ok=True)
        raise
    return rc
