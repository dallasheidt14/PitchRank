"""Move named games from one team to another, one side per game, through the guarded RPCs.

Use it for games filed under a merged-away (deprecated) team id, which
scripts/reassign_games_between_teams.py refuses because it only accepts live teams, and for any
set of games chosen by provider id (see list_id_games.py).

    python .claude/skills/splitting-fused-provider-ids/scripts/move_game_sides.py \
        --from <old team uuid> --to <new team uuid> --games-file ids.txt [--provider-team-id <id>]
    python ... --resume data/exports/move_game_sides_<time>.json --execute
    python ... --revert data/exports/move_game_sides_<time>.json --execute

The side moved is whichever one currently holds --from. A move is a clear followed by a fill, so
a game can be left with an empty side if a run dies between the two. The log is written before the
first write and rewritten after every game, and --resume finishes any logged game by id.
Dry run unless --execute.

Skipped and reported: a game whose other side is already --to (it would play itself), a game with
no score (an unscored fixture; exclude it instead, as the merging-duplicate-teams skill's
"Splitting a fused row" says), and, with --provider-team-id, a game whose moved side carries a
different provider id.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from scripts.reassign_games_between_teams import move_side, read_side  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)


def plan_game(sb, gid, src, dst, provider_team_id):
    """The row for one game: its side and either 'planned' or the reason it is skipped."""
    row = {"game_id": gid, "side": None, "from": src, "to": dst, "result": "planned"}
    game = (
        sb.table("games").select("home_provider_id,away_provider_id,home_score,away_score")
        .eq("id", gid).execute().data
    )
    if not game:
        row["result"] = "skipped_no_such_game"
        return row
    game = game[0]
    held = [s for s in ("home", "away") if read_side(sb, gid, s) == src]
    if not held:
        row["result"] = "skipped_not_held_by_from"
        return row
    if len(held) == 2:  # the fused row is on both sides: the provider id picks the squad's side
        held = [s for s in held if provider_team_id and game[f"{s}_provider_id"] == provider_team_id]
        if len(held) != 1:
            row["result"] = "skipped_ambiguous_side"
            return row
    row["side"] = held[0]
    other = "away" if held[0] == "home" else "home"
    if read_side(sb, gid, other) == dst:
        row["result"] = "skipped_would_self_play"
    elif game["home_score"] is None or game["away_score"] is None:
        row["result"] = "skipped_unscored"
    elif provider_team_id and game[f"{held[0]}_provider_id"] != provider_team_id:
        row["result"] = "skipped_other_provider_id"
    return row


def run_rows(sb, rows, execute, path):
    """Write the log first, then move each planned row, rewriting the log after every game."""
    def save():
        if execute:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, indent=1))

    save()
    for r in rows:
        if r["result"] not in ("planned", "error"):
            print(r["game_id"], r["side"], r["result"])
            continue
        if not execute:
            print(r["game_id"], r["side"], "would_move")
            continue
        try:
            r["result"] = move_side(sb, r["game_id"], r["side"], r["from"], r["to"])
        except Exception as exc:  # the side may now be empty: stop, and let --resume find it by id
            r["result"] = "error"
            r["error"] = str(exc)
            save()
            sys.exit(f"stopped at {r['game_id']}: {exc}\nfinish with --resume {path} --execute")
        save()
        print(r["game_id"], r["side"], r["result"])
    if execute:
        print("log:", path, "(undo with --revert <log> --execute)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src")
    ap.add_argument("--to", dest="dst")
    ap.add_argument("--game", action="append", default=[])
    ap.add_argument("--games-file", help="text file with one game id per line")
    ap.add_argument("--provider-team-id", help="refuse a side whose provider id differs from this")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="wins over --execute")
    ap.add_argument("--resume", help="log of a stopped run: finish its planned and errored games")
    ap.add_argument("--revert", help="log to undo")
    args = ap.parse_args()
    execute = args.execute and not args.dry_run
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    if args.revert:
        for r in json.load(open(args.revert)):
            if r["result"] in ("moved", "already_moved"):
                result = move_side(sb, r["game_id"], r["side"], r["to"], r["from"]) if execute else "would_move_back"
                print(r["game_id"], r["side"], result)
        return

    if args.resume:
        path = Path(args.resume)
        run_rows(sb, json.load(open(path)), execute, path)
        return

    if args.games_file:
        args.game += [ln.strip() for ln in open(args.games_file) if ln.strip()]
    if not (args.src and args.dst and args.game):
        ap.error("--from, --to and at least one --game or --games-file are required")
    if args.src == args.dst:
        ap.error("--from and --to are the same team")
    dst = sb.table("teams").select("is_deprecated").eq("team_id_master", args.dst).execute().data
    if not dst or dst[0]["is_deprecated"]:
        ap.error(f"--to {args.dst} is not a live team")

    rows = [plan_game(sb, gid, args.src, args.dst, args.provider_team_id) for gid in args.game]
    path = ROOT / "data" / "exports" / f"move_game_sides_{datetime.now():%Y%m%d_%H%M%S}.json"
    run_rows(sb, rows, execute, path)


if __name__ == "__main__":
    main()
