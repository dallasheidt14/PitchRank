"""Resumable intake journal for event scrapers.

Shell 01 Step 4 primitive. Provides the ``raw_scrape.jsonl`` newline-first
append-only journal plus byte-accurate tail recovery, Windows-safe
end-of-scrape compaction, skip-set computation for resume, and the
``removed_teams.json`` diff artifact.

This module contains no provider-specific logic — it's a pure storage layer
consumed by ``GotsportScraper.fetch_teams_by_cohort`` (Shell 01 Step 6
integration) and any future ``ProviderScraper`` implementation.

Path convention mirrors ``src.scrapers.provider._intake_path``:
``reports/<event_key>/intake/raw_scrape.jsonl``.

The JSONL record schema is the caller's concern — this module round-trips
dicts and indexes by ``provider_team_id`` and ``run_id``. Expected fields
(per the plan) include ``run_id``, ``provider_team_id``, ``alias_writer_action``,
``canonical.scraper_state``, and ``scrape_ts``; anything else the caller
attaches is preserved verbatim.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


__all__ = [
    "DURABLE_ACTIONS",
    "IntakeJournal",
    "JournalCorruptionError",
    "RemovedTeamsDiff",
    "compute_skip_set",
]


# ``alias_writer`` actions that represent terminal state — the team was either
# durably written, durably rejected, or is durably awaiting human review. The
# scraper SHOULD write a JSONL record for these and skip them on the next run
# (unless --force-teams or --revalidate says otherwise).
#
# ``db_error`` is deliberately NOT durable — a transient DB failure leaves the
# team in an ambiguous state and we want to retry it on the next run.
DURABLE_ACTIONS = frozenset(
    {
        "created",
        "updated",
        "conflict",
        "conflict_skipped_rejected",
        "conflict_loop_detected",
        "skipped_weaker_metadata",
        "skipped_rejected",
        "skipped_already_approved",
        "deduped_pending",
        "queued",
        "none",
    }
)


class JournalCorruptionError(RuntimeError):
    """Raised when the JSONL journal has corruption that can't be safely repaired.

    Tail-line corruption is recoverable via truncation; mid-file corruption
    is not, because truncating would lose durably-recorded state. Callers
    should surface this to the operator (not auto-recover).
    """


@dataclass(frozen=True)
class RemovedTeamsDiff:
    """Output of ``IntakeJournal.compute_removed_teams``."""

    run_id: str
    removed_provider_team_ids: list[str]


class IntakeJournal:
    """Stateful append-only JSONL journal for one event scrape.

    Usage::

        j = IntakeJournal(event_key="gotsport__45224__unknown")
        j.startup_cleanup()                       # delete stale .tmp if any
        store = j.read()                          # resume: {pid: record}
        skip = compute_skip_set(store, force_teams=False)
        j.open_for_append()
        try:
            for team in scraped:
                if team.provider_team_id in skip:
                    continue
                record = build_record(team)       # caller-provided
                if record["alias_writer_action"] in DURABLE_ACTIONS:
                    j.append(record)
        finally:
            j.close()
        kept, dropped = j.compact()               # latest-run_id-wins

    The handle stays open across the full scrape so flush+fsync per append
    gives a durable per-team write point. Compaction MUST close the handle
    before ``os.replace`` on Windows — the class does this automatically.
    """

    def __init__(self, event_key: str, base_dir: Path | str = "reports"):
        self.event_key = event_key
        self._base_dir = Path(base_dir)
        self.path = self._base_dir / event_key / "intake" / "raw_scrape.jsonl"
        self.tmp_path = self.path.with_name(self.path.name + ".tmp")
        self.removed_teams_path = self.path.with_name("removed_teams.json")
        self._handle: Any = None  # io.BufferedWriter once open
        self.last_good_offset: int = 0

    # ----- lifecycle ---------------------------------------------------------

    def startup_cleanup(self) -> bool:
        """Delete a leftover ``.tmp`` from a crashed compaction.

        The canonical ``raw_scrape.jsonl`` is authoritative; a surviving
        ``.tmp`` is from a compaction that crashed between write and
        ``os.replace`` and has no value.
        """
        if self.tmp_path.exists():
            self.tmp_path.unlink()
            logger.info("[startup_cleanup] deleted stale %s", self.tmp_path.name)
            return True
        return False

    def open_for_append(self) -> None:
        """Open the canonical journal for binary-append writes.

        Uses binary mode so newline translation on Windows doesn't silently
        break the byte-accurate offset tracking. Creates parent directories
        on first run.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "ab")  # noqa: SIM115 — closed in .close()
        self.last_good_offset = self._handle.tell()

    def close(self) -> None:
        """Close the append handle if it's open. Idempotent."""
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None

    def __enter__(self) -> "IntakeJournal":
        self.open_for_append()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ----- writes ------------------------------------------------------------

    def append(self, record: dict[str, Any]) -> int:
        """Append one record using the newline-first protocol.

        ``"\\n" + json.dumps(record)`` ensures a partially-written tail line
        can be detected by the tail-recovery logic (the last record always
        ends the file with a valid JSON object on its own line; a truncated
        tail-line is followed by no more bytes).

        Returns the new ``last_good_offset`` so callers that want to record
        their own durable cursor can.
        """
        if self._handle is None:
            raise RuntimeError("IntakeJournal.append called before open_for_append")
        payload = ("\n" + json.dumps(record, ensure_ascii=False)).encode("utf-8")
        self._handle.write(payload)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.last_good_offset = self._handle.tell()
        return self.last_good_offset

    # ----- reads + recovery --------------------------------------------------

    def read(self) -> dict[str, dict[str, Any]]:
        """Resume read with byte-accurate tail-corruption recovery.

        Returns ``{provider_team_id: record}`` with latest-``run_id``-wins
        semantics. Silently truncates a partial tail line (the scraper
        crashed mid-append); raises ``JournalCorruptionError`` on a parse
        failure mid-file (unrecoverable — truncating would lose durable
        state).

        If the file doesn't exist, returns an empty dict.
        """
        if not self.path.exists():
            self.last_good_offset = 0
            return {}

        raw = self.path.read_bytes()
        if not raw:
            self.last_good_offset = 0
            return {}

        # Lines are "\n"-prefixed under the newline-first protocol, so
        # splitlines() correctly yields one entry per record (the leading
        # empty string from the first "\n" is filtered).
        store: dict[str, dict[str, Any]] = {}
        offset = 0
        byte_cursor = 0
        lines = raw.split(b"\n")
        last_idx = len(lines) - 1

        for i, line in enumerate(lines):
            line_len_with_sep = len(line) + (0 if i == last_idx else 1)
            if not line.strip():
                byte_cursor += line_len_with_sep
                offset = byte_cursor
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                is_last = i == last_idx
                if is_last:
                    # Partial tail line — scraper crashed mid-append. Truncate
                    # back to the last fully-written record and carry on.
                    with open(self.path, "r+b") as f:
                        f.seek(offset)
                        f.truncate()
                    logger.info(
                        "[journal_recovery] truncated partial tail line at offset=%d",
                        offset,
                    )
                    break
                raise JournalCorruptionError(
                    f"Mid-file JSON decode error in {self.path} at line {i + 1}: {e}. "
                    f"Manual inspection required — truncating would drop durable state."
                ) from e
            byte_cursor += line_len_with_sep
            offset = byte_cursor
            pid = record.get("provider_team_id")
            if pid is None:
                continue
            prior = store.get(pid)
            if prior is None or _run_id_newer(record.get("run_id"), prior.get("run_id")):
                store[pid] = record

        self.last_good_offset = offset
        return store

    # ----- compaction --------------------------------------------------------

    def compact(self) -> tuple[int, int]:
        """Windows-safe end-of-scrape compaction.

        1. Close the append handle (Windows ``os.replace`` fails if the
           destination has open handles).
        2. Read the full file, collecting latest-``run_id``-wins per
           ``provider_team_id``.
        3. Write the compacted records to ``<name>.tmp``, flush, fsync, close.
        4. ``os.replace`` atomically swaps tmp into place.

        Returns ``(kept, dropped)``. Terminal operation — after compact,
        the append handle is not reopened here (callers that still want to
        write would re-``open_for_append``, though in practice compaction is
        the last thing a scrape does).
        """
        self.close()
        if not self.path.exists():
            logger.info("[compaction] no journal to compact at %s", self.path)
            return (0, 0)

        # Count the total records in the pre-compaction file for accurate
        # ``dropped`` accounting — ``read()`` already deduplicates latest-wins.
        total_records = self._count_records()
        store = self.read()
        kept = len(store)
        dropped = total_records - kept

        with open(self.tmp_path, "wb") as tmp:
            for record in store.values():
                tmp.write(("\n" + json.dumps(record, ensure_ascii=False)).encode("utf-8"))
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(self.tmp_path, self.path)
        logger.info(
            "[compaction] kept %d records, dropped %d stale entries (%s)",
            kept, dropped, self.path,
        )
        return (kept, dropped)

    def _count_records(self) -> int:
        """Count parseable non-empty records in the journal (pre-compaction)."""
        if not self.path.exists():
            return 0
        raw = self.path.read_bytes()
        if not raw:
            return 0
        count = 0
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                # Partial tail line — doesn't count.
                continue
            count += 1
        return count

    # ----- removed-teams diff ------------------------------------------------

    def compute_removed_teams(
        self, live_provider_team_ids: set[str], run_id: str
    ) -> RemovedTeamsDiff:
        """Diff the just-compacted store against the live scraped set.

        Any ``provider_team_id`` in the journal (post-compaction) but NOT in
        the current scrape's live set is considered "removed" — the team was
        present on a prior run and has since disappeared from the event. We
        do NOT auto-delete; the diff is surfaced for human review.
        """
        journal_store = self.read()
        removed = sorted(set(journal_store.keys()) - live_provider_team_ids)
        return RemovedTeamsDiff(run_id=run_id, removed_provider_team_ids=removed)

    def write_removed_teams_artifact(self, diff: RemovedTeamsDiff) -> Path:
        """Persist ``removed_teams.json`` next to the journal."""
        payload = {
            "run_id": diff.run_id,
            "removed_provider_team_ids": diff.removed_provider_team_ids,
        }
        self.removed_teams_path.parent.mkdir(parents=True, exist_ok=True)
        self.removed_teams_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        logger.info(
            "[removed_teams] %d ids -> %s",
            len(diff.removed_provider_team_ids),
            self.removed_teams_path,
        )
        return self.removed_teams_path


# ---------------------------------------------------------------------------
# Pure functions — no I/O. Callers compose these with DB lookups for the
# ``--revalidate`` case (which requires checking the live alias row's
# ``review_status`` / ``match_method``).
# ---------------------------------------------------------------------------


def compute_skip_set(
    store: dict[str, dict[str, Any]],
    *,
    force_teams: bool = False,
) -> set[str]:
    """Return the set of ``provider_team_id`` values to skip on this run.

    Default behavior: skip every team whose last-recorded
    ``alias_writer_action`` is a durable terminal state. A ``db_error``
    record is NOT durable — the team will be retried.

    ``force_teams=True`` (from ``--force-teams``) clears the skip set
    entirely — every team is re-processed regardless of prior state.

    ``--revalidate`` is NOT handled here because it requires a DB lookup
    on each alias row's ``review_status`` and ``match_method``. Callers
    that need it should:

    1. Call ``compute_skip_set`` with ``force_teams=False`` to get the
       default skip set.
    2. For each ``provider_team_id`` in the skip set, query
       ``team_alias_map`` and drop the pid from the skip set if
       ``review_status != 'approved'`` OR ``match_method`` is not in
       the curated-method allowlist (``'direct_id'``, ``'manual'``,
       ``'manual_review'``, ``'manual_queue'``, ``'import'``).
    3. Use the reduced skip set for the scrape.
    """
    if force_teams:
        return set()
    return {
        pid
        for pid, record in store.items()
        if record.get("alias_writer_action") in DURABLE_ACTIONS
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_id_newer(incoming: str | None, existing: str | None) -> bool:
    """Compare two run_id strings; ISO-8601 UTC sorts lexically."""
    if incoming is None:
        return False
    if existing is None:
        return True
    return incoming > existing
