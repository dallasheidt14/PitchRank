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
    "derive_structure_from_raw_scrape",
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

    for rec in records:
        try:
            age = normalize_age_group(str(rec.get("cohort_age_group") or ""))
        except ValueError:
            continue
        gender = normalize_gender_label(str(rec.get("cohort_gender") or ""))
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
