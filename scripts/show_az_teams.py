#!/usr/bin/env python3
"""Show all teams from Arizona in scraped data"""
import csv
from pathlib import Path
from collections import defaultdict

# Find the most recent file
files = sorted(Path('data/raw/tgs').glob('tgs_events_3900_3910_*.csv'), reverse=True)
if files:
    csv_file = files[0]
else:
    print("No CSV file found")
    exit(1)

print(f"Checking: {csv_file.name}\n")

az_teams = defaultdict(lambda: {
    'team_id': '',
    'team_name': '',
    'club_name': '',
    'age_group': '',
    'gender': '',
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
            
            # Create unique key
            key = f"{team_id}|{team_name}"
            
            if not az_teams[key]['team_id']:
                az_teams[key]['team_id'] = team_id
                az_teams[key]['team_name'] = team_name
                az_teams[key]['club_name'] = club_name
                az_teams[key]['age_group'] = age_year
                az_teams[key]['gender'] = gender
            
            az_teams[key]['games'] += 1

print(f"Found {len(az_teams)} unique teams from Arizona\n")
print("=" * 100)
print(f"{'Team ID':<12} {'Team Name':<40} {'Club Name':<30} {'Age':<6} {'Gender':<8} {'Games':<6}")
print("=" * 100)

for key in sorted(az_teams.keys()):
    team = az_teams[key]
    print(f"{team['team_id']:<12} {team['team_name']:<40} {team['club_name']:<30} {team['age_group']:<6} {team['gender']:<8} {team['games']:<6}")

print("=" * 100)
print(f"\nTotal: {len(az_teams)} teams")

