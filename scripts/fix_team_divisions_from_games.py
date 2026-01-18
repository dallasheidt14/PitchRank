#!/usr/bin/env python3
"""
Fix team divisions based on their actual games.

This script:
1. Analyzes each team's games to determine if they're HD or AD
2. Renames teams that have ONLY HD games to add " HD" suffix
3. Renames teams that have ONLY AD games to add " AD" suffix
4. Identifies teams with BOTH HD and AD games (need to be split)

Usage:
    # Step 1: Analyze and show what would change (dry run)
    python scripts/fix_team_divisions_from_games.py --analyze

    # Step 2: Rename teams with single division (dry run)
    python scripts/fix_team_divisions_from_games.py --rename --dry-run

    # Step 3: Rename teams with single division (execute)
    python scripts/fix_team_divisions_from_games.py --rename

    # Step 4: Show teams that need splitting
    python scripts/fix_team_divisions_from_games.py --show-split-candidates
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MLS_NEXT_AGES = ['U13', 'U14', 'U15', 'U16', 'U17']


def get_supabase():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def extract_division_from_competition(competition, division_name):
    """Extract HD/AD division from competition and division_name fields."""
    if not competition and not division_name:
        return None
    
    combined = f"{competition or ''} {division_name or ''}".upper()
    
    # Check for HD
    if ' HD' in combined or combined.startswith('HD') or combined.endswith('HD'):
        return 'HD'
    
    # Check for AD (but not "SHOWCASE" or other words containing AD)
    if combined == 'AD' or combined.startswith('AD ') or ' AD ' in combined or combined.endswith(' AD'):
        return 'AD'
    
    return None


def detect_division_from_name(team_name: str) -> str:
    """Detect HD/AD from team name."""
    if not team_name:
        return None
    name_upper = team_name.upper().strip()
    if name_upper.endswith(' HD') or ' HD ' in name_upper:
        return 'HD'
    elif name_upper.endswith(' AD') or ' AD ' in name_upper:
        return 'AD'
    return None


def analyze_team_divisions(db):
    """Analyze each team's games to determine their division."""
    print("\n" + "="*70)
    print("ANALYZING TEAM DIVISIONS FROM GAMES")
    print("="*70)
    
    # Get all MLS NEXT teams
    teams_result = db.table('teams').select(
        'team_id_master, team_name, age_group'
    ).in_('age_group', MLS_NEXT_AGES + [a.lower() for a in MLS_NEXT_AGES]).execute()
    
    print(f"📊 Found {len(teams_result.data)} MLS NEXT teams")
    
    # Get all Modular11 games (no limit - get all)
    print("📖 Fetching all Modular11 games (this may take a moment)...")
    games_result = db.table('games').select(
        'id, home_team_master_id, away_team_master_id, competition, division_name'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).execute()
    
    # Supabase may paginate, so get all pages
    all_games = list(games_result.data or [])
    while games_result.data and len(games_result.data) > 0:
        # Try to get next page if available
        try:
            games_result = db.table('games').select(
                'id, home_team_master_id, away_team_master_id, competition, division_name'
            ).eq('provider_id', MODULAR11_PROVIDER_ID).range(
                len(all_games), len(all_games) + 1000
            ).execute()
            if games_result.data:
                all_games.extend(games_result.data)
            else:
                break
        except:
            break
    
    print(f"📊 Found {len(all_games)} Modular11 games")
    
    # Debug: count games by division
    division_counts = {'HD': 0, 'AD': 0, 'none': 0}
    
    # Count HD/AD games per team
    team_game_counts = defaultdict(lambda: {'HD': 0, 'AD': 0, 'none': 0})
    
    for game in all_games:
        competition = game.get('competition', '') or ''
        division_name = game.get('division_name', '') or ''
        game_division = extract_division_from_competition(competition, division_name)
        
        # Debug: count divisions
        if game_division:
            division_counts[game_division] += 1
        else:
            division_counts['none'] += 1
        
        # Count for home team
        home_id = game.get('home_team_master_id')
        if home_id:
            if game_division == 'HD':
                team_game_counts[home_id]['HD'] += 1
            elif game_division == 'AD':
                team_game_counts[home_id]['AD'] += 1
            else:
                team_game_counts[home_id]['none'] += 1
        
        # Count for away team
        away_id = game.get('away_team_master_id')
        if away_id:
            if game_division == 'HD':
                team_game_counts[away_id]['HD'] += 1
            elif game_division == 'AD':
                team_game_counts[away_id]['AD'] += 1
            else:
                team_game_counts[away_id]['none'] += 1
    
    # Debug output
    print(f"\n📊 Games by division:")
    print(f"  HD games: {division_counts['HD']}")
    print(f"  AD games: {division_counts['AD']}")
    print(f"  Games without division: {division_counts['none']}")
    print(f"  Teams with games: {len(team_game_counts)}")
    
    # Categorize teams
    teams_to_rename_hd = []
    teams_to_rename_ad = []
    teams_to_split = []
    teams_no_change = []
    
    for team in teams_result.data:
        team_id = team['team_id_master']
        team_name = team['team_name']
        current_div = detect_division_from_name(team_name)
        counts = team_game_counts[team_id]
        
        total_games = counts['HD'] + counts['AD'] + counts['none']
        
        # Skip teams with no games
        if total_games == 0:
            continue
        
        # If team already has division in name, check if it matches
        if current_div:
            if counts[current_div] > 0 and counts['HD' if current_div == 'AD' else 'AD'] == 0:
                teams_no_change.append({
                    'team_id': team_id,
                    'team_name': team_name,
                    'division': current_div,
                    'hd_games': counts['HD'],
                    'ad_games': counts['AD'],
                    'none_games': counts['none']
                })
            elif counts['HD'] > 0 and counts['AD'] > 0:
                teams_to_split.append({
                    'team_id': team_id,
                    'team_name': team_name,
                    'hd_games': counts['HD'],
                    'ad_games': counts['AD'],
                    'none_games': counts['none']
                })
            continue
        
        # Team doesn't have division in name - determine from games
        if counts['HD'] > 0 and counts['AD'] == 0:
            # Only HD games
            teams_to_rename_hd.append({
                'team_id': team_id,
                'team_name': team_name,
                'hd_games': counts['HD'],
                'ad_games': counts['AD'],
                'none_games': counts['none']
            })
        elif counts['AD'] > 0 and counts['HD'] == 0:
            # Only AD games
            teams_to_rename_ad.append({
                'team_id': team_id,
                'team_name': team_name,
                'hd_games': counts['HD'],
                'ad_games': counts['AD'],
                'none_games': counts['none']
            })
        elif counts['HD'] > 0 and counts['AD'] > 0:
            # Both HD and AD games - needs splitting
            teams_to_split.append({
                'team_id': team_id,
                'team_name': team_name,
                'hd_games': counts['HD'],
                'ad_games': counts['AD'],
                'none_games': counts['none']
            })
        else:
            # Only games without division info - categorize separately
            teams_no_change.append({
                'team_id': team_id,
                'team_name': team_name,
                'hd_games': counts['HD'],
                'ad_games': counts['AD'],
                'none_games': counts['none'],
                'category': 'no_division_games'
            })
    
    # Count teams with only "none" games
    teams_only_none = [t for t in teams_no_change if t.get('category') == 'no_division_games']
    
    # Print summary
    print(f"\n📊 ANALYSIS RESULTS:")
    print(f"  Teams to rename to HD: {len(teams_to_rename_hd)}")
    print(f"  Teams to rename to AD: {len(teams_to_rename_ad)}")
    print(f"  Teams that need splitting: {len(teams_to_split)}")
    print(f"  Teams with correct division: {len(teams_no_change) - len(teams_only_none)}")
    print(f"  Teams with only games without division info: {len(teams_only_none)}")
    
    # Show samples
    if teams_to_rename_hd:
        print(f"\n📋 Sample teams to rename to HD (showing first 10):")
        for team in teams_to_rename_hd[:10]:
            print(f"  {team['team_name']}")
            print(f"    HD games: {team['hd_games']}, AD games: {team['ad_games']}, None: {team['none_games']}")
    
    if teams_to_rename_ad:
        print(f"\n📋 Sample teams to rename to AD (showing first 10):")
        for team in teams_to_rename_ad[:10]:
            print(f"  {team['team_name']}")
            print(f"    HD games: {team['hd_games']}, AD games: {team['ad_games']}, None: {team['none_games']}")
    
    if teams_to_split:
        print(f"\n📋 Teams that need splitting (showing first 10):")
        for team in teams_to_split[:10]:
            print(f"  {team['team_name']}")
            print(f"    HD games: {team['hd_games']}, AD games: {team['ad_games']}, None: {team['none_games']}")
    
    return {
        'rename_hd': teams_to_rename_hd,
        'rename_ad': teams_to_rename_ad,
        'split': teams_to_split,
        'no_change': teams_no_change
    }


def rename_teams(db, teams_to_rename_hd, teams_to_rename_ad, dry_run=True):
    """Rename teams to add HD/AD suffix."""
    print("\n" + "="*70)
    print("RENAMING TEAMS")
    print("="*70)
    
    if dry_run:
        print("🔍 DRY RUN - No changes will be made")
    
    renamed = 0
    errors = []
    
    # Rename HD teams
    for team in teams_to_rename_hd:
        old_name = team['team_name']
        new_name = old_name + " HD"
        
        if dry_run:
            print(f"Would rename: {old_name} → {new_name}")
        else:
            try:
                db.table('teams').update({
                    'team_name': new_name
                }).eq('team_id_master', team['team_id']).execute()
                print(f"✅ Renamed: {old_name} → {new_name}")
                renamed += 1
            except Exception as e:
                error_msg = f"Error renaming {old_name}: {e}"
                print(f"❌ {error_msg}")
                errors.append(error_msg)
    
    # Rename AD teams
    for team in teams_to_rename_ad:
        old_name = team['team_name']
        new_name = old_name + " AD"
        
        if dry_run:
            print(f"Would rename: {old_name} → {new_name}")
        else:
            try:
                db.table('teams').update({
                    'team_name': new_name
                }).eq('team_id_master', team['team_id']).execute()
                print(f"✅ Renamed: {old_name} → {new_name}")
                renamed += 1
            except Exception as e:
                error_msg = f"Error renaming {old_name}: {e}"
                print(f"❌ {error_msg}")
                errors.append(error_msg)
    
    print(f"\n📊 Renamed {renamed} teams")
    if errors:
        print(f"❌ {len(errors)} errors occurred")
    
    return renamed, errors


def show_split_candidates(db, teams_to_split):
    """Show detailed info about teams that need splitting."""
    print("\n" + "="*70)
    print("TEAMS THAT NEED SPLITTING")
    print("="*70)
    print("These teams have BOTH HD and AD games and need to be split into two teams.")
    print("This requires manual intervention or a more complex script.\n")
    
    print(f"📊 Total teams needing split: {len(teams_to_split)}\n")
    
    for i, team in enumerate(teams_to_split, 1):
        print(f"{i}. {team['team_name']}")
        print(f"   HD games: {team['hd_games']}")
        print(f"   AD games: {team['ad_games']}")
        print(f"   Games without division: {team['none_games']}")
        print(f"   Team ID: {team['team_id']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Fix team divisions based on their actual games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze and show what would change
  python scripts/fix_team_divisions_from_games.py --analyze

  # Rename teams (dry run)
  python scripts/fix_team_divisions_from_games.py --rename --dry-run

  # Rename teams (execute)
  python scripts/fix_team_divisions_from_games.py --rename

  # Show teams that need splitting
  python scripts/fix_team_divisions_from_games.py --show-split-candidates
        """
    )
    
    parser.add_argument('--analyze', action='store_true', help='Analyze team divisions from games')
    parser.add_argument('--rename', action='store_true', help='Rename teams to add HD/AD suffix')
    parser.add_argument('--show-split-candidates', action='store_true', help='Show teams that need splitting')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without executing')
    
    args = parser.parse_args()
    
    if not any([args.analyze, args.rename, args.show_split_candidates]):
        parser.print_help()
        sys.exit(1)
    
    db = get_supabase()
    
    if args.analyze or args.rename or args.show_split_candidates:
        analysis = analyze_team_divisions(db)
    
    if args.rename:
        rename_teams(
            db,
            analysis['rename_hd'],
            analysis['rename_ad'],
            dry_run=args.dry_run
        )
    
    if args.show_split_candidates:
        show_split_candidates(db, analysis['split'])


if __name__ == '__main__':
    main()

