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
from pathlib import Path
from typing import Any

from src.tournaments.gotsport_event_structure import (
    KIND_BRACKET,
    KIND_CROSS_POOL,
    KIND_POOL,
    KIND_UNKNOWN,
    ScrapedDivision,
)
from src.tournaments.storage._io import read_json

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


def _would_replace_a_complete_structure(path: Path, *, is_complete: bool) -> bool:
    """Would saving here throw away an already-complete walk for a partial one?

    Mirrors ``tournament_intake._recovery_holds_a_complete_walk``, the guard the
    sibling recovery-file writer applies to the same paid artifact: a probe
    costing pennies must never silently replace a full walk that cost dollars.
    A save that is itself complete is never refused — a complete walk may
    always replace whatever came before it, partial or complete. Only a
    partial save landing on a structure already recorded complete loses.

    Read as raw JSON rather than through ``read_event_structure`` so a schema
    mismatch cannot itself raise here — an unreadable or missing file holds
    nothing to protect, same as the sibling guard treats it.
    """
    if is_complete:
        return False
    try:
        existing = read_json(path)
    except (OSError, ValueError):
        return False
    return isinstance(existing, dict) and existing.get("is_complete") is True


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
        event_structure_path,
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
        is_complete = bool(probe.get("complete"))
        structure_key = event_key("gotsport", event_id, None)
        if _would_replace_a_complete_structure(event_structure_path(structure_key), is_complete=is_complete):
            st.error(
                "A complete walk of this event is already saved. This walk is only "
                "partial and would replace it with less — scrape the whole event "
                "before saving, or the complete structure already on disk is lost."
            )
        else:
            write_event_structure(
                structure_key,
                EventStructure(
                    event_id=event_id,
                    walked_at=utc_now_iso(),
                    is_complete=is_complete,
                    divisions=tuple(divisions),
                ),
            )
            st.success("Saved.")
