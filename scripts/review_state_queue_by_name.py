#!/usr/bin/env python3
"""Settle pending state reviews that the team's own name already answers.

Usage (credentials come from ``.env.local`` if present, else the root ``.env``, loaded by
the tool this imports):

    python scripts/review_state_queue_by_name.py            # dry run: counts and a sample
    python scripts/review_state_queue_by_name.py --execute  # approve, reject and set

The sweep never corrects a state from a name alone, so rows like "Colorado Elevation FC" stored as UT
reach a person. This reads the place a pending row's team names and acts only where that
reading is unambiguous:

- the name agrees with the stored state: reject the row, so the sweep stops raising it
  (a row proposing no move included);
- the team or club name spells out the proposed state: write it and mark the row approved;
- the team name spells out a third state: write it and reject the row.

Every write carries Tier C's stamp; none is recorded as a person's approval.

A learned town word may keep a team where it is but never moves one on its own -- "Diego Maradona" is
not San Diego. The team's own words outrank its club name, because a club's branches are
separate clubs: "ALBION SC San Diego" under "Albion SC Colorado" is a California team.

A row is left for a person when its team moved since it was queued, when the name points two
ways, names a state it cannot place, or names none, when the state word is really a place
("Washington Co", "Delaware Knights" in Delaware, Ohio), when an affiliate marker names
another state, when a mapped GotSport answer names a different state, or when a move would
overturn the provider's record, an operator's answer, an approval or a revert.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AbstractSet, Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402

from scripts.assign_team_states import (  # noqa: E402
    MAPPED_OUTCOME,
    PAGE_SIZE,
    REPROBE_AFTER_DAYS,
    SUPABASE_KEY,
    SUPABASE_URL,
    TIER_CONFIDENCE,
    UNSET_DEFAULT_ASSOCIATION,
    affiliate_contradicts,
    apply_decision,
    build_locality_index,
    fetch_approved_states,
    fetch_live_teams,
    fetch_recent_probes,
    fetch_revert_blocks,
    mirror_rankings,
    name_tokens,
    outranked,
    state_from_name,
    stored_state,
)
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

console = Console()

REVIEWER = "review_state_queue_by_name"
# A state spelled out in a team's name is Tier C's evidence, so a write from it carries
# Tier C's stamp and stays correctable by the provider's record.
NAME_TIER = "C"

# Words that make the state word before them a county, a town or a region.
PLACE_SUFFIXES = ("county", "co", "city", "valley", "township", "twp", "heights")

# Towns named after a state, keyed by the state word and the state the town is in. A team
# stored in that state and named for the word is most likely from the town.
STATE_NAMED_TOWNS = {
    ("delaware", "OH"),
    ("oregon", "WI"),
    ("washington", "IL"),
    ("indiana", "PA"),
}


def _words(text: Optional[str]) -> str:
    """Lowercase letters separated by single spaces, the way ``state_from_name`` reads a name:
    "Washington-County" must meet the place check in the form the state reader saw it."""
    return " " + " ".join(re.split(r"[^a-z]+", (text or "").lower())).strip() + " "


def queued_state(row: Dict) -> Optional[str]:
    """The state the team held when its row was queued, blank normalised to None."""
    return (row.get("current_state_code") or "").strip() or None


def names_a_place(team: Dict, state: str) -> bool:
    """Whether the word ``state`` was read from is really a county, a town or a region here."""
    text = _words(f"{team.get('team_name') or ''} {team.get('club_name') or ''}")
    word = STATE_CODE_TO_NAME[state].lower()
    if any(f" {word} {suffix} " in text for suffix in PLACE_SUFFIXES):
        return True
    return (word, stored_state(team)) in STATE_NAMED_TOWNS and f" {word} " in text


def name_reading(team: Dict, locality_index: Dict[str, str]) -> Tuple[Optional[str], str]:
    """``(state, how)``: the one state the team's name points at, and whether the team name
    spells it out (``team``), the club name does (``club``), or only a learned town word does
    (``town``). ``how`` is ``conflict`` when the team's own words point two ways,
    ``unplaced`` when the team name holds a state name ``state_from_name`` declines to read
    (two states, an affiliate marker, "Kansas City"), and ``none`` when nothing names a state.

    Neither reader's None may be taken as silence, because each also returns None for a
    two-way split: town words are read here rather than through ``locality_state``, and a
    declined team name leaves the row rather than letting the club name answer.
    """
    spelled = state_from_name(team.get("team_name"))
    if spelled is None and any(f" {n.lower()} " in _words(team.get("team_name")) for n in STATE_CODE_TO_NAME.values()):
        return None, "unplaced"
    club_spelled = state_from_name(team.get("club_name"))
    # Town words from the team name only: pooled with the club's, a branch's own town and
    # its parent club's cancel out.
    towns = {locality_index[t] for t in name_tokens({**team, "club_name": None}) if t in locality_index}
    readings = towns | ({spelled} if spelled else set())
    if len(readings) > 1:
        return None, "conflict"
    if readings:
        state = readings.pop()
        if state == spelled:
            return state, "team"
        if state == club_spelled:
            return state, "club"
        return state, "town"
    return (club_spelled, "club") if club_spelled else (None, "none")


def classify(
    row: Dict,
    team: Optional[Dict],
    locality_index: Dict[str, str],
    provider_state: Optional[str],
    approved_states: AbstractSet[Tuple[str, str]] = frozenset(),
    revert_blocks: AbstractSet[Tuple[str, str]] = frozenset(),
) -> Tuple[str, Optional[str]]:
    """``(action, state)``: ``approve``, ``reject`` or ``set``, else ``left: <why>``.

    ``approved_states`` and ``revert_blocks`` come from the sweep's ledger readers
    (``fetch_approved_states``, ``fetch_revert_blocks``): a person's
    approval is stamped with the proposing tier, never ``operator``, so the provenance
    column alone cannot show it.
    """
    if team is None:
        return "left: team deprecated", None
    team_id, current = team["team_id_master"], stored_state(team)
    proposed = (row.get("proposed_state_code") or "").strip()
    if current != queued_state(row):
        return "left: team moved since queued", None
    state, how = name_reading(team, locality_index)
    if how == "conflict":
        return "left: name points two ways", None
    if how == "unplaced":
        return "left: team name names a state it cannot place", None
    if not state or state not in STATE_CODE_TO_NAME:
        return "left: name gives no state", None
    if names_a_place(team, state):
        return "left: state word names a place", None
    if affiliate_contradicts(team.get("team_name"), state) or affiliate_contradicts(team.get("club_name"), state):
        return "left: an affiliate marker names another state", None
    if provider_state and provider_state != state:
        return "left: GotSport disagrees with the name", None
    if state == current:
        return "reject", state
    # A town word only ever keeps a team where it is. The sweep's own Tier E proposes from
    # the same learned words, so reading one back is not a second opinion: "santa" carried
    # Pumas Santa Fe FC, from New Mexico, to a California proposal and would approve it.
    if how == "town":
        return "left: only a town word supports a move", None
    if outranked(team.get("state_source"), NAME_TIER):
        return "left: stored state outranks a name", None
    if (team_id, current) in approved_states:
        return "left: an operator approved the stored state", None
    if (team_id, state) in revert_blocks:
        return "left: an operator reverted this state", None
    if state == proposed:
        return "approve", state
    if how == "team":
        return "set", state
    return "left: the club name alone cannot override", None


def fetch_pending_reviews(sb) -> List[Dict]:
    rows: List[Dict] = []
    offset = 0
    while True:
        page = (
            sb.table("team_state_review_queue")
            .select("id,team_id_master,current_state_code,proposed_state_code")
            .eq("status", "pending")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = page.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def provider_states(sb) -> Dict[str, str]:
    """``team_id_master`` -> the state a recent GotSport answer named, the unset default
    excepted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPROBE_AFTER_DAYS)
    return {
        team_id: state
        for team_id, (outcome, state) in fetch_recent_probes(sb, cutoff).items()
        if outcome == MAPPED_OUTCOME and state and state != UNSET_DEFAULT_ASSOCIATION
    }


def settle(sb, row: Dict, action: str, state: str) -> str:
    """Write one decision and return what happened.

    An approval is written here rather than through ``approve_team_state``: that RPC ledgers
    an ``approve`` row, which the sweep reads back as a person's ratification and ranks
    above the provider's record. A write whose team moved since the row was queued lands
    nothing and leaves the row pending, so no proposal is suppressed for a change that never
    happened.
    """
    if action != "reject":
        decision = {
            "team_id": row["team_id_master"],
            "pre_image": queued_state(row),
            "proposed": state,
            "tier": NAME_TIER,
            "confidence": TIER_CONFIDENCE[NAME_TIER],
        }
        if not apply_decision(sb, decision, f"team name says {state}; review {row['id']}", actor=REVIEWER):
            return f"{action} skipped: team moved"
        mirror_rankings(sb, [decision])
    if action == "approve":
        sb.table("team_state_review_queue").update(
            {"status": "approved", "reviewed_by": REVIEWER, "reviewed_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", row["id"]).eq("status", "pending").execute()
    else:
        sb.rpc("reject_team_state", {"p_review_id": row["id"], "p_reviewer": REVIEWER}).execute()
    return action


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle pending state reviews the team's name answers")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default. Report and sample; write nothing")
    mode.add_argument("--execute", action="store_true", help="Approve, reject and set")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    teams = fetch_live_teams(sb)
    locality_index = build_locality_index(teams)
    by_id = {t["team_id_master"]: t for t in teams}
    answers = provider_states(sb)
    approved_states = fetch_approved_states(sb)
    revert_blocks = fetch_revert_blocks(sb)
    rows = fetch_pending_reviews(sb)

    plan = []
    counts: Counter = Counter()
    for row in rows:
        team = by_id.get(row["team_id_master"])
        action, state = classify(
            row, team, locality_index, answers.get(row["team_id_master"]), approved_states, revert_blocks
        )
        counts[action] += 1
        if state:
            plan.append((row, team, action, state))

    console.print(f"{len(rows):,} pending reviews")
    for action, count in counts.most_common():
        console.print(f"  {count:>6,}  {action}")

    if not args.execute:
        for action in ("approve", "reject", "set"):
            sample = [p for p in plan if p[2] == action][:10]
            if sample:
                console.print(f"[bold]{action}[/bold]")
            for row, team, _, state in sample:
                # Provider-written names reach Rich here, and Rich reads square brackets as markup.
                name = escape((team.get("team_name") or "")[:45])
                club = escape(team.get("club_name") or "")
                console.print(f"  {stored_state(team)} -> {state}  {name} | {club}")
        console.print("[yellow]Dry run. Re-run with --execute to write.[/yellow]")
        return

    # One team can hold several pending rows; the first approve or set moves it, so the write
    # for the next is refused as stale. That refusal is the intended outcome.
    done: Counter = Counter()
    for row, _team, action, state in plan:
        try:
            done[settle(sb, row, action, state)] += 1
        except Exception as exc:  # noqa: BLE001 -- one refused row must not stop the rest
            done[f"{action} refused"] += 1
            console.print(f"[dim]  review {row['id']}: {escape(str(exc)[:100])}[/dim]")
    for action, count in done.most_common():
        console.print(f"[green]✓[/green] {count:,} {action}")


if __name__ == "__main__":
    main()
