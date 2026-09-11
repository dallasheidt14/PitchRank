"""The Backtest tab's event intake: walk a played event, show what it really was.

Kept out of ``tournament_intake.py`` so the app file does not grow another few
hundred lines, following ``division_render`` and ``reports.ui``. Everything that
decides what the operator sees is pure and lives in ``summarize_structure``; the
render function only draws it.

Reads the PitchRank database to match teams and writes nothing to it. That is a
requirement of this surface, not an accident of the current implementation.
``tests/unit/test_backtest_event_intake.py`` statically scans every
``src/tournaments`` module this file reaches (a hand list, kept honest by a
test that re-derives it) for a database-writing import or call, and fails if
one appears. It does not reach past ``tournament_intake.py``: this function
calls ``_render_seeding_event_scrape`` and friends from there, and that file
is a multi-feature hub with genuinely-writing code for tabs this one never
renders, so the scan cannot cross into it without flagging those too. That
leg is instead verified by hand (Task 9 report, 2026-09-10) by tracing every
function the Backtest render path actually calls.
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
    from src.tournaments.storage.event_structure import (
        EventStructure,
        StructureOverwriteRefused,
        write_event_structure,
    )
    from tournament_intake import (
        _BACKTEST_KEYS,
        _as_plain_text,
        _render_seeding_event_scrape,
        _render_seeding_override,
        _render_seeding_progress_metrics,
        _render_seeding_warnings,
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
    # The only signal that credentials or the merge map failed inside
    # resolve_master_ids, plus the age/gender-missing counts — without this an
    # operator whose merge resolver is broken sees every team "Still open" with
    # no explanation why.
    _render_seeding_warnings(parsed)

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
    st.markdown("#### Teams matched to your database")
    by_index, outstanding = _render_seeding_progress_metrics(parsed, resolved, overrides)

    for row in outstanding:
        _render_seeding_override(row, by_index[row.source_index], supabase_client, keys=_BACKTEST_KEYS)

    event_id = st.session_state.get(_BACKTEST_KEYS.result_event_id)
    probe = st.session_state.get(_BACKTEST_KEYS.probe) or {}
    if not event_id or not divisions:
        return
    if st.button("Save this event's structure", key="_backtest_save_structure"):
        structure_key = event_key("gotsport", event_id, None)
        try:
            write_event_structure(
                structure_key,
                EventStructure(
                    event_id=event_id,
                    walked_at=utc_now_iso(),
                    is_complete=bool(probe.get("complete")),
                    divisions=tuple(divisions),
                ),
            )
        except StructureOverwriteRefused:
            # write_event_structure itself refuses this — the guard is a
            # property of the writer, not of this one caller's good manners.
            # This is the friendly path: a plain message instead of a
            # traceback, and the complete structure on disk is left alone.
            st.error(
                "A complete walk of this event is already saved. This walk is only "
                "partial and would replace it with less — scrape the whole event "
                "before saving, or the complete structure already on disk is lost."
            )
        else:
            st.success("Saved.")
