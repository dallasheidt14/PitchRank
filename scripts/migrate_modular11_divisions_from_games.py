#!/usr/bin/env python3
"""
Migrate Modular11 Team Aliases: Determine Division from Games

This script fixes Modular11 team aliases by:
1. Finding all MLS NEXT teams (U13-U17)
2. Extracting base club ID from existing aliases or games
3. Determining division (HD/AD) from games' competition field
4. Creating new aliases in format {club_id}_{age}_{division} (e.g., "391_U16_AD")
5. Handling teams with no existing alias by inferring club ID from games

Usage:
    # Dry run (preview changes)
    python scripts/migrate_modular11_divisions_from_games.py --dry-run

    # Execute migration
    python scripts/migrate_modular11_divisions_from_games.py

    # Verbose output
    python scripts/migrate_modular11_divisions_from_games.py --verbose
"""
import argparse
import os
import sys
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

# Load environment variables - prioritize .env.local if it exists
env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MLS_NEXT_AGES = ['u13', 'u14', 'u15', 'u16', 'u17']


def get_supabase():
    """Get Supabase client."""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


# Reuse helper functions from migrate_modular11_aliases.py
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


def normalize_age_group(age_group: str) -> str:
    """Normalize age group format to U16, U13, etc."""
    if not age_group:
        return None
    age = age_group.strip().upper()
    if not age.startswith('U'):
        age = f'U{age}'
    return age


def get_mls_next_teams(db):
    """
    Get all MLS NEXT teams (U13-U17) that have Modular11 data.
    
    Returns teams that either:
    1. Have Modular11 provider_id, OR
    2. Have Modular11 aliases, OR
    3. Have Modular11 games
    """
    # Query with case-insensitive age groups
    age_groups = MLS_NEXT_AGES + [age.upper() for age in MLS_NEXT_AGES]
    
    # First, get teams with Modular11 provider_id
    teams_with_provider = db.table('teams').select(
        'team_id_master, team_name, age_group, gender, club_name'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).in_('age_group', age_groups).execute()
    
    team_ids_found = {t['team_id_master'] for t in (teams_with_provider.data or [])}
    
    # Get teams that have Modular11 aliases
    aliases_result = db.table('team_alias_map').select('team_id_master').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).execute()
    
    alias_team_ids = {a['team_id_master'] for a in (aliases_result.data or [])}
    
    # Get teams that have Modular11 games
    games_result = db.table('games').select(
        'home_team_master_id, away_team_master_id'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).limit(10000).execute()
    
    game_team_ids = set()
    for game in (games_result.data or []):
        if game.get('home_team_master_id'):
            game_team_ids.add(game['home_team_master_id'])
        if game.get('away_team_master_id'):
            game_team_ids.add(game['away_team_master_id'])
    
    # Combine all team IDs
    all_modular11_team_ids = team_ids_found | alias_team_ids | game_team_ids
    
    # Now fetch full team details for these teams
    if not all_modular11_team_ids:
        return []
    
    # Fetch in batches (Supabase has limits)
    all_teams = []
    team_ids_list = list(all_modular11_team_ids)
    
    for i in range(0, len(team_ids_list), 100):
        batch = team_ids_list[i:i+100]
        result = db.table('teams').select(
            'team_id_master, team_name, age_group, gender, club_name'
        ).in_('team_id_master', batch).in_('age_group', age_groups).execute()
        
        if result.data:
            all_teams.extend(result.data)
    
    return all_teams


def get_base_club_id(db, team_id_master: str) -> str:
    """
    Get base club ID from existing aliases or games.
    
    Returns base club ID (e.g., "391") or None.
    """
    # First try: Query team_alias_map for existing Modular11 aliases
    result = db.table('team_alias_map').select('provider_team_id').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('team_id_master', team_id_master).execute()
    
    base_ids = []
    for alias in (result.data or []):
        pid = alias['provider_team_id']
        # Strip any suffix to get base ID
        base = pid.split('_')[0]
        # Make sure it's numeric (Modular11 club IDs are numeric)
        if base.isdigit():
            base_ids.append(base)
    
    if base_ids:
        # Prefer most specific format (with age/division) if multiple aliases exist
        # Count occurrences and return most common
        most_common = Counter(base_ids).most_common(1)
        if most_common:
            return most_common[0][0]
    
    # Fallback: Query games table for this team
    games_result = db.table('games').select(
        'home_team_master_id, away_team_master_id, home_provider_id, away_provider_id'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).or_(
        f'home_team_master_id.eq.{team_id_master},away_team_master_id.eq.{team_id_master}'
    ).limit(100).execute()
    
    # Collect all provider_ids seen for this team
    seen_provider_ids = []
    
    for game in (games_result.data or []):
        # Check home_provider_id when team is home
        if game.get('home_team_master_id') == team_id_master:
            pid = game.get('home_provider_id', '')
            if pid:
                base = pid.split('_')[0]
                if base.isdigit():
                    seen_provider_ids.append(base)
        # Check away_provider_id when team is away
        if game.get('away_team_master_id') == team_id_master:
            pid = game.get('away_provider_id', '')
            if pid:
                base = pid.split('_')[0]
                if base.isdigit():
                    seen_provider_ids.append(base)
    
    # Return the most common provider_id
    if seen_provider_ids:
        most_common = Counter(seen_provider_ids).most_common(1)
        if most_common:
            return most_common[0][0]
    
    return None


def determine_division_from_games(db, team_id_master: str, team_name: str = None) -> str:
    """
    Determine division (HD/AD) from games' competition field.
    
    Returns 'HD', 'AD', or None.
    """
    # Query games table for all games where team is home or away
    games_result = db.table('games').select(
        'competition, division_name'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).or_(
        f'home_team_master_id.eq.{team_id_master},away_team_master_id.eq.{team_id_master}'
    ).limit(1000).execute()
    
    hd_count = 0
    ad_count = 0
    
    for game in (games_result.data or []):
        competition = game.get('competition', '') or ''
        division_name = game.get('division_name', '') or ''
        division = extract_division_from_competition(competition, division_name)
        
        if division == 'HD':
            hd_count += 1
        elif division == 'AD':
            ad_count += 1
    
    # Determine division based on majority
    if hd_count > ad_count:
        return 'HD'
    elif ad_count > hd_count:
        return 'AD'
    elif hd_count == 0 and ad_count == 0:
        # No division found in games - fallback to team name
        if team_name:
            return detect_division_from_name(team_name)
    
    # Tie or no clear winner
    return None


def create_proper_alias(db, team_id_master: str, base_club_id: str, age_group: str, division: str = None, dry_run: bool = True):
    """
    Create properly formatted alias with critical checks.
    
    Returns (success: bool, message: str, warnings: list)
    """
    age_normalized = normalize_age_group(age_group)
    if not age_normalized:
        return False, "Invalid age group", []
    
    # Build alias: {base_club_id}_{age_group}_{division} or {base_club_id}_{age_group}
    if division:
        new_alias_id = f"{base_club_id}_{age_normalized}_{division}"
    else:
        new_alias_id = f"{base_club_id}_{age_normalized}"
    
    warnings = []
    
    # CRITICAL CHECK 1: Check if team already has ANY new-format alias
    existing_team_aliases = db.table('team_alias_map').select('id, provider_team_id').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('team_id_master', team_id_master).execute()
    
    for alias in (existing_team_aliases.data or []):
        pid = alias['provider_team_id']
        # Check if it's a new format alias (contains _U## pattern)
        if re.search(r'_U\d+', pid):
            return False, f"Team already has new-format alias: {pid}", []
    
    # CRITICAL CHECK 2: Check if this exact alias already exists (may point to different team)
    alias_exists = db.table('team_alias_map').select('id, team_id_master').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('provider_team_id', new_alias_id).execute()
    
    if alias_exists.data:
        existing_team_id = alias_exists.data[0]['team_id_master']
        if existing_team_id != team_id_master:
            warnings.append(f"Alias {new_alias_id} already exists for different team ({existing_team_id})")
            return False, f"Alias conflict: {new_alias_id} exists for different team", warnings
        else:
            # Alias exists for same team - skip creation
            return False, f"Alias already exists for this team: {new_alias_id}", []
    
    # Create alias if not dry_run
    if dry_run:
        return True, f"[DRY RUN] Would create: {new_alias_id}", warnings
    
    try:
        db.table('team_alias_map').insert({
            'provider_id': MODULAR11_PROVIDER_ID,
            'provider_team_id': new_alias_id,
            'team_id_master': team_id_master,
            'match_method': 'migration',
            'match_confidence': 1.0,
            'review_status': 'approved',
            'division': division,
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }).execute()
        
        return True, f"Created: {new_alias_id}", warnings
    except Exception as e:
        return False, f"Error creating alias: {e}", warnings


def main():
    """Main orchestration function."""
    parser = argparse.ArgumentParser(
        description='Migrate Modular11 team aliases by determining division from games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview changes)
  python scripts/migrate_modular11_divisions_from_games.py --dry-run

  # Execute migration
  python scripts/migrate_modular11_divisions_from_games.py

  # Verbose output
  python scripts/migrate_modular11_divisions_from_games.py --verbose
        """
    )
    
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without executing')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    args = parser.parse_args()
    
    db = get_supabase()
    
    print("\n" + "="*70)
    print("MODULAR11 DIVISION MIGRATION FROM GAMES")
    print("="*70)
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
    print()
    
    # Get all MLS NEXT teams
    print("Fetching MLS NEXT teams (U13-U17)...")
    teams = get_mls_next_teams(db)
    print(f"Found {len(teams)} teams")
    print()
    
    # Statistics
    stats = {
        'processed': 0,
        'aliases_created': 0,
        'skipped_existing': 0,
        'no_base_id': 0,
        'no_division': 0,
        'conflicts': 0,
        'errors': 0,
        'warnings': []
    }
    
    teams_needing_review = []
    
    # Process each team
    for i, team in enumerate(teams, 1):
        team_id = team['team_id_master']
        team_name = team.get('team_name', 'Unknown')
        age_group = team.get('age_group', '')
        
        if args.verbose:
            print(f"[{i}/{len(teams)}] Processing: {team_name} ({age_group})")
        
        stats['processed'] += 1
        
        # Step 1: Get base club ID
        base_club_id = get_base_club_id(db, team_id)
        
        if not base_club_id:
            stats['no_base_id'] += 1
            teams_needing_review.append({
                'team_id': team_id,
                'team_name': team_name,
                'age_group': age_group,
                'reason': 'No base club ID found (no aliases or games)'
            })
            if args.verbose:
                print(f"  ⚠️  No base club ID found")
            continue
        
        # Step 2: Determine division from games
        division = determine_division_from_games(db, team_id, team_name)
        
        if not division:
            stats['no_division'] += 1
            if args.verbose:
                print(f"  ⚠️  No division found (will create alias without division)")
        
        # Step 3: Create proper alias
        success, message, warnings = create_proper_alias(
            db, team_id, base_club_id, age_group, division, dry_run=args.dry_run
        )
        
        if warnings:
            stats['warnings'].extend(warnings)
        
        if success:
            stats['aliases_created'] += 1
            if args.verbose:
                print(f"  ✅ {message}")
        else:
            if 'already exists' in message.lower() or 'already has' in message.lower():
                stats['skipped_existing'] += 1
                if args.verbose:
                    print(f"  ⏭️  {message}")
            elif 'conflict' in message.lower():
                stats['conflicts'] += 1
                teams_needing_review.append({
                    'team_id': team_id,
                    'team_name': team_name,
                    'age_group': age_group,
                    'reason': message
                })
                if args.verbose:
                    print(f"  ⚠️  {message}")
            else:
                stats['errors'] += 1
                teams_needing_review.append({
                    'team_id': team_id,
                    'team_name': team_name,
                    'age_group': age_group,
                    'reason': message
                })
                if args.verbose:
                    print(f"  ❌ {message}")
        
        if args.verbose:
            print()
    
    # Generate report
    print("\n" + "="*70)
    print("MIGRATION SUMMARY")
    print("="*70)
    print(f"Teams Processed: {stats['processed']}")
    print(f"Aliases Created: {stats['aliases_created']}")
    print(f"Skipped (Already Exists): {stats['skipped_existing']}")
    print(f"No Base Club ID: {stats['no_base_id']}")
    print(f"No Division Found: {stats['no_division']}")
    print(f"Conflicts: {stats['conflicts']}")
    print(f"Errors: {stats['errors']}")
    
    if stats['warnings']:
        print(f"\nWarnings: {len(stats['warnings'])}")
        if args.verbose:
            for warning in stats['warnings'][:10]:
                print(f"  - {warning}")
            if len(stats['warnings']) > 10:
                print(f"  ... and {len(stats['warnings']) - 10} more")
    
    if teams_needing_review:
        print(f"\n⚠️  Teams Needing Manual Review: {len(teams_needing_review)}")
        print("\nFirst 10 teams:")
        for team in teams_needing_review[:10]:
            print(f"  - {team['team_name']} ({team['age_group']}): {team['reason']}")
        if len(teams_needing_review) > 10:
            print(f"  ... and {len(teams_needing_review) - 10} more")
        
        # Optionally export to CSV
        if args.verbose and not args.dry_run:
            csv_path = Path(__file__).parent.parent / 'data' / 'exports' / f'teams_needing_review_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            import csv
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['team_id', 'team_name', 'age_group', 'reason'])
                writer.writeheader()
                writer.writerows(teams_needing_review)
            print(f"\n📄 Exported review list to: {csv_path}")
    
    print("\n" + "="*70)
    if args.dry_run:
        print("🔍 DRY RUN COMPLETE - No changes were made")
        print("Run without --dry-run to execute migration")
    else:
        print("✅ MIGRATION COMPLETE")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()

