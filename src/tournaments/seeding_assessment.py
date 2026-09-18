"""Quote and review facts for the accepted roster, independent of ratings."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.tournaments.gotsport_event_roster import published_u_ages
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_pack import duplicate_identity_rows

_PRICING = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend/lib/matchbalance-pricing.json").read_text(encoding="utf-8")
)


def event_price(team_count: int) -> str:
    if team_count <= 0:
        return "—"
    return next(tier["price"] for tier in _PRICING if tier["maxTeams"] is None or team_count <= tier["maxTeams"])


def age_number(row: RosterRow) -> int | None:
    match = re.fullmatch(r"u([0-9]{1,2})", row.section_age_group.lower())
    return int(match[1]) if match else None


def source_fingerprint(rows: Sequence[RosterRow]) -> str:
    """Bind coverage and decisions to all source fields, including registration identity."""
    return hashlib.sha256(json.dumps([asdict(row) for row in rows], sort_keys=True).encode()).hexdigest()


def package_roster(parsed: ParsedRoster) -> ParsedRoster:
    return ParsedRoster(tuple(row for row in parsed.rows if age_number(row) is None or age_number(row) >= 10),
                        parsed.warnings)


def could_belong(row: RosterRow, age: str, gender: str) -> bool:
    if row.section_gender and row.section_gender != gender:
        return False
    if row.section_age_group:
        return row.section_age_group == age
    # Constrain uncertainty to every published age, including inclusive ranges.
    ages = published_u_ages(row.listed_division, expand_ranges=True)
    if ages:
        return age in {"u19" if value == 18 else f"u{value}" for value in ages}
    return True


def effective_roster(
    parsed: ParsedRoster, decisions: Mapping[int, dict[str, Any]], *, include_excluded: bool = False,
) -> ParsedRoster:
    rows = []
    for row in parsed.rows:
        decision = decisions.get(row.source_index, {})
        if decision.get("exclude") and not include_excluded:
            continue
        fields = {key: decision[key] for key in (
            "section_age_group", "section_gender", "team_name_raw", "team_name_stripped", "intake_issue",
            "has_star_marker", "has_c_marker",
        ) if key in decision}
        rows.append(replace(row, **fields))
    return ParsedRoster(tuple(rows), parsed.warnings)


def corrected_identities(before, after, resolved, overrides):
    """Name edits invalidate identity; cohort edits invalidate cohort-based name matches."""
    old = {row.source_index: row for row in before.rows}
    new = {row.source_index: row for row in after.rows}
    outcomes, manual = [], dict(overrides)
    reset = set()
    for item in resolved:
        previous, current = old.get(item.source_index), new.get(item.source_index)
        if previous and current:
            name_changed = previous.team_name_raw != current.team_name_raw
            cohort_changed = (previous.section_age_group, previous.section_gender) != (
                current.section_age_group, current.section_gender)
            if name_changed or (cohort_changed and item.status in ("exact_name", "review")
                                and item.source_index not in manual):
                item = ResolvedTeam(item.source_index, "unresolved")
                manual.pop(item.source_index, None)
                reset.add(item.source_index)
        outcomes.append(item)
    return tuple(outcomes), manual, reset


@dataclass(frozen=True)
class Assessment:
    total: int
    possible_total: int
    matched: int
    manual: frozenset[int]
    pending: frozenset[int]
    not_found: frozenset[int]
    cohort_review: frozenset[int]
    attention: frozenset[int]
    cohorts: tuple[dict[str, Any], ...]
    provisional: bool
    price: str
    excluded: int


def assess_roster(
    parsed: ParsedRoster, resolved: Sequence[ResolvedTeam], overrides: Mapping[int, dict[str, Any]],
    *, coverage: str = "unknown", completed: Sequence[int] | None = None,
) -> Assessment:
    by_index = {item.source_index: item for item in resolved}
    active = [row for row in parsed.rows if age_number(row) is None or age_number(row) >= 10]
    active_indices = {row.source_index for row in active}
    confirmed = [row for row in active if age_number(row) is not None and not row.intake_issue]
    duplicate_rows = duplicate_identity_rows(active, resolved, overrides)
    not_found = {
        index for index, override in overrides.items()
        if index in active_indices and (override or {}).get("not_found")
    }
    manual, pending, cohort_review, matched = set(), set(), set(), set()
    for row in active:
        index = row.source_index
        item = by_index.get(index)
        if index in not_found:
            pass
        else:
            override_id = (overrides.get(index) or {}).get("team_id_master")
            identity = override_id or (
                item.team_id_master if item and item.status in ("gotsport_id", "exact_name") else None
            )
            if identity and index not in duplicate_rows:
                matched.add(index)
            elif index in duplicate_rows or (completed is None or index in completed):
                manual.add(index)
            else:
                pending.add(index)
        if age_number(row) is None or row.section_gender not in ("Male", "Female") or row.intake_issue:
            cohort_review.add(index)
    groups: dict[tuple[str, str], list[int]] = {}
    for row in active:
        if row.source_index not in cohort_review:
            groups.setdefault((row.section_age_group, row.section_gender), []).append(row.source_index)
    cohorts = []
    for (age, gender), indices in sorted(groups.items(), key=lambda pair: (int(pair[0][0][1:]), pair[0][1])):
        open_count = len(set(indices) - matched - not_found)
        uncertain_members = any(row.source_index in cohort_review and could_belong(row, age, gender) for row in active)
        ready = coverage == "complete" and not uncertain_members and not open_count
        cohorts.append({
            "Cohort": f"{'Boys' if gender == 'Male' else 'Girls'} {age.upper()}",
            "key": f"{age}|{gender}", "Teams": len(indices), "Matched": len(indices) - open_count,
            "Open": open_count, "Status": "Ready" if ready else "Review matches" if open_count else "Check coverage",
        })
    total, maximum = len(confirmed), len(active)
    provisional = coverage != "complete" or bool(cohort_review)
    low, high = event_price(total), event_price(maximum)
    price = low if low == high else f"{low} to {high}"
    if coverage != "complete":
        price = (f"{low} minimum" if low.startswith("$") else low) if total else "Pending full roster"
    return Assessment(total, maximum, len(matched), frozenset(manual), frozenset(pending),
                      frozenset(not_found), frozenset(cohort_review),
                      frozenset(manual | pending | cohort_review), tuple(cohorts),
                      provisional, price, len(parsed.rows) - len(active))


def carry_decisions(old_rows, new_rows, overrides, decisions):
    """Carry only unique, unchanged registrations; never carry a row-number match."""
    old_counts = Counter(row.registration_id for row in old_rows if row.registration_id)
    new_counts = Counter(row.registration_id for row in new_rows if row.registration_id)
    old_by_id = {row.registration_id: row for row in old_rows if row.registration_id}
    kept_overrides, kept_decisions = {}, {}
    for row in new_rows:
        previous = old_by_id.get(row.registration_id)
        if not previous or old_counts[row.registration_id] != 1 or new_counts[row.registration_id] != 1:
            continue
        if (previous.team_name_raw, previous.listed_division, previous.provider_team_id) != (
            row.team_name_raw, row.listed_division, row.provider_team_id
        ):
            continue
        if previous.source_index in overrides:
            kept_overrides[row.source_index] = dict(overrides[previous.source_index])
        if previous.source_index in decisions:
            kept_decisions[row.source_index] = dict(decisions[previous.source_index])
    return kept_overrides, kept_decisions
