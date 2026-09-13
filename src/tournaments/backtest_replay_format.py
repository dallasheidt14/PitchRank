"""Translate captured division fixtures into an executable replay graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from src.tournaments.schedule_simulator import CAPTURED_GRAPH_FORMAT

_MATCH_REFERENCE = re.compile(r"\b(winner|loser)\b.*?\b(?:match|game)?\s*#?\s*(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReplayFormatAssessment:
    format_code: str = ""
    reason: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.format_code) and not self.reason


def _fixture_sort_key(indexed_fixture: tuple[int, Any]) -> tuple[int, int, str, int]:
    index, fixture = indexed_fixture
    number = str(fixture.match_number or "").strip()
    if number.isdigit():
        return 0, int(number), "", index
    return 1, index, str(fixture.kickoff or ""), index


def ordered_captured_fixtures(fixtures: Sequence[Any]) -> tuple[Any, ...]:
    """Use published match numbers when page tables are not chronological."""

    return tuple(item for _, item in sorted(enumerate(fixtures), key=_fixture_sort_key))


def _participant_identity(registration_id: str | None, label: str) -> tuple[str, str]:
    registration = str(registration_id or "").strip()
    if registration:
        return "registration", registration
    return "name", " ".join(str(label or "").split()).casefold()


def build_captured_fixture_slots(division, fixtures: Sequence[Any] | None = None) -> tuple[dict[str, Any], ...]:
    """Build exact scheduled edges plus qualification references from saved evidence."""

    ordered = ordered_captured_fixtures(tuple(fixtures if fixtures is not None else division.fixtures))
    if not ordered:
        raise ValueError("No fixture rows were captured")

    participant_slots: dict[tuple[str, str], tuple[int, int, int]] = {}
    ambiguous_names: set[tuple[str, str]] = set()
    for pool_index, pool in enumerate(division.pools):
        for slot_index, member in enumerate(pool.members):
            registration_key = _participant_identity(member.registration_id, "")
            if registration_key[1]:
                participant_slots[registration_key] = (
                    pool_index,
                    slot_index,
                    int(member.standings_position) - 1,
                )
            name_key = _participant_identity(None, member.team_name)
            if not name_key[1]:
                continue
            if name_key in participant_slots:
                ambiguous_names.add(name_key)
            else:
                participant_slots[name_key] = (
                    pool_index,
                    slot_index,
                    int(member.standings_position) - 1,
                )
    for key in ambiguous_names:
        participant_slots.pop(key, None)

    match_number_to_index = {
        str(fixture.match_number): index
        for index, fixture in enumerate(ordered)
        if str(fixture.match_number or "").strip()
    }

    def historical_loser(fixture: Any) -> str:
        winner = str(fixture.winner_registration_id or "")
        home = str(fixture.home_registration_id or "")
        away = str(fixture.away_registration_id or "")
        if not winner:
            return ""
        return away if winner == home else home if winner == away else ""

    def side_reference(
        fixture: Any,
        *,
        side: str,
        match_index: int,
    ) -> dict[str, Any]:
        registration_id = getattr(fixture, f"{side}_registration_id")
        label = str(getattr(fixture, f"{side}_label") or "")
        if fixture.kind == "bracket":
            label_reference = _MATCH_REFERENCE.search(label)
            if label_reference:
                referenced = match_number_to_index.get(label_reference.group(2))
                if referenced is not None and referenced < match_index:
                    return {
                        "kind": "match_winner" if label_reference.group(1).casefold() == "winner" else "match_loser",
                        "match_index": referenced,
                        "evidence": "published_slot_label",
                    }
            registration = str(registration_id or "")
            if registration:
                for prior_index in range(match_index - 1, -1, -1):
                    prior = ordered[prior_index]
                    if prior.kind != "bracket":
                        continue
                    if registration == str(prior.winner_registration_id or ""):
                        return {
                            "kind": "match_winner",
                            "match_index": prior_index,
                            "evidence": "captured_result_path",
                        }
                    if registration == historical_loser(prior):
                        return {
                            "kind": "match_loser",
                            "match_index": prior_index,
                            "evidence": "captured_result_path",
                        }

        identity = _participant_identity(registration_id, label)
        slot = participant_slots.get(identity)
        if slot is None:
            raise ValueError(
                f"Fixture {fixture.match_number or fixture.source_url} {side} side "
                f"'{label or registration_id}' does not resolve to a captured pool member or prior match"
            )
        pool_index, slot_index, final_rank = slot
        if fixture.kind == "bracket":
            return {
                "kind": "pool_rank",
                "pool_index": pool_index,
                "rank": final_rank,
                "evidence": "captured_final_standings_position",
            }
        return {
            "kind": "pool_slot",
            "pool_index": pool_index,
            "slot_index": slot_index,
            "evidence": "captured_fixture_participant",
        }

    slots: list[dict[str, Any]] = []
    for match_index, fixture in enumerate(ordered):
        if fixture.kind not in {"pool", "cross_pool", "bracket"}:
            raise ValueError(
                f"Fixture {fixture.match_number or fixture.source_url} has unclassified stage '{fixture.kind}'"
            )
        home = side_reference(fixture, side="home", match_index=match_index)
        away = side_reference(fixture, side="away", match_index=match_index)
        if fixture.kind == "pool":
            stage = "Pool"
            pool_index = int(home["pool_index"])
            pool_name = str(division.pools[pool_index].label or f"Pool {pool_index + 1}")
        elif fixture.kind == "cross_pool":
            stage = "Cross-pool"
            pool_name = ""
        else:
            stage = str(fixture.bracket_label or "Bracket")
            pool_name = ""
        slots.append(
            {
                "match_number": str(fixture.match_number or ""),
                "stage": stage,
                "pool_name": pool_name,
                "counts_for_standings": fixture.kind in {"pool", "cross_pool"},
                "home": home,
                "away": away,
                "source_url": str(fixture.source_url or division.source_url or ""),
            }
        )
    return tuple(slots)


def assess_replay_format(division, *, manual_format: str = "") -> ReplayFormatAssessment:
    """Confirm that every captured fixture can be replayed without a canned shape."""

    del manual_format
    if not division.pools_readable or not division.fixtures_readable:
        return ReplayFormatAssessment(reason="Pools or fixtures could not be read completely")
    pool_sizes = tuple(len(pool.members) for pool in division.pools)
    if not pool_sizes or any(size <= 0 for size in pool_sizes):
        return ReplayFormatAssessment(reason="No complete pool membership was captured")
    try:
        build_captured_fixture_slots(division)
    except ValueError as exc:
        return ReplayFormatAssessment(reason=str(exc))
    return ReplayFormatAssessment(format_code=CAPTURED_GRAPH_FORMAT)
