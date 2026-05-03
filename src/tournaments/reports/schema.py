"""Report Card dataclasses — leaves + the ``ReportCard`` aggregate.

Mirrors the storage-layer JSON-backed dataclass conventions:

- Leaves use ``frozen_medians.py:29-92`` — ``@dataclass(frozen=True)`` +
  ``schema_version: int = 1`` + ``to_dict`` via ``asdict`` + classmethod
  ``from_dict`` lenient on missing fields.
- The ``ReportCard`` aggregate uses ``schedule_simulator.py:29-130`` —
  hand-written ``to_dict`` recursing via ``[child.to_dict() for child in ...]``
  because ``asdict`` on tuples of frozen dataclasses produces lists of
  plain dicts, which is what ``write_json`` wants.

``OverrideAuditRow`` is a passthrough container: each
``run_overrides_audit.jsonl`` record already carries the orchestrator's
shape (cf. ``run_orchestrator._write_run_overrides_audit``), so this
dataclass just enforces the schema-version gate on read and round-trips
the dict verbatim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from src.tournaments.storage.schema_version import assert_supported_version

__all__ = [
    "BalanceScore",
    "BetterExperienceRow",
    "Champion",
    "CohortScorecardRow",
    "DivisionBalanceRow",
    "EarlyMeetingConcern",
    "EventReportCard",
    "HeadlineSummary",
    "Metric",
    "OverrideAuditRow",
    "ReportCard",
    "RiskFlag",
    "StandingsRow",
    "TeamMovement",
    "TopReason",
]


MetricUnit = Literal["count", "rate", "gd"]
RiskSeverity = Literal["info", "warning", "blocker"]
TeamMove = Literal["move_up", "move_down", "stay"]


@dataclass(frozen=True)
class Metric:
    """One row of the side-by-side metrics table.

    ``actual`` and ``delta`` may be ``None`` for v1 metrics whose actual
    side is unavailable (capped GD, same-club early, intra-event rematches,
    same-coach early). ``unit`` drives the renderer's formatting:
    ``"count"`` → integer, ``"rate"`` → percentage, ``"gd"`` → fixed
    decimal.
    """

    label: str
    actual: float | int | None
    optimized: float | int | None
    delta: float | int | None
    unit: MetricUnit

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Metric":
        return cls(
            label=payload["label"],
            actual=payload.get("actual"),
            optimized=payload.get("optimized"),
            delta=payload.get("delta"),
            unit=payload["unit"],
        )


@dataclass(frozen=True)
class BalanceScore:
    """Composite 0-100 score per spec §9.

    ``actual`` and ``delta`` are ``None`` in v1 because Shell 06's
    ``summary.json["actual_results"]`` carries only aggregates — no
    per-match rows for the actual tournament — so ``same_club_early_rate``
    and ``rematch_rate`` for the actual side cannot be computed.
    Substituting zero would bias the actual baseline upward by 20 points;
    the renderer surfaces ``"n/a"`` instead.
    """

    actual: float | None
    optimized: float
    delta: float | None
    preset_id: str
    # Data-quality penalty applied to the optimized score for teams with
    # insufficient game history (low_games) or no point-in-time snapshot
    # (snapshot_fallback). Defaults to 0.0 for backward compatibility with
    # pre-penalty Report Cards on disk.
    data_quality_penalty: float = 0.0
    low_games_team_count: int = 0
    snapshot_fallback_team_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BalanceScore":
        return cls(
            actual=payload.get("actual"),
            optimized=float(payload["optimized"]),
            delta=payload.get("delta"),
            preset_id=payload["preset_id"],
            data_quality_penalty=float(payload.get("data_quality_penalty") or 0.0),
            low_games_team_count=int(payload.get("low_games_team_count") or 0),
            snapshot_fallback_team_count=int(payload.get("snapshot_fallback_team_count") or 0),
        )


@dataclass(frozen=True)
class RiskFlag:
    """One amber-block entry on the Report Card.

    ``category`` is a free-form string for v1 — validated by the
    template's render-side branching, not by ``__post_init__``, so new
    categories can land without a schema bump.
    """

    severity: RiskSeverity
    category: str
    message: str
    affected_teams: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RiskFlag":
        return cls(
            severity=payload["severity"],
            category=payload["category"],
            message=payload["message"],
            affected_teams=tuple(payload.get("affected_teams") or ()),
        )


@dataclass(frozen=True)
class TeamMovement:
    """One actual-vs-optimized division reseat.

    ``canonical_team_id`` is the FK that survives rescrape (verified at
    ``backtest_tournament_cohort.py:300, 790-803``). ``team_name`` is the
    operator-facing display name from the registry's ``event_team_name``.
    """

    canonical_team_id: str
    team_name: str
    from_division: str
    to_division: str
    move: TeamMove

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TeamMovement":
        return cls(
            canonical_team_id=payload["canonical_team_id"],
            team_name=payload["team_name"],
            from_division=payload["from_division"],
            to_division=payload["to_division"],
            move=payload["move"],
        )


@dataclass(frozen=True)
class StandingsRow:
    """One team's record within a division — actual or optimized side.

    Both sides use the same shape so the template renders identically.
    ``avg_gd`` is signed (positive = team scored more than allowed).
    """

    canonical_team_id: str
    team_name: str
    division_name: str
    played: int
    wins: int
    losses: int
    ties: int
    goals_for: int
    goals_against: int
    goal_differential: int
    pool_label: str = ""
    """Bracket / pool label within the division (e.g. ``"A"``, ``"B"``).
    Empty string for divisions that ran as a single pool. Used by the
    template to render per-bracket standings sub-tables instead of one
    monolithic division table — backtest-mode invariant: the report's
    standings layout must mirror the actual tournament's bracket
    structure."""

    @property
    def avg_goal_differential(self) -> float:
        return float(self.goal_differential) / self.played if self.played else 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StandingsRow":
        return cls(
            canonical_team_id=payload["canonical_team_id"],
            team_name=payload["team_name"],
            division_name=payload["division_name"],
            played=int(payload["played"]),
            wins=int(payload["wins"]),
            losses=int(payload["losses"]),
            ties=int(payload["ties"]),
            goals_for=int(payload["goals_for"]),
            goals_against=int(payload["goals_against"]),
            goal_differential=int(payload["goal_differential"]),
            pool_label=str(payload.get("pool_label") or ""),
        )


@dataclass(frozen=True)
class BetterExperienceRow:
    """One team whose simulated experience would have been more competitive
    than what they actually got. Ranked by absolute reduction in pain
    (actual ``|avg_gd|`` minus optimized ``|avg_gd|``)."""

    canonical_team_id: str
    team_name: str
    actual_division: str
    actual_avg_gd: float
    optimized_division: str
    optimized_avg_gd: float
    pain_reduction: float  # |actual_avg_gd| - |optimized_avg_gd|, positive = better

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BetterExperienceRow":
        return cls(
            canonical_team_id=payload["canonical_team_id"],
            team_name=payload["team_name"],
            actual_division=payload["actual_division"],
            actual_avg_gd=float(payload["actual_avg_gd"]),
            optimized_division=payload["optimized_division"],
            optimized_avg_gd=float(payload["optimized_avg_gd"]),
            pain_reduction=float(payload["pain_reduction"]),
        )


@dataclass(frozen=True)
class HeadlineSummary:
    """Above-the-fold one-paragraph summary for a TD."""

    team_count: int
    better_experience_count: int
    asked_to_step_up_count: int
    unchanged_count: int
    actual_avg_gd: float | None
    optimized_avg_gd: float | None
    actual_close_game_rate: float | None
    optimized_close_game_rate: float | None
    actual_blowout_5plus_rate: float | None
    optimized_blowout_5plus_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HeadlineSummary":
        return cls(
            team_count=int(payload.get("team_count") or 0),
            better_experience_count=int(payload.get("better_experience_count") or 0),
            asked_to_step_up_count=int(payload.get("asked_to_step_up_count") or 0),
            unchanged_count=int(payload.get("unchanged_count") or 0),
            actual_avg_gd=payload.get("actual_avg_gd"),
            optimized_avg_gd=payload.get("optimized_avg_gd"),
            actual_close_game_rate=payload.get("actual_close_game_rate"),
            optimized_close_game_rate=payload.get("optimized_close_game_rate"),
            actual_blowout_5plus_rate=payload.get("actual_blowout_5plus_rate"),
            optimized_blowout_5plus_rate=payload.get("optimized_blowout_5plus_rate"),
        )


@dataclass(frozen=True)
class DivisionBalanceRow:
    """Per-division actual-vs-optimized scorecard. Surfaces which divisions
    were the worst-built and which would benefit most from re-seeding."""

    division_name: str
    team_count: int
    actual_match_count: int
    actual_avg_gd: float
    actual_close_game_rate: float
    actual_blowout_5plus_rate: float
    optimized_match_count: int
    optimized_avg_gd: float
    optimized_close_game_rate: float
    optimized_blowout_5plus_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DivisionBalanceRow":
        return cls(
            division_name=payload["division_name"],
            team_count=int(payload["team_count"]),
            actual_match_count=int(payload["actual_match_count"]),
            actual_avg_gd=float(payload["actual_avg_gd"]),
            actual_close_game_rate=float(payload["actual_close_game_rate"]),
            actual_blowout_5plus_rate=float(payload["actual_blowout_5plus_rate"]),
            optimized_match_count=int(payload["optimized_match_count"]),
            optimized_avg_gd=float(payload["optimized_avg_gd"]),
            optimized_close_game_rate=float(payload["optimized_close_game_rate"]),
            optimized_blowout_5plus_rate=float(payload["optimized_blowout_5plus_rate"]),
        )


@dataclass(frozen=True)
class EarlyMeetingConcern:
    """One operational red-flag matchup the TD needs to be aware of: same-club
    or intra-event rematch in pool/semi rounds. ``side`` is "actual" or
    "optimized" to distinguish concerns the actual schedule has from
    concerns the optimized schedule introduces."""

    side: str  # "actual" | "optimized"
    kind: str  # "same_club" | "rematch"
    division_name: str
    stage: str  # "Pool" | "Semi Final A" | "Semi Final B" for optimized; for actual, stage may be ""
    home_team_name: str
    away_team_name: str
    detail: str  # e.g. "shared club: Phoenix Rising" or "second meeting in pool play"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EarlyMeetingConcern":
        return cls(
            side=payload["side"],
            kind=payload["kind"],
            division_name=payload["division_name"],
            stage=payload.get("stage", ""),
            home_team_name=payload["home_team_name"],
            away_team_name=payload["away_team_name"],
            detail=payload.get("detail", ""),
        )


@dataclass(frozen=True)
class Champion:
    """Per-division winner: team with best record. Used for both actual
    and projected sides of the Report Card. Tie-break: wins desc, GD desc,
    GF desc, team_name asc.

    ``side`` is "actual" or "projected" so the renderer can pair them.
    ``optimized_division`` is filled only on the actual side and only when
    the team also appears in the optimized standings — lets the template
    show "won Blue actual, projected to Red" inline.
    """

    side: str  # "actual" | "projected"
    division_name: str
    canonical_team_id: str
    team_name: str
    wins: int
    losses: int
    ties: int
    goals_for: int
    goals_against: int
    goal_differential: int
    optimized_division: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Champion":
        return cls(
            side=payload["side"],
            division_name=payload["division_name"],
            canonical_team_id=payload["canonical_team_id"],
            team_name=payload["team_name"],
            wins=int(payload["wins"]),
            losses=int(payload["losses"]),
            ties=int(payload["ties"]),
            goals_for=int(payload["goals_for"]),
            goals_against=int(payload["goals_against"]),
            goal_differential=int(payload["goal_differential"]),
            optimized_division=payload.get("optimized_division", ""),
        )


@dataclass(frozen=True)
class TopReason:
    """One auto-generated "why MatchBalance beats the status quo" bullet."""

    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TopReason":
        return cls(text=payload["text"])


@dataclass(frozen=True)
class OverrideAuditRow:
    """Passthrough container for one ``run_overrides_audit.jsonl`` record.

    The orchestrator (``run_orchestrator._write_run_overrides_audit``)
    already stamps every row with ``run_id``, ``applied_at``,
    ``delta_balance_score``, plus the schema-version gate. This dataclass
    enforces ``assert_supported_version`` on read and round-trips the dict
    verbatim — equivalent to inlining the call but explicit at the type
    boundary.
    """

    record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.record)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OverrideAuditRow":
        assert_supported_version(payload, source="OverrideAuditRow")
        return cls(record=dict(payload))


@dataclass(frozen=True)
class ReportCard:
    """Composite Report Card payload — one per ``(event_key, scenario, run_id)``.

    Hand-written ``to_dict`` recurses via ``[child.to_dict() for child in self.<tuple>]``
    (mirrors ``TournamentScheduleSimulation.to_dict`` at
    ``schedule_simulator.py:120``). ``from_dict`` is lenient on
    ``schema_version`` per the storage convention; the strict gate lives
    in ``read_comparison_json`` (mirrors ``FrozenMedians`` at
    ``frozen_medians.py:80``).
    """

    event_key: str
    scenario: str
    run_id: str
    age_group: str
    gender: str
    event_name: str
    computed_at: str
    balance_score: BalanceScore
    metrics: tuple[Metric, ...]
    risk_flags: tuple[RiskFlag, ...]
    top_reasons: tuple[TopReason, ...]
    team_movements: tuple[TeamMovement, ...]
    override_audit: tuple[OverrideAuditRow, ...] = field(default_factory=tuple)
    actual_standings: tuple[StandingsRow, ...] = field(default_factory=tuple)
    optimized_standings: tuple[StandingsRow, ...] = field(default_factory=tuple)
    better_experience: tuple[BetterExperienceRow, ...] = field(default_factory=tuple)
    worse_experience: tuple[BetterExperienceRow, ...] = field(default_factory=tuple)
    headline_summary: HeadlineSummary | None = None
    division_balance: tuple[DivisionBalanceRow, ...] = field(default_factory=tuple)
    early_meeting_concerns: tuple[EarlyMeetingConcern, ...] = field(default_factory=tuple)
    actual_champions: tuple[Champion, ...] = field(default_factory=tuple)
    projected_champions: tuple[Champion, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "scenario": self.scenario,
            "run_id": self.run_id,
            "age_group": self.age_group,
            "gender": self.gender,
            "event_name": self.event_name,
            "computed_at": self.computed_at,
            "balance_score": self.balance_score.to_dict(),
            "metrics": [m.to_dict() for m in self.metrics],
            "risk_flags": [r.to_dict() for r in self.risk_flags],
            "top_reasons": [t.to_dict() for t in self.top_reasons],
            "team_movements": [m.to_dict() for m in self.team_movements],
            "override_audit": [a.to_dict() for a in self.override_audit],
            "actual_standings": [s.to_dict() for s in self.actual_standings],
            "optimized_standings": [s.to_dict() for s in self.optimized_standings],
            "better_experience": [b.to_dict() for b in self.better_experience],
            "worse_experience": [b.to_dict() for b in self.worse_experience],
            "headline_summary": self.headline_summary.to_dict() if self.headline_summary else None,
            "division_balance": [d.to_dict() for d in self.division_balance],
            "early_meeting_concerns": [c.to_dict() for c in self.early_meeting_concerns],
            "actual_champions": [c.to_dict() for c in self.actual_champions],
            "projected_champions": [c.to_dict() for c in self.projected_champions],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportCard":
        return cls(
            event_key=payload["event_key"],
            scenario=payload["scenario"],
            run_id=payload["run_id"],
            age_group=payload["age_group"],
            gender=payload["gender"],
            event_name=payload["event_name"],
            computed_at=payload["computed_at"],
            balance_score=BalanceScore.from_dict(payload["balance_score"]),
            metrics=tuple(Metric.from_dict(m) for m in payload.get("metrics") or ()),
            risk_flags=tuple(RiskFlag.from_dict(r) for r in payload.get("risk_flags") or ()),
            top_reasons=tuple(TopReason.from_dict(t) for t in payload.get("top_reasons") or ()),
            team_movements=tuple(TeamMovement.from_dict(m) for m in payload.get("team_movements") or ()),
            override_audit=tuple(OverrideAuditRow.from_dict(a) for a in payload.get("override_audit") or ()),
            actual_standings=tuple(StandingsRow.from_dict(s) for s in payload.get("actual_standings") or ()),
            optimized_standings=tuple(StandingsRow.from_dict(s) for s in payload.get("optimized_standings") or ()),
            better_experience=tuple(BetterExperienceRow.from_dict(b) for b in payload.get("better_experience") or ()),
            worse_experience=tuple(BetterExperienceRow.from_dict(b) for b in payload.get("worse_experience") or ()),
            headline_summary=HeadlineSummary.from_dict(payload["headline_summary"]) if payload.get("headline_summary") else None,
            division_balance=tuple(DivisionBalanceRow.from_dict(d) for d in payload.get("division_balance") or ()),
            early_meeting_concerns=tuple(EarlyMeetingConcern.from_dict(c) for c in payload.get("early_meeting_concerns") or ()),
            actual_champions=tuple(Champion.from_dict(c) for c in payload.get("actual_champions") or ()),
            projected_champions=tuple(Champion.from_dict(c) for c in payload.get("projected_champions") or ()),
            schema_version=int(payload.get("schema_version", 1)),
        )


@dataclass(frozen=True)
class CohortScorecardRow:
    """One row of the event-level cohort scorecard table."""

    age_group: str
    gender: str
    run_id: str
    team_count: int
    division_count: int
    balance_score_optimized: float
    data_quality_penalty: float
    better_experience_count: int
    asked_to_step_up_count: int
    actual_avg_gd: float | None
    optimized_avg_gd: float | None
    actual_blowout_5plus_rate: float | None
    optimized_blowout_5plus_rate: float | None
    optimized_match_count: int
    concerns_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CohortScorecardRow":
        return cls(
            age_group=payload["age_group"],
            gender=payload["gender"],
            run_id=payload["run_id"],
            team_count=int(payload["team_count"]),
            division_count=int(payload["division_count"]),
            balance_score_optimized=float(payload["balance_score_optimized"]),
            data_quality_penalty=float(payload.get("data_quality_penalty") or 0.0),
            better_experience_count=int(payload["better_experience_count"]),
            asked_to_step_up_count=int(payload["asked_to_step_up_count"]),
            actual_avg_gd=payload.get("actual_avg_gd"),
            optimized_avg_gd=payload.get("optimized_avg_gd"),
            actual_blowout_5plus_rate=payload.get("actual_blowout_5plus_rate"),
            optimized_blowout_5plus_rate=payload.get("optimized_blowout_5plus_rate"),
            optimized_match_count=int(payload["optimized_match_count"]),
            concerns_count=int(payload["concerns_count"]),
        )


@dataclass(frozen=True)
class EventReportCard:
    """Event-wide rollup across all completed cohort runs in a scenario.

    Computed by walking ``reports/<event>/scenarios/<scenario>/runs/`` and
    aggregating one ``ReportCard`` per cohort (latest completed run wins).
    Mirrors ``ReportCard``'s shape conventions: hand-written ``to_dict`` /
    ``from_dict``, schema_version stamp, dataclass(frozen=True).
    """

    event_key: str
    scenario: str
    event_name: str
    computed_at: str
    cohort_count: int
    total_team_count: int
    avg_balance_score_optimized: float
    min_balance_score_optimized: float
    max_balance_score_optimized: float
    aggregate_actual_avg_gd: float | None
    aggregate_optimized_avg_gd: float | None
    aggregate_actual_close_game_rate: float | None
    aggregate_optimized_close_game_rate: float | None
    aggregate_actual_blowout_5plus_rate: float | None
    aggregate_optimized_blowout_5plus_rate: float | None
    cohort_scorecards: tuple[CohortScorecardRow, ...]
    event_better_experience: tuple[BetterExperienceRow, ...]
    event_worse_experience: tuple[BetterExperienceRow, ...]
    event_concerns: tuple[EarlyMeetingConcern, ...]
    cohort_champions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "scenario": self.scenario,
            "event_name": self.event_name,
            "computed_at": self.computed_at,
            "cohort_count": self.cohort_count,
            "total_team_count": self.total_team_count,
            "avg_balance_score_optimized": self.avg_balance_score_optimized,
            "min_balance_score_optimized": self.min_balance_score_optimized,
            "max_balance_score_optimized": self.max_balance_score_optimized,
            "aggregate_actual_avg_gd": self.aggregate_actual_avg_gd,
            "aggregate_optimized_avg_gd": self.aggregate_optimized_avg_gd,
            "aggregate_actual_close_game_rate": self.aggregate_actual_close_game_rate,
            "aggregate_optimized_close_game_rate": self.aggregate_optimized_close_game_rate,
            "aggregate_actual_blowout_5plus_rate": self.aggregate_actual_blowout_5plus_rate,
            "aggregate_optimized_blowout_5plus_rate": self.aggregate_optimized_blowout_5plus_rate,
            "cohort_scorecards": [c.to_dict() for c in self.cohort_scorecards],
            "event_better_experience": [b.to_dict() for b in self.event_better_experience],
            "event_worse_experience": [b.to_dict() for b in self.event_worse_experience],
            "event_concerns": [c.to_dict() for c in self.event_concerns],
            "cohort_champions": list(self.cohort_champions),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventReportCard":
        return cls(
            event_key=payload["event_key"],
            scenario=payload["scenario"],
            event_name=payload["event_name"],
            computed_at=payload["computed_at"],
            cohort_count=int(payload["cohort_count"]),
            total_team_count=int(payload["total_team_count"]),
            avg_balance_score_optimized=float(payload["avg_balance_score_optimized"]),
            min_balance_score_optimized=float(payload["min_balance_score_optimized"]),
            max_balance_score_optimized=float(payload["max_balance_score_optimized"]),
            aggregate_actual_avg_gd=payload.get("aggregate_actual_avg_gd"),
            aggregate_optimized_avg_gd=payload.get("aggregate_optimized_avg_gd"),
            aggregate_actual_close_game_rate=payload.get("aggregate_actual_close_game_rate"),
            aggregate_optimized_close_game_rate=payload.get("aggregate_optimized_close_game_rate"),
            aggregate_actual_blowout_5plus_rate=payload.get("aggregate_actual_blowout_5plus_rate"),
            aggregate_optimized_blowout_5plus_rate=payload.get("aggregate_optimized_blowout_5plus_rate"),
            cohort_scorecards=tuple(CohortScorecardRow.from_dict(c) for c in payload.get("cohort_scorecards") or ()),
            event_better_experience=tuple(BetterExperienceRow.from_dict(b) for b in payload.get("event_better_experience") or ()),
            event_worse_experience=tuple(BetterExperienceRow.from_dict(b) for b in payload.get("event_worse_experience") or ()),
            event_concerns=tuple(EarlyMeetingConcern.from_dict(c) for c in payload.get("event_concerns") or ()),
            cohort_champions=tuple(payload.get("cohort_champions") or ()),
            schema_version=int(payload.get("schema_version", 1)),
        )
