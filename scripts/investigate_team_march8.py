#!/usr/bin/env python3
"""
Investigation script: Trace March 8, 2026 game imports for team 9da0e6d9-4e0e-40fc-9a86-11adf89eb690

Run this locally where you have database/Supabase access:
    python scripts/investigate_team_march8.py
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path('.env.local'), override=True)
load_dotenv()

from supabase import create_client

TEAM_ID = "9da0e6d9-4e0e-40fc-9a86-11adf89eb690"
GAME_DATE = "2026-03-08"

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)


def investigate():
    print("=" * 80)
    print(f"INVESTIGATION: Team {TEAM_ID}")
    print(f"Looking for games on {GAME_DATE}")
    print("=" * 80)

    # 1. Get team info
    print("\n--- TEAM INFO ---")
    team = supabase.table("teams").select(
        "team_id_master, team_name, club_name, age_group, gender, state_code, "
        "provider_team_id, provider_id, created_at, updated_at, last_scraped_at, is_deprecated"
    ).eq("team_id_master", TEAM_ID).execute()

    if team.data:
        for t in team.data:
            for k, v in t.items():
                print(f"  {k}: {v}")
            provider_id = t.get("provider_id")
    else:
        print("  TEAM NOT FOUND!")
        return

    # 1b. Get provider name
    if provider_id:
        prov = supabase.table("providers").select("provider_name, code").eq("id", provider_id).execute()
        if prov.data:
            print(f"  provider_name: {prov.data[0].get('provider_name')}")
            print(f"  provider_code: {prov.data[0].get('code')}")

    # 2. Get all aliases for this team
    print("\n--- TEAM ALIASES ---")
    aliases = supabase.table("team_alias_map").select(
        "provider_team_id, provider_id, match_method, match_confidence, review_status, created_at"
    ).eq("team_id_master", TEAM_ID).execute()

    if aliases.data:
        for a in aliases.data:
            # Look up provider name
            if a.get("provider_id"):
                p = supabase.table("providers").select("code").eq("id", a["provider_id"]).execute()
                pcode = p.data[0]["code"] if p.data else "unknown"
            else:
                pcode = "unknown"
            print(f"  [{pcode}] provider_team_id={a['provider_team_id']}  "
                  f"method={a['match_method']}  confidence={a['match_confidence']}  "
                  f"status={a['review_status']}  created={a['created_at']}")
    else:
        print("  No aliases found")

    # 3. Get March 8 games (home)
    print(f"\n--- GAMES ON {GAME_DATE} (as home team) ---")
    home_games = supabase.table("games").select(
        "id, game_date, home_team_master_id, away_team_master_id, "
        "home_provider_id, away_provider_id, home_score, away_score, "
        "competition, event_name, division_name, venue, source_url, "
        "provider_id, created_at, scraped_at"
    ).eq("home_team_master_id", TEAM_ID).eq("game_date", GAME_DATE).execute()

    # 3b. Get March 8 games (away)
    away_games = supabase.table("games").select(
        "id, game_date, home_team_master_id, away_team_master_id, "
        "home_provider_id, away_provider_id, home_score, away_score, "
        "competition, event_name, division_name, venue, source_url, "
        "provider_id, created_at, scraped_at"
    ).eq("away_team_master_id", TEAM_ID).eq("game_date", GAME_DATE).execute()

    all_games = (home_games.data or []) + (away_games.data or [])
    print(f"  Found {len(all_games)} games on {GAME_DATE}")

    provider_ids_seen = set()
    for g in all_games:
        print(f"\n  Game ID: {g['id']}")
        print(f"    date: {g['game_date']}")
        print(f"    home_master_id: {g['home_team_master_id']}")
        print(f"    away_master_id: {g['away_team_master_id']}")
        print(f"    home_provider_id: {g['home_provider_id']}")
        print(f"    away_provider_id: {g['away_provider_id']}")
        print(f"    score: {g['home_score']}-{g['away_score']}")
        print(f"    competition: {g['competition']}")
        print(f"    event_name: {g['event_name']}")
        print(f"    division: {g['division_name']}")
        print(f"    venue: {g['venue']}")
        print(f"    source_url: {g['source_url']}")
        print(f"    provider_id: {g['provider_id']}")
        print(f"    created_at: {g['created_at']}")
        print(f"    scraped_at: {g['scraped_at']}")

        if g.get("provider_id"):
            provider_ids_seen.add(g["provider_id"])

        # Look up opponent team name
        opp_id = g["away_team_master_id"] if g["home_team_master_id"] == TEAM_ID else g["home_team_master_id"]
        if opp_id:
            opp = supabase.table("teams").select("team_name, club_name").eq("team_id_master", opp_id).execute()
            if opp.data:
                print(f"    opponent: {opp.data[0].get('team_name')} ({opp.data[0].get('club_name')})")

    # 4. Resolve provider names for games
    if provider_ids_seen:
        print("\n--- PROVIDERS FOR MARCH 8 GAMES ---")
        for pid in provider_ids_seen:
            p = supabase.table("providers").select("provider_name, code").eq("id", pid).execute()
            if p.data:
                print(f"  {pid} = {p.data[0].get('provider_name')} ({p.data[0].get('code')})")

    # 5. Check build_logs around March 8
    print("\n--- BUILD LOGS AROUND MARCH 8 ---")
    # Look for imports that happened on March 8-9
    logs = supabase.table("build_logs").select(
        "build_id, stage, provider_id, started_at, completed_at, "
        "records_processed, records_succeeded, records_failed, parameters"
    ).gte("started_at", "2026-03-08T00:00:00").lte("started_at", "2026-03-09T23:59:59").order(
        "started_at"
    ).execute()

    if logs.data:
        for log in logs.data:
            prov_name = "unknown"
            if log.get("provider_id"):
                p = supabase.table("providers").select("code").eq("id", log["provider_id"]).execute()
                if p.data:
                    prov_name = p.data[0]["code"]
            print(f"\n  build_id: {log['build_id']}")
            print(f"    stage: {log['stage']}")
            print(f"    provider: {prov_name}")
            print(f"    started_at: {log['started_at']}")
            print(f"    completed_at: {log['completed_at']}")
            print(f"    processed: {log['records_processed']}")
            print(f"    succeeded: {log['records_succeeded']}")
            print(f"    failed: {log['records_failed']}")
            params = log.get("parameters")
            if params:
                print(f"    parameters: {json.dumps(params, indent=6)}")
    else:
        print("  No build logs found for March 8-9")

    # 6. Check ALL games for this team to see patterns
    print("\n--- ALL GAMES FOR THIS TEAM (last 10 by created_at) ---")
    recent_home = supabase.table("games").select(
        "game_date, competition, event_name, provider_id, created_at, scraped_at, source_url"
    ).eq("home_team_master_id", TEAM_ID).order("created_at", desc=True).limit(5).execute()

    recent_away = supabase.table("games").select(
        "game_date, competition, event_name, provider_id, created_at, scraped_at, source_url"
    ).eq("away_team_master_id", TEAM_ID).order("created_at", desc=True).limit(5).execute()

    all_recent = sorted(
        (recent_home.data or []) + (recent_away.data or []),
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )[:10]

    for g in all_recent:
        prov_name = "unknown"
        if g.get("provider_id"):
            p = supabase.table("providers").select("code").eq("id", g["provider_id"]).execute()
            if p.data:
                prov_name = p.data[0]["code"]
        print(f"  game_date={g['game_date']}  provider={prov_name}  "
              f"competition={g.get('competition')}  event={g.get('event_name')}  "
              f"created={g['created_at']}  scraped={g.get('scraped_at')}")

    print("\n" + "=" * 80)
    print("INVESTIGATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    investigate()
