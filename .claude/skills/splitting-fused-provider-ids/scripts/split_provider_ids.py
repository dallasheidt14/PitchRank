"""Give a squad its own team row and repoint its provider ids to it.

Dry run unless --execute. Logs the prior alias owners so --revert can restore them.

    python .claude/skills/splitting-fused-provider-ids/scripts/split_provider_ids.py \
        --name "Club ECNL G2011/12" --club "Club Name" --age-group u15 --gender Female --state-code CA \
        --league ECNL --alias tgs:25917:<current master uuid> --alias gotsport:451289:<current master uuid>

The first --alias also becomes the new row's own provider_team_id. Games are moved separately with
move_game_sides.py (or scripts/reassign_games_between_teams.py).
"""
import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

def parse_alias(text):
    code, pid, master = text.split(":")
    return code, pid, master


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name")
    ap.add_argument("--club")
    ap.add_argument("--age-group", help="stored form, e.g. u15")
    ap.add_argument("--gender", choices=["Male", "Female"])
    ap.add_argument("--state-code")
    ap.add_argument("--league")
    ap.add_argument("--alias", action="append", default=[], help="provider_code:provider_team_id:current_master_uuid")
    ap.add_argument("--to-existing", help="repoint the aliases to this live team instead of creating one")
    ap.add_argument("--own-provider-team-id", help="the new row's provider_team_id when the first alias id is already taken on teams (e.g. by a deprecated row)")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="wins over --execute")
    ap.add_argument("--log", help="where to write the log (default data/exports/split_provider_ids_<time>.json)")
    ap.add_argument("--revert", help="log to undo: aliases go back to their prior team")
    args = ap.parse_args()
    execute = args.execute and not args.dry_run

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    providers = {p["code"]: p["id"] for p in sb.table("providers").select("id,code").execute().data}

    if args.revert:
        log = json.load(open(args.revert))
        for a in log["aliases"]:
            print(f"alias {a['provider_team_id']}: {a['to']} -> {a['from']}")
            if execute:
                sb.table("team_alias_map").update({"team_id_master": a["from"], "match_method": a["prior_method"]}) \
                    .eq("provider_id", a["provider_id"]).eq("provider_team_id", a["provider_team_id"]) \
                    .eq("team_id_master", a["to"]).execute()
        print(f"New team {log['new_team']} stays, with no games once they are moved back." if execute else "dry run")
        return

    missing = [k for k in ("name", "club", "age_group", "gender", "state_code") if not getattr(args, k)]
    if args.to_existing:
        missing = []
    if missing or not args.alias:
        ap.error(f"required: {', '.join(missing)} and at least one --alias")
    if not args.to_existing:
        if not re.fullmatch(r"u[0-9]{1,2}", args.age_group):
            ap.error("--age-group must look like u15")
        if args.state_code not in STATE_CODE_TO_NAME:
            ap.error(f"--state-code {args.state_code!r} is not a known state code")
    aliases = [parse_alias(a) for a in args.alias]
    for code, _, _ in aliases:
        if code not in providers:
            ap.error(f"unknown provider code {code!r}; known: {sorted(providers)}")

    first_code, first_pid, _ = aliases[0]
    own_pid = args.own_provider_team_id or first_pid
    existing = (
        sb.table("teams").select("team_id_master,team_name,age_group,gender,is_deprecated")
        .eq("provider_id", providers[first_code]).eq("provider_team_id", own_pid).execute().data
    )
    if args.to_existing:
        live = sb.table("teams").select("team_id_master,is_deprecated").eq("team_id_master", args.to_existing).execute().data
        if not live or live[0]["is_deprecated"]:
            sys.exit(f"--to-existing {args.to_existing} is not a live team")
        new_id = args.to_existing
        print("repointing to existing team:", new_id)
    elif existing:
        row = existing[0]
        if (row["team_name"], row["age_group"], row["gender"]) != (args.name, args.age_group, args.gender):
            sys.exit(
                f"{first_code}:{own_pid} is already the provider_team_id of another team row: {row}. "
                "Pass --own-provider-team-id with a unique value, or, when it is the fused row's own id, "
                "repoint that row's provider_team_id to an id that stays and give the real id to the new row."
            )
        if row["is_deprecated"]:
            sys.exit(f"the existing row {row['team_id_master']} is deprecated")
        new_id = row["team_id_master"]
        print("team row already exists:", new_id)
    else:
        new_id = str(uuid.uuid4())
        row = {
            "team_id_master": new_id, "provider_id": providers[first_code], "provider_team_id": own_pid,
            "team_name": args.name, "team_name_original": args.name, "club_name": args.club,
            "state": STATE_CODE_TO_NAME[args.state_code], "state_code": args.state_code,
            "age_group": args.age_group, "gender": args.gender, "league": args.league, "is_deprecated": False,
        }
        print("would create team:" if not execute else "creating team:", json.dumps(row))
        if execute:
            sb.table("teams").insert(row).execute()

    log = {"at": datetime.now(timezone.utc).isoformat(), "new_team": new_id, "aliases": []}
    path = Path(args.log) if args.log else ROOT / "data" / "exports" / f"split_provider_ids_{datetime.now():%Y%m%d_%H%M%S}.json"

    def save():
        if execute:
            path.parent.mkdir(parents=True, exist_ok=True)
            json.dump(log, open(path, "w"), indent=2)

    for code, pid, old in aliases:
        cur = (
            sb.table("team_alias_map").select("team_id_master,match_method,review_status")
            .eq("provider_id", providers[code]).eq("provider_team_id", pid).execute().data
        )
        if not cur:
            print(f"alias {code}:{pid} has no alias row; skipping (create the alias by hand if it should exist)")
            continue
        owner = cur[0]["team_id_master"]
        print(f"alias {code}:{pid} currently -> {owner} (review_status {cur[0]['review_status']})")
        if owner == new_id:
            print("  already points at the new team")
            continue
        if owner != old:
            print(f"  skipped: expected {old}")
            continue
        log["aliases"].append({
            "provider_id": providers[code], "provider_team_id": pid, "from": old, "to": new_id,
            "prior_method": cur[0]["match_method"],
        })
    save()
    for a in log["aliases"] if execute else []:
        sb.table("team_alias_map").update({"team_id_master": new_id, "match_method": "direct_id"})             .eq("provider_id", a["provider_id"]).eq("provider_team_id", a["provider_team_id"])             .eq("team_id_master", a["from"]).execute()

    if execute:
        print("log:", path)
        print("NEW_TEAM_ID", new_id)
    else:
        print("dry run; re-run with --execute (the team id is chosen then)")


if __name__ == "__main__":
    main()
