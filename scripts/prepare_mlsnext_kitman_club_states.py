#!/usr/bin/env python3
"""Fill config/mlsnext_kitman_club_states.json for every Kitman club that can be settled, and list the rest.

Kitman gives no state, so a team created from a squad takes its club's state from that table. A
club is settled when those of its existing MLS NEXT teams with a state agree on one, or when the
Elite Academy table already names it. Everything else goes to ``club_states_todo.csv`` for the owner, with the
states other providers' teams of the same club hold shown as a hint only: a hint can be a state
the club's teams travelled to, which is why it is never written into the table.

The owner's picks come back through ``--answers`` (the todo sheet with ``your_state`` filled in) and
are written with the settled clubs. An entry already in the table is never changed. Dry run unless
--write.

Usage:
    python scripts/prepare_mlsnext_kitman_club_states.py
    python scripts/prepare_mlsnext_kitman_club_states.py --write
    python scripts/prepare_mlsnext_kitman_club_states.py --answers club_states_todo.csv --write
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.find_cross_provider_duplicates import normalize  # noqa: E402
from scripts.fix_band_cohorts import csv_safe, csv_unsafe  # noqa: E402
from scripts.match_mlsnext_kitman_teams import _provider_ids, fetch_bridge, fetch_other_provider_teams  # noqa: E402
from src.models.mlsnext_kitman_keys import CLUB_STATES  # noqa: E402
from src.models.modular11_ea_keys import CLUB_STATES as EA_CLUB_STATES  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

TABLE_PATH = Path(__file__).resolve().parent.parent / "config" / "mlsnext_kitman_club_states.json"
STATE_RE = re.compile(r"[A-Z]{2}")
TODO_COLUMNS = ["club_name", "squads", "ages", "hint_states", "existing_mls_next_states", "your_state"]


def _unanimous(states: list[str]) -> str:
    distinct = {s for s in states if s}
    return next(iter(distinct)) if len(distinct) == 1 else ""


def settle(clubs: dict[str, int], bridge: list[dict], ea_table: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    by_club: dict[str, list[str]] = defaultdict(list)
    for team in bridge:
        by_club[normalize(team["club_name"])].append((team.get("state_code") or "").strip())
    ea_by_norm = {normalize(club): state for club, state in ea_table.items()}
    settled, unsettled = {}, []
    for club in sorted(clubs):
        if is_placeholder_club(club) or club in CLUB_STATES:
            continue
        state = _unanimous(by_club.get(normalize(club), [])) or ea_by_norm.get(normalize(club), "")
        if state in STATE_CODE_TO_NAME:
            settled[club] = state
        else:
            unsettled.append(club)
    return settled, unsettled


def read_answers(path: Path, clubs: set[str]) -> dict[str, str]:
    """The owner's ``your_state`` picks from a returned todo sheet, for the clubs the squads name.

    A pick is a two-letter code. The sheet's formula escape is undone before a club name is matched.
    """
    answers = {}
    for row in _read_csv(path):
        club = csv_unsafe(row["club_name"])
        state = row["your_state"].strip().upper()
        if club in clubs and STATE_RE.fullmatch(state):
            answers[club] = state
    return answers


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", type=Path, default=Path("data/mlsnext_kitman"))
    parser.add_argument("--write", action="store_true", help="add the settled clubs to the table")
    parser.add_argument("--answers", type=Path, help="a returned club_states_todo.csv with your_state filled in")
    args = parser.parse_args(argv)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sb = create_client(url, key)
    squads = _read_csv(args.in_dir / "squads.csv")
    clubs = Counter(s["club_name"] for s in squads)
    ages = defaultdict(set)
    for s in squads:
        ages[s["club_name"]].add(s["age_group"])
    provider_ids = _provider_ids(sb)
    bridge = fetch_bridge(sb, provider_ids)
    settled, unsettled = settle(clubs, bridge, EA_CLUB_STATES)
    answers = read_answers(args.answers, set(clubs)) if args.answers else {}
    unsettled = [club for club in unsettled if club not in answers]
    others = fetch_other_provider_teams(
        sb, provider_ids, {s["age_group"] for s in squads}, {normalize(c) for c in unsettled}
    )
    hints: dict[str, Counter] = defaultdict(Counter)
    for team in others:
        if team.get("state_code"):
            hints[normalize(team["club_name"])][team["state_code"]] += 1
    existing: dict[str, Counter] = defaultdict(Counter)
    for team in bridge:
        if team.get("state_code"):
            existing[normalize(team["club_name"])][team["state_code"]] += 1
    todo = [
        {
            "club_name": csv_safe(club),
            "squads": clubs[club],
            "ages": ",".join(sorted(ages[club])),
            "hint_states": " ".join(f"{s}:{n}" for s, n in hints[normalize(club)].most_common()),
            "existing_mls_next_states": " ".join(f"{s}:{n}" for s, n in existing[normalize(club)].most_common()),
            "your_state": "",
        }
        for club in unsettled
    ]
    with (args.in_dir / "club_states_todo.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TODO_COLUMNS)
        writer.writeheader()
        writer.writerows(todo)
    already = sum(c in CLUB_STATES for c in clubs)
    print(
        f"clubs={len(clubs)} already_in_table={already} settled_now={len(settled)} "
        f"answered={len(answers)} todo={len(unsettled)}"
    )
    if args.write:
        table = {**settled, **answers, **CLUB_STATES}
        TABLE_PATH.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(settled) + len(answers)} clubs to {TABLE_PATH.name}")
    else:
        print("DRY RUN — table not changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
