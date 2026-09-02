#!/usr/bin/env python3
"""Put back the states GotSport's unset-default association overwrote.

``AL`` is the state Tier A proposes when a team's GotSport association really is Alabama
*and* when it was never set at all; the payload cannot tell the two apart. R8b in
``assign_team_states.decide`` stops it happening again. This undoes what it already did.

**It does not undo every AL write.** Of the 86 live teams the sweep had written to AL by
2026-09-02, 65 belong to clubs whose own teams are in Alabama and are correct. This
restores only the ones whose club says otherwise -- the four Cold Spring Harbor Huntington
(LIJSL) teams in New York, and the rest across IN, PA, MI, MO, IL, OK, GA, UT, WI and CO.
A team whose club offers no evidence either way is left alone: nothing here knows better
than the value it already has, and a wrong restore is as bad as the wrong write.

The selection deliberately mirrors R8b's own test -- "does another reading dispute AL" --
so a team this script restores is a team the rule would now queue rather than apply.

This is not ``revert_team_states``: that scopes by actor and time window, and these writes
are interleaved with several days of correct ones, so a window revert would undo far more.

Writes are stamped ``operator`` rather than ``assign_team_states``, because undoing a
specific fault is a person's decision and must stay separable from the sweep's own work --
including from a later revert of it.

    python scripts/revert_al_association_writes.py            # dry run, writes nothing
    python scripts/revert_al_association_writes.py --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.assign_team_states import (  # noqa: E402
    IN_BATCH,
    PAGE_SIZE,
    UNSET_DEFAULT_ASSOCIATION,
    club_key,
    fetch_live_teams,
    stored_state,
)
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402

console = Console()

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

SWEEP_ACTOR = "assign_team_states"
OPERATOR_ACTOR = "operator"


def fetch_default_writes(sb) -> Dict[str, Optional[str]]:
    """``team_id_master`` → the state it held before the sweep wrote the default.

    The newest such write per team, so a team written, moved away and written again goes
    back to what it held before the last one rather than the first.
    """
    newest: Dict[str, Dict] = {}
    offset = 0
    while True:
        page = (
            sb.table("team_state_audit")
            .select("id,team_id_master,old_state_code")
            .eq("new_state_code", UNSET_DEFAULT_ASSOCIATION)
            .eq("applied_by", SWEEP_ACTOR)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        rows = page.data or []
        for row in rows:
            newest[row["team_id_master"]] = row
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return {tid: (r.get("old_state_code") or "").strip() or None for tid, r in newest.items()}


def club_states(teams: List[Dict]) -> Dict[str, Counter]:
    """Per club, how many of its teams sit in each state, ignoring the tool's own writes.

    ``state_source`` is skipped for the same reason Tier B's anchor index skips it: a
    club whose teams this run is auditing must not vouch for itself.
    """
    index: Dict[str, Counter] = defaultdict(Counter)
    for team in teams:
        # ``club_key`` blanks a placeholder already; saying so here too is what keeps the
        # rule visible at the point the decision is made. "No Club Selection" is 1,596
        # teams across 23 states -- the largest club_name in the database and not a club.
        if is_placeholder_club(team.get("club_name")):
            continue
        key = club_key(team.get("club_name"))
        state = stored_state(team)
        if key and state and not (team.get("state_source") or "").startswith("tier_"):
            index[key][state] += 1
    return index


def disputed_by_club(teams: List[Dict], written: Dict[str, Optional[str]]) -> List[Tuple[Dict, str]]:
    """The teams still holding the default whose own club says something else."""
    index = club_states(teams)
    out: List[Tuple[Dict, str]] = []
    for team in teams:
        tid = team["team_id_master"]
        if tid not in written or stored_state(team) != UNSET_DEFAULT_ASSOCIATION:
            continue
        counts = index.get(club_key(team.get("club_name")))
        if not counts:
            continue
        majority, _ = counts.most_common(1)[0]
        if majority != UNSET_DEFAULT_ASSOCIATION:
            out.append((team, majority))
    return out


def restore(sb, team_id: str, previous: Optional[str], reason: str) -> bool:
    """Put one team back. False means it moved between the read and the write."""
    result = sb.rpc(
        "apply_team_state",
        {
            "p_team_id": team_id,
            "p_expected_state_code": UNSET_DEFAULT_ASSOCIATION,
            "p_state_code": previous,
            # No source and no confidence. The restored value is whatever the team held
            # before the sweep touched it, and nothing here vouches for where that came
            # from; claiming provenance would tell the next sweep this was settled and
            # stop it correcting a value nobody has actually checked.
            "p_source": None,
            "p_confidence": None,
            "p_actor": OPERATOR_ACTOR,
            "p_action": "correct",
            "p_reason": reason,
        },
    ).execute()
    return bool(result.data)


def mirror_rankings(sb, restored: Dict[str, Optional[str]]) -> int:
    """Carry the restored states into ``rankings_full`` so the boards agree today."""
    by_state: Dict[Optional[str], List[str]] = defaultdict(list)
    for team_id, previous in restored.items():
        by_state[previous].append(team_id)

    mirrored = 0
    for state, team_ids in by_state.items():
        for start in range(0, len(team_ids), IN_BATCH):
            batch = team_ids[start : start + IN_BATCH]
            result = (
                sb.table("rankings_full").update({"state_code": state}).in_("team_id", batch).execute()
            )
            mirrored += len(result.data or [])
    return mirrored


def main() -> None:
    parser = argparse.ArgumentParser(description="Undo the unset-default association writes")
    parser.add_argument("--execute", action="store_true", help="Write. Without it, nothing changes")
    parser.add_argument("--limit", type=int, help="Restore at most this many")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    written = fetch_default_writes(sb)
    console.print(f"[bold]{len(written):,}[/bold] teams were written to {UNSET_DEFAULT_ASSOCIATION} by {SWEEP_ACTOR}")
    if not written:
        return

    teams = fetch_live_teams(sb)
    targets = disputed_by_club(teams, written)
    still_holding = sum(
        1
        for t in teams
        if t["team_id_master"] in written and stored_state(t) == UNSET_DEFAULT_ASSOCIATION
    )
    console.print(
        f"  {still_holding:,} still hold it; {len(targets):,} have a club that disputes it, "
        f"{still_holding - len(targets):,} do not and are left alone"
    )

    table = Table(title=f"Restoring from {UNSET_DEFAULT_ASSOCIATION}")
    for column in ("Team", "Club", "Club says", "Back to"):
        table.add_column(column)
    for team, majority in sorted(targets, key=lambda pair: pair[0].get("team_name") or ""):
        table.add_row(
            escape((team.get("team_name") or "")[:40]),
            escape((team.get("club_name") or "-")[:28]),
            majority,
            written[team["team_id_master"]] or "(blank)",
        )
    console.print(table)

    if args.limit:
        targets = targets[: args.limit]

    if not args.execute:
        console.print(f"[yellow]Dry run: would restore {len(targets):,}. Re-run with --execute.[/yellow]")
        return

    restored: Dict[str, Optional[str]] = {}
    skipped = 0
    for team, _ in targets:
        team_id = team["team_id_master"]
        previous = written[team_id]
        if restore(sb, team_id, previous, "AL is also GotSport's unset default; restoring pre-write state"):
            restored[team_id] = previous
        else:
            skipped += 1

    console.print(f"[green]✓[/green] Restored {len(restored):,}, skipped {skipped:,} that moved")
    console.print(f"[green]✓[/green] Mirrored {mirror_rankings(sb, restored):,} ranking rows")
    console.print(
        "[yellow]The restored value is what the team held before, not a verdict that it is "
        "right -- several of these were wrong before the sweep touched them. Provenance is "
        "cleared, so run the sweep next and let Tier B settle them on the club.[/yellow]"
    )


if __name__ == "__main__":
    main()
