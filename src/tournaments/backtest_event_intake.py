"""The Backtest tab's event intake: walk a played event, show what it really was.

Kept out of ``tournament_intake.py`` so the app file does not grow another few
hundred lines, following ``division_render`` and ``reports.ui``. Everything that
decides what the operator sees is pure and lives in ``summarize_structure``; the
render function only draws it.

Reads the PitchRank database to match teams and writes nothing to it. That is a
requirement of this surface, not an accident of the current implementation —
``tests/unit/test_backtest_event_intake.py`` fails if a write appears.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.tournaments.gotsport_event_structure import (
    KIND_BRACKET,
    KIND_CROSS_POOL,
    KIND_POOL,
    ScrapedDivision,
)

__all__ = ["render_backtest_event_intake", "summarize_structure"]


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
                "group_id": division.group_id,
                "pools": pools,
                "pool_games": kinds.count(KIND_POOL),
                "cross_pool_games": kinds.count(KIND_CROSS_POOL),
                "knockout_games": kinds.count(KIND_BRACKET),
                "knockout": ", ".join(labels),
                "readable": readable,
                "note": note,
            }
        )
    return rows


def render_backtest_event_intake(supabase_client: Any) -> None:
    """Walk a played event and show the structure it was actually run under.

    Imports from ``tournament_intake`` inside the function: the app module
    imports this one, so a module-scope import would be circular.

    ``divisions`` (this event's structure) and ``parsed``/``resolved`` (its
    teams) both come off the same walk but are unrelated collections here — a
    division whose team table went unrecognised contributes a structure row
    with no corresponding team rows, so neither block below assumes the two
    line up index-for-index.
    """
    import pandas as pd
    import streamlit as st

    from src.tournaments.storage._io import utc_now_iso
    from src.tournaments.storage.event_key import event_key
    from src.tournaments.storage.event_structure import EventStructure, write_event_structure
    from tournament_intake import (
        _BACKTEST_KEYS,
        _SEEDING_NEEDS_DECISION,
        _as_plain_text,
        _render_seeding_event_scrape,
        _render_seeding_override,
    )

    st.markdown("### Scrape a played event")
    st.caption(
        "Reads every division's pools and games, including the semis, final and "
        "consolation games, exactly as the event published them. Every page is paid "
        "for, so check a couple of divisions first."
    )
    _render_seeding_event_scrape(supabase_client, keys=_BACKTEST_KEYS)

    result = st.session_state.get(_BACKTEST_KEYS.result)
    if not result:
        return
    parsed, resolved = result

    divisions = st.session_state.get(_BACKTEST_KEYS.structure) or ()
    if divisions:
        rows = summarize_structure(divisions)
        st.markdown("#### Structure this event was run under")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        unreadable = [row for row in rows if not row["readable"]]
        if unreadable:
            st.warning(
                f"{len(unreadable)} division(s) could not be read in full. They are listed "
                "above rather than dropped, and their pools are not guessed from the games."
            )
            for row in unreadable:
                st.caption(_as_plain_text(f"{row['division']}: {row['note']}"))

    overrides = st.session_state[_BACKTEST_KEYS.overrides]
    by_index = {item.source_index: item for item in resolved}
    outstanding = [
        row
        for row in parsed.rows
        if by_index[row.source_index].status in _SEEDING_NEEDS_DECISION
        and row.source_index not in overrides
    ]

    st.markdown("#### Teams matched to your database")
    columns = st.columns(4)
    columns[0].metric("Teams", len(parsed.rows))
    columns[1].metric("Matched", len(parsed.rows) - len(outstanding))
    columns[2].metric("You fixed", len(overrides))
    columns[3].metric("Still open", len(outstanding))

    for row in outstanding:
        _render_seeding_override(row, by_index[row.source_index], supabase_client, keys=_BACKTEST_KEYS)

    event_id = st.session_state.get(_BACKTEST_KEYS.result_event_id)
    probe = st.session_state.get(_BACKTEST_KEYS.probe) or {}
    if not event_id or not divisions:
        return
    if st.button("Save this event's structure", key="_backtest_save_structure"):
        write_event_structure(
            event_key("gotsport", event_id, None),
            EventStructure(
                event_id=event_id,
                walked_at=utc_now_iso(),
                is_complete=bool(probe.get("complete")),
                divisions=tuple(divisions),
            ),
        )
        st.success("Saved.")
