"""Translate captured division fixtures into an executable replay graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from src.tournaments.schedule_simulator import CAPTURED_GRAPH_FORMAT

_MATCH_REFERENCE = re.compile(
    r"\b(winner|loser)\b\s+(?:of\s+)?(?:match|game)\s*#?\s*(\d+)\b",
    re.IGNORECASE,
)
_WILDCARD_REFERENCE = re.compile(r"\bwild\s*card\s*#?\s*(\d+)\b", re.IGNORECASE)
_CROSS_POOL_QUALIFICATION = re.compile(
    r"\badvance\b.*\bregardless\s+of\s+(?:group|pool)\b",
    re.IGNORECASE,
)


def _include_fixture_in_projection(fixture: Any) -> bool:
    """Replay only fixtures that the capture proves were played.

    Legacy fixtures did not retain result status, so ``not_captured`` remains
    replayable only when both captured scores exist. New captures must contain
    both scores and an explicit ``played`` status.
    """

    status = str(getattr(fixture, "result_status", "not_captured") or "not_captured").strip().casefold()
    has_scores = (
        getattr(fixture, "home_score", None) is not None
        and getattr(fixture, "away_score", None) is not None
    )
    return has_scores and status in {"played", "not_captured"}


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
    """Use match numbers only when every captured fixture has one.

    GotSport occasionally leaves a real fixture's Match # blank. In that mixed
    case the parser's page order is the only complete published ordering;
    moving every numbered playoff match ahead of the blank pool row can resolve
    a qualifier before its standings games have run.
    """

    indexed = tuple(enumerate(fixtures))
    if any(not str(fixture.match_number or "").strip().isdigit() for _, fixture in indexed):
        return tuple(fixture for _, fixture in indexed)
    return tuple(item for _, item in sorted(indexed, key=_fixture_sort_key))


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

    match_number_indices: dict[str, list[int]] = {}
    for index, fixture in enumerate(ordered):
        number = str(fixture.match_number or "").strip()
        if number:
            match_number_indices.setdefault(number, []).append(index)
    division_wide_qualification = any(
        _CROSS_POOL_QUALIFICATION.search(str(pool.label or ""))
        for pool in division.pools
    )

    def wildcard_references(fixture: Any) -> dict[str, dict[str, Any]]:
        ranks = [int(value) - 1 for value in _WILDCARD_REFERENCE.findall(fixture.bracket_label)]
        if not ranks:
            return {}
        if not division_wide_qualification:
            raise ValueError(
                f"Fixture {fixture.match_number or fixture.source_url} uses wildcard slots, "
                "but the captured rules do not establish that every team is ranked together "
                "regardless of pool"
            )
        if len(ranks) != 2 or any(rank < 0 for rank in ranks):
            raise ValueError(
                f"Fixture {fixture.match_number or fixture.source_url} has an unsupported "
                f"wildcard qualification label '{fixture.bracket_label}'"
            )
        return {
            side: {
                "kind": "division_rank",
                "rank": rank,
                "evidence": "published_wildcard_slot_label",
            }
            for side, rank in zip(("home", "away"), ranks, strict=True)
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
        published_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if published_reference is not None:
            return published_reference
        registration_id = getattr(fixture, f"{side}_registration_id")
        label = str(getattr(fixture, f"{side}_label") or "")
        if fixture.kind == "bracket":
            label_reference = _MATCH_REFERENCE.search(label)
            if label_reference:
                published_number = label_reference.group(2)
                referenced_indices = match_number_indices.get(published_number, [])
                if len(referenced_indices) > 1:
                    raise ValueError(
                        f"Fixture {fixture.match_number or fixture.source_url} {side} side "
                        f"'{label}' references ambiguous published match number {published_number}"
                    )
                referenced = referenced_indices[0] if referenced_indices else None
                if referenced is not None and referenced < match_index:
                    if not _include_fixture_in_projection(ordered[referenced]):
                        raise ValueError(
                            f"Fixture {fixture.match_number or fixture.source_url} {side} side "
                            f"'{label}' references published match {published_number}, which was not played"
                        )
                    return {
                        "kind": "match_winner" if label_reference.group(1).casefold() == "winner" else "match_loser",
                        "match_index": referenced,
                        "evidence": "published_slot_label",
                    }
                raise ValueError(
                    f"Fixture {fixture.match_number or fixture.source_url} {side} side "
                    f"'{label}' references a missing or later published match"
                )
            registration = str(registration_id or "")
            if registration:
                for prior_index in range(match_index - 1, -1, -1):
                    prior = ordered[prior_index]
                    if prior.kind != "bracket" or not _include_fixture_in_projection(prior):
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
            if division_wide_qualification:
                raise ValueError(
                    f"Fixture {fixture.match_number or fixture.source_url} needs its published "
                    "wildcard slot labels before division-wide qualification can be replayed"
                )
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
        published_references = wildcard_references(fixture)
        home = side_reference(
            fixture,
            side="home",
            match_index=match_index,
            published_reference=published_references.get("home"),
        )
        away = side_reference(
            fixture,
            side="away",
            match_index=match_index,
            published_reference=published_references.get("away"),
        )
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
        include_in_projection = _include_fixture_in_projection(fixture)
        slot = {
            "match_number": str(fixture.match_number or ""),
            "stage": stage,
            "pool_name": pool_name,
            "counts_for_standings": (
                include_in_projection and fixture.kind in {"pool", "cross_pool"}
            ),
            "home": home,
            "away": away,
            "source_url": str(fixture.source_url or division.source_url or ""),
        }
        # Omit the true value so requests made from fully played captures remain
        # byte-compatible with runs created before this optional field existed.
        if not include_in_projection:
            slot["include_in_projection"] = False
        slots.append(slot)
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
