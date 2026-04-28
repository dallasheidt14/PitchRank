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
    "Metric",
    "OverrideAuditRow",
    "ReportCard",
    "RiskFlag",
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BalanceScore":
        return cls(
            actual=payload.get("actual"),
            optimized=float(payload["optimized"]),
            delta=payload.get("delta"),
            preset_id=payload["preset_id"],
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
            schema_version=int(payload.get("schema_version", 1)),
        )
