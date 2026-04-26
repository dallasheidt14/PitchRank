"""Raw-scrape JSONL access — re-exports the Shell 01 IntakeJournal primitives.

The storage layer doesn't reinvent the JSONL machinery; it re-exports
``IntakeJournal`` and friends from ``src.scrapers.intake_journal`` so
callers that work in scenario-relative terms have a single import surface.

The convenience helper ``load_raw_scrape`` returns the latest-run-wins
record list for an event_key — handy for Streamlit triage UIs that don't
need the full ``IntakeJournal`` lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.scrapers.intake_journal import (
    DURABLE_ACTIONS,
    IntakeJournal,
    JournalCorruptionError,
    RemovedTeamsDiff,
    compute_skip_set,
)

__all__ = [
    "DURABLE_ACTIONS",
    "IntakeJournal",
    "JournalCorruptionError",
    "RemovedTeamsDiff",
    "compute_skip_set",
    "load_raw_scrape",
]


def load_raw_scrape(event_key: str, *, base_dir: Path | str = "reports") -> list[dict[str, Any]]:
    """Return the latest-run-wins records from ``intake/raw_scrape.jsonl``.

    Returns an empty list when the journal does not exist. The IntakeJournal
    class still owns the read mechanics — this helper just unwraps the dict
    into list form for read-only consumers.
    """
    journal = IntakeJournal(event_key=event_key, base_dir=base_dir)
    if not journal.path.exists():
        return []
    store = journal.read()
    return list(store.values())
