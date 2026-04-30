"""Identify the SincSports tournament-schedule teams with no alias-map entry.

Run after a tournament-schedule import that reports failed_games_count > 0.
Reads the most recent sincsports tournament JSONL, computes the unique
(team_id, team_name) pairs across both perspectives, and checks
team_alias_map for each. The records the importer dropped to failed_match
are typically the ones whose teams have no SincSports provider_team_id
entry yet.

This is a diagnostic, not a fix. It outputs a list the operator can either
seed manually into team_alias_map or accept as a known-limitation set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

env_local = Path(__file__).parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv(Path(__file__).parent.parent / ".env")

if not os.environ.get("SUPABASE_KEY") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

from supabase import create_client  # noqa: E402


def latest_tournament_jsonl() -> Path:
    raw = Path(__file__).parent.parent / "data" / "raw"
    files = sorted(raw.glob("sincsports_games_tournament_*.jsonl"))
    if not files:
        print("ERROR: no sincsports tournament JSONL in data/raw", file=sys.stderr)
        sys.exit(1)
    return files[-1]


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = latest_tournament_jsonl()

    print(f"Reading: {path}")

    teams: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        for tid_field, tname_field in (("team_id", "team_name"), ("opponent_id", "opponent_name")):
            tid = rec.get(tid_field) or ""
            tname = rec.get(tname_field) or ""
            if tid:
                teams.setdefault(tid, tname)
    print(f"Unique teams in JSONL: {len(teams)}")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    prov = sb.table("providers").select("id").eq("code", "sincsports").execute()
    sincsports_id = prov.data[0]["id"]

    chunk = 100
    tids = list(teams.keys())
    matched: set[str] = set()
    for i in range(0, len(tids), chunk):
        batch = tids[i : i + chunk]
        res = (
            sb.table("team_alias_map")
            .select("provider_team_id")
            .eq("provider_id", sincsports_id)
            .in_("provider_team_id", batch)
            .execute()
        )
        for row in res.data:
            matched.add(row["provider_team_id"])

    missing = [(tid, teams[tid]) for tid in tids if tid not in matched]

    print(f"\nIn alias_map: {len(matched)}")
    print(f"Missing from alias_map: {len(missing)}")
    print()
    for tid, tname in sorted(missing, key=lambda x: x[1]):
        print(f"  {tid:>10}  {tname}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
