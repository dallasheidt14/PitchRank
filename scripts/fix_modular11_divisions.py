#!/usr/bin/env python3
"""
Fix Modular11 HD/AD Division Issues

This script comprehensively fixes HD/AD division issues for Modular11 teams:

1. Creates missing AD teams when AD games exist but no AD team
2. Creates proper division-suffixed aliases (391_HD, 391_AD)
3. Moves misassigned games to the correct team
4. Handles teams without HD/AD in their name

IMPORTANT: Run audit_modular11_divisions.py first to understand the state!

Usage:
    # Dry run - show what would change
    python scripts/fix_modular11_divisions.py --dry-run

    # Fix a specific club/age
    python scripts/fix_modular11_divisions.py --club "RSL AZ" --age-group u16

    # Fix all clubs (with confirmation prompts)
    python scripts/fix_modular11_divisions.py --all

    # Output SQL for manual review instead of executing
    python scripts/fix_modular11_divisions.py --sql-only
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
MLS_NEXT_AGES = ['U13', 'U14', 'U15', 'U16', 'U17', 'u13', 'u14', 'u15', 'u16', 'u17']


def get_supabase():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


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
        if f' {age}' in name or f' {age.upper()}' in name:
            name = name.replace(f' {age}', '').replace(f' {age.upper()}', '').strip()
    return name


def detect_division_from_name(team_name: str) -> str:
    if not team_name:
        return 'UNKNOWN'
    name_upper = team_name.upper().strip()
    if name_upper.endswith(' HD') or ' HD ' in name_upper:
        return 'HD'
    elif name_upper.endswith(' AD') or ' AD ' in name_upper:
        return 'AD'
    return 'UNKNOWN'


def extract_division_from_raw_data(raw_data: dict) -> str:
    if not raw_data:
        return 'UNKNOWN'
    mls_div = raw_data.get('mls_division') or raw_data.get('_modular11_division')
    if mls_div:
        return mls_div.upper()
    for field in ['team_name', 'home_team_name', 'away_team_name']:
        name = raw_data.get(field, '')
        if name:
            div = detect_division_from_name(name)
            if div != 'UNKNOWN':
                return div
    return 'UNKNOWN'


def find_team_by_name_parts(db, club_name: str, age_group: str, division: str):
    """Find a team by club name, age, and division."""
    # Try exact match first
    search_patterns = [
        f"{club_name} {age_group} {division}",
        f"{club_name} {age_group.upper()} {division}",
    ]

    for pattern in search_patterns:
        result = db.table('teams').select('*').ilike('team_name', pattern).single().execute()
        if result.data:
            return result.data

    return None


def get_provider_team_id_for_alias(db, team_id: str) -> str:
    """Get the base provider_team_id from existing alias for a team."""
    result = db.table('team_alias_map').select('provider_team_id').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('team_id_master', team_id).execute()

    if result.data:
        # Get the base ID (strip _HD/_AD suffix if present)
        pid = result.data[0]['provider_team_id']
        if pid.endswith('_HD') or pid.endswith('_AD'):
            return pid[:-3]
        return pid
    return None


def analyze_club(db, club_name: str, age_group: str):
    """
    Analyze a single club/age combination and determine what fixes are needed.

    Returns dict with analysis and recommended actions.
    """
    analysis = {
        'club_name': club_name,
        'age_group': age_group,
        'hd_team': None,
        'ad_team': None,
        'unknown_team': None,
        'old_aliases': [],
        'hd_alias_exists': False,
        'ad_alias_exists': False,
        'hd_games': [],
        'ad_games': [],
        'unknown_games': [],
        'actions': []
    }

    # Find teams for this club/age
    search_base = f"%{club_name}%{age_group}%"
    teams_result = db.table('teams').select('*').ilike('team_name', search_base).execute()

    for team in (teams_result.data or []):
        team_name = team['team_name']
        div = detect_division_from_name(team_name)

        if div == 'HD':
            analysis['hd_team'] = team
        elif div == 'AD':
            analysis['ad_team'] = team
        else:
            analysis['unknown_team'] = team

    # Get the primary team (HD > Unknown > AD for analysis)
    primary_team = analysis['hd_team'] or analysis['unknown_team'] or analysis['ad_team']
    if not primary_team:
        print(f"  ⚠️  No team found for {club_name} {age_group}")
        return analysis

    # Check aliases
    for team in [analysis['hd_team'], analysis['ad_team'], analysis['unknown_team']]:
        if not team:
            continue

        aliases_result = db.table('team_alias_map').select('*').eq(
            'provider_id', MODULAR11_PROVIDER_ID
        ).eq('team_id_master', team['team_id_master']).execute()

        for alias in (aliases_result.data or []):
            pid = alias['provider_team_id']
            if pid.endswith('_HD'):
                analysis['hd_alias_exists'] = True
            elif pid.endswith('_AD'):
                analysis['ad_alias_exists'] = True
            else:
                analysis['old_aliases'].append({
                    'id': alias['id'],
                    'provider_team_id': pid,
                    'team_id': team['team_id_master'],
                    'team_name': team['team_name']
                })

    # Analyze games for the primary team (to see if there are misassigned games)
    team_to_analyze = primary_team
    games_result = db.table('games').select('id, raw_data, home_team_master_id, away_team_master_id').or_(
        f"home_team_master_id.eq.{team_to_analyze['team_id_master']},away_team_master_id.eq.{team_to_analyze['team_id_master']}"
    ).execute()

    for game in (games_result.data or []):
        raw_data = game.get('raw_data') or {}
        div = extract_division_from_raw_data(raw_data)

        # Determine if this team is home or away in the game
        is_home = game['home_team_master_id'] == team_to_analyze['team_id_master']

        game_info = {
            'id': game['id'],
            'position': 'home' if is_home else 'away',
            'division': div
        }

        if div == 'HD':
            analysis['hd_games'].append(game_info)
        elif div == 'AD':
            analysis['ad_games'].append(game_info)
        else:
            analysis['unknown_games'].append(game_info)

    # Determine actions needed
    team_div = detect_division_from_name(team_to_analyze['team_name'])

    # Action 1: Create AD team if AD games exist but no AD team
    if len(analysis['ad_games']) > 0 and not analysis['ad_team']:
        analysis['actions'].append({
            'type': 'CREATE_AD_TEAM',
            'description': f"Create AD team for {club_name} {age_group}",
            'details': {
                'base_team': team_to_analyze,
                'ad_game_count': len(analysis['ad_games'])
            }
        })

    # Action 2: Create HD alias if old alias exists but no HD alias
    if analysis['old_aliases'] and not analysis['hd_alias_exists'] and (analysis['hd_team'] or team_div == 'UNKNOWN'):
        target_team = analysis['hd_team'] or team_to_analyze
        base_pid = analysis['old_aliases'][0]['provider_team_id']
        analysis['actions'].append({
            'type': 'CREATE_HD_ALIAS',
            'description': f"Create {base_pid}_HD alias",
            'details': {
                'base_provider_team_id': base_pid,
                'target_team_id': target_team['team_id_master'],
                'target_team_name': target_team['team_name']
            }
        })

    # Action 3: Create AD alias if AD team exists but no AD alias
    if analysis['ad_team'] and not analysis['ad_alias_exists']:
        base_pid = analysis['old_aliases'][0]['provider_team_id'] if analysis['old_aliases'] else None
        if base_pid:
            analysis['actions'].append({
                'type': 'CREATE_AD_ALIAS',
                'description': f"Create {base_pid}_AD alias",
                'details': {
                    'base_provider_team_id': base_pid,
                    'target_team_id': analysis['ad_team']['team_id_master'],
                    'target_team_name': analysis['ad_team']['team_name']
                }
            })

    # Action 4: Move AD games to AD team if both exist
    if len(analysis['ad_games']) > 0 and analysis['ad_team'] and team_div != 'AD':
        analysis['actions'].append({
            'type': 'MOVE_AD_GAMES',
            'description': f"Move {len(analysis['ad_games'])} AD games to AD team",
            'details': {
                'from_team_id': team_to_analyze['team_id_master'],
                'to_team_id': analysis['ad_team']['team_id_master'],
                'game_count': len(analysis['ad_games']),
                'game_ids': [g['id'] for g in analysis['ad_games']]
            }
        })

    return analysis


def execute_action(db, action: dict, dry_run: bool = True, sql_only: bool = False):
    """Execute a single fix action."""
    action_type = action['type']
    details = action['details']

    if action_type == 'CREATE_AD_TEAM':
        base_team = details['base_team']
        club_name = extract_club_name(base_team['team_name'])
        age_group = base_team['age_group']
        new_team_name = f"{club_name} {age_group} AD"

        if sql_only:
            new_id = str(uuid.uuid4())
            print(f"""
-- Create AD team: {new_team_name}
INSERT INTO teams (team_id_master, team_name, club_name, age_group, gender, provider_id)
VALUES ('{new_id}', '{new_team_name}', '{club_name}', '{age_group}', '{base_team['gender']}', '{MODULAR11_PROVIDER_ID}');
""")
            return {'team_id': new_id, 'team_name': new_team_name}

        if dry_run:
            print(f"  [DRY RUN] Would create team: {new_team_name}")
            return {'team_id': 'dry-run-id', 'team_name': new_team_name}

        # Actually create the team
        new_id = str(uuid.uuid4())
        db.table('teams').insert({
            'team_id_master': new_id,
            'team_name': new_team_name,
            'club_name': club_name,
            'age_group': age_group,
            'gender': base_team['gender'],
            'provider_id': MODULAR11_PROVIDER_ID,
            'provider_team_id': None  # Will be set via alias
        }).execute()

        print(f"  ✅ Created team: {new_team_name} ({new_id})")
        return {'team_id': new_id, 'team_name': new_team_name}

    elif action_type == 'CREATE_HD_ALIAS':
        base_pid = details['base_provider_team_id']
        team_id = details['target_team_id']
        new_pid = f"{base_pid}_HD"

        if sql_only:
            print(f"""
-- Create HD alias: {new_pid}
INSERT INTO team_alias_map (provider_id, provider_team_id, team_id_master, match_method, match_confidence, review_status, division)
VALUES ('{MODULAR11_PROVIDER_ID}', '{new_pid}', '{team_id}', 'migration', 1.0, 'approved', 'HD');
""")
            return True

        if dry_run:
            print(f"  [DRY RUN] Would create alias: {new_pid} → {details['target_team_name']}")
            return True

        db.table('team_alias_map').insert({
            'provider_id': MODULAR11_PROVIDER_ID,
            'provider_team_id': new_pid,
            'team_id_master': team_id,
            'match_method': 'migration',
            'match_confidence': 1.0,
            'review_status': 'approved',
            'division': 'HD',
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }).execute()

        print(f"  ✅ Created alias: {new_pid} → {details['target_team_name']}")
        return True

    elif action_type == 'CREATE_AD_ALIAS':
        base_pid = details['base_provider_team_id']
        team_id = details['target_team_id']
        new_pid = f"{base_pid}_AD"

        if sql_only:
            print(f"""
-- Create AD alias: {new_pid}
INSERT INTO team_alias_map (provider_id, provider_team_id, team_id_master, match_method, match_confidence, review_status, division)
VALUES ('{MODULAR11_PROVIDER_ID}', '{new_pid}', '{team_id}', 'migration', 1.0, 'approved', 'AD');
""")
            return True

        if dry_run:
            print(f"  [DRY RUN] Would create alias: {new_pid} → {details['target_team_name']}")
            return True

        db.table('team_alias_map').insert({
            'provider_id': MODULAR11_PROVIDER_ID,
            'provider_team_id': new_pid,
            'team_id_master': team_id,
            'match_method': 'migration',
            'match_confidence': 1.0,
            'review_status': 'approved',
            'division': 'AD',
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }).execute()

        print(f"  ✅ Created alias: {new_pid} → {details['target_team_name']}")
        return True

    elif action_type == 'MOVE_AD_GAMES':
        from_team = details['from_team_id']
        to_team = details['to_team_id']
        game_ids = details['game_ids']

        if sql_only:
            print(f"""
-- Move {len(game_ids)} AD games to AD team
-- First disable immutability trigger
ALTER TABLE games DISABLE TRIGGER enforce_game_immutability;

UPDATE games SET home_team_master_id = '{to_team}'
WHERE home_team_master_id = '{from_team}'
  AND id IN ({','.join(f"'{g}'" for g in game_ids)});

UPDATE games SET away_team_master_id = '{to_team}'
WHERE away_team_master_id = '{from_team}'
  AND id IN ({','.join(f"'{g}'" for g in game_ids)});

-- Re-enable immutability trigger
ALTER TABLE games ENABLE TRIGGER enforce_game_immutability;
""")
            return True

        if dry_run:
            print(f"  [DRY RUN] Would move {len(game_ids)} games from {from_team} to {to_team}")
            return True

        # Need to handle game moves carefully - might need to disable trigger
        print(f"  ⚠️  Moving {len(game_ids)} games requires manual SQL execution for safety")
        print(f"      Run with --sql-only to generate the SQL")
        return False

    return False


def fix_club(db, club_name: str, age_group: str, dry_run: bool = True, sql_only: bool = False):
    """Fix all issues for a specific club/age."""
    print(f"\n{'='*60}")
    print(f"Fixing: {club_name} {age_group}")
    print(f"{'='*60}")

    analysis = analyze_club(db, club_name, age_group)

    if not analysis['actions']:
        print("  ✅ No fixes needed!")
        return

    print(f"\n  Found {len(analysis['hd_games'])} HD games, {len(analysis['ad_games'])} AD games")
    print(f"  HD team: {analysis['hd_team']['team_name'] if analysis['hd_team'] else 'NONE'}")
    print(f"  AD team: {analysis['ad_team']['team_name'] if analysis['ad_team'] else 'NONE'}")
    print(f"  Old aliases: {[a['provider_team_id'] for a in analysis['old_aliases']]}")

    print(f"\n  Actions needed ({len(analysis['actions'])}):")
    for action in analysis['actions']:
        print(f"    - {action['type']}: {action['description']}")

    # Execute actions in order
    created_ad_team = None

    for action in analysis['actions']:
        if action['type'] == 'CREATE_AD_TEAM':
            result = execute_action(db, action, dry_run, sql_only)
            if result:
                created_ad_team = result

        elif action['type'] == 'CREATE_AD_ALIAS':
            # If we just created the AD team, update the target
            if created_ad_team and not dry_run:
                action['details']['target_team_id'] = created_ad_team['team_id']
                action['details']['target_team_name'] = created_ad_team['team_name']
            execute_action(db, action, dry_run, sql_only)

        elif action['type'] == 'CREATE_HD_ALIAS':
            execute_action(db, action, dry_run, sql_only)

        elif action['type'] == 'MOVE_AD_GAMES':
            # If we just created the AD team, update the target
            if created_ad_team and not dry_run:
                action['details']['to_team_id'] = created_ad_team['team_id']
            execute_action(db, action, dry_run, sql_only)


def main():
    parser = argparse.ArgumentParser(description='Fix Modular11 HD/AD division issues')
    parser.add_argument('--club', type=str, help='Club name to fix')
    parser.add_argument('--age-group', type=str, help='Age group to fix (e.g., u16)')
    parser.add_argument('--all', action='store_true', help='Fix all clubs (with confirmation)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without making changes')
    parser.add_argument('--sql-only', action='store_true', help='Output SQL instead of executing')

    args = parser.parse_args()

    db = get_supabase()

    if args.club and args.age_group:
        fix_club(db, args.club, args.age_group, args.dry_run, args.sql_only)
    elif args.all:
        print("🔍 Finding all clubs needing fixes...")
        # This would integrate with the audit script
        print("⚠️  --all mode not yet implemented. Run audit first, then fix individual clubs.")
    else:
        print("Usage:")
        print("  python scripts/fix_modular11_divisions.py --club 'RSL AZ' --age-group u16 --dry-run")
        print("  python scripts/fix_modular11_divisions.py --club 'RSL AZ' --age-group u16 --sql-only")
        print("  python scripts/fix_modular11_divisions.py --club 'RSL AZ' --age-group u16")
        print("\nRun audit_modular11_divisions.py first to see what needs fixing!")


if __name__ == '__main__':
    main()
