#!/usr/bin/env python3
"""
Diagnose why a team shows fewer games in rankings than in the games table.

This script investigates the discrepancy between:
- games_played: Games counted by the ranking engine (from rankings_full)
- total_games: All games linked to the team in the games table

Usage:
    python scripts/diagnose_team_games.py TEAM_ID
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

# Load environment
load_dotenv()

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_team_games.py TEAM_ID")
        print("Example: python scripts/diagnose_team_games.py 82d5d532-7ab2-4078-b6b4-df24ae87ebfb")
        sys.exit(1)

    team_id = sys.argv[1]

    # Initialize Supabase client
    supabase = create_client(
        os.environ.get("NEXT_PUBLIC_SUPABASE_URL"),
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )

    print(f"\n{'='*70}")
    print(f"DIAGNOSING TEAM GAMES DISCREPANCY")
    print(f"Team ID: {team_id}")
    print(f"{'='*70}\n")

    # 1. Get team info
    print("1. TEAM INFO")
    print("-" * 40)
    team = supabase.table('teams').select('*').eq('team_id_master', team_id).execute()
    if not team.data:
        print(f"   ERROR: Team not found with team_id_master={team_id}")
        sys.exit(1)

    t = team.data[0]
    print(f"   Name: {t.get('team_name')}")
    print(f"   Club: {t.get('club_name')}")
    print(f"   State: {t.get('state')} ({t.get('state_code')})")
    print(f"   Age Group: {t.get('age_group')}")
    print(f"   Gender: {t.get('gender')}")
    print(f"   Is Deprecated: {t.get('is_deprecated')}")
    print()

    # 2. Get rankings_full entry
    print("2. RANKINGS_FULL ENTRY")
    print("-" * 40)
    ranking = supabase.table('rankings_full').select('*').eq('team_id', team_id).execute()
    if not ranking.data:
        print(f"   WARNING: No entry in rankings_full for this team!")
        print(f"   This means the team hasn't been processed by the ranking engine.")
    else:
        r = ranking.data[0]
        print(f"   Games Played: {r.get('games_played')}")
        print(f"   Games Last 180 Days: {r.get('games_last_180_days')}")
        print(f"   Status: {r.get('status')}")
        print(f"   Last Game: {r.get('last_game')}")
        print(f"   Last Calculated: {r.get('last_calculated')}")
        print(f"   Power Score Final: {r.get('power_score_final')}")
        print(f"   Age Group (in rankings): {r.get('age_group')}")
        print(f"   Gender (in rankings): {r.get('gender')}")
    print()

    # 3. Count games in games table
    print("3. GAMES TABLE COUNTS")
    print("-" * 40)

    # All games
    all_games = supabase.table('games').select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score, competition').or_(f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}').order('game_date', desc=True).execute()

    print(f"   Total games in games table: {len(all_games.data)}")

    if all_games.data:
        # Calculate date ranges
        cutoff_365 = (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%d')
        cutoff_180 = (datetime.utcnow() - timedelta(days=180)).strftime('%Y-%m-%d')

        games_365 = [g for g in all_games.data if g.get('game_date', '') >= cutoff_365]
        games_180 = [g for g in all_games.data if g.get('game_date', '') >= cutoff_180]
        games_with_scores = [g for g in all_games.data if g.get('home_score') is not None and g.get('away_score') is not None]

        print(f"   Games in last 365 days: {len(games_365)}")
        print(f"   Games in last 180 days: {len(games_180)}")
        print(f"   Games with valid scores: {len(games_with_scores)}")
    print()

    # 4. Check for team aliases and merged teams
    print("4. TEAM ALIASES & MERGES")
    print("-" * 40)

    aliases = supabase.table('team_aliases').select('*, provider:providers(name)').eq('team_id_master', team_id).execute()
    print(f"   Number of aliases: {len(aliases.data)}")
    for alias in aliases.data:
        provider_name = alias.get('provider', {}).get('name', 'Unknown') if alias.get('provider') else 'Unknown'
        print(f"   - {alias.get('provider_team_id')} ({provider_name})")

    # Check if this is a canonical team (target of merges)
    merges_as_canonical = supabase.table('team_merges').select('*').eq('canonical_team_id', team_id).eq('status', 'approved').execute()
    if merges_as_canonical.data:
        print(f"\n   This team is the CANONICAL target of {len(merges_as_canonical.data)} merge(s):")
        for merge in merges_as_canonical.data:
            print(f"   - Deprecated: {merge.get('deprecated_team_id')}")
            print(f"     Games Transferred: {merge.get('games_transferred')}")

    # Check if there are any deprecated teams pointing to this one
    deprecated_pointing_here = supabase.table('teams').select('team_id_master, team_name').eq('merged_into', team_id).execute()
    if deprecated_pointing_here.data:
        print(f"\n   Deprecated teams pointing here: {len(deprecated_pointing_here.data)}")
        for dep in deprecated_pointing_here.data:
            print(f"   - {dep.get('team_name')} ({dep.get('team_id_master')})")
    print()

    # 5. Detailed game analysis
    print("5. GAME DETAILS (Recent 20)")
    print("-" * 40)

    for i, game in enumerate(all_games.data[:20]):
        game_date = game.get('game_date', 'Unknown')
        home_id = game.get('home_team_master_id')
        away_id = game.get('away_team_master_id')
        home_score = game.get('home_score')
        away_score = game.get('away_score')
        competition = game.get('competition', '-')

        is_home = home_id == team_id
        opp_id = away_id if is_home else home_id

        # Check opponent team metadata
        if opp_id:
            opp = supabase.table('teams').select('team_name, age_group, gender, is_deprecated').eq('team_id_master', opp_id).execute()
            if opp.data:
                opp_info = opp.data[0]
                opp_name = opp_info.get('team_name', 'Unknown')
                opp_age = opp_info.get('age_group', '?')
                opp_gender = opp_info.get('gender', '?')
                opp_deprecated = opp_info.get('is_deprecated', False)
            else:
                opp_name = "NOT FOUND"
                opp_age = "?"
                opp_gender = "?"
                opp_deprecated = None
        else:
            opp_name = "NULL OPP ID"
            opp_age = "?"
            opp_gender = "?"
            opp_deprecated = None

        # Determine if game would be filtered
        issues = []
        if home_score is None or away_score is None:
            issues.append("NO_SCORE")
        if not opp_id:
            issues.append("NO_OPP_ID")
        if opp_deprecated:
            issues.append("OPP_DEPRECATED")
        if opp_age == '?' or not opp_age:
            issues.append("NO_OPP_AGE")
        if opp_gender == '?' or not opp_gender:
            issues.append("NO_OPP_GENDER")

        score_str = f"{home_score}-{away_score}" if home_score is not None else "N/A"
        issues_str = f" ⚠️  {', '.join(issues)}" if issues else " ✓"

        print(f"   {i+1:2}. {game_date} | {'H' if is_home else 'A'} vs {opp_name[:25]:25} ({opp_age}/{opp_gender}) | {score_str:5} | {competition[:15]:15} |{issues_str}")

    print()

    # 6. Summary and likely cause
    print("6. DIAGNOSIS SUMMARY")
    print("-" * 40)

    if ranking.data:
        ranking_games = ranking.data[0].get('games_played', 0)
        total_games = len(all_games.data)

        if ranking_games < total_games:
            print(f"   DISCREPANCY: Rankings show {ranking_games} games, but {total_games} exist in games table\n")

            # Check for common issues
            games_without_scores = len([g for g in all_games.data if g.get('home_score') is None or g.get('away_score') is None])
            if games_without_scores > 0:
                print(f"   - {games_without_scores} games have missing scores (filtered from rankings)")

            # Check opponent metadata
            opp_issues = 0
            for game in all_games.data:
                opp_id = game.get('away_team_master_id') if game.get('home_team_master_id') == team_id else game.get('home_team_master_id')
                if opp_id:
                    opp = supabase.table('teams').select('age_group, gender').eq('team_id_master', opp_id).execute()
                    if not opp.data or not opp.data[0].get('age_group') or not opp.data[0].get('gender'):
                        opp_issues += 1

            if opp_issues > 0:
                print(f"   - {opp_issues} games have opponents with missing age_group or gender metadata")

            # Check rankings last calculated
            last_calc = ranking.data[0].get('last_calculated')
            if last_calc:
                print(f"\n   Rankings were last calculated: {last_calc}")
                print(f"   If games were added after this, they won't be reflected.")

            print("\n   RECOMMENDED ACTIONS:")
            print("   1. Ensure all opponent teams have age_group and gender set")
            print("   2. Re-run the ranking calculation to include new games")
            print("   3. Check if any game scores are missing")
    else:
        print("   Team has no rankings entry - needs to be processed by ranking engine")

if __name__ == '__main__':
    main()
