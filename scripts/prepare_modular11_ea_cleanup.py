#!/usr/bin/env python3
"""Prepare one age group's EA cleanup inputs for the merge and state skills. Read-only.

Run before matching an age, so the matcher sees one row per squad, each with a state. From the
age's ``teams.csv`` and live PitchRank teams it writes, in ``data/modular11_ea/<age>/cleanup/``:

- ``candidate_pool.csv``: every live team of the age whose club is an EA club or a branch of one.
- ``duplicate_pairs.json``: rows of one EA club and tier that look like copies of one squad, in
  the ``apply_vetted_team_merges.py`` shape, with both rows' age group, gender, state and club as
  read, plus an ``evidence`` object. Only proposals: the ``merging-duplicate-teams`` skill reviews
  them before anything merges.
- ``stateless.csv``: pool teams with no state, for the ``assigning-team-states`` skill.
- ``state_pool.json`` (with ``--state-snapshot``): that skill's dry-run snapshot cut down to the
  pool, in the snapshot's own shape.

A pair is proposed only between rows of the same EA club (not a branch) carrying the same tier
marker, when neither name has a squad word the other lacks and the two rows never played each
other or on the same day. The survivor follows the merge skill's order: name, then games, then
the last game played.

Usage:
    python scripts/prepare_modular11_ea_cleanup.py --age u17 [--state-snapshot run.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date
from functools import reduce
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.find_cross_provider_duplicates import (  # noqa: E402
    build_evidence,
    fetch_games,
    load_merge_map,
    merged_into,
    resolver,
)
from scripts.find_squad_key_duplicates import direction, evidence_refusal  # noqa: E402
from scripts.match_modular11_ea_teams import (  # noqa: E402
    EaTeam,
    _name_tokens,
    club_relation,
    fetch_db_teams,
    squad_words,
    tier_marker,
)
from scripts.scrape_modular11_ea import season_bounds  # noqa: E402
from scripts.team_cleanup.vetted import stamp  # noqa: E402
from supabase import create_client  # noqa: E402

POOL_COLUMNS = [
    "team_id_master",
    "team_name",
    "club_name",
    "state_code",
    "provider_code",
    "ea_club",
    "relation",
    "tier",
]


def build_pool(ea_rows: list[dict], teams: list[dict]) -> list[dict]:
    clubs = sorted({row["club_name"] for row in ea_rows})
    pool = []
    for team in sorted(teams, key=lambda t: t["team_id_master"]):
        relations = {club: club_relation(club, team.get("club_name"), team["team_name"]) for club in clubs}
        same = [club for club, relation in relations.items() if relation == "same"]
        branch = [club for club, relation in relations.items() if relation == "branch"]
        if not (same or branch):
            continue
        pool.append(
            {
                **team,
                "ea_club": "|".join(same or branch),
                "relation": "same" if same else "branch",
                "tier": tier_marker(team["team_name"]) or "",
            }
        )
    return pool


def _ea_team(ea_rows: list[dict], club: str, tier: str) -> EaTeam:
    rows = [r for r in ea_rows if r["club_name"] == club]
    row = next((r for r in rows if r["name_tier"] == tier), rows[0])
    return EaTeam(
        row["provider_team_id"], club, row["display_name"], row["age_group"], frozenset({tier}), "", int(row["season"])
    )


def _distinct_squads(ea: EaTeam, a: dict, b: dict) -> bool:
    """Either name carries a squad word the other name does not."""
    return any(
        set(squad_words(ea, one["team_name"])) - set(_name_tokens(other["team_name"]))
        for one, other in ((a, b), (b, a))
    )


def propose_pairs(pool: list[dict], ea_rows: list[dict], ev, season_start: str) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in pool:
        if row["relation"] == "same" and row["tier"] and "|" not in row["ea_club"]:
            groups[(row["ea_club"], row["tier"])].append(row)
    pairs = []
    for (club, tier), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        ea = _ea_team(ea_rows, club, tier)
        keep = reduce(lambda a, b: direction({"a": a, "b": b}, ev)[0], members)
        for merge in members:
            if merge is keep or evidence_refusal({"a": keep, "b": merge}, ev) or _distinct_squads(ea, keep, merge):
                continue
            k, m = keep["team_id_master"], merge["team_id_master"]
            pairs.append(
                {
                    "merge_id": m,
                    "keep_id": k,
                    "merge_name": merge["team_name"],
                    "keep_name": keep["team_name"],
                    **stamp(merge, keep),
                    "evidence": {
                        "ea_club": club,
                        "tier": tier,
                        "games_keep": ev.games[k],
                        "games_merge": ev.games[m],
                        "season_game_days_keep": sum(d >= season_start for d in ev.dates[k]),
                        "season_game_days_merge": sum(d >= season_start for d in ev.dates[m]),
                        "last_game_keep": max(ev.dates[k], default=None),
                        "last_game_merge": max(ev.dates[m], default=None),
                    },
                }
            )
    return pairs


def filter_snapshot(snapshot: dict, pool_ids: set[str]) -> dict:
    return {**snapshot, "decisions": [d for d in snapshot["decisions"] if d["team_id"] in pool_ids]}


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_pool_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POOL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(age: str, in_dir: Path, sb, snapshot_path: Path | None = None) -> dict[str, int]:
    age_dir = in_dir / age
    ea_rows = _read_csv(age_dir / "teams.csv")
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    teams = [t for t in fetch_db_teams(sb, age) if canonical(t["team_id_master"]) == t["team_id_master"]]
    pool = build_pool(ea_rows, teams)
    ids = [row["team_id_master"] for row in pool]
    games = fetch_games(sb, sorted(merged_into(ids, merge_map, canonical))) if ids else []
    ev = build_evidence(games, [], canonical, ids)
    season_start = season_bounds(date(int(ea_rows[0]["season"]), 8, 1))[0][:10]
    pairs = propose_pairs(pool, ea_rows, ev, season_start)
    stateless = [row for row in pool if not (row.get("state_code") or "").strip()]

    out = age_dir / "cleanup"
    out.mkdir(parents=True, exist_ok=True)
    _write_pool_csv(out / "candidate_pool.csv", pool)
    (out / "duplicate_pairs.json").write_text(json.dumps(pairs, indent=2) + "\n", encoding="utf-8")
    _write_pool_csv(out / "stateless.csv", stateless)
    if snapshot_path:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        kept = filter_snapshot(snapshot, set(ids))
        (out / "state_pool.json").write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    return {"pool": len(pool), "pairs": len(pairs), "stateless": len(stateless)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True)
    parser.add_argument("--in-dir", type=Path, default=Path("data/modular11_ea"))
    parser.add_argument("--state-snapshot", type=Path, help="assign_team_states.py --out file to cut down to the pool")
    args = parser.parse_args(argv)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1
    counts = run(args.age, args.in_dir, create_client(url, key), args.state_snapshot)
    print(" ".join(f"{name}={value}" for name, value in counts.items()))
    print(f"Wrote {args.in_dir / args.age / 'cleanup'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
