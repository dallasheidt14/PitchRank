#!/usr/bin/env python3
"""Export Modular11 teams with potential DB matches for manual mapping"""
import csv
import os
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client
from rapidfuzz import fuzz

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

def normalize_club_name(name):
    """Normalize club name by removing common suffixes/prefixes"""
    name_lower = name.lower().strip()
    suffixes = [' sa', ' sc', ' fc', ' cf', ' ac', ' afc', ' soccer club', 
                ' football club', ' soccer academy', ' futbol club', 
                ' athletic club', ' soccer', ' academy']
    for suffix in sorted(suffixes, key=len, reverse=True):
        if name_lower.endswith(suffix):
            name_lower = name_lower[:-len(suffix)].strip()
            break
    prefixes = ['fc ', 'cf ', 'ac ', 'afc ']
    for prefix in prefixes:
        if name_lower.startswith(prefix):
            name_lower = name_lower[len(prefix):].strip()
            break
    return name_lower

# Get ALL Male teams from database
print("Fetching all Male teams from database...")
all_db_teams = []
offset = 0
while True:
    result = supabase.table('teams').select('team_id_master, team_name, club_name, age_group').eq('gender', 'Male').range(offset, offset + 999).execute()
    if not result.data:
        break
    all_db_teams.extend(result.data)
    offset += 1000
    if len(result.data) < 1000:
        break

print(f"Found {len(all_db_teams)} Male teams in database")

# Build club lookup
db_clubs = defaultdict(list)
for t in all_db_teams:
    club = t.get('club_name', '') or ''
    club_norm = normalize_club_name(club) if club else normalize_club_name(t.get('team_name', ''))
    db_clubs[club_norm].append(t)

# Read ALL Modular11 teams
print("Reading Modular11 teams...")
modular_clubs = defaultdict(lambda: {'games': 0, 'ages': set(), 'divisions': set(), 'team_ids': set()})

csv_path = 'scrapers/modular11_scraper/output/modular11_results_20251203_105706.csv'
if not Path(csv_path).exists():
    csv_path = 'scrapers/modular11_scraper/output/modular11_u13.csv'

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        club = row.get('club_name', '')
        age = row.get('age_group', '')
        team_name = row.get('team_name', '')
        team_id = row.get('team_id', '')
        div = 'HD' if team_name.endswith(' HD') else 'AD'
        
        modular_clubs[club]['games'] += 1
        modular_clubs[club]['ages'].add(age)
        modular_clubs[club]['divisions'].add(div)
        modular_clubs[club]['team_ids'].add(team_id)

print(f"Found {len(modular_clubs)} unique Modular11 clubs")

# Find potential matches
results = []
for club, info in modular_clubs.items():
    club_norm = normalize_club_name(club)
    
    # Find best matches in DB
    potential_matches = []
    
    # Direct normalized match
    if club_norm in db_clubs:
        for db_team in db_clubs[club_norm][:5]:
            potential_matches.append({
                'db_team_id': db_team['team_id_master'],
                'db_team_name': db_team['team_name'],
                'db_club_name': db_team.get('club_name', ''),
                'db_age_group': db_team.get('age_group', ''),
                'match_type': 'exact_club',
                'score': 100
            })
    
    # Fuzzy match if no exact
    if not potential_matches:
        for db_club_norm, db_teams in db_clubs.items():
            score = fuzz.ratio(club_norm, db_club_norm)
            if score >= 70:
                for db_team in db_teams[:3]:
                    potential_matches.append({
                        'db_team_id': db_team['team_id_master'],
                        'db_team_name': db_team['team_name'],
                        'db_club_name': db_team.get('club_name', ''),
                        'db_age_group': db_team.get('age_group', ''),
                        'match_type': 'fuzzy',
                        'score': score
                    })
    
    # Sort by score
    potential_matches.sort(key=lambda x: -x['score'])
    
    results.append({
        'modular11_club': club,
        'modular11_club_normalized': club_norm,
        'modular11_team_id': list(info['team_ids'])[0] if info['team_ids'] else '',
        'modular11_ages': ', '.join(sorted(info['ages'])),
        'modular11_divisions': ', '.join(sorted(info['divisions'])),
        'modular11_games': info['games'],
        'potential_matches': potential_matches[:5]  # Top 5
    })

# Sort by games
results.sort(key=lambda x: -x['modular11_games'])

# Export to CSV
output_path = 'scrapers/modular11_scraper/output/teams_for_manual_mapping.csv'
with open(output_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow([
        'modular11_club', 
        'modular11_club_normalized',
        'modular11_team_id',
        'modular11_ages', 
        'modular11_divisions',
        'modular11_games',
        'match_1_db_team_id',
        'match_1_db_team_name',
        'match_1_db_club',
        'match_1_db_age',
        'match_1_score',
        'match_2_db_team_id',
        'match_2_db_team_name',
        'match_2_db_club',
        'match_2_db_age',
        'match_2_score',
        'match_3_db_team_id',
        'match_3_db_team_name',
        'match_3_db_club',
        'match_3_db_age',
        'match_3_score',
        'selected_db_team_id'  # User fills this in
    ])
    
    for r in results:
        row = [
            r['modular11_club'],
            r['modular11_club_normalized'],
            r['modular11_team_id'],
            r['modular11_ages'],
            r['modular11_divisions'],
            r['modular11_games'],
        ]
        
        # Add up to 3 potential matches
        for i in range(3):
            if i < len(r['potential_matches']):
                m = r['potential_matches'][i]
                row.extend([
                    m['db_team_id'],
                    m['db_team_name'],
                    m['db_club_name'],
                    m['db_age_group'],
                    m['score']
                ])
            else:
                row.extend(['', '', '', '', ''])
        
        row.append('')  # selected_db_team_id - user fills in
        writer.writerow(row)

print(f"\nExported {len(results)} clubs to: {output_path}")
print("\nInstructions:")
print("1. Open the CSV in Excel/Google Sheets")
print("2. Review the potential matches for each Modular11 club")
print("3. Fill in 'selected_db_team_id' with the correct DB team UUID")
print("4. Save the file and we'll import the mappings")













