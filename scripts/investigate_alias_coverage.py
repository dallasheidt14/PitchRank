#!/usr/bin/env python3
"""Investigate Modular11 alias coverage."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MLS_NEXT_AGES = ['U13', 'U14', 'U15', 'U16', 'U17', 'u13', 'u14', 'u15', 'u16', 'u17']

db = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

print("="*70)
print("MODULAR11 ALIAS COVERAGE INVESTIGATION")
print("="*70)

# Get all Modular11 aliases
aliases_result = db.table('team_alias_map').select(
    'team_id_master, provider_team_id'
).eq('provider_id', MODULAR11_PROVIDER_ID).execute()

alias_team_ids = set(a['team_id_master'] for a in (aliases_result.data or []))
print(f"\n📊 Total Modular11 aliases: {len(aliases_result.data or [])}")
print(f"📊 Unique teams with aliases: {len(alias_team_ids)}")

# Get all MLS NEXT age group teams
teams_result = db.table('teams').select(
    'team_id_master, team_name, age_group'
).in_('age_group', MLS_NEXT_AGES).execute()

all_teams = teams_result.data or []
print(f"\n📊 Total MLS NEXT teams: {len(all_teams)}")

# Teams with vs without aliases
teams_with_alias = [t for t in all_teams if t['team_id_master'] in alias_team_ids]
teams_without_alias = [t for t in all_teams if t['team_id_master'] not in alias_team_ids]

print(f"📊 Teams WITH Modular11 alias: {len(teams_with_alias)}")
print(f"📊 Teams WITHOUT Modular11 alias: {len(teams_without_alias)}")

# Check which teams have games
print("\n" + "-"*50)
print("Checking game counts for teams without aliases...")

teams_needing_aliases = []
for team in teams_without_alias[:100]:  # Check first 100
    games = db.table('games').select('id', count='exact').or_(
        f"home_team_master_id.eq.{team['team_id_master']},away_team_master_id.eq.{team['team_id_master']}"
    ).execute()

    game_count = games.count if hasattr(games, 'count') else len(games.data or [])
    if game_count > 0:
        teams_needing_aliases.append({
            'team': team,
            'games': game_count
        })

print(f"\n📊 Of first 100 teams without aliases:")
print(f"   {len(teams_needing_aliases)} have games and need aliases")

if teams_needing_aliases:
    print("\n   Top 10 teams with games but no Modular11 alias:")
    for item in sorted(teams_needing_aliases, key=lambda x: -x['games'])[:10]:
        print(f"   - {item['team']['team_name']} ({item['team']['age_group']}): {item['games']} games")

# Check by age group
print("\n" + "-"*50)
print("Breakdown by age group:")
by_age = defaultdict(lambda: {'total': 0, 'with_alias': 0, 'without_alias': 0})

for team in all_teams:
    age = team['age_group'].upper()
    by_age[age]['total'] += 1
    if team['team_id_master'] in alias_team_ids:
        by_age[age]['with_alias'] += 1
    else:
        by_age[age]['without_alias'] += 1

for age in sorted(by_age.keys()):
    stats = by_age[age]
    pct = (stats['with_alias'] / stats['total'] * 100) if stats['total'] > 0 else 0
    print(f"   {age}: {stats['with_alias']}/{stats['total']} have aliases ({pct:.0f}%)")

# Check what providers teams have
print("\n" + "-"*50)
print("Checking provider distribution...")

provider_result = db.table('teams').select('provider_id').in_('age_group', MLS_NEXT_AGES).execute()
providers = defaultdict(int)
for t in (provider_result.data or []):
    pid = t.get('provider_id') or 'None'
    providers[pid] += 1

print("\nTeams by provider_id:")
for pid, count in sorted(providers.items(), key=lambda x: -x[1]):
    label = "Modular11" if pid == MODULAR11_PROVIDER_ID else pid[:20] if pid != 'None' else 'None'
    print(f"   {label}: {count}")
