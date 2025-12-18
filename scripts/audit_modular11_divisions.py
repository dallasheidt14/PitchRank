#!/usr/bin/env python3
"""
Audit Modular11 HD/AD Division State

This script provides a comprehensive audit of the current state of Modular11
teams, aliases, and games to understand what migration/fixes are needed.

It answers:
1. Which clubs have HD teams? AD teams? Both? Neither properly named?
2. Which aliases use old format (391) vs new format (391_HD, 391_AD)?
3. How many games are potentially misassigned (AD games on HD teams)?
4. What specific fixes are needed for each club/age group?

Usage:
    python scripts/audit_modular11_divisions.py
    python scripts/audit_modular11_divisions.py --age-group u16
    python scripts/audit_modular11_divisions.py --verbose
    python scripts/audit_modular11_divisions.py --output audit_report.json
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MLS_NEXT_AGES = ['U13', 'U14', 'U15', 'U16', 'U17', 'u13', 'u14', 'u15', 'u16', 'u17']


def get_supabase():
    """Get Supabase client"""
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

    # Remove HD/AD suffix
    for suffix in [' HD', ' AD', ' hd', ' ad']:
        if name.endswith(suffix):
            name = name[:-3].strip()
            break

    # Remove age group
    for age in MLS_NEXT_AGES:
        if f' {age}' in name or f' {age.upper()}' in name:
            name = name.replace(f' {age}', '').replace(f' {age.upper()}', '').strip()

    return name


def detect_division_from_name(team_name: str) -> str:
    """Detect HD/AD from team name. Returns 'HD', 'AD', or 'UNKNOWN'."""
    if not team_name:
        return 'UNKNOWN'

    name_upper = team_name.upper().strip()
    if name_upper.endswith(' HD') or ' HD ' in name_upper:
        return 'HD'
    elif name_upper.endswith(' AD') or ' AD ' in name_upper:
        return 'AD'
    return 'UNKNOWN'


def extract_division_from_raw_data(raw_data: dict) -> str:
    """Extract division from game's raw_data. Returns 'HD', 'AD', or 'UNKNOWN'."""
    if not raw_data:
        return 'UNKNOWN'

    # Check mls_division field
    mls_div = raw_data.get('mls_division') or raw_data.get('_modular11_division')
    if mls_div:
        return mls_div.upper()

    # Check team names for suffix
    for field in ['team_name', 'home_team_name', 'away_team_name']:
        name = raw_data.get(field, '')
        if name:
            div = detect_division_from_name(name)
            if div != 'UNKNOWN':
                return div

    return 'UNKNOWN'


def get_alias_format(provider_team_id: str) -> str:
    """Determine alias format: 'suffixed_hd', 'suffixed_ad', or 'old'."""
    if provider_team_id.endswith('_HD'):
        return 'suffixed_hd'
    elif provider_team_id.endswith('_AD'):
        return 'suffixed_ad'
    return 'old'


def audit_teams(db, age_filter: str = None, verbose: bool = False):
    """
    Comprehensive audit of Modular11 teams, aliases, and games.
    """
    print("🔍 Auditing Modular11 division state...\n")

    # Step 1: Get all Modular11 teams
    query = db.table('teams').select('team_id_master, team_name, age_group, gender, club_name')

    # Filter by provider if possible (teams created from Modular11)
    # Note: This might miss teams that were manually created

    teams_result = query.execute()
    all_teams = teams_result.data or []

    # Filter to MLS NEXT age groups
    mls_teams = [t for t in all_teams if t['age_group'] in MLS_NEXT_AGES]

    if age_filter:
        mls_teams = [t for t in mls_teams if t['age_group'].lower() == age_filter.lower()]

    print(f"📊 Found {len(mls_teams)} teams in MLS NEXT age groups")

    # Step 2: Get all Modular11 aliases
    aliases_result = db.table('team_alias_map').select(
        'id, provider_team_id, team_id_master, division, match_method'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).execute()

    all_aliases = aliases_result.data or []
    print(f"📊 Found {len(all_aliases)} Modular11 aliases")

    # Build alias lookup by team_id_master
    aliases_by_team = defaultdict(list)
    for alias in all_aliases:
        aliases_by_team[alias['team_id_master']].append(alias)

    # Step 3: Analyze each team
    clubs = defaultdict(lambda: {
        'hd_team': None,
        'ad_team': None,
        'unknown_teams': [],
        'hd_aliases': [],
        'ad_aliases': [],
        'old_aliases': [],
        'issues': []
    })

    for team in mls_teams:
        team_id = team['team_id_master']
        team_name = team['team_name']
        age_group = team['age_group']

        # Extract club name for grouping
        club_name = extract_club_name(team_name)
        if not club_name:
            club_name = team.get('club_name') or 'UNKNOWN_CLUB'

        club_key = f"{club_name}|{age_group}"
        club_data = clubs[club_key]

        # Detect division from team name
        division = detect_division_from_name(team_name)

        # Categorize team
        if division == 'HD':
            if club_data['hd_team']:
                club_data['issues'].append(f"Multiple HD teams: {club_data['hd_team']['team_name']} and {team_name}")
            club_data['hd_team'] = team
        elif division == 'AD':
            if club_data['ad_team']:
                club_data['issues'].append(f"Multiple AD teams: {club_data['ad_team']['team_name']} and {team_name}")
            club_data['ad_team'] = team
        else:
            club_data['unknown_teams'].append(team)

        # Categorize aliases for this team
        team_aliases = aliases_by_team.get(team_id, [])
        for alias in team_aliases:
            fmt = get_alias_format(alias['provider_team_id'])
            if fmt == 'suffixed_hd':
                club_data['hd_aliases'].append(alias)
            elif fmt == 'suffixed_ad':
                club_data['ad_aliases'].append(alias)
            else:
                club_data['old_aliases'].append(alias)

    # Step 4: Analyze game assignments for clubs with issues
    print("\n🔍 Analyzing game assignments...")

    clubs_needing_attention = []

    for club_key, data in clubs.items():
        club_name, age_group = club_key.split('|')

        analysis = {
            'club_name': club_name,
            'age_group': age_group,
            'hd_team': data['hd_team']['team_name'] if data['hd_team'] else None,
            'hd_team_id': data['hd_team']['team_id_master'] if data['hd_team'] else None,
            'ad_team': data['ad_team']['team_name'] if data['ad_team'] else None,
            'ad_team_id': data['ad_team']['team_id_master'] if data['ad_team'] else None,
            'unknown_teams': [t['team_name'] for t in data['unknown_teams']],
            'has_hd_alias': len(data['hd_aliases']) > 0,
            'has_ad_alias': len(data['ad_aliases']) > 0,
            'old_alias_count': len(data['old_aliases']),
            'old_aliases': [a['provider_team_id'] for a in data['old_aliases']],
            'issues': data['issues'],
            'actions_needed': []
        }

        # Determine what actions are needed
        has_hd = data['hd_team'] is not None
        has_ad = data['ad_team'] is not None
        has_unknown = len(data['unknown_teams']) > 0
        has_old_alias = len(data['old_aliases']) > 0
        has_hd_alias = len(data['hd_aliases']) > 0
        has_ad_alias = len(data['ad_aliases']) > 0

        # Check game misassignment for teams with old aliases
        if has_old_alias and (has_hd or has_unknown):
            # Get games for HD/unknown team and check for AD games
            team_to_check = data['hd_team'] or data['unknown_teams'][0]
            team_id = team_to_check['team_id_master']

            # Count games by division in raw_data
            games_result = db.table('games').select('id, raw_data').or_(
                f"home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}"
            ).limit(500).execute()

            hd_games = 0
            ad_games = 0
            unknown_games = 0

            for game in (games_result.data or []):
                raw_data = game.get('raw_data') or {}
                div = extract_division_from_raw_data(raw_data)
                if div == 'HD':
                    hd_games += 1
                elif div == 'AD':
                    ad_games += 1
                else:
                    unknown_games += 1

            analysis['games_on_primary_team'] = {
                'total': len(games_result.data or []),
                'hd_games': hd_games,
                'ad_games': ad_games,
                'unknown_division': unknown_games
            }

            # Determine actions
            if ad_games > 0 and not has_ad:
                analysis['actions_needed'].append(f"CREATE_AD_TEAM: {ad_games} AD games need a home")

            if ad_games > 0 and has_ad and not has_ad_alias:
                analysis['actions_needed'].append(f"CREATE_AD_ALIAS: AD team exists but no alias")
                analysis['actions_needed'].append(f"MOVE_GAMES: {ad_games} AD games to AD team")

            if has_old_alias and not has_hd_alias and (has_hd or has_unknown):
                analysis['actions_needed'].append("CREATE_HD_ALIAS: Upgrade old alias to _HD format")

        # Check if AD team exists but has no alias
        if has_ad and not has_ad_alias:
            analysis['actions_needed'].append("CREATE_AD_ALIAS: AD team has no Modular11 alias")

        # Only include clubs that need attention
        if analysis['actions_needed'] or analysis['issues'] or has_unknown:
            clubs_needing_attention.append(analysis)

    return clubs_needing_attention


def print_report(clubs: list, verbose: bool = False):
    """Print human-readable audit report."""

    if not clubs:
        print("\n✅ All clubs appear to be properly configured!")
        return

    print(f"\n{'='*80}")
    print(f"AUDIT REPORT: {len(clubs)} clubs need attention")
    print(f"{'='*80}\n")

    # Group by severity
    critical = []  # Has AD games but no AD team
    high = []      # Missing aliases or need game moves
    medium = []    # Unknown division teams

    for club in clubs:
        if any('CREATE_AD_TEAM' in a for a in club['actions_needed']):
            critical.append(club)
        elif any('MOVE_GAMES' in a or 'CREATE' in a for a in club['actions_needed']):
            high.append(club)
        else:
            medium.append(club)

    def print_club(club, show_details=True):
        print(f"\n📍 {club['club_name']} ({club['age_group']})")
        print(f"   HD Team: {club['hd_team'] or '❌ NONE'}")
        print(f"   AD Team: {club['ad_team'] or '❌ NONE'}")
        if club['unknown_teams']:
            print(f"   Unknown Division Teams: {club['unknown_teams']}")
        print(f"   Aliases: HD={club['has_hd_alias']}, AD={club['has_ad_alias']}, Old={club['old_alias_count']} {club['old_aliases']}")

        if 'games_on_primary_team' in club:
            g = club['games_on_primary_team']
            print(f"   Games: {g['total']} total ({g['hd_games']} HD, {g['ad_games']} AD, {g['unknown_division']} unknown)")

        if club['actions_needed']:
            print(f"   ⚠️  Actions: {', '.join(club['actions_needed'])}")
        if club['issues']:
            print(f"   🚨 Issues: {', '.join(club['issues'])}")

    if critical:
        print(f"\n🔴 CRITICAL ({len(critical)} clubs) - AD games exist but no AD team:")
        print("-" * 60)
        for club in critical:
            print_club(club)

    if high:
        print(f"\n🟠 HIGH ({len(high)} clubs) - Missing aliases or need game moves:")
        print("-" * 60)
        for club in high[:20 if not verbose else len(high)]:
            print_club(club)
        if len(high) > 20 and not verbose:
            print(f"\n   ... and {len(high) - 20} more (use --verbose to see all)")

    if medium:
        print(f"\n🟡 MEDIUM ({len(medium)} clubs) - Teams without HD/AD in name:")
        print("-" * 60)
        for club in medium[:10 if not verbose else len(medium)]:
            print_club(club)
        if len(medium) > 10 and not verbose:
            print(f"\n   ... and {len(medium) - 10} more (use --verbose to see all)")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY OF ACTIONS NEEDED:")
    print(f"{'='*80}")

    action_counts = defaultdict(int)
    for club in clubs:
        for action in club['actions_needed']:
            action_type = action.split(':')[0]
            action_counts[action_type] += 1

    for action, count in sorted(action_counts.items()):
        print(f"  {action}: {count} clubs")

    print(f"\nTotal clubs needing attention: {len(clubs)}")
    print(f"  Critical: {len(critical)}")
    print(f"  High: {len(high)}")
    print(f"  Medium: {len(medium)}")


def main():
    parser = argparse.ArgumentParser(description='Audit Modular11 HD/AD division state')
    parser.add_argument('--age-group', type=str, help='Filter by age group (e.g., u16)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show all clubs, not just summary')
    parser.add_argument('--output', '-o', type=str, help='Output JSON report to file')

    args = parser.parse_args()

    db = get_supabase()

    clubs = audit_teams(db, age_filter=args.age_group, verbose=args.verbose)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(clubs, f, indent=2, default=str)
        print(f"\n📄 Report saved to {args.output}")

    print_report(clubs, verbose=args.verbose)


if __name__ == '__main__':
    main()
