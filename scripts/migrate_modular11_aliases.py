#!/usr/bin/env python3
"""
Migrate Modular11 Aliases to New Format and Fix Existing Games

This script handles the complete migration of existing Modular11 data:

1. CREATE NEW ALIASES: Creates properly formatted aliases (391_U16_AD) for all
   existing Modular11 teams based on their age_group and division (from team name)

2. IDENTIFY MISASSIGNED GAMES: Finds games where raw_data.mls_division doesn't
   match the team's division (e.g., AD game assigned to HD team)

3. CREATE MISSING TEAMS: If AD games exist but no AD team, creates the AD team

4. MOVE GAMES: Reassigns games to the correct team based on their actual division

Usage:
    # Step 1: Audit current state
    python scripts/migrate_modular11_aliases.py --audit

    # Step 2: Create new aliases (dry run)
    python scripts/migrate_modular11_aliases.py --create-aliases --dry-run

    # Step 3: Create new aliases (execute)
    python scripts/migrate_modular11_aliases.py --create-aliases

    # Step 4: Find misassigned games
    python scripts/migrate_modular11_aliases.py --find-misassigned

    # Step 5: Fix misassigned games (dry run)
    python scripts/migrate_modular11_aliases.py --fix-games --dry-run

    # Step 6: Fix misassigned games (execute)
    python scripts/migrate_modular11_aliases.py --fix-games
"""
import argparse
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

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


def extract_division_from_raw_data(raw_data: dict) -> str:
    """Extract division from game's raw_data."""
    if not raw_data:
        return None
    mls_div = raw_data.get('mls_division') or raw_data.get('_modular11_division')
    if mls_div:
        return mls_div.upper()
    for field in ['team_name', 'home_team_name', 'away_team_name']:
        name = raw_data.get(field, '')
        if name:
            div = detect_division_from_name(name)
            if div:
                return div
    return None


def extract_club_name(team_name: str) -> str:
    """Extract club name by removing age group and HD/AD suffix."""
    if not team_name:
        return ''
    name = team_name.strip()
    for suffix in [' HD', ' AD', ' hd', ' ad']:
        if name.endswith(suffix):
            name = name[:-3].strip()
            break
    for age in MLS_NEXT_AGES:
        if f' {age}' in name or f' {age.upper()}' in name or f' {age.lower()}' in name:
            name = name.replace(f' {age}', '').replace(f' {age.upper()}', '').replace(f' {age.lower()}', '').strip()
    return name


def normalize_age(age_group: str) -> str:
    """Normalize age group format to U16, U13, etc."""
    if not age_group:
        return None
    age = age_group.strip().upper()
    if not age.startswith('U'):
        age = f'U{age}'
    return age


def get_base_provider_team_id(db, team_id: str) -> str:
    """Get the base provider_team_id (without suffixes) for a team."""
    result = db.table('team_alias_map').select('provider_team_id').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('team_id_master', team_id).execute()

    for alias in (result.data or []):
        pid = alias['provider_team_id']
        # Strip any suffix to get base ID
        base = pid.split('_')[0]
        # Make sure it's numeric (Modular11 club IDs are numeric)
        if base.isdigit():
            return base
    return None


# ============================================================================
# AUDIT FUNCTIONS
# ============================================================================

def audit_current_state(db):
    """Comprehensive audit of current Modular11 alias state."""
    print("\n" + "="*70)
    print("MODULAR11 ALIAS AUDIT")
    print("="*70)

    # Get all Modular11 teams
    teams_result = db.table('teams').select(
        'team_id_master, team_name, age_group, gender, club_name'
    ).in_('age_group', MLS_NEXT_AGES + [a.lower() for a in MLS_NEXT_AGES]).execute()

    teams = teams_result.data or []
    print(f"\n📊 Total MLS NEXT age group teams: {len(teams)}")

    # Categorize teams
    teams_with_hd = [t for t in teams if detect_division_from_name(t['team_name']) == 'HD']
    teams_with_ad = [t for t in teams if detect_division_from_name(t['team_name']) == 'AD']
    teams_unknown = [t for t in teams if detect_division_from_name(t['team_name']) is None]

    print(f"   Teams with HD in name: {len(teams_with_hd)}")
    print(f"   Teams with AD in name: {len(teams_with_ad)}")
    print(f"   Teams without HD/AD: {len(teams_unknown)}")

    # Get all Modular11 aliases
    aliases_result = db.table('team_alias_map').select(
        'id, provider_team_id, team_id_master, division'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).execute()

    aliases = aliases_result.data or []
    print(f"\n📊 Total Modular11 aliases: {len(aliases)}")

    # Categorize aliases by format
    aliases_new_format = []  # 391_U16_AD format
    aliases_div_only = []    # 391_AD format
    aliases_age_only = []    # 391_U16 format
    aliases_old = []         # 391 format

    for alias in aliases:
        pid = alias['provider_team_id']
        parts = pid.split('_')

        if len(parts) == 3 and parts[1].upper().startswith('U') and parts[2] in ('HD', 'AD'):
            aliases_new_format.append(alias)
        elif len(parts) == 2 and parts[1] in ('HD', 'AD'):
            aliases_div_only.append(alias)
        elif len(parts) == 2 and parts[1].upper().startswith('U'):
            aliases_age_only.append(alias)
        else:
            aliases_old.append(alias)

    print(f"   New format (391_U16_AD): {len(aliases_new_format)}")
    print(f"   Division only (391_AD): {len(aliases_div_only)}")
    print(f"   Age only (391_U16): {len(aliases_age_only)}")
    print(f"   Old format (391): {len(aliases_old)}")

    # Check which teams need new aliases
    teams_needing_aliases = []
    for team in teams:
        team_id = team['team_id_master']
        age_group = normalize_age(team['age_group'])
        division = detect_division_from_name(team['team_name'])

        # Check if team has a properly formatted alias
        has_proper_alias = False
        base_id = get_base_provider_team_id(db, team_id)

        if base_id and age_group:
            expected_alias = f"{base_id}_{age_group}"
            if division:
                expected_alias += f"_{division}"

            for alias in aliases:
                if alias['provider_team_id'] == expected_alias and alias['team_id_master'] == team_id:
                    has_proper_alias = True
                    break

        if not has_proper_alias and base_id:
            teams_needing_aliases.append({
                'team': team,
                'base_id': base_id,
                'expected_alias': f"{base_id}_{age_group}_{division}" if division else f"{base_id}_{age_group}"
            })

    print(f"\n📊 Teams needing new-format aliases: {len(teams_needing_aliases)}")

    # Sample of teams needing aliases
    if teams_needing_aliases:
        print("\n   Sample (first 10):")
        for item in teams_needing_aliases[:10]:
            print(f"   - {item['team']['team_name']} → needs {item['expected_alias']}")

    return {
        'teams': teams,
        'aliases': aliases,
        'teams_needing_aliases': teams_needing_aliases
    }


# ============================================================================
# CREATE ALIASES
# ============================================================================

def create_new_format_aliases(db, dry_run=True):
    """Create new-format aliases (391_U16_AD) for all teams that need them."""
    print("\n" + "="*70)
    print("CREATING NEW-FORMAT ALIASES")
    print("="*70)

    audit = audit_current_state(db)
    teams_needing = audit['teams_needing_aliases']

    if not teams_needing:
        print("\n✅ All teams already have properly formatted aliases!")
        return

    print(f"\n{'🔍 DRY RUN - ' if dry_run else ''}Creating {len(teams_needing)} new aliases...")

    created = 0
    errors = 0

    for item in teams_needing:
        team = item['team']
        base_id = item['base_id']
        expected_alias = item['expected_alias']
        division = detect_division_from_name(team['team_name'])

        if dry_run:
            print(f"  [DRY RUN] Would create: {expected_alias} → {team['team_name']}")
            created += 1
            continue

        try:
            # Check if alias already exists
            existing = db.table('team_alias_map').select('id').eq(
                'provider_id', MODULAR11_PROVIDER_ID
            ).eq('provider_team_id', expected_alias).execute()

            if existing.data:
                print(f"  ⚠️  Alias {expected_alias} already exists, skipping")
                continue

            # Create the alias
            db.table('team_alias_map').insert({
                'provider_id': MODULAR11_PROVIDER_ID,
                'provider_team_id': expected_alias,
                'team_id_master': team['team_id_master'],
                'match_method': 'migration',
                'match_confidence': 1.0,
                'review_status': 'approved',
                'division': division,
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }).execute()

            print(f"  ✅ Created: {expected_alias} → {team['team_name']}")
            created += 1

        except Exception as e:
            print(f"  ❌ Error creating {expected_alias}: {e}")
            errors += 1

    print(f"\n{'Would create' if dry_run else 'Created'}: {created} aliases")
    if errors:
        print(f"Errors: {errors}")


# ============================================================================
# FIND MISASSIGNED GAMES
# ============================================================================

def find_misassigned_games(db, limit=500):
    """Find games where raw_data.mls_division doesn't match team's division."""
    print("\n" + "="*70)
    print("FINDING MISASSIGNED GAMES")
    print("="*70)

    # Get all teams with their divisions
    teams_result = db.table('teams').select(
        'team_id_master, team_name, age_group'
    ).in_('age_group', MLS_NEXT_AGES + [a.lower() for a in MLS_NEXT_AGES]).execute()

    team_divisions = {}
    for team in (teams_result.data or []):
        div = detect_division_from_name(team['team_name'])
        team_divisions[team['team_id_master']] = {
            'name': team['team_name'],
            'division': div,
            'age_group': team['age_group']
        }

    # Get games with raw_data
    games_result = db.table('games').select(
        'id, home_team_master_id, away_team_master_id, raw_data, game_date'
    ).not_.is_('raw_data', 'null').limit(limit).execute()

    misassigned = []

    for game in (games_result.data or []):
        raw_data = game.get('raw_data') or {}
        actual_div = extract_division_from_raw_data(raw_data)

        if not actual_div:
            continue

        # Check home team
        home_id = game['home_team_master_id']
        if home_id in team_divisions:
            team_info = team_divisions[home_id]
            if team_info['division'] and team_info['division'] != actual_div:
                misassigned.append({
                    'game_id': game['id'],
                    'game_date': game['game_date'],
                    'position': 'home',
                    'current_team_id': home_id,
                    'current_team_name': team_info['name'],
                    'current_division': team_info['division'],
                    'actual_division': actual_div,
                    'age_group': team_info['age_group']
                })

        # Check away team
        away_id = game['away_team_master_id']
        if away_id in team_divisions:
            team_info = team_divisions[away_id]
            if team_info['division'] and team_info['division'] != actual_div:
                misassigned.append({
                    'game_id': game['id'],
                    'game_date': game['game_date'],
                    'position': 'away',
                    'current_team_id': away_id,
                    'current_team_name': team_info['name'],
                    'current_division': team_info['division'],
                    'actual_division': actual_div,
                    'age_group': team_info['age_group']
                })

    print(f"\n📊 Checked {len(games_result.data or [])} games")
    print(f"📊 Found {len(misassigned)} misassigned team-game links")

    if misassigned:
        # Group by team
        by_team = defaultdict(list)
        for m in misassigned:
            by_team[m['current_team_name']].append(m)

        print(f"\n📊 Affected teams: {len(by_team)}")
        print("\nTop 10 teams with misassigned games:")
        for team_name, games in sorted(by_team.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"  {team_name}: {len(games)} games")
            # Show sample
            sample = games[0]
            print(f"    Example: Game on {sample['game_date']} is {sample['actual_division']} but assigned to {sample['current_division']} team")

    return misassigned


# ============================================================================
# FIX MISASSIGNED GAMES
# ============================================================================

def fix_misassigned_games(db, dry_run=True):
    """Move misassigned games to the correct team."""
    print("\n" + "="*70)
    print("FIXING MISASSIGNED GAMES")
    print("="*70)

    misassigned = find_misassigned_games(db, limit=5000)

    if not misassigned:
        print("\n✅ No misassigned games found!")
        return

    # Group by current team and target division
    fixes_needed = defaultdict(list)
    for m in misassigned:
        key = (m['current_team_id'], m['current_team_name'], m['actual_division'], m['age_group'])
        fixes_needed[key].append(m)

    print(f"\n📊 Need to fix {len(misassigned)} game assignments across {len(fixes_needed)} team pairs")

    # For each group, find or create the target team
    fixed = 0
    created_teams = 0
    errors = 0

    for (current_team_id, current_team_name, target_div, age_group), games in fixes_needed.items():
        # Extract club name
        club_name = extract_club_name(current_team_name)
        age_norm = normalize_age(age_group)

        # Look for target team
        search_pattern = f"%{club_name}%{age_norm}%{target_div}%"
        target_result = db.table('teams').select('team_id_master, team_name').ilike(
            'team_name', search_pattern
        ).execute()

        target_team = None
        if target_result.data:
            target_team = target_result.data[0]

        print(f"\n{club_name} {age_norm}: {len(games)} {target_div} games on wrong team")
        print(f"  Current: {current_team_name}")

        if target_team:
            print(f"  Target:  {target_team['team_name']} (exists)")
        else:
            print(f"  Target:  {club_name} {age_norm} {target_div} (NEEDS CREATION)")

            if not dry_run:
                # Create the missing team
                new_team_id = str(uuid.uuid4())
                new_team_name = f"{club_name} {age_norm} {target_div}"

                try:
                    db.table('teams').insert({
                        'team_id_master': new_team_id,
                        'team_name': new_team_name,
                        'club_name': club_name,
                        'age_group': age_norm,
                        'gender': 'M',  # MLS NEXT is male
                        'provider_id': MODULAR11_PROVIDER_ID
                    }).execute()

                    # Create alias for new team
                    base_id = get_base_provider_team_id(db, current_team_id)
                    if base_id:
                        alias_id = f"{base_id}_{age_norm}_{target_div}"
                        db.table('team_alias_map').insert({
                            'provider_id': MODULAR11_PROVIDER_ID,
                            'provider_team_id': alias_id,
                            'team_id_master': new_team_id,
                            'match_method': 'migration',
                            'match_confidence': 1.0,
                            'review_status': 'approved',
                            'division': target_div,
                            'created_at': datetime.utcnow().isoformat() + 'Z'
                        }).execute()

                    target_team = {'team_id_master': new_team_id, 'team_name': new_team_name}
                    created_teams += 1
                    print(f"  ✅ Created team: {new_team_name}")

                except Exception as e:
                    print(f"  ❌ Error creating team: {e}")
                    errors += 1
                    continue

        if not target_team:
            if dry_run:
                print(f"  [DRY RUN] Would create team and move {len(games)} games")
            continue

        # Move games to target team
        if dry_run:
            print(f"  [DRY RUN] Would move {len(games)} games to {target_team['team_name']}")
            fixed += len(games)
            continue

        # Actually move games
        for game in games:
            try:
                if game['position'] == 'home':
                    db.table('games').update({
                        'home_team_master_id': target_team['team_id_master']
                    }).eq('id', game['game_id']).execute()
                else:
                    db.table('games').update({
                        'away_team_master_id': target_team['team_id_master']
                    }).eq('id', game['game_id']).execute()
                fixed += 1
            except Exception as e:
                print(f"  ❌ Error moving game {game['game_id']}: {e}")
                errors += 1

        print(f"  ✅ Moved {len(games)} games")

    print(f"\n{'Would fix' if dry_run else 'Fixed'}: {fixed} game assignments")
    if created_teams:
        print(f"{'Would create' if dry_run else 'Created'}: {created_teams} teams")
    if errors:
        print(f"Errors: {errors}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Migrate Modular11 aliases and fix existing games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Step 1: Audit current state
  python scripts/migrate_modular11_aliases.py --audit

  # Step 2: Create new aliases (dry run first!)
  python scripts/migrate_modular11_aliases.py --create-aliases --dry-run
  python scripts/migrate_modular11_aliases.py --create-aliases

  # Step 3: Find and fix misassigned games
  python scripts/migrate_modular11_aliases.py --find-misassigned
  python scripts/migrate_modular11_aliases.py --fix-games --dry-run
  python scripts/migrate_modular11_aliases.py --fix-games
        """
    )

    parser.add_argument('--audit', action='store_true', help='Audit current alias state')
    parser.add_argument('--create-aliases', action='store_true', help='Create new-format aliases')
    parser.add_argument('--find-misassigned', action='store_true', help='Find misassigned games')
    parser.add_argument('--fix-games', action='store_true', help='Fix misassigned games')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without executing')

    args = parser.parse_args()

    if not any([args.audit, args.create_aliases, args.find_misassigned, args.fix_games]):
        parser.print_help()
        return

    db = get_supabase()

    if args.audit:
        audit_current_state(db)

    if args.create_aliases:
        create_new_format_aliases(db, dry_run=args.dry_run)

    if args.find_misassigned:
        find_misassigned_games(db)

    if args.fix_games:
        fix_misassigned_games(db, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
