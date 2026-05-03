"""Per-cohort tournament structure dataclasses + CSV round-trip.

Spec §7 defines the per-cohort structure inputs the Streamlit UI collects
and the CLI consumes via ``group_structure_summary.csv`` (legacy filename
preserved). v1 ships ``name / team_count / pool_sizes / advancement`` per
division — the existing ``DivisionSpec`` contract at
``src/tournaments/seeding_optimizer.py:35``. Richer per-division template
fields (``pool_play_games``, ``knockout_format``) are deferred until a
later shell needs them.

Schema-version stamp lives in the sibling
``group_structure_summary.schema.json`` (one stamp per file), not as a
per-row dataclass field.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.tournaments.storage._io import read_csv, read_json, write_csv, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

if TYPE_CHECKING:
    from src.tournaments.seeding_optimizer import DivisionSpec

logger = logging.getLogger(__name__)

__all__ = [
    "CohortStructure",
    "DivisionStructure",
    "FIELDNAMES",
    "derive_structure_from_game_results",
    "derive_structure_from_raw_scrape",
    "derive_structure_from_standings",
    "read_structure",
    "write_structure",
]


# Cohort keys round-trip through ``normalize_age_group`` /
# ``normalize_gender_label`` so the structure CSV's keys match the
# Streamlit UI's iteration order — ``_group_cohorts`` keys cohorts by
# the same normalized (age, gender) tuple. Division names ARE preserved
# verbatim (gotsport's ``group_name``: ``Red``, ``White``,
# ``Capelli Sport+ Southwest``, etc.) — only the cohort header is
# normalized for UI compatibility.
def _age_sort_key(age: str) -> int:
    """Stabilize cohort order: ``u9 < u10 < u13`` rather than lex-sorting."""
    match = re.search(r"\d+", age)
    return int(match.group(0)) if match else 999


FIELDNAMES: tuple[str, ...] = (
    "cohort_age_group",
    "cohort_gender",
    "division_name",
    "team_count",
    "pool_sizes",
    "advancement",
)


@dataclass(frozen=True)
class DivisionStructure:
    """One division within a cohort.

    Field-for-field compatible with ``seeding_optimizer.DivisionSpec`` so
    ``to_division_spec()`` is a direct construction.
    """

    name: str
    team_count: int
    pool_sizes: tuple[int, ...] = ()
    advancement: str | None = None

    def to_division_spec(self) -> "DivisionSpec":
        """Return a ``DivisionSpec`` for the seeding optimizer.

        Imported lazily so this module's import cost stays minimal — the
        seeding optimizer pulls in ``itertools`` / ``math`` / heavy match
        machinery that storage callers don't always need.
        """
        from src.tournaments.seeding_optimizer import DivisionSpec

        return DivisionSpec(
            name=self.name,
            team_count=self.team_count,
            pool_sizes=self.pool_sizes,
            advancement=self.advancement,
        )


@dataclass(frozen=True)
class CohortStructure:
    """All divisions for one ``(age_group, gender)`` cohort."""

    age_group: str
    gender: str
    divisions: tuple[DivisionStructure, ...]


def _serialize_pool_sizes(pool_sizes: tuple[int, ...]) -> str:
    """``(4, 4, 4)`` -> ``"4|4|4"``; ``()`` -> ``""``."""
    return "|".join(str(size) for size in pool_sizes)


def _deserialize_pool_sizes(raw: str) -> tuple[int, ...]:
    """``"4|4|4"`` -> ``(4, 4, 4)``; ``""`` -> ``()``."""
    raw = (raw or "").strip()
    if not raw:
        return ()
    return tuple(int(part) for part in raw.split("|") if part.strip())


def _schema_path(scenario_path: Path) -> Path:
    return scenario_path / "group_structure_summary.schema.json"


def _csv_path(scenario_path: Path) -> Path:
    return scenario_path / "group_structure_summary.csv"


def read_structure(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> list[CohortStructure]:
    """Read ``group_structure_summary.csv`` and group rows by cohort.

    Sibling ``group_structure_summary.schema.json`` is validated via
    ``assert_supported_version`` (raises on a newer schema). FIELDNAMES
    drift is logged as a warning, not raised — same forward-compat policy
    as ``registry.read_registry``.
    """
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    schema_path = _schema_path(scenario_path)
    if schema_path.exists():
        sidecar = read_json(schema_path)
        assert_supported_version(sidecar, source=str(schema_path))
        sidecar_fields = tuple(sidecar.get("fieldnames") or ())
        if sidecar_fields and sidecar_fields != FIELDNAMES:
            logger.warning(
                "[structure] %s sibling FIELDNAMES drift; on-disk=%s expected=%s",
                schema_path.name,
                sidecar_fields,
                FIELDNAMES,
            )

    rows = read_csv(_csv_path(scenario_path))
    grouped: dict[tuple[str, str], list[DivisionStructure]] = defaultdict(list)
    cohort_order: list[tuple[str, str]] = []
    for row in rows:
        cohort_key = (
            str(row.get("cohort_age_group") or ""),
            str(row.get("cohort_gender") or ""),
        )
        if cohort_key not in grouped:
            cohort_order.append(cohort_key)
        team_count_raw = str(row.get("team_count") or "0").strip() or "0"
        advancement_raw = str(row.get("advancement") or "").strip()
        grouped[cohort_key].append(
            DivisionStructure(
                name=str(row.get("division_name") or ""),
                team_count=int(team_count_raw),
                pool_sizes=_deserialize_pool_sizes(str(row.get("pool_sizes") or "")),
                advancement=advancement_raw or None,
            )
        )

    return [
        CohortStructure(
            age_group=cohort_key[0],
            gender=cohort_key[1],
            divisions=tuple(grouped[cohort_key]),
        )
        for cohort_key in cohort_order
    ]


def derive_structure_from_raw_scrape(
    records: Iterable[dict[str, Any]],
    *,
    pools_by_group_id: dict[str, Any] | None = None,
) -> list[CohortStructure]:
    """Reconstruct ``CohortStructure`` list from ``raw_scrape.jsonl`` records.

    Backtest mode: the past tournament's structure is a fact captured in
    the scrape. Each record's ``cohort_age_group`` /
    ``cohort_gender`` (normalized via ``normalize_age_group`` /
    ``normalize_gender_label`` so the keys match the Streamlit UI's
    cohort iteration) is the cohort header; ``group_name`` (e.g.,
    ``"Red"``, ``"Washington"``, ``"Capelli Sport+ Southwest"``) is
    the division name — preserved verbatim, never renamed.
    ``team_count`` is the count of records sharing that
    ``(natural_cohort, group_name)`` pair.

    Records with no parseable ``cohort_age_group`` are dropped (no cohort
    identity); records with no ``group_name`` are dropped (no division
    identity). ``advancement`` stays empty — that's a schedule-page
    detail not yet captured.

    When ``pools_by_group_id`` is provided (from
    ``intake/pool_assignments.json`` written by the pool enricher),
    ``DivisionStructure.pool_sizes`` is populated as the tuple of pool
    team counts in pool-label sort order. The map is keyed by the
    gotsport tier ``group_id``; the join is ``group_id`` carried on each
    raw_scrape record. Tiers with no captured pool data leave
    ``pool_sizes`` empty.
    """
    # Lazy import to avoid pulling the seeding optimizer's heavy deps
    # (itertools / math / match machinery) into every storage caller.
    from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label

    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    cohorts_seen: set[tuple[str, str]] = set()
    divisions_by_cohort: dict[tuple[str, str], set[str]] = defaultdict(set)
    group_id_by_division: dict[tuple[str, str, str], str] = {}

    # Lazy import: avoid a circular ``triage`` <-> ``storage`` dependency at
    # module load time (triage already imports several storage primitives).
    from src.tournaments.triage import effective_cohort_for_team

    for rec in records:
        try:
            natural_age = normalize_age_group(str(rec.get("cohort_age_group") or ""))
        except ValueError:
            continue
        natural_gender = normalize_gender_label(str(rec.get("cohort_gender") or ""))
        # Backtest-mode play-up routing: a team filed in U13 Boys naturally
        # but with ``playing_up: True`` and ``also_appears_in_brackets: ["U14B"]``
        # belongs to U14 Boys' structure for derivation purposes.
        age, gender = effective_cohort_for_team(natural_age, natural_gender, rec)
        division = str(rec.get("group_name") or "").strip()
        if not division:
            continue
        cohort_key = (age, gender)
        cohorts_seen.add(cohort_key)
        divisions_by_cohort[cohort_key].add(division)
        counts[(age, gender, division)] += 1
        group_id = rec.get("group_id")
        if group_id is not None and (age, gender, division) not in group_id_by_division:
            group_id_by_division[(age, gender, division)] = str(group_id)

    pools_lookup = pools_by_group_id or {}

    def _pool_sizes_for(age: str, gender: str, division: str) -> tuple[int, ...]:
        gid = group_id_by_division.get((age, gender, division))
        if gid is None:
            return ()
        pools = pools_lookup.get(gid) or pools_lookup.get(str(gid))
        if not pools:
            return ()
        # Tolerate both PoolAssignment dataclass instances and plain dicts
        # (the storage layer round-trips dataclasses; tests can pass dicts).
        return tuple(
            getattr(p, "team_count", None)
            if hasattr(p, "team_count")
            else len(p.get("provider_team_ids") or ())
            for p in sorted(
                pools,
                key=lambda p: getattr(p, "label", None) or p.get("label") or "",
            )
        )

    return [
        CohortStructure(
            age_group=age,
            gender=gender,
            divisions=tuple(
                DivisionStructure(
                    name=div,
                    team_count=counts[(age, gender, div)],
                    pool_sizes=_pool_sizes_for(age, gender, div),
                )
                for div in sorted(divisions_by_cohort[(age, gender)])
            ),
        )
        for age, gender in sorted(cohorts_seen, key=lambda c: (_age_sort_key(c[0]), c[1]))
    ]


def write_structure(
    event_key: str,
    scenario: str,
    cohorts: list[CohortStructure],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Write cohorts to ``group_structure_summary.csv`` + sibling schema stamp."""
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    rows: list[dict[str, str]] = []
    for cohort in cohorts:
        for division in cohort.divisions:
            rows.append(
                {
                    "cohort_age_group": cohort.age_group,
                    "cohort_gender": cohort.gender,
                    "division_name": division.name,
                    "team_count": str(division.team_count),
                    "pool_sizes": _serialize_pool_sizes(division.pool_sizes),
                    "advancement": division.advancement or "",
                }
            )
    write_csv(_csv_path(scenario_path), rows, fieldnames=FIELDNAMES)
    write_json(
        _schema_path(scenario_path),
        stamp_schema_version({"fieldnames": list(FIELDNAMES)}),
    )


def derive_structure_from_game_results(
    raw_scrape_records: Iterable[dict[str, Any]],
    game_results: list[Any],
    *,
    canonical_team_id_by_provider_id: dict[str, str] | None = None,
) -> list[CohortStructure]:
    """Derive backtest-faithful structure from actually-played games.

    Backtest-mode invariant: division/group structure must mirror the
    actual tournament. Only team assignments are optimizable. This helper
    inverts ``derive_structure_from_raw_scrape``'s heuristic
    (which relies on ``pools_by_group_id`` from a separate pool-enricher
    artifact) by reading ``game_results.jsonl`` directly:

    - **Division names** = each team's actual played tier
      (``raw_scrape.group_name``), same as the roster derivation.
    - **team_count per division** = unique canonical-team count among
      teams that actually PLAYED at least one game in that division.
      Teams in raw_scrape that never appeared in a game (DNS, dropped
      late) are excluded — the optimizer can only seed teams that
      actually played.
    - **pool_sizes per division** = inferred from games-per-team
      distribution. If every team in the division played the same N
      games and N+1 == team_count, the format is a single round-robin
      pool of (team_count) teams ``(team_count,)``. If teams played
      ~K-1 games and team_count is divisible by K, the format is
      ``team_count // K`` pools of K (e.g. 8 teams playing 3 each ->
      ``(4, 4)``). Non-standard formats (e.g. "4-game guarantee" with
      6 teams each playing 4 of 5 opponents) leave ``pool_sizes``
      empty so the simulator falls back to a single round-robin and
      the structure-mismatch risk flag fires downstream.
    - **advancement** stays empty in v1 (knockout structure inference
      is a v2 widening).

    ``canonical_team_id_by_provider_id`` lets the caller pre-bridge from
    game_results' reg-id keys to canonical pids; when absent, the helper
    treats game-side reg-ids as opaque identifiers (game-count math still
    works, but per-team identity won't cross-link to raw_scrape rows).
    """
    from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label
    from src.tournaments.triage import effective_cohort_for_team

    # Index raw_scrape: provider_team_id -> (cohort_key, division_name)
    team_to_cohort_div: dict[str, tuple[tuple[str, str], str]] = {}
    cohorts_seen: set[tuple[str, str]] = set()
    divisions_by_cohort: dict[tuple[str, str], set[str]] = defaultdict(set)
    pid_to_reg: dict[str, str] = {}
    for rec in raw_scrape_records:
        try:
            natural_age = normalize_age_group(str(rec.get("cohort_age_group") or ""))
        except ValueError:
            continue
        natural_gender = normalize_gender_label(str(rec.get("cohort_gender") or ""))
        # Play-up routing — same as derive_structure_from_raw_scrape.
        age, gender = effective_cohort_for_team(natural_age, natural_gender, rec)
        division = str(rec.get("group_name") or "").strip()
        if not division:
            continue
        cohort_key = (age, gender)
        cohorts_seen.add(cohort_key)
        divisions_by_cohort[cohort_key].add(division)
        pid = str(rec.get("provider_team_id") or "")
        if pid:
            team_to_cohort_div[pid] = (cohort_key, division)
            reg = str(rec.get("provider_registration_id") or "")
            if reg:
                pid_to_reg[pid] = reg

    # Reverse lookup: reg_id -> pid (game_results stores reg_ids)
    reg_to_pid = {reg: pid for pid, reg in pid_to_reg.items()}

    # Bucket games per (cohort_key, division, team_pid). Count distinct
    # opponents within the division too so we can detect the "play 4 of 5"
    # partial round-robin format that doesn't fit pool_sizes.
    games_per_team: dict[tuple[tuple[str, str], str, str], int] = defaultdict(int)
    teams_played: dict[tuple[tuple[str, str], str], set[str]] = defaultdict(set)
    for game in game_results:
        if getattr(game, "home_score", None) is None or getattr(game, "away_score", None) is None:
            continue
        home_reg = str(getattr(game, "home_provider_team_id", "") or "")
        away_reg = str(getattr(game, "away_provider_team_id", "") or "")
        home_pid = reg_to_pid.get(home_reg)
        away_pid = reg_to_pid.get(away_reg)
        if not home_pid or not away_pid:
            continue
        home_loc = team_to_cohort_div.get(home_pid)
        away_loc = team_to_cohort_div.get(away_pid)
        if home_loc is None or away_loc is None:
            continue
        # Only count INTRA-division games (cross-division would be a
        # different format altogether — knockout, crossover, etc.).
        if home_loc != away_loc:
            continue
        cohort_key, division = home_loc
        games_per_team[(cohort_key, division, home_pid)] += 1
        games_per_team[(cohort_key, division, away_pid)] += 1
        teams_played[(cohort_key, division)].add(home_pid)
        teams_played[(cohort_key, division)].add(away_pid)

    def _infer_pool_sizes(team_count: int, games_each: int) -> tuple[int, ...]:
        """Map (team_count, games_each) -> pool_sizes. Empty tuple when
        the format is non-standard (operator should review)."""
        if team_count <= 0:
            return ()
        if games_each + 1 == team_count:
            return (team_count,)  # single round-robin pool
        # Multi-pool: each team plays (K-1) games inside their pool of K.
        # team_count must be divisible by K.
        K = games_each + 1
        if K >= 2 and team_count % K == 0:
            num_pools = team_count // K
            return tuple([K] * num_pools)
        return ()  # non-standard (e.g., 4-game guarantee in N=6)

    cohort_structures: list[CohortStructure] = []
    for cohort_key in sorted(cohorts_seen, key=lambda c: (_age_sort_key(c[0]), c[1])):
        divisions: list[DivisionStructure] = []
        for division in sorted(divisions_by_cohort[cohort_key]):
            played_teams = teams_played.get((cohort_key, division), set())
            team_count = len(played_teams)
            if team_count == 0:
                continue  # division had no played games yet
            # Median games-per-team — robust to byes / forfeits with
            # different counts. Sort and pick the middle value.
            counts = sorted(
                games_per_team[(cohort_key, division, pid)] for pid in played_teams
            )
            median = counts[len(counts) // 2]
            divisions.append(
                DivisionStructure(
                    name=division,
                    team_count=team_count,
                    pool_sizes=_infer_pool_sizes(team_count, median),
                )
            )
        if divisions:
            cohort_structures.append(
                CohortStructure(
                    age_group=cohort_key[0],
                    gender=cohort_key[1],
                    divisions=tuple(divisions),
                )
            )
    return cohort_structures


def derive_structure_from_standings(
    raw_scrape_records: Iterable[dict[str, Any]],
    standings: list[tuple[str, Any]],
    *,
    pools_by_group_id: dict[str, list[dict[str, Any]]] | None = None,
    games: list[Any] | None = None,
) -> list[CohortStructure]:
    """Backtest ground-truth structure from gotsport standings tables.

    Standings are the most reliable source: gotsport renders one row per
    team per pool, with ``rank`` reset per pool (rank=1 starts a new pool
    boundary). Counting rows per pool gives ``pool_sizes`` exactly;
    counting distinct rank=1 markers gives ``pool_count`` per division.

    Cohort and division identity comes from joining
    ``standings[i].provider_team_id`` (the gotsport canonical team id)
    against ``raw_scrape.provider_team_id`` to look up cohort_age_group /
    cohort_gender / group_name. Play-up routing is applied via
    ``effective_cohort_for_team`` so a team that competed up an age group
    is filed in the older cohort.

    Returns ``[]`` when standings are empty (event not yet completed, or
    schedule pages had no standings tables).
    """
    from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label
    from src.tournaments.triage import effective_cohort_for_team

    if not standings:
        return []

    # Standings page links carry per-event REGISTRATION ids, while
    # raw_scrape.provider_team_id is the canonical API id (post canonical-id
    # resolver). Bridge through provider_registration_id so the lookup
    # succeeds. Mirrors the pattern used by run_orchestrator and the
    # actual-standings computation.
    raw_by_pid: dict[str, dict[str, Any]] = {}
    raw_by_reg: dict[str, dict[str, Any]] = {}
    for rec in raw_scrape_records:
        pid = str(rec.get("provider_team_id") or "")
        reg = str(rec.get("provider_registration_id") or "")
        if pid:
            raw_by_pid[pid] = rec
        if reg:
            raw_by_reg[reg] = rec

    def _lookup_raw(team_id_from_standings: str) -> dict[str, Any] | None:
        if team_id_from_standings in raw_by_pid:
            return raw_by_pid[team_id_from_standings]
        return raw_by_reg.get(team_id_from_standings)

    # Bucket standings by (cohort_key, division_name).  Within each bucket,
    # split into pools at every "rank == 1" boundary (pools render
    # consecutively per group_id; rank resets at each new pool table).
    pool_sizes_by_division: dict[tuple[tuple[str, str], str], list[int]] = defaultdict(list)
    teams_by_division: dict[tuple[tuple[str, str], str], int] = defaultdict(int)
    cohorts_seen: set[tuple[str, str]] = set()
    divisions_by_cohort: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Group standings by group_id so we process pools per division in order.
    by_group: dict[str, list[Any]] = defaultdict(list)
    for group_id, standing in standings:
        by_group[str(group_id)].append(standing)

    for group_id, rows in by_group.items():
        # Determine the (cohort, division) for this group_id by looking at
        # the first standings team's raw_scrape record. All teams in one
        # group_id share the same tier (gotsport's tier == our division).
        rec = None
        for r in rows:
            pid = str(getattr(r, "provider_team_id", "") or "")
            rec = _lookup_raw(pid)
            if rec is not None:
                break
        if rec is None:
            continue
        try:
            natural_age = normalize_age_group(str(rec.get("cohort_age_group") or ""))
        except ValueError:
            continue
        natural_gender = normalize_gender_label(str(rec.get("cohort_gender") or ""))
        # NOTE: play-up routing typically applies to the TEAM not the group;
        # gotsport tiers stay in the older bracket regardless of any one
        # team's natural age. We use the natural cohort of the FIRST raw
        # record we matched. For a play-up team that's the only sample
        # match, the routing flips appropriately.
        age, gender = effective_cohort_for_team(natural_age, natural_gender, rec)
        division = str(rec.get("group_name") or "").strip()
        if not division:
            continue
        cohort_key = (age, gender)
        cohorts_seen.add(cohort_key)
        divisions_by_cohort[cohort_key].add(division)

        # Detect pool boundaries: each rank==1 row starts a new pool. Count
        # rows per pool. Standings rows are ordered top-down; ranks within a
        # pool are 1..N consecutively.
        current_pool_size = 0
        pool_sizes: list[int] = []
        for r in rows:
            rank = int(getattr(r, "rank", 0) or 0)
            if rank == 1 and current_pool_size > 0:
                pool_sizes.append(current_pool_size)
                current_pool_size = 0
            current_pool_size += 1
        if current_pool_size > 0:
            pool_sizes.append(current_pool_size)

        # Aggregate across multiple group_ids that map to the same
        # (cohort, division)? Unusual — gotsport tiers are 1:1 with our
        # divisions. If it ever happens, concatenate the pool sizes.
        pool_sizes_by_division[(cohort_key, division)].extend(pool_sizes)
        teams_by_division[(cohort_key, division)] += sum(pool_sizes)

    # Detect playoff format per division when caller provides pool
    # assignments + games (the additional inputs needed). Without them
    # advancement stays empty (the simulator falls back to round-robin).
    playoff_formats: dict[tuple[str, str, str], str] = {}
    if pools_by_group_id and games is not None:
        from src.tournaments.playoff_format import detect_playoff_formats_for_event

        playoff_formats = detect_playoff_formats_for_event(
            list(raw_by_pid.values()) + list(raw_by_reg.values()),
            pools_by_group_id,
            games,
            standings,
        )

    cohort_structures: list[CohortStructure] = []
    for cohort_key in sorted(cohorts_seen, key=lambda c: (_age_sort_key(c[0]), c[1])):
        divisions: list[DivisionStructure] = []
        for division in sorted(divisions_by_cohort[cohort_key]):
            advancement = playoff_formats.get((cohort_key[0], cohort_key[1], division)) or None
            divisions.append(
                DivisionStructure(
                    name=division,
                    team_count=teams_by_division[(cohort_key, division)],
                    pool_sizes=tuple(pool_sizes_by_division[(cohort_key, division)]),
                    advancement=advancement,
                )
            )
        if divisions:
            cohort_structures.append(
                CohortStructure(
                    age_group=cohort_key[0],
                    gender=cohort_key[1],
                    divisions=tuple(divisions),
                )
            )
    return cohort_structures
