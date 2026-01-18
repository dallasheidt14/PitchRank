#!/usr/bin/env python3
"""Check which Modular11 teams are matching to database teams"""
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

# Get all U13 Male teams from database
print("Fetching U13 Male teams from database...")
result = supabase.table('teams').select('team_id_master, team_name, club_name').eq('age_group', 'u13').eq('gender', 'Male').execute()
db_teams = result.data
print(f"Found {len(db_teams)} U13 Male teams in database")

# Read Modular11 U13 teams
modular_teams = {}
with open('scrapers/modular11_scraper/output/modular11_u13.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_name = row.get('team_name', '')
        club_name = row.get('club_name', '')
        if team_name and team_name not in modular_teams:
            modular_teams[team_name] = club_name

print(f"Found {len(modular_teams)} unique Modular11 U13 teams")

# Find matches
print("\n" + "="*80)
print("MATCHING TEAMS (fuzzy score >= 80)")
print("="*80)

matches = []
for m_team, m_club in modular_teams.items():
    best_score = 0
    best_match = None
    
    for db_team in db_teams:
        db_name = db_team['team_name']
        # Try matching on full name
        score = fuzz.token_sort_ratio(m_team.lower(), db_name.lower())
        
        # Also try matching club name if available
        if db_team.get('club_name'):
            club_score = fuzz.token_sort_ratio(m_club.lower(), db_team['club_name'].lower())
            score = max(score, club_score + 10)  # Boost for club match
        
        if score > best_score:
            best_score = score
            best_match = db_team
    
    if best_score >= 80:
        matches.append({
            'modular_team': m_team,
            'modular_club': m_club,
            'db_team': best_match['team_name'],
            'score': best_score
        })

# Sort by score
matches.sort(key=lambda x: -x['score'])

print(f"\nFound {len(matches)} matching teams:\n")
for m in matches[:30]:
    print(f"[{m['score']:3.0f}%] {m['modular_club']:<30} -> {m['db_team']}")

if len(matches) > 30:
    print(f"\n... and {len(matches) - 30} more")

# Show unmatched teams
print("\n" + "="*80)
print("TOP UNMATCHED MODULAR11 TEAMS (no match >= 80%)")
print("="*80)

matched_clubs = set(m['modular_club'] for m in matches)
unmatched = [(t, c) for t, c in modular_teams.items() if c not in matched_clubs]

# Count games per club
club_games = defaultdict(int)
with open('scrapers/modular11_scraper/output/modular11_u13.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        club_games[row.get('club_name', '')] += 1

unmatched_with_count = [(t, c, club_games.get(c, 0)) for t, c in unmatched]
unmatched_with_count.sort(key=lambda x: -x[2])

print(f"\nTop 20 unmatched clubs by game count:\n")
seen_clubs = set()
for team, club, games in unmatched_with_count[:40]:
    if club not in seen_clubs:
        print(f"  {games:3d} games | {club}")
        seen_clubs.add(club)
        if len(seen_clubs) >= 20:
            break

print(f"\n{len(set(c for _, c in unmatched))} unique clubs have no match")













