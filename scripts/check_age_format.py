#!/usr/bin/env python3
"""Check age group format differences"""
import csv
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

# Check what age_group format the database uses
result = supabase.table('teams').select('age_group', count='exact').eq('age_group', 'U13').execute()
print(f'Teams with age_group=U13: {result.count}')

result = supabase.table('teams').select('age_group', count='exact').eq('age_group', 'u13').execute()
print(f'Teams with age_group=u13: {result.count}')

# Check what Modular11 CSV uses
with open('scrapers/modular11_scraper/output/modular11_u13.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    row = next(reader)
    print(f'\nModular11 CSV age_group format: "{row.get("age_group")}"')
    print(f'Modular11 CSV gender format: "{row.get("gender")}"')
    print(f'Modular11 CSV team_name example: "{row.get("team_name")}"')
    print(f'Modular11 CSV club_name example: "{row.get("club_name")}"')

# Check what database teams look like for u13
print('\nSample u13 teams in DB:')
result = supabase.table('teams').select('team_name, age_group, gender').eq('age_group', 'u13').limit(10).execute()
for t in result.data:
    print(f'  "{t["team_name"]}" | age={t["age_group"]} | gender={t["gender"]}')

# Try to find a specific team
print('\nSearching for IdeaSport teams in DB:')
result = supabase.table('teams').select('team_name, age_group, gender').ilike('team_name', '%ideasport%').limit(10).execute()
for t in result.data:
    print(f'  "{t["team_name"]}" | age={t["age_group"]} | gender={t["gender"]}')













