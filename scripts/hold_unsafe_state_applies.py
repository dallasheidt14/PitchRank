#!/usr/bin/env python3
"""Split a state snapshot into the applies that are safe to replay and the ones to hold.

Usage (credentials come from ``.env.local`` if present, else the root ``.env``, loaded by
the tool this imports):

    python scripts/hold_unsafe_state_applies.py in.json safe.json held.json

Two shapes are held:

- an apply that the stored value's provenance outranks -- a club count over a provider
  record or an operator's own answer, or the record over an operator's answer -- the
  rewrite loop where a fill shifts the club counts and the next sweep undoes the last;
- a Tier B correction on a club the same snapshot sends to two different states -- the
  two-and-two swap (IMP-161), where RSL-AZ Yuma is told CA->TX and TX->CA in one run.

Everything else, including every queue decision and every confirm, passes through
unchanged so ``--execute --snapshot safe.json`` replays it exactly as the dry run decided.
The held file is a bare list for reading, not a snapshot for applying. The replay re-reads
provenance beside every write as well; this split is what lets an operator read the held
rows before anything is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402

from scripts.assign_team_states import (  # noqa: E402
    SUPABASE_KEY,
    SUPABASE_URL,
    club_key,
    fetch_state_sources,
    outranked,
)
from supabase import create_client  # noqa: E402

console = Console()


def split(
    decisions: List[Dict], provenance: Dict[str, Optional[str]]
) -> Tuple[List[Dict], List[Dict]]:
    """``(kept, held)``: every decision passes through except an apply in one of the two
    shapes, which is held with a ``held_because`` naming the shape.

    ``provenance`` is ``team_id`` -> the ``state_source`` the team carries right now.
    """
    applies = [d for d in decisions if d["action"] == "apply"]
    targets: Dict[str, set] = defaultdict(set)
    for d in applies:
        if d["tier"] == "B" and d["pre_image"] is not None:
            targets[club_key(d.get("club_name"))].add(d["proposed"])

    held, kept = [], []
    for d in decisions:
        if d["action"] != "apply":
            kept.append(d)
            continue
        why = None
        source = provenance.get(d["team_id"])
        if outranked(source, d["tier"]):
            why = f"{d['tier']} would overwrite a {source} value"
        elif d["tier"] == "B" and d["pre_image"] is not None:
            club = club_key(d.get("club_name"))
            if len(targets[club]) > 1:
                why = f"club is sent to {sorted(targets[club])} in the same run (IMP-161)"
        if why:
            held.append({**d, "held_because": why})
        else:
            kept.append(d)
    return kept, held


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a state snapshot into safe and held applies")
    parser.add_argument("snapshot", type=Path, help="The dry run's --out file")
    parser.add_argument("safe", type=Path, help="Where to write the snapshot to replay")
    parser.add_argument("held", type=Path, help="Where to write the held applies, for reading")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    snap = json.loads(args.snapshot.read_text(encoding="utf-8"))

    provenance = fetch_state_sources(
        sb, [d["team_id"] for d in snap["decisions"] if d["action"] == "apply"]
    )
    kept, held = split(snap["decisions"], provenance)
    args.safe.write_text(json.dumps({**snap, "decisions": kept}, indent=1), encoding="utf-8")
    args.held.write_text(json.dumps(held, indent=1), encoding="utf-8")
    by_action = {a: sum(1 for d in kept if d["action"] == a) for a in ("apply", "queue", "confirm")}
    console.print(
        f"kept {by_action['apply']:,} applies, {by_action['queue']:,} queue rows and "
        f"{by_action['confirm']:,} confirms -> {args.safe}"
    )
    console.print(f"held {len(held):,} applies -> {args.held}")
    for d in held:
        # Provider-written names reach Rich here, and Rich reads square brackets as markup.
        name = escape((d.get("team_name") or "")[:45])
        club = escape(d.get("club_name") or "")
        console.print(f"  {d['pre_image']} -> {d['proposed']}  {name} | {club} | {d['held_because']}")


if __name__ == "__main__":
    main()
