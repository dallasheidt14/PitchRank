"""Per-team triage projection + readiness predicate.

Single source of truth for the four-state team classification model
(``resolved`` / ``candidates`` / ``placeholder`` / ``external``) plus the
``unknown`` blocker state. The projection collapses an append-only
``overrides.jsonl`` ledger into the latest per-team / per-cohort state.

Three shells consume this module:

- Shell 04 (triage UI) — renders rows tinted by ``_classify_team_state``,
  writes overrides via ``build_override_record`` + ``append_override``.
- Shell 06 (run gate) — calls ``is_ready`` to refuse a run when any team is
  not resolved or any cohort lacks structure / games-coverage.
- Shell 07 (Report Card) — re-uses ``project_overrides`` so the post-run
  metrics see the same per-team state the operator triaged.

Pure-Python — no Streamlit, no Supabase imports. The caller injects a
Supabase client into ``is_ready`` when the placeholder + games-coverage
checks need DB access.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from src.tournaments.storage import (
    SchemaVersionError,
    check_games_import_status,
    check_local_results_coverage,
    load_overrides,
    load_raw_scrape,
    read_event_metadata,
    read_registry,
    read_structure,
)

# Sanity-gate format for ``actor`` emails. Not RFC 5322 — just enough to
# refuse "x" / "asdf" / "   " from contaminating the audit ledger.
_ACTOR_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

logger = logging.getLogger(__name__)

__all__ = [
    "DivisionResolution",
    "DivisionSource",
    "ProjectedCohortState",
    "ProjectedTeamState",
    "ReadinessResult",
    "SOURCE_EXPLICIT",
    "SOURCE_NONE",
    "SOURCE_PREFIX",
    "SOURCE_STALE",
    "TeamState",
    "_OVERRIDE_TYPES",
    "_STRENGTH_MODES",
    "_classify_team_state",
    "_is_placeholder_team",
    "_is_play_up",
    "build_override_record",
    "is_ready",
    "project_overrides",
    "registry_provider_id",
    "resolve_division_assignment",
]


_OVERRIDE_TYPES: tuple[str, ...] = (
    "accept_match",
    "fix_match",
    "mark_external",
    "edit_external",
    "manual_add",
    "recompute_medians",
    "assign_division",
)
"""Closed set of override ``type`` values. Pinned by tests so a future
refactor can't quietly add a new one without updating the projection
table.
"""

_STRENGTH_MODES: tuple[str, ...] = ("median", "manual", "exclude")
"""Strength-mode vocabulary for external teams. ``exclude`` semantics for
the Report Card are deferred to Shell 07 — this shell only persists the
value.
"""

_TEAM_SCOPED_TYPES: frozenset[str] = frozenset(
    {"accept_match", "fix_match", "mark_external", "edit_external", "manual_add", "assign_division"}
)
_COHORT_SCOPED_TYPES: frozenset[str] = frozenset({"recompute_medians"})


TeamState = Literal["resolved", "candidates", "placeholder", "external", "unknown"]


@dataclass(frozen=True)
class ProjectedTeamState:
    """Latest projected per-team override state.

    ``last_override_ts`` is the ``ts`` of the record that produced this
    projection — useful for audit and debounce, never reads the prior
    projection's ts.
    """

    state: TeamState
    team_id_master: str | None = None
    manual_seed_group: str | None = None
    assigned_division_name: str | None = None
    strength_mode: str | None = None
    manual_power_score: float | None = None
    note: str | None = None
    last_override_ts: str | None = None
    # ``cohort_age_group`` + ``cohort_gender`` are populated for ``manual_add``
    # overrides only. The registry CSV doesn't carry manual-add rows, so
    # these fields are how ``is_ready`` discovers them. Other override types
    # leave them ``None`` — the cohort comes from the registry entry instead.
    cohort_age_group: str | None = None
    cohort_gender: str | None = None


@dataclass(frozen=True)
class ProjectedCohortState:
    """Latest projected per-cohort override state (medians only for v1)."""

    medians_by_division: Mapping[str, float] = field(default_factory=dict)
    last_override_ts: str | None = None


@dataclass(frozen=True)
class ReadinessResult:
    """Output of ``is_ready``. ``blockers`` is empty iff ``ready`` is True."""

    ready: bool
    blockers: tuple[str, ...]


def _is_placeholder_team(team_name: str | None, provider_team_id: str) -> bool:
    """Return True if ``team_name`` is the canonical ``unknown_<pid>`` placeholder.

    Authoritative predicate at ``scripts/scrape_games.py:50-58``. Inlined
    here rather than imported to keep this module independent of the
    scripts package (script-side ``sys.path`` setup is brittle for a
    storage-tier import).
    """
    name = (team_name or "").strip()
    pid = (provider_team_id or "").strip()
    if not name or not pid:
        return False
    return name.lower() == f"unknown_{pid}".lower()


def _is_play_up(resolved_age: str | None, cohort_age: str) -> bool:
    """Return True if the resolved team's age cohort is younger than its registered cohort.

    "Play-up" in youth soccer = a team competing in an older age cohort
    than its rostered birth-year cohort. ``u12`` team in ``u14`` cohort →
    True. Same age → False. Missing inputs → False (not enough info to
    judge).
    """
    if not resolved_age or not cohort_age:
        return False
    try:
        resolved_n = int(str(resolved_age).removeprefix("u").removeprefix("U"))
        cohort_n = int(str(cohort_age).removeprefix("u").removeprefix("U"))
    except (TypeError, ValueError):
        return False
    return resolved_n < cohort_n


def _classify_team_state(
    record: dict,
    *,
    resolved_team: dict | None,
    projected: ProjectedTeamState | None,
) -> TeamState:
    """Project (raw_scrape record + override) → one of five UI states.

    Priority order:

    1. Override-projected ``external`` wins outright — the operator
       explicitly externalized the team.
    2. Override-projected ``resolved`` becomes ``placeholder`` only when
       the resolved team's name matches ``unknown_<provider_team_id>``.
       Otherwise it's a real ``resolved``.
    3. Fall through to the scraper's ``canonical.scraper_state``:

       - ``review_queued`` → ``candidates`` (operator must triage).
       - ``alias_written`` → ``placeholder`` if the linked DB team is the
         ``unknown_<pid>`` row, else ``resolved``.
       - ``unresolved`` → ``external`` (no DB candidate; operator can edit
         or accept the externalization).

    4. Anything else (missing ``canonical``, novel state) → ``unknown``.
       Returning ``unknown`` instead of silently labelling the team
       ``external`` keeps a corrupted scrape journal from passing
       readiness — ``is_ready`` lists ``unknown`` as a blocker.
    """
    pid = str(record.get("provider_team_id") or "").strip()

    if projected is not None:
        if projected.state == "external":
            return "external"
        if projected.state == "resolved":
            if resolved_team and _is_placeholder_team(resolved_team.get("team_name"), pid):
                return "placeholder"
            return "resolved"

    canonical = record.get("canonical") or {}
    scraper_state = canonical.get("scraper_state")

    if scraper_state == "review_queued":
        return "candidates"
    if scraper_state == "alias_written":
        if resolved_team is None:
            return "unknown"
        if _is_placeholder_team(resolved_team.get("team_name"), pid):
            return "placeholder"
        return "resolved"
    if scraper_state == "unresolved":
        return "external"

    return "unknown"


def build_override_record(
    *,
    ts: str,
    actor: str,
    scope: str,
    type: str,
    team_ref: str,
    before: dict,
    after: dict,
    reason: str,
) -> dict:
    """Build an override envelope dict ready for ``append_override``.

    Refuses empty ``actor`` (page-level reviewer-email gate must produce a
    non-empty value). Refuses ``type`` outside ``_OVERRIDE_TYPES`` and
    ``scope`` outside ``("team", "cohort")``. Schema-version stamping is
    the storage layer's job — this builder leaves it off.
    """
    actor_clean = (actor or "").strip()
    if not actor_clean:
        raise ValueError("override actor must be a non-empty reviewer email")
    if not _ACTOR_EMAIL_RE.fullmatch(actor_clean):
        raise ValueError(f"override actor must be a valid reviewer email; got {actor!r}")
    if type not in _OVERRIDE_TYPES:
        raise ValueError(f"override type {type!r} not in {_OVERRIDE_TYPES!r}")
    if scope not in ("team", "cohort"):
        raise ValueError(f"override scope must be 'team' or 'cohort'; got {scope!r}")
    return {
        "ts": ts,
        "actor": actor,
        "scope": scope,
        "type": type,
        "team_ref": team_ref,
        "before": dict(before or {}),
        "after": dict(after or {}),
        "reason": reason,
    }


def _apply_team_override(
    type_: str,
    after: Mapping[str, Any],
    prior: ProjectedTeamState | None,
    *,
    ts: str | None,
) -> ProjectedTeamState:
    """Apply a single team-scoped override to the prior projection.

    Per-type rules pinned in the plan's Override Record Contract §6.
    """
    after = after or {}
    carried_division = prior.assigned_division_name if prior is not None else None
    if type_ == "assign_division":
        carry = prior or ProjectedTeamState(state="unknown")
        return replace(
            carry,
            assigned_division_name=str(after.get("assigned_division_name") or "") or None,
            last_override_ts=ts,
        )
    if type_ in ("accept_match", "fix_match"):
        return ProjectedTeamState(
            state="resolved",
            team_id_master=str(after.get("team_id_master") or "") or None,
            assigned_division_name=carried_division,
            last_override_ts=ts,
        )
    if type_ == "mark_external":
        return ProjectedTeamState(
            state="external",
            assigned_division_name=carried_division,
            last_override_ts=ts,
        )
    if type_ == "edit_external":
        strength_mode = str(after.get("strength_mode") or "") or None
        manual_power_score = _coerce_optional_float(after.get("manual_power_score"))
        if strength_mode != "manual":
            manual_power_score = None
        carried_team_id = prior.team_id_master if prior is not None else None
        return ProjectedTeamState(
            state="external",
            team_id_master=carried_team_id,
            manual_seed_group=str(after.get("manual_seed_group") or "") or None,
            assigned_division_name=carried_division,
            strength_mode=strength_mode,
            manual_power_score=manual_power_score,
            note=str(after.get("note") or "") or None,
            last_override_ts=ts,
        )
    if type_ == "manual_add":
        state = str(after.get("state") or "")
        cohort_age = str(after.get("cohort_age_group") or "") or None
        cohort_gender = str(after.get("cohort_gender") or "") or None
        if state == "resolved":
            return ProjectedTeamState(
                state="resolved",
                team_id_master=str(after.get("team_id_master") or "") or None,
                manual_seed_group=str(after.get("manual_seed_group") or "") or None,
                assigned_division_name=carried_division,
                last_override_ts=ts,
                cohort_age_group=cohort_age,
                cohort_gender=cohort_gender,
            )
        # Default to external for any non-"resolved" manual_add — keeps
        # the projection deterministic if the writer ever omits the field.
        strength_mode = str(after.get("strength_mode") or "") or None
        manual_power_score = _coerce_optional_float(after.get("manual_power_score"))
        if strength_mode != "manual":
            manual_power_score = None
        return ProjectedTeamState(
            state="external",
            manual_seed_group=str(after.get("manual_seed_group") or "") or None,
            assigned_division_name=carried_division,
            strength_mode=strength_mode,
            manual_power_score=manual_power_score,
            note=str(after.get("note") or "") or None,
            last_override_ts=ts,
            cohort_age_group=cohort_age,
            cohort_gender=cohort_gender,
        )
    raise ValueError(f"unhandled team-scoped override type: {type_!r}")


def _coerce_optional_float(value: Any) -> float | None:
    """Defensive ``float()`` for override-projection scalars.

    A future writer could persist ``""`` / non-numeric strings — without
    this guard, ``float(value)`` raises ``ValueError`` mid-projection and
    corrupts the entire scenario's ``team_state``. Returning ``None`` on
    parse failure keeps the team rendered as median-mode (no manual score).
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


DivisionSource = Literal["explicit", "prefix", "stale", "none"]
"""Pinned vocabulary for ``DivisionResolution.source``. Re-exported so
callers can branch on the constants below instead of bare string literals
(typo-safe — a misspelled ``"None"`` would silently miscategorize)."""

SOURCE_EXPLICIT: DivisionSource = "explicit"
SOURCE_PREFIX: DivisionSource = "prefix"
SOURCE_STALE: DivisionSource = "stale"
SOURCE_NONE: DivisionSource = "none"


@dataclass(frozen=True)
class DivisionResolution:
    """Result of ``resolve_division_assignment``.

    ``source`` distinguishes never-assigned (``SOURCE_NONE``), operator-confirmed
    (``SOURCE_EXPLICIT``), heuristic-resolved (``SOURCE_PREFIX``), and
    assigned-to-deleted-division (``SOURCE_STALE``). Callers act on ``name`` for
    routing and on ``source`` for telemetry / fallback decisions.

    Approved consumer policies for ``SOURCE_STALE`` (intentionally diverge
    by use case):

    - ``run_orchestrator._build_cohort_request_payload`` — route the team
      to the prefix-resolved fallback name and emit a
      ``division_routing_stale_assignment`` parser_warning so cleanup is
      observable.
    - ``tournament_intake._build_division_groups`` — silently group with
      explicit/prefix matches. The Shell 04 left pane is purely a render
      surface; stale teams are surfaced separately by the per-row form.
    - ``tournament_intake._recompute_medians_inner`` — skip the team
      entirely (do NOT contaminate medians) and emit an ``st.warning``.
    """

    name: str | None
    source: DivisionSource


def resolve_division_assignment(
    projected: ProjectedTeamState | None,
    event_team_name: str | None,
    *,
    division_names: list[str],
) -> DivisionResolution:
    """Pick the authoritative division for a team in this cohort.

    Precedence: explicit override-projected assignment → longest-prefix
    match on ``event_team_name`` → none. The ``stale`` source surfaces
    removed-division cleanup needs distinctly from genuine "never
    assigned" teams.
    """
    if projected and projected.assigned_division_name:
        if projected.assigned_division_name in division_names:
            return DivisionResolution(name=projected.assigned_division_name, source=SOURCE_EXPLICIT)
        # Stale: division was renamed/removed in structure form.
        # Fall through to prefix; caller emits a parser_warning.
        return DivisionResolution(name=_longest_prefix(event_team_name, division_names), source=SOURCE_STALE)
    matched = _longest_prefix(event_team_name, division_names)
    if matched is None:
        return DivisionResolution(name=None, source=SOURCE_NONE)
    return DivisionResolution(name=matched, source=SOURCE_PREFIX)


def _longest_prefix(event_team_name: str | None, division_names: list[str]) -> str | None:
    """Return the longest division name that prefixes ``event_team_name``.

    Single source of truth for the bracket-prefix heuristic — reused by
    the resolver's prefix + stale paths.
    """
    bracket = (event_team_name or "").strip()
    if not bracket or not division_names:
        return None
    for name in sorted(division_names, key=len, reverse=True):
        if name and bracket.startswith(name):
            return name
    return None


def project_overrides(
    records: list[dict],
) -> tuple[Mapping[str, ProjectedTeamState], Mapping[str, ProjectedCohortState]]:
    """Walk overrides in append order; latest record per ``(scope, team_ref)`` wins.

    Records whose ``type`` is not in ``_OVERRIDE_TYPES`` are skipped with
    a single ``logging.warning`` (forward-compat — old code reading newer
    ledgers should not crash on unrecognized types).

    The append-only contract means there is no revert type — later writes
    simply replace the projected state for the same ``team_ref``.
    """
    team_state: dict[str, ProjectedTeamState] = {}
    cohort_state: dict[str, ProjectedCohortState] = {}

    for record in records or []:
        type_ = record.get("type")
        if type_ not in _OVERRIDE_TYPES:
            logger.warning("[triage] skipping override with unknown type=%r", type_)
            continue
        scope = record.get("scope")
        team_ref = str(record.get("team_ref") or "")
        ts = record.get("ts")
        after = record.get("after") or {}

        if scope == "team" and type_ in _TEAM_SCOPED_TYPES:
            prior = team_state.get(team_ref)
            team_state[team_ref] = _apply_team_override(type_, after, prior, ts=ts)
        elif scope == "cohort" and type_ in _COHORT_SCOPED_TYPES:
            cohort_state[team_ref] = ProjectedCohortState(
                medians_by_division=dict(after.get("medians_by_division") or {}),
                last_override_ts=ts,
            )
        else:
            logger.warning(
                "[triage] skipping override with mismatched scope=%r type=%r",
                scope,
                type_,
            )

    return team_state, cohort_state


def _scraper_state_from_status(status: str | None) -> str:
    """Map a registry ``canonical_resolution_status`` to the JSONL ``scraper_state``.

    Used by ``is_ready`` when raw_scrape is incomplete — falling back on
    the registry's snapshot is still better than ``unknown`` for every
    team that didn't appear in the journal.
    """
    if not status:
        return "unresolved"
    if status in ("direct_provider_id", "strict_exact", "high_confidence"):
        return "alias_written"
    if status == "review":
        return "review_queued"
    return "unresolved"


def _fetch_resolved_teams(
    supabase_client: Any,
    team_id_masters: Iterable[str],
) -> dict[str, dict]:
    """Fetch ``team_id_master → {team_id_master, team_name}`` for placeholder detection.

    Empty iterable or ``supabase_client is None`` returns ``{}`` — the
    caller skips the placeholder branch.
    """
    if supabase_client is None:
        return {}
    ids = sorted({str(tid) for tid in team_id_masters if tid})
    if not ids:
        return {}
    response = supabase_client.table("teams").select("team_id_master, team_name").in_("team_id_master", ids).execute()
    rows = response.data or []
    return {str(row["team_id_master"]): row for row in rows if row.get("team_id_master")}


def registry_provider_id(entry: Any) -> str:
    """Resolve the per-row provider key.

    Prefers ``resolved_gotsport_provider_team_id`` (post-resolution); falls
    back to ``event_registration_id`` for unresolved rows and manual-adds.
    """
    primary = str(getattr(entry, "resolved_gotsport_provider_team_id", "") or "").strip()
    if primary:
        return primary
    return str(getattr(entry, "event_registration_id", "") or "").strip()


def parse_bracket_key(bracket: str) -> tuple[str, str] | None:
    """``"U14B"`` -> ``("u14", "Male")``; ``"U13G"`` -> ``("u13", "Female")``.

    Returns ``None`` for unparseable bracket strings (e.g. tier-name-only
    brackets that don't carry a U-prefix).
    """
    bracket = (bracket or "").strip()
    if len(bracket) < 3 or not bracket.upper().startswith("U"):
        return None
    suffix = bracket[-1].upper()
    if suffix not in ("B", "G"):
        return None
    digits = bracket[1:-1]
    if not digits.isdigit():
        return None
    age = f"u{int(digits)}"
    gender = "Male" if suffix == "B" else "Female"
    return age, gender


def effective_cohort_for_team(
    natural_age: str,
    natural_gender: str,
    raw_record: dict[str, Any] | None,
) -> tuple[str, str]:
    """Backtest-mode cohort routing: a team belongs to the bracket they
    ACTUALLY competed in. A team filed under U13 Boys naturally but with
    ``playing_up: True`` and ``also_appears_in_brackets: ["U14B"]``
    belongs to U14 Boys for analysis purposes (their natural age is
    metadata, not identity).

    Falls back to the natural cohort when the raw_scrape record is
    missing, the team isn't playing up, or no bracket key parses cleanly.
    """
    if not raw_record:
        return natural_age, natural_gender
    if not raw_record.get("playing_up"):
        return natural_age, natural_gender
    appears_in = raw_record.get("also_appears_in_brackets") or []
    for bracket in appears_in:
        parsed = parse_bracket_key(str(bracket))
        if parsed is not None:
            return parsed
    return natural_age, natural_gender


def is_ready(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
    supabase_client: Any = None,
) -> ReadinessResult:
    """Return whether the scenario can hand off to a backtest run.

    Blockers are calibrated to the spec §7 validation rules:

    - Per team — any ``candidates`` / ``placeholder`` / ``unknown`` state.
    - Per cohort — missing structure, or ``check_games_import_status`` !=
      ``"complete"``.

    ``supabase_client`` is required for the placeholder + games-coverage
    checks. Without it, those branches are skipped and the result is a
    weaker "no scraper-state blockers" check — fine for unit-test
    construction but never accepted by Shell 06's gate.
    """
    registry = read_registry(event_key, scenario, base_dir=base_dir)
    overrides = load_overrides(event_key, scenario, base_dir=base_dir)
    try:
        structure = read_structure(event_key, scenario, base_dir=base_dir)
    except (FileNotFoundError, SchemaVersionError) as exc:
        # Rescrape can produce event_team_registry.csv before
        # group_structure_summary.csv exists; surface a typed blocker
        # rather than crashing the whole cohort render.
        return ReadinessResult(
            ready=False,
            blockers=(f"group structure missing or unreadable: {exc}",),
        )
    try:
        meta = read_event_metadata(event_key, base_dir=base_dir)
    except (FileNotFoundError, SchemaVersionError) as exc:
        return ReadinessResult(
            ready=False,
            blockers=(f"event metadata missing or unreadable: {exc}",),
        )
    raw_scrape = list(load_raw_scrape(event_key, base_dir=base_dir))

    team_state, _cohort_state = project_overrides(overrides)

    raw_by_pid: dict[str, dict] = {}
    for record in raw_scrape:
        pid = str(record.get("provider_team_id") or "").strip()
        if pid:
            raw_by_pid[pid] = record

    structure_by_cohort = {(c.age_group, c.gender): c for c in structure}

    team_ids_for_placeholder: set[str] = set()
    for entry in registry:
        pid = registry_provider_id(entry)
        projected = team_state.get(pid)
        if projected and projected.team_id_master:
            team_ids_for_placeholder.add(projected.team_id_master)
        elif entry.resolved_team_id_master:
            team_ids_for_placeholder.add(entry.resolved_team_id_master)
    resolved_team_by_id = _fetch_resolved_teams(supabase_client, team_ids_for_placeholder)

    blockers: list[str] = []
    cohorts_seen: set[tuple[str, str]] = set()
    cohort_team_ids: dict[tuple[str, str], set[str]] = {}
    cohort_provider_ids: dict[tuple[str, str], set[str]] = {}
    registry_pids = {registry_provider_id(entry) for entry in registry}
    registry_pids.discard("")

    for entry in registry:
        pid = registry_provider_id(entry)
        if not pid:
            continue

        record = raw_by_pid.get(pid)
        if record is None:
            record = {
                "provider_team_id": pid,
                "canonical": {
                    "scraper_state": _scraper_state_from_status(entry.canonical_resolution_status),
                },
            }
        # Backtest-mode play-up routing: bucket the team into the bracket
        # they actually competed in (older), not their natural age cohort.
        # Without this, preflight/coverage checks see the wrong roster
        # vs what the orchestrator builds at run time.
        cohort = effective_cohort_for_team(
            entry.event_age_group, entry.event_gender, record
        )
        cohorts_seen.add(cohort)
        projected = team_state.get(pid)

        team_id_master: str | None = None
        if projected and projected.team_id_master:
            team_id_master = projected.team_id_master
        elif entry.resolved_team_id_master:
            team_id_master = entry.resolved_team_id_master
        resolved_team = resolved_team_by_id.get(team_id_master) if team_id_master else None

        state = _classify_team_state(record, resolved_team=resolved_team, projected=projected)

        cohort_label = f"{cohort[1]} {cohort[0]}"
        team_label = entry.event_team_name or pid
        if state == "candidates":
            blockers.append(f"{cohort_label}: {team_label} pending review")
        elif state == "placeholder":
            blockers.append(f"{cohort_label}: {team_label} matched to placeholder")
        elif state == "unknown":
            blockers.append(f"{cohort_label}: {team_label} state unknown — re-scrape or triage")

        if state in ("resolved", "placeholder") and team_id_master:
            cohort_team_ids.setdefault(cohort, set()).add(team_id_master)
        # Local-coverage path joins on the gotsport reg_id stored in
        # ``game_results.jsonl`` (the schedule enricher extracts
        # ``team=<id>`` from anchor hrefs, which are reg_ids). The
        # canonical-id resolver rewrites ``provider_team_id`` on each
        # raw_scrape record to the api_id, so a join on ``pid`` would
        # never match a single game. Use ``provider_registration_id``
        # (preserved alongside the canonical id post-resolver), falling
        # back to ``pid`` for synthetic records or older journals that
        # pre-date the registration-id field.
        if state != "external":
            coverage_pid = str(record.get("provider_registration_id") or "") or pid
            cohort_provider_ids.setdefault(cohort, set()).add(coverage_pid)

    # Second pass: manual-add teams. They live only in ``team_state`` (never
    # in the registry CSV) and carry their cohort attribution in
    # ``ProjectedTeamState.cohort_age_group`` / ``cohort_gender``. Without
    # this walk, a manual-add team with zero games would slip past the
    # readiness gate.
    for team_ref, projected in team_state.items():
        if team_ref in registry_pids:
            continue
        if not team_ref.startswith("manual_"):
            continue
        cohort_age = projected.cohort_age_group
        cohort_gender = projected.cohort_gender
        if not cohort_age or not cohort_gender:
            blockers.append(f"manual-add {team_ref}: cohort attribution missing (rewrite override)")
            continue
        cohort = (cohort_age, cohort_gender)
        cohorts_seen.add(cohort)
        cohort_label = f"{cohort_gender} {cohort_age}"
        team_label = projected.note or team_ref
        if projected.state == "external":
            # External manual-adds aren't blockers; they pass through to the
            # ranking pane via frozen medians. Don't enforce games coverage
            # for them either.
            continue
        if projected.state == "resolved":
            if not projected.team_id_master:
                blockers.append(f"{cohort_label}: manual-add {team_label} missing team_id_master")
                continue
            cohort_team_ids.setdefault(cohort, set()).add(projected.team_id_master)
            continue
        # Any other state on a manual_add row is a misconfigured writer.
        blockers.append(f"{cohort_label}: manual-add {team_label} state {projected.state!r}")

    # Prefer the local artifact (``intake/game_results.jsonl``) when it
    # exists — backtest mode reads game results straight from gotsport's
    # schedule pages and shouldn't depend on the Supabase ``games`` table
    # being populated. Falls back to the Supabase coverage check (and its
    # ``games`` round-trip) only when no local artifact is present, which
    # is the seeding-mode signature.
    intake_dir_path = Path(base_dir) / event_key / "intake"
    local_results_path = intake_dir_path / "game_results.jsonl"
    use_local_coverage = local_results_path.exists()

    for cohort in sorted(cohorts_seen):
        cohort_label = f"{cohort[1]} {cohort[0]}"
        if cohort not in structure_by_cohort:
            blockers.append(f"{cohort_label}: structure not entered")
            continue
        # Mirror the optimizer's _pool_specs_from_division and _validate_flights
        # checks at preflight time so the cohort tints to amber before the user
        # burns a bulk-run cycle to discover an unrunnable structure.
        cohort_structure = structure_by_cohort[cohort]
        team_count_for_cohort = len(cohort_team_ids.get(cohort, set()))
        division_total_slots = 0
        for division in cohort_structure.divisions:
            pool_sizes = tuple(int(s) for s in (division.pool_sizes or ()) if int(s) > 0)
            if pool_sizes and sum(pool_sizes) != int(division.team_count):
                blockers.append(
                    f"{cohort_label}: division '{division.name}' pool sizes sum to "
                    f"{sum(pool_sizes)} but team_count is {division.team_count} — "
                    "edit pool sizes or team count in Division setup."
                )
            division_total_slots += int(division.team_count)
        if team_count_for_cohort and division_total_slots != team_count_for_cohort:
            blockers.append(
                f"{cohort_label}: division team_count totals {division_total_slots} but "
                f"{team_count_for_cohort} teams resolved to this cohort — add/remove teams "
                "or adjust division team counts in Division setup."
            )
        if use_local_coverage:
            provider_ids = cohort_provider_ids.get(cohort, set())
            if not provider_ids:
                blockers.append(f"{cohort_label}: no resolved teams in local coverage check")
                continue
            try:
                status = check_local_results_coverage(event_key, sorted(provider_ids), base_dir=base_dir)
            except Exception as exc:  # noqa: BLE001 — local file errors surface as blocker
                blockers.append(f"{cohort_label}: local games coverage check failed ({exc})")
                continue
            if status != "complete":
                blockers.append(f"{cohort_label}: local games coverage {status}")
            continue
        if supabase_client is None:
            continue
        team_ids = cohort_team_ids.get(cohort, set())
        try:
            status = check_games_import_status(meta.event_name, sorted(team_ids), supabase_client=supabase_client)
        except Exception as exc:  # noqa: BLE001 — Supabase failure surfaces as blocker, not crash
            blockers.append(f"{cohort_label}: games coverage check failed ({exc})")
            continue
        if status != "complete":
            blockers.append(f"{cohort_label}: games coverage {status}")

    return ReadinessResult(ready=not blockers, blockers=tuple(blockers))
