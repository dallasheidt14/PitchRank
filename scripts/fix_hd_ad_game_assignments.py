#!/usr/bin/env python3
"""
Fix HD/AD Game Assignments for Modular11 Teams

This script identifies games that were incorrectly assigned to an HD team
when they should belong to an AD team (or vice versa), and provides
options to reassign them.

Usage:
    # Dry run - show what would change
    python scripts/fix_hd_ad_game_assignments.py --team-id <HD_TEAM_UUID> --dry-run

    # Fix games after AD team is created
    python scripts/fix_hd_ad_game_assignments.py --team-id <HD_TEAM_UUID> --new-team-id <AD_TEAM_UUID>
"""
import argparse
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


def get_supabase():
    """Get Supabase client"""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def extract_division_from_raw_data(raw_data: dict) -> str:
    """Extract HD/AD division from game's raw_data"""
    if not raw_data:
        return None

    # Check mls_division field first (most reliable)
    mls_div = raw_data.get('mls_division') or raw_data.get('_modular11_division')
    if mls_div:
        return mls_div.upper()

    # Fallback: check team names for HD/AD suffix
    for field in ['team_name', 'home_team_name', 'away_team_name', 'opponent_name']:
        name = raw_data.get(field, '')
        if name:
            name_upper = name.upper().strip()
            if name_upper.endswith(' HD'):
                return 'HD'
            elif name_upper.endswith(' AD'):
                return 'AD'

    return None


def find_misassigned_games(db, team_id: str, expected_division: str = None):
    """
    Find games where a team is assigned but the raw_data indicates a different division.

    Args:
        db: Supabase client
        team_id: The team_id_master to check
        expected_division: If provided, find games that DON'T match this division
                          (e.g., expected_division='HD' finds AD games assigned to HD team)

    Returns:
        List of games with their division info
    """
    # Get team info
    team_result = db.table('teams').select('team_name, age_group, gender').eq(
        'team_id_master', team_id
    ).single().execute()

    if not team_result.data:
        print(f"❌ Team not found: {team_id}")
        return []

    team_info = team_result.data
    print(f"\n📋 Team: {team_info['team_name']} ({team_info['age_group']}, {team_info['gender']})")
    print(f"   ID: {team_id}")

    # Detect expected division from team name if not provided
    if not expected_division:
        team_name_upper = team_info['team_name'].upper()
        if ' HD' in team_name_upper or team_name_upper.endswith(' HD'):
            expected_division = 'HD'
        elif ' AD' in team_name_upper or team_name_upper.endswith(' AD'):
            expected_division = 'AD'
        else:
            # Assume HD if no suffix (original teams are usually HD)
            expected_division = 'HD'
            print(f"   ⚠️  No division in team name, assuming: {expected_division}")

    print(f"   Expected Division: {expected_division}")

    # Get all games for this team (as home or away)
    home_games = db.table('games').select('id, game_date, home_score, away_score, raw_data').eq(
        'home_team_master_id', team_id
    ).execute()

    away_games = db.table('games').select('id, game_date, home_score, away_score, raw_data').eq(
        'away_team_master_id', team_id
    ).execute()

    all_games = []

    # Process home games
    for game in (home_games.data or []):
        raw_data = game.get('raw_data') or {}
        actual_division = extract_division_from_raw_data(raw_data)
        all_games.append({
            'id': game['id'],
            'game_date': game['game_date'],
            'score': f"{game.get('home_score', '?')}-{game.get('away_score', '?')}",
            'position': 'home',
            'expected_division': expected_division,
            'actual_division': actual_division,
            'misassigned': actual_division and actual_division != expected_division,
            'team_name_in_raw': raw_data.get('team_name') or raw_data.get('home_team_name'),
            'mls_division_in_raw': raw_data.get('mls_division')
        })

    # Process away games
    for game in (away_games.data or []):
        raw_data = game.get('raw_data') or {}
        actual_division = extract_division_from_raw_data(raw_data)
        all_games.append({
            'id': game['id'],
            'game_date': game['game_date'],
            'score': f"{game.get('home_score', '?')}-{game.get('away_score', '?')}",
            'position': 'away',
            'expected_division': expected_division,
            'actual_division': actual_division,
            'misassigned': actual_division and actual_division != expected_division,
            'team_name_in_raw': raw_data.get('opponent_name') or raw_data.get('away_team_name'),
            'mls_division_in_raw': raw_data.get('mls_division')
        })

    # Sort by date
    all_games.sort(key=lambda x: x['game_date'] or '')

    return all_games


def reassign_games(db, games_to_reassign: list, new_team_id: str, dry_run: bool = True):
    """
    Reassign games from one team to another.

    Args:
        db: Supabase client
        games_to_reassign: List of game dicts with 'id' and 'position' keys
        new_team_id: The team_id_master to assign games to
        dry_run: If True, just show what would happen
    """
    if dry_run:
        print(f"\n🔍 DRY RUN - Would reassign {len(games_to_reassign)} games to {new_team_id}")
        return

    print(f"\n🔄 Reassigning {len(games_to_reassign)} games to {new_team_id}...")

    success = 0
    errors = 0

    for game in games_to_reassign:
        try:
            if game['position'] == 'home':
                db.table('games').update({
                    'home_team_master_id': new_team_id
                }).eq('id', game['id']).execute()
            else:
                db.table('games').update({
                    'away_team_master_id': new_team_id
                }).eq('id', game['id']).execute()
            success += 1
        except Exception as e:
            print(f"  ❌ Error reassigning game {game['id']}: {e}")
            errors += 1

    print(f"\n✅ Reassigned {success} games")
    if errors:
        print(f"❌ {errors} errors occurred")


def main():
    parser = argparse.ArgumentParser(description='Fix HD/AD game assignments for Modular11 teams')
    parser.add_argument('--team-id', required=True, help='The team_id_master to check (usually the HD team)')
    parser.add_argument('--new-team-id', help='The team_id_master to reassign misassigned games to (the AD team)')
    parser.add_argument('--expected-division', choices=['HD', 'AD'], help='The expected division for --team-id')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen without making changes')
    parser.add_argument('--show-all', action='store_true', help='Show all games, not just misassigned ones')

    args = parser.parse_args()

    db = get_supabase()

    # Find games
    games = find_misassigned_games(db, args.team_id, args.expected_division)

    if not games:
        print("\n❌ No games found for this team")
        return

    # Categorize games
    correctly_assigned = [g for g in games if not g['misassigned']]
    misassigned = [g for g in games if g['misassigned']]
    unknown_division = [g for g in games if g['actual_division'] is None]

    print(f"\n📊 Game Summary:")
    print(f"   Total games: {len(games)}")
    print(f"   ✅ Correctly assigned: {len(correctly_assigned)}")
    print(f"   ❌ Misassigned (wrong division): {len(misassigned)}")
    print(f"   ❓ Unknown division: {len(unknown_division)}")

    # Show misassigned games
    if misassigned:
        print(f"\n❌ MISASSIGNED GAMES ({len(misassigned)}):")
        print("-" * 80)
        for game in misassigned:
            print(f"  {game['game_date']} | {game['position']:4} | Score: {game['score']:5} | "
                  f"Expected: {game['expected_division']} | Actual: {game['actual_division']} | "
                  f"raw.mls_division={game['mls_division_in_raw']}")

    if args.show_all:
        print(f"\n✅ CORRECTLY ASSIGNED GAMES ({len(correctly_assigned)}):")
        print("-" * 80)
        for game in correctly_assigned:
            print(f"  {game['game_date']} | {game['position']:4} | Score: {game['score']:5} | "
                  f"Division: {game['actual_division'] or '?'}")

    # Reassign if new team provided
    if args.new_team_id and misassigned:
        # Verify new team exists
        new_team = db.table('teams').select('team_name').eq(
            'team_id_master', args.new_team_id
        ).single().execute()

        if not new_team.data:
            print(f"\n❌ New team not found: {args.new_team_id}")
            return

        print(f"\n🎯 Will reassign to: {new_team.data['team_name']} ({args.new_team_id})")

        reassign_games(db, misassigned, args.new_team_id, dry_run=args.dry_run)
    elif misassigned and not args.new_team_id:
        print(f"\n💡 To reassign these games, run with --new-team-id <AD_TEAM_UUID>")
        print(f"   First create the AD team in the Modular11 Team Review tab, then run:")
        print(f"   python scripts/fix_hd_ad_game_assignments.py --team-id {args.team_id} --new-team-id <AD_TEAM_UUID>")


if __name__ == '__main__':
    main()
