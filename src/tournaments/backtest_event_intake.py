"""The Backtest tab's event intake: walk a played event, show what it really was.

``summarize_structure`` is the pure division summary. ``backtest_intake_ui``
renders the completed-event workflow and ``backtest_intake_state`` owns its
coherent, reloadable capture. The Seeding surface remains a separate workflow.

Reads the PitchRank database to match teams and writes nothing to it. That is a
requirement of this surface, not an accident of the current implementation.
``tests/unit/test_backtest_event_intake.py`` statically scans every
``src/tournaments`` module this file reaches (a hand list, kept honest by a
test that re-derives it) for a database-writing import or call, and fails if
one appears. It does not reach past ``tournament_intake.py``: this function
calls ``_render_seeding_event_scrape`` and friends from there, and that file
is a multi-feature hub with genuinely-writing code for tabs this one never
renders, so the scan cannot cross into it without flagging those too. That
leg is covered by the shared walk tests and Backtest Streamlit interaction tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.tournaments.gotsport_event_structure import (
    KIND_BRACKET,
    KIND_CROSS_POOL,
    KIND_POOL,
    KIND_UNKNOWN,
    ScrapedDivision,
)

__all__ = ["render_backtest_event_intake", "summarize_structure"]


def _cohort_label(division: ScrapedDivision) -> str:
    """Which board a division belongs to, or that the event did not say.

    A label like ``Gold`` names no age at all, so the walk resolves nothing for
    it. Printing that as a blank cell reads as a rendering fault; saying it
    plainly is the honest answer and tells the operator the event is the thing
    that is silent.
    """
    if not division.age_group and not division.gender:
        return "not stated"
    gender = {"Male": "Boys", "Female": "Girls"}.get(division.gender, division.gender)
    return " ".join(part for part in (gender, division.age_group.upper()) if part)


def summarize_structure(divisions: Sequence[ScrapedDivision]) -> list[dict[str, Any]]:
    """One display row per division. Never drops one, never invents one.

    A division whose pools could not be read says so. It is not omitted, and its
    pools are not reconstructed from its fixtures — a division exists whose two
    pools only ever played each other, so the fixture list is not evidence of
    who was grouped with whom.
    """
    rows: list[dict[str, Any]] = []
    for division in divisions:
        kinds = [fixture.kind for fixture in division.fixtures]
        labels = [fixture.bracket_label for fixture in division.fixtures if fixture.bracket_label]
        if division.pools_readable:
            pools = ", ".join(
                f"{pool.label or 'unnamed'} ({len(pool.members)})" for pool in division.pools
            ) or "none published yet"
        else:
            pools = "could not be read"
        readable = division.pools_readable and division.fixtures_readable
        note = "; ".join(division.warnings)
        if not readable and not note:
            # parse_division_structure always explains an unreadable division in
            # its own warnings, but a division built another way (a test fixture,
            # a future caller) might not — the note must still say something was
            # wrong rather than read as blank.
            label = division.division_label or f"group {division.group_id}"
            note = f"{label}: could not be read in full"
        rows.append(
            {
                "division": division.division_label or f"group {division.group_id}",
                "cohort": _cohort_label(division),
                "group_id": division.group_id,
                "pools": pools,
                "pool_games": kinds.count(KIND_POOL),
                "cross_pool_games": kinds.count(KIND_CROSS_POOL),
                "knockout_games": kinds.count(KIND_BRACKET),
                # classify_fixtures assigns this when either side of an unlabelled
                # game is missing from every pool's standings table — a division
                # can be fully readable and still have one of these, and a count
                # that only ever adds pool + cross_pool + knockout would under-
                # report how many games this division actually played without
                # ever saying so.
                "unclassified_games": kinds.count(KIND_UNKNOWN),
                "knockout": ", ".join(labels),
                "readable": readable,
                "note": note,
            }
        )
    return rows

def render_backtest_event_intake(supabase_client: Any) -> None:
    """Completed-event intake, independent from the upcoming-event Seeding UI."""
    from src.tournaments.backtest_intake_ui import render_intake

    render_intake(supabase_client)
