"""List the games one provider team id holds on one team, within a date window.

    python .claude/skills/splitting-fused-provider-ids/scripts/list_id_games.py \
        --team <team uuid> --provider tgs --provider-team-id 64010 --before 2026-08-01 --out ids.txt

Prints one line per game (date, score, opponent) and writes the game ids to --out, ready for
move_game_sides.py --games-file. Read-only.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", required=True)
    ap.add_argument("--provider", required=True, help="provider code the games were imported under")
    ap.add_argument("--provider-team-id", required=True)
    ap.add_argument("--since")
    ap.add_argument("--before")
    ap.add_argument("--out")
    args = ap.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    found = sb.table("providers").select("id").eq("code", args.provider).execute().data
    if not found:
        sys.exit(f"unknown provider code {args.provider!r}")
    prov = found[0]["id"]

    ids = []
    for side, other, pid_col in (("home", "away", "home_provider_id"), ("away", "home", "away_provider_id")):
        q = (
            sb.table("games")
            .select(f"id,game_date,home_score,away_score,is_excluded,event_name,competition,{other}_team_master_id")
            .eq(f"{side}_team_master_id", args.team).eq(pid_col, args.provider_team_id).eq("provider_id", prov)
        )
        if args.since:
            q = q.gte("game_date", args.since)
        if args.before:
            q = q.lt("game_date", args.before)
        games, offset = [], 0
        while True:
            page = q.order("id").range(offset, offset + 999).execute().data
            games += page
            if len(page) < 1000:
                break
            offset += 1000
        for g in games:
            opp = sb.table("teams").select("team_name").eq("team_id_master", g[f"{other}_team_master_id"]).execute().data
            ids.append((g["game_date"], g["id"]))
            label = g["event_name"] or g["competition"] or ""
            print(g["game_date"], g["id"], f"{g['home_score']}-{g['away_score']}", "excluded" if g["is_excluded"] else "",
                  "|", opp[0]["team_name"] if opp else "?", "|", label)
    print(f"{len(ids)} games")
    if args.out:
        Path(args.out).write_text("\n".join(i for _, i in sorted(ids)) + "\n")


if __name__ == "__main__":
    main()
