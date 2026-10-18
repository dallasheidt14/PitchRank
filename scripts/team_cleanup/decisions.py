"""The owner's standing decisions on team-cleanup proposals, in the shape scans and writers share."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

DECISIONS_TABLE = "team_cleanup_decisions"
CHANGES_TABLE = "team_cleanup_changes"
CARDS_TABLE = "team_cleanup_cards"
CARD_COLS = "card_id,page_run,lane,decision,note,decided_at,created_at"
MERGES = "merges"
KEEP_SEPARATE = "keep_separate"
KEEP_SEPARATE_COLS = "id,team_id_master,other_team_id,decided_at,superseded_at"
# A single-team proposal's decisions, as a page saves them and the table records them.
APPLY, DONT_APPLY, UNSURE = "apply", "dont_apply", "unsure"
TEAM_DECISIONS = (APPLY, DONT_APPLY, UNSURE)
DONT_APPLY_COLS = "id,team_id_master,field,proposed_value,decided_at,superseded_at"

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


def team_subject(team_id: str, field: str) -> str:
    return f"{team_id}|{field}"


def resolve_execute(execute_flag: bool, dry_run_flag: bool) -> bool:
    """Fail safe: asking for both means the caller wants the preview."""
    return execute_flag and not dry_run_flag


def new_page_run() -> str:
    """A review page build's id: its UTC build time, which page_built_at reads back, and a random
    suffix, since two builds can share a second."""
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


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


def card_rows(run_id: str, stage: str, page_run: str, built_at: str, lanes: dict[str, list[dict]]) -> list[dict]:
    """Each card of a page build as team_cleanup_cards holds it, the automatic lane's decided Apply at the
    build. ``lanes`` maps a lane to its cards."""
    return [
        {
            "card_id": c["id"],
            "run_id": run_id,
            "stage": stage,
            "lane": lane,
            "page_run": page_run,
            "position": c["n"],
            "card": c,
            "decision": APPLY if lane == "auto" else None,
            "decided_at": built_at if lane == "auto" else None,
        }
        for lane, cards in lanes.items()
        for c in cards
    ]


def team_decision_row(stage: str, card: dict) -> dict:
    """A single-team card's decision, from its decisions.json row."""
    return {
        "stage": stage,
        "subject_key": team_subject(card["team_id_master"], card["field"]),
        "team_id_master": card["team_id_master"],
        "field": card["field"],
        "proposed_value": card["new_value"],
        "decision": card["decision"],
        "note": card["note"],
        "decided_at": card["decided_at"],
        "source": card["source"],
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
