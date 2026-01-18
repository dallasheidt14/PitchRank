#!/usr/bin/env python3
"""Show detailed Arizona teams with venue info"""
import csv
from pathlib import Path
from collections import defaultdict

files = sorted(Path('data/raw/tgs').glob('tgs_events_3900_3910_*.csv'), reverse=True)
if not files:
    print("No CSV file found")
    exit(1)

csv_file = files[0]
print(f"Checking: {csv_file.name}\n")

az_teams = defaultdict(lambda: {
    'team_id': '',
    'team_name': '',
    'club_name': '',
    'age_group': '',
    'gender': '',
    'venues': set(),
    'zips': set(),
    'games': 0
})

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        state_code = row.get('state_code', '')
        if state_code == 'AZ':
            team_id = row.get('team_id', '')
            team_name = row.get('team_name', '')
            club_name = row.get('club_name', '')
            age_year = row.get('age_year', '')
            gender = row.get('gender', '')
            venue = row.get('venue', '')
            
            # Create unique key
            key = f"{team_id}|{team_name}"
            
            if not az_teams[key]['team_id']:
                az_teams[key]['team_id'] = team_id
                az_teams[key]['team_name'] = team_name
                az_teams[key]['club_name'] = club_name
                az_teams[key]['age_group'] = age_year
                az_teams[key]['gender'] = gender
            
            az_teams[key]['venues'].add(venue)
            az_teams[key]['games'] += 1

print(f"Found {len(az_teams)} unique teams from Arizona\n")
print("=" * 120)
print(f"{'Team Name':<45} {'Club':<25} {'Age':<6} {'Games':<6} {'Sample Venue':<30}")
print("=" * 120)

for key in sorted(az_teams.keys()):
    team = az_teams[key]
    sample_venue = list(team['venues'])[0][:30] if team['venues'] else ''
    print(f"{team['team_name']:<45} {team['club_name']:<25} {team['age_group']:<6} {team['games']:<6} {sample_venue:<30}")

print("=" * 120)
print(f"\nTotal: {len(az_teams)} teams")









