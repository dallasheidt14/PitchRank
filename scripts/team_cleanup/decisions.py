"""The owner's standing decisions on team-cleanup proposals, in the shape scans and writers share."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

DECISIONS_TABLE = "team_cleanup_decisions"
MERGES = "merges"
KEEP_SEPARATE = "keep_separate"
KEEP_SEPARATE_COLS = "id,team_id_master,other_team_id,decided_at,superseded_at"

# PostgREST's answer when the table is not in its schema cache, i.e. the migration is not applied.
TABLE_MISSING = "PGRST205"

SCANS_WAIT_FOR_DECISIONS = (
    "Duplicate scans stay off until the owner's Keep-separate decisions can be read, "
    "so no pair the owner kept apart is proposed again."
)
MERGES_WAIT_FOR_DECISIONS = (
    "Merges wait until the owner's Keep-separate decisions can be read, "
    "so no pair the owner kept apart is merged."
)

_RUN = re.compile(r"^(?:decisions-)?(\d{8}T\d{6}Z)-")


class DecisionsUnavailable(RuntimeError):
    """The owner's decisions could not be read, so a scan must not proceed as if there were none."""

    @property
    def table_missing(self) -> bool:
        return getattr(self.__cause__, "code", None) == TABLE_MISSING


@dataclass(frozen=True)
class KeepSeparate:
    team_id: str
    other_team_id: str
    decided_at: str


def pair_subject(team_id: str, other_team_id: str) -> str:
    return "|".join(sorted((team_id, other_team_id)))


def resolve_execute(execute_flag: bool, dry_run_flag: bool) -> bool:
    """Fail safe: asking for both means the caller wants the preview."""
    return execute_flag and not dry_run_flag


def page_built_at(manifest: dict) -> str:
    """A review page's build time, read from its run id, in UTC."""
    stamp = manifest.get("run") or manifest.get("collection")
    match = _RUN.match(stamp or "")
    if not match:
        raise ValueError(f"the manifest carries no build time (run or collection {stamp!r})")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


def keep_separate_row(merge_id: str, keep_id: str, note: str, decided_at: str, source: str) -> dict:
    return {
        "stage": MERGES,
        "subject_key": pair_subject(merge_id, keep_id),
        "team_id_master": merge_id,
        "other_team_id": keep_id,
        "decision": KEEP_SEPARATE,
        "note": note or None,
        "decided_at": decided_at,
        "source": source,
    }


def active_keep_separate(rows) -> list[KeepSeparate]:
    return [
        KeepSeparate(r["team_id_master"], r["other_team_id"], r["decided_at"])
        for r in rows
        if r["superseded_at"] is None
    ]


def keep_separate_index(decisions, canonical) -> dict[frozenset, KeepSeparate]:
    """Each decision keyed by the pair of rows its two teams resolve to now.

    A decision names the rows the owner saw, and either may have been merged since; the row it
    went into carries the same squad, so the decision still holds there. A pair that now
    resolves to one row was merged regardless, and holds nothing until that merge is undone.
    """
    index = {}
    for decision in decisions:
        pair = frozenset((canonical(decision.team_id), canonical(decision.other_team_id)))
        if len(pair) == 2:
            index[pair] = decision
    return index


def kept_apart_reason(index, canonical, team_id: str, other_team_id: str) -> str | None:
    decision = index.get(frozenset((canonical(team_id), canonical(other_team_id))))
    return f"the owner chose Keep separate on {decision.decided_at[:10]}" if decision else None
