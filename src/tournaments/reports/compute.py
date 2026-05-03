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
The registry CSV, override ledger, and ``run_orchestrator.override_in_cohort``
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
    BetterExperienceRow,
    Champion,
    DivisionBalanceRow,
    EarlyMeetingConcern,
    HeadlineSummary,
    Metric,
    OverrideAuditRow,
    ReportCard,
    RiskFlag,
    StandingsRow,
    TeamMovement,
    TopReason,
)
from src.tournaments.storage import (
    EventMetadata,
    SchemaVersionError,
    assert_supported_version,
    load_overrides,
    load_raw_scrape,
    read_event_metadata,
    read_game_results,
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
    registry_provider_id,
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

DATA_QUALITY_PENALTY_PER_TEAM: float = 1.0
"""Points deducted from the optimized Balance Score per team that triggers a
``low_games`` or ``snapshot_fallback`` warning. Same team can be hit by both
(compounding is intentional — both signals are independent data-quality
issues). Final score is floored at 0.0. Override via
``meta.extras["balance_score_weights"]["data_quality_penalty_per_team"]``."""

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
        raise ReportCardError(f"run_metadata.json missing at {path}; cannot determine cohort identity")
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
    *,
    low_games_team_count: int = 0,
    snapshot_fallback_team_count: int = 0,
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
        raise ValueError(f"Unsupported balance_score_weights preset_id: {preset_id!r} (v1 only supports 'default')")

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
                message=("Cohort has no pool/semi early-meeting matches; same-club and rematch rates forced to 0."),
            )
        )
    else:
        same_club_early_rate = same_club_early_count / total_early
        rematch_rate = rematch_count / total_early

    raw_optimized_score = (
        50 * one_goal_rate + 30 * (1 - blowout_5plus_rate) + 10 * (1 - same_club_early_rate) + 10 * (1 - rematch_rate)
    )

    # Data-quality penalty: dock points per team flagged for low_games or
    # snapshot_fallback. A 98/100 built on 9 teams with poor input data isn't
    # really a 98 — surface the degradation in the headline score.
    penalty_per_team = float(
        weights_dict.get("data_quality_penalty_per_team")
        if weights_dict.get("data_quality_penalty_per_team") is not None
        else DATA_QUALITY_PENALTY_PER_TEAM
    )
    affected_teams = int(low_games_team_count) + int(snapshot_fallback_team_count)
    data_quality_penalty = penalty_per_team * affected_teams
    optimized_score = max(0.0, raw_optimized_score - data_quality_penalty)

    if affected_teams > 0:
        flags.append(
            RiskFlag(
                severity="info",
                category="data_quality_penalty",
                message=(
                    f"Balance Score reduced by {data_quality_penalty:.0f} pts "
                    f"({penalty_per_team:.0f}/team × {affected_teams} affected): "
                    f"{int(low_games_team_count)} low-games + "
                    f"{int(snapshot_fallback_team_count)} snapshot-fallback. "
                    f"Raw score before penalty: {raw_optimized_score:.0f}."
                ),
            )
        )

    return (
        BalanceScore(
            actual=None,
            optimized=float(optimized_score),
            delta=None,
            preset_id=preset_id,
            data_quality_penalty=float(data_quality_penalty),
            low_games_team_count=int(low_games_team_count),
            snapshot_fallback_team_count=int(snapshot_fallback_team_count),
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

    # Each template asserts a directional improvement ("Reduced", "Raised",
    # "Tightened"), so we filter to genuine wins only — emitting "Reduced
    # 5+ goal mismatches" when blowouts went UP would mislead the
    # Report Card reader. Direction per metric:
    #   blowout_5plus / avg_gd: lower-is-better (opt < actual)
    #   one_goal_rate: higher-is-better (opt > actual)
    actual_5plus = actual_results.get("blowout_5plus_rate")
    opt_5plus = optimized_proj.get("blowout_5plus_rate")
    if actual_5plus is not None and opt_5plus is not None and float(opt_5plus) < float(actual_5plus):
        # Directional gate (opt < actual on a non-negative rate) guarantees
        # actual_5plus > 0, so the divide is safe and the prior
        # ``if actual_5plus == 0`` zero-guard is unreachable here.
        actual_count = int(round(float(actual_5plus) * int(actual_results.get("actual_game_count", 0) or 0)))
        opt_count = int(round(float(opt_5plus) * int(optimized_proj.get("match_count", 0) or 0)))
        pct_change = (float(opt_5plus) - float(actual_5plus)) / float(actual_5plus)
        text = TOP_REASON_TEMPLATES["blowout_5plus"].format(
            actual_count=actual_count,
            optimized_count=opt_count,
            pct_change=pct_change,
        )
        candidates.append(("blowout_5plus", abs(float(opt_5plus) - float(actual_5plus)), text))

    actual_one = actual_results.get("close_game_rate")
    opt_one = optimized_proj.get("close_game_rate")
    if actual_one is not None and opt_one is not None and float(opt_one) > float(actual_one):
        text = TOP_REASON_TEMPLATES["one_goal_rate"].format(
            actual_pct=float(actual_one),
            optimized_pct=float(opt_one),
        )
        candidates.append(("one_goal_rate", abs(float(opt_one) - float(actual_one)), text))

    actual_avg = actual_results.get("average_goal_differential")
    opt_avg = optimized_proj.get("average_goal_differential")
    if actual_avg is not None and opt_avg is not None and float(opt_avg) < float(actual_avg):
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
                message=("Snapshot date or event start date not recorded; freshness cannot be computed."),
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
                        message=(f"{team_name}: external team using cohort-recomputed median power score."),
                        affected_teams=(team_name,),
                    )
                )
            else:
                flags.append(
                    RiskFlag(
                        severity="info",
                        category="external_no_override",
                        message=(f"{team_name}: external team without a recompute_medians cohort override."),
                        affected_teams=(team_name,),
                    )
                )
        if _is_placeholder_team(team_name=team_name, provider_team_id=pid):
            flags.append(
                RiskFlag(
                    severity="warning",
                    category="placeholder_match",
                    message=(
                        f"{team_name}: matched to ``unknown_<provider_id>`` placeholder; resolve before publishing."
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
                    message=(f"{team_name}: only {games} games this season (threshold: < {LOW_GAMES_THRESHOLD})."),
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
            message=("Coach data not yet collected; same-coach metric reserved for v2."),
        )
    )

    return tuple(flags)


def _empty_record() -> dict[str, int]:
    return {"played": 0, "wins": 0, "losses": 0, "ties": 0, "gf": 0, "ga": 0}


def _accumulate(record: dict[str, int], team_score: int, opp_score: int) -> None:
    record["played"] += 1
    record["gf"] += team_score
    record["ga"] += opp_score
    if team_score > opp_score:
        record["wins"] += 1
    elif team_score < opp_score:
        record["losses"] += 1
    else:
        record["ties"] += 1


def _standings_sort_key(row: StandingsRow) -> tuple:
    # Division asc, then by points desc (W=3, T=1), then GD desc, then GF desc.
    points = row.wins * 3 + row.ties
    return (row.division_name, -points, -row.goal_differential, -row.goals_for, row.team_name)


def _compute_actual_standings(
    event_key: str,
    base_dir: Path | str,
    entrants: list[dict[str, Any]],
) -> tuple[StandingsRow, ...]:
    """Per-team W/L/T/GF/GA/GD from intake/game_results.jsonl.

    Joins game_results' reg-id keys to entrants via raw_scrape's
    provider_team_id <-> provider_registration_id pairing. Each team's
    division_name is their actual played tier (entrant.actual_division_name,
    set by the orchestrator from raw_scrape.group_name).
    """
    games = read_game_results(event_key, base_dir=base_dir)
    if not games:
        return ()
    raw_records = load_raw_scrape(event_key, base_dir=base_dir)
    pid_to_reg = {
        str(r.get("provider_team_id") or ""): str(r.get("provider_registration_id") or "")
        for r in raw_records
        if r.get("provider_team_id") and r.get("provider_registration_id")
    }
    reg_to_pid = {reg_id: pid for pid, reg_id in pid_to_reg.items()}
    entrant_by_pid = {
        str(e.get("provider_team_id") or ""): e for e in entrants if e.get("provider_team_id")
    }

    aggregates: dict[tuple[str, str], dict[str, int]] = {}  # (canonical_id, division) -> stats
    name_by_canonical: dict[str, str] = {}
    for game in games:
        if game.home_score is None or game.away_score is None:
            continue
        home_pid = reg_to_pid.get(str(game.home_provider_team_id or ""))
        away_pid = reg_to_pid.get(str(game.away_provider_team_id or ""))
        if not home_pid or not away_pid:
            continue
        home_entrant = entrant_by_pid.get(home_pid)
        away_entrant = entrant_by_pid.get(away_pid)
        if not home_entrant or not away_entrant:
            continue
        home_canonical = str(home_entrant.get("canonical_team_id") or "")
        away_canonical = str(away_entrant.get("canonical_team_id") or "")
        if not home_canonical or not away_canonical:
            continue
        home_div = str(home_entrant.get("actual_division_name") or "")
        away_div = str(away_entrant.get("actual_division_name") or "")
        name_by_canonical[home_canonical] = str(home_entrant.get("event_team_name") or "")
        name_by_canonical[away_canonical] = str(away_entrant.get("event_team_name") or "")
        _accumulate(
            aggregates.setdefault((home_canonical, home_div), _empty_record()),
            int(game.home_score),
            int(game.away_score),
        )
        _accumulate(
            aggregates.setdefault((away_canonical, away_div), _empty_record()),
            int(game.away_score),
            int(game.home_score),
        )

    rows: list[StandingsRow] = []
    for (canonical_id, division_name), stats in aggregates.items():
        if not division_name:
            continue
        rows.append(
            StandingsRow(
                canonical_team_id=canonical_id,
                team_name=name_by_canonical.get(canonical_id, ""),
                division_name=division_name,
                played=stats["played"],
                wins=stats["wins"],
                losses=stats["losses"],
                ties=stats["ties"],
                goals_for=stats["gf"],
                goals_against=stats["ga"],
                goal_differential=stats["gf"] - stats["ga"],
            )
        )
    rows.sort(key=_standings_sort_key)
    return tuple(rows)


def _compute_optimized_standings(
    optimized_proj: dict[str, Any],
    entrants: list[dict[str, Any]],
) -> tuple[StandingsRow, ...]:
    """Per-team W/L/T/GF/GA/GD from the simulator's predicted scores."""
    entrants_by_id = {
        str(e.get("entrant_id") or ""): e for e in entrants if e.get("entrant_id")
    }
    aggregates: dict[str, dict[str, int]] = {}  # canonical_id -> stats
    division_by_canonical: dict[str, str] = {}
    name_by_canonical: dict[str, str] = {}
    for division in optimized_proj.get("divisions") or []:
        division_name = str(division.get("division_name") or "")
        for match in division.get("matches") or []:
            home_score = match.get("home_score")
            away_score = match.get("away_score")
            if home_score is None or away_score is None:
                continue
            for eid, team_score, opp_score in (
                (str(match.get("home_team_id") or ""), int(home_score), int(away_score)),
                (str(match.get("away_team_id") or ""), int(away_score), int(home_score)),
            ):
                entrant = entrants_by_id.get(eid)
                if not entrant:
                    continue
                canonical_id = str(entrant.get("canonical_team_id") or "")
                if not canonical_id:
                    continue
                division_by_canonical.setdefault(canonical_id, division_name)
                name_by_canonical.setdefault(canonical_id, str(entrant.get("event_team_name") or ""))
                _accumulate(
                    aggregates.setdefault(canonical_id, _empty_record()),
                    team_score,
                    opp_score,
                )

    rows = [
        StandingsRow(
            canonical_team_id=canonical_id,
            team_name=name_by_canonical.get(canonical_id, ""),
            division_name=division_by_canonical.get(canonical_id, ""),
            played=stats["played"],
            wins=stats["wins"],
            losses=stats["losses"],
            ties=stats["ties"],
            goals_for=stats["gf"],
            goals_against=stats["ga"],
            goal_differential=stats["gf"] - stats["ga"],
        )
        for canonical_id, stats in aggregates.items()
    ]
    rows.sort(key=_standings_sort_key)
    return tuple(rows)


def _compute_experience_shifts(
    actual: tuple[StandingsRow, ...],
    optimized: tuple[StandingsRow, ...],
    *,
    top_n: int = 5,
) -> tuple[tuple[BetterExperienceRow, ...], tuple[BetterExperienceRow, ...]]:
    """Compute both better- and worse-experience leaderboards in one pass.

    Returns ``(better, worse)``:
    - ``better`` — top N teams by pain reduction (largest drop in
      ``|avg GD|``); the optimizer would give them closer games.
    - ``worse`` — top N teams asked to step up: dominant teams whose
      ``|opt avg GD|`` is materially smaller than ``|actual avg GD|`` AND
      they were winning in the actual event (actual_avg_gd > 0). These are
      the teams whose results "compress" — they no longer dominate.

    Tournament-balance interpretation: ``worse`` is also a balance win
    (the tournament becomes more competitive), but the dominant team
    individually loses some of their margin.
    """
    actual_by_id = {row.canonical_team_id: row for row in actual}
    optimized_by_id = {row.canonical_team_id: row for row in optimized}
    candidates: list[BetterExperienceRow] = []
    for canonical_id, actual_row in actual_by_id.items():
        opt_row = optimized_by_id.get(canonical_id)
        if not opt_row or actual_row.played == 0 or opt_row.played == 0:
            continue
        actual_avg = actual_row.avg_goal_differential
        opt_avg = opt_row.avg_goal_differential
        candidates.append(
            BetterExperienceRow(
                canonical_team_id=canonical_id,
                team_name=actual_row.team_name,
                actual_division=actual_row.division_name,
                actual_avg_gd=actual_avg,
                optimized_division=opt_row.division_name,
                optimized_avg_gd=opt_avg,
                pain_reduction=abs(actual_avg) - abs(opt_avg),
            )
        )

    better = sorted(candidates, key=lambda r: (-r.pain_reduction, r.team_name))[:top_n]

    # "Asked to step up" = teams dominating actual (actual_avg_gd > 0) whose
    # margin compresses in the optimized side. Filter to actual_avg_gd > 0
    # so we don't surface teams already getting blown out who got blown out
    # MORE — those are a separate "miscalibration" concern, not "step up".
    step_up_candidates = [r for r in candidates if r.actual_avg_gd > 0 and r.pain_reduction > 0]
    # Sort by largest absolute compression of a positive actual GD.
    step_up_candidates.sort(key=lambda r: (-r.pain_reduction, r.team_name))
    return tuple(better), tuple(step_up_candidates[:top_n])


def _build_headline_summary(
    actual_results: dict[str, Any],
    optimized_proj: dict[str, Any],
    better: tuple[BetterExperienceRow, ...],
    worse: tuple[BetterExperienceRow, ...],
    entrants: list[dict[str, Any]],
) -> HeadlineSummary:
    """One-paragraph above-the-fold summary for a TD."""
    team_count = len(entrants)
    affected = {row.canonical_team_id for row in better} | {row.canonical_team_id for row in worse}
    unchanged = max(0, team_count - len(affected))
    return HeadlineSummary(
        team_count=team_count,
        better_experience_count=len(better),
        asked_to_step_up_count=len(worse),
        unchanged_count=unchanged,
        actual_avg_gd=actual_results.get("average_goal_differential") if actual_results else None,
        optimized_avg_gd=optimized_proj.get("average_goal_differential") if optimized_proj else None,
        actual_close_game_rate=actual_results.get("close_game_rate") if actual_results else None,
        optimized_close_game_rate=optimized_proj.get("close_game_rate") if optimized_proj else None,
        actual_blowout_5plus_rate=actual_results.get("blowout_5plus_rate") if actual_results else None,
        optimized_blowout_5plus_rate=optimized_proj.get("blowout_5plus_rate") if optimized_proj else None,
    )


def _build_division_balance(
    actual_results: dict[str, Any],
    optimized_proj: dict[str, Any],
    actual_standings: tuple[StandingsRow, ...],
    optimized_standings: tuple[StandingsRow, ...],
) -> tuple[DivisionBalanceRow, ...]:
    """Per-division actual-vs-optimized scorecard. Sorted by largest avg-GD
    improvement first so the worst-built divisions surface at the top.
    """
    actual_by_div = (actual_results.get("divisions") or {}) if actual_results else {}
    optimized_by_div = {
        str(d.get("division_name") or ""): d for d in (optimized_proj.get("divisions") or [])
    }
    team_count_by_div: dict[str, int] = {}
    for row in optimized_standings:
        team_count_by_div[row.division_name] = team_count_by_div.get(row.division_name, 0) + 1
    # Fallback: if optimized standings are empty for some reason, fall back to actual.
    if not team_count_by_div:
        for row in actual_standings:
            team_count_by_div[row.division_name] = team_count_by_div.get(row.division_name, 0) + 1

    division_names = sorted(set(actual_by_div) | set(optimized_by_div))
    rows: list[DivisionBalanceRow] = []
    for name in division_names:
        if not name:
            continue
        actual = actual_by_div.get(name, {}) or {}
        optimized = optimized_by_div.get(name, {}) or {}
        rows.append(
            DivisionBalanceRow(
                division_name=name,
                team_count=team_count_by_div.get(name, 0),
                actual_match_count=int(actual.get("actual_game_count") or actual.get("match_count") or 0),
                actual_avg_gd=float(actual.get("average_goal_differential") or 0.0),
                actual_close_game_rate=float(actual.get("close_game_rate") or 0.0),
                actual_blowout_5plus_rate=float(actual.get("blowout_5plus_rate") or 0.0),
                optimized_match_count=int(optimized.get("match_count") or 0),
                optimized_avg_gd=float(optimized.get("average_goal_differential") or 0.0),
                optimized_close_game_rate=float(optimized.get("close_game_rate") or 0.0),
                optimized_blowout_5plus_rate=float(optimized.get("blowout_5plus_rate") or 0.0),
            )
        )
    # Sort by avg-GD improvement (actual - optimized) desc — most-improved first.
    rows.sort(key=lambda r: -(r.actual_avg_gd - r.optimized_avg_gd))
    return tuple(rows)


def _build_early_meeting_concerns(
    optimized_proj: dict[str, Any],
    entrants: list[dict[str, Any]],
) -> tuple[EarlyMeetingConcern, ...]:
    """Operational red-flags: same-club + intra-event rematch matchups in
    pool/semi rounds of the optimized schedule. Names, not counts.

    Actual-side concerns deferred — v1 actual_results carries no per-match
    rows for the actual tournament (per spec). Once v2 widens
    actual_results.matches[*], this helper is widened to cover both sides.
    """
    entrants_by_id = {str(e.get("entrant_id") or ""): e for e in entrants if e.get("entrant_id")}
    matches = list(_iter_optimized_matches(optimized_proj))
    concerns: list[EarlyMeetingConcern] = []

    # Same-club early meetings — surface team names + the shared club.
    for match in matches:
        if match.get("stage") not in EARLY_STAGES:
            continue
        home = entrants_by_id.get(str(match.get("home_team_id") or ""))
        away = entrants_by_id.get(str(match.get("away_team_id") or ""))
        if home is None or away is None:
            continue
        home_club = str(home.get("club_name") or "")
        away_club = str(away.get("club_name") or "")
        if home_club and away_club and home_club == away_club:
            concerns.append(
                EarlyMeetingConcern(
                    side="optimized",
                    kind="same_club",
                    division_name=str(match.get("division_name") or ""),
                    stage=str(match.get("stage") or ""),
                    home_team_name=str(home.get("event_team_name") or ""),
                    away_team_name=str(away.get("event_team_name") or ""),
                    detail=f"shared club: {home_club}",
                )
            )

    # Intra-event rematches — pairs that play more than once in pool/semi.
    pair_matches: dict[frozenset[str], list[dict[str, Any]]] = {}
    for match in matches:
        if match.get("stage") not in EARLY_STAGES:
            continue
        home_id = str(match.get("home_team_id") or "")
        away_id = str(match.get("away_team_id") or "")
        if not home_id or not away_id:
            continue
        pair_matches.setdefault(frozenset({home_id, away_id}), []).append(match)
    for pair, ms in pair_matches.items():
        if len(ms) <= 1:
            continue
        # Use the second occurrence (the rematch itself) for naming.
        second = ms[1]
        home = entrants_by_id.get(str(second.get("home_team_id") or ""))
        away = entrants_by_id.get(str(second.get("away_team_id") or ""))
        if home is None or away is None:
            continue
        concerns.append(
            EarlyMeetingConcern(
                side="optimized",
                kind="rematch",
                division_name=str(second.get("division_name") or ""),
                stage=str(second.get("stage") or ""),
                home_team_name=str(home.get("event_team_name") or ""),
                away_team_name=str(away.get("event_team_name") or ""),
                detail=f"{len(ms)} meetings in pool/semi",
            )
        )

    concerns.sort(key=lambda c: (c.kind, c.division_name, c.home_team_name))
    return tuple(concerns)


def _compute_champions(
    standings: tuple[StandingsRow, ...],
    side: str,
    *,
    optimized_division_by_team: dict[str, str] | None = None,
) -> tuple[Champion, ...]:
    """Per-division champion = best W/L/T record. Tie-break: wins desc,
    then GD desc, then GF desc, then team_name asc.

    ``optimized_division_by_team`` is an optional ``{canonical_team_id ->
    optimized_division}`` map. When provided (typically for actual-side
    champions), the renderer can show "won Blue actual, projected to Red".
    """
    by_div: dict[str, list[StandingsRow]] = {}
    for row in standings:
        if row.played == 0:
            continue
        by_div.setdefault(row.division_name, []).append(row)
    champions: list[Champion] = []
    for division_name, rows in by_div.items():
        rows.sort(key=lambda r: (-r.wins, -r.goal_differential, -r.goals_for, r.team_name))
        winner = rows[0]
        opt_div = ""
        if optimized_division_by_team:
            opt_div = optimized_division_by_team.get(winner.canonical_team_id, "")
        champions.append(
            Champion(
                side=side,
                division_name=division_name,
                canonical_team_id=winner.canonical_team_id,
                team_name=winner.team_name,
                wins=winner.wins,
                losses=winner.losses,
                ties=winner.ties,
                goals_for=winner.goals_for,
                goals_against=winner.goals_against,
                goal_differential=winner.goal_differential,
                optimized_division=opt_div,
            )
        )
    champions.sort(key=lambda c: c.division_name)
    return tuple(champions)


def _detect_structure_format_mismatch(
    actual_standings: tuple[StandingsRow, ...],
    optimized_standings: tuple[StandingsRow, ...],
) -> list[RiskFlag]:
    """Flag divisions where projected games-per-team differs materially from
    actual games-per-team. Surfaces a structure-spec mismatch (operator's
    pool_sizes don't reflect the format the actual tournament used).

    Heuristic: median games-per-team mismatch >= 2 in either direction.
    """
    flags: list[RiskFlag] = []
    actual_by_div: dict[str, list[int]] = {}
    optimized_by_div: dict[str, list[int]] = {}
    for r in actual_standings:
        if r.played > 0:
            actual_by_div.setdefault(r.division_name, []).append(r.played)
    for r in optimized_standings:
        if r.played > 0:
            optimized_by_div.setdefault(r.division_name, []).append(r.played)
    divisions = sorted(set(actual_by_div) & set(optimized_by_div))
    for div in divisions:
        a_games = sorted(actual_by_div[div])
        o_games = sorted(optimized_by_div[div])
        a_med = a_games[len(a_games) // 2]
        o_med = o_games[len(o_games) // 2]
        if abs(a_med - o_med) >= 2:
            flags.append(
                RiskFlag(
                    severity="warning",
                    category="structure_format_mismatch",
                    message=(
                        f"Division {div!r}: optimized schedule produces ~{o_med} games per team, "
                        f"but the actual tournament played ~{a_med} games per team. "
                        f"Edit pool_sizes in Division setup to match the actual format."
                    ),
                )
            )
    return flags


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
    # Use ``registry_provider_id`` so overrides keyed by the
    # ``event_registration_id`` fallback (unresolved registry rows, manual-adds)
    # are not falsely flagged as ``rescrape_orphan_override``. This mirrors how
    # ``triage.is_ready`` derives the per-row identity.
    registry_pids = {pid for entry in registry if (pid := registry_provider_id(entry))}

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
    # Count teams whose input quality should dock the Balance Score. Same
    # team can appear in both buckets (compounding intentional). Counted
    # here from the same data sources _build_risk_flags walks below, so
    # the penalty count and the rendered flag count stay consistent.
    low_games_team_count = sum(
        1 for entrant in entrants if int(entrant.get("games_played") or 0) < LOW_GAMES_THRESHOLD
    )
    snapshot_fallback_team_count = sum(1 for row in fallbacks if row.get("team_name"))
    balance_score, balance_score_flags = _compute_balance_score(
        optimized_proj,
        same_club_early_count,
        rematch_count,
        extras,
        low_games_team_count=low_games_team_count,
        snapshot_fallback_team_count=snapshot_fallback_team_count,
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
    actual_standings = _compute_actual_standings(event_key, base_dir, entrants)
    optimized_standings = _compute_optimized_standings(optimized_proj, entrants)
    better_experience, worse_experience = _compute_experience_shifts(
        actual_standings, optimized_standings
    )
    headline_summary = _build_headline_summary(
        actual_results, optimized_proj, better_experience, worse_experience, entrants
    )
    division_balance = _build_division_balance(
        actual_results, optimized_proj, actual_standings, optimized_standings
    )
    early_meeting_concerns = _build_early_meeting_concerns(optimized_proj, entrants)
    optimized_division_by_team = {
        row.canonical_team_id: row.division_name for row in optimized_standings
    }
    actual_champions = _compute_champions(
        actual_standings, "actual", optimized_division_by_team=optimized_division_by_team
    )
    projected_champions = _compute_champions(optimized_standings, "projected")
    # Structure-spec mismatch flags merged into the existing risk_flags list
    # (returned tuple is immutable; rebuild with extras tacked on).
    risk_flags = tuple(list(risk_flags) + _detect_structure_format_mismatch(
        actual_standings, optimized_standings
    ))

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
        actual_standings=actual_standings,
        optimized_standings=optimized_standings,
        better_experience=better_experience,
        worse_experience=worse_experience,
        headline_summary=headline_summary,
        division_balance=division_balance,
        early_meeting_concerns=early_meeting_concerns,
        actual_champions=actual_champions,
        projected_champions=projected_champions,
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
