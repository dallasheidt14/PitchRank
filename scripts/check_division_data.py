#!/usr/bin/env python3
"""Quick check of division info in games table."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

db = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Check competition field for HD/AD
print("Checking competition field in games...")
result = db.table('games').select('competition').limit(1000).execute()

hd_games = []
ad_games = []
other_games = []

for g in (result.data or []):
    comp = (g.get('competition') or '').upper()
    if ' HD' in comp or comp.endswith('HD') or 'HOMEGROWN' in comp:
        hd_games.append(g.get('competition'))
    elif ' AD' in comp or comp.endswith('AD') or 'ACADEMY' in comp:
        ad_games.append(g.get('competition'))
    else:
        other_games.append(g.get('competition'))

print(f"\nOf 1000 games sampled:")
print(f"  HD games: {len(hd_games)}")
print(f"  AD games: {len(ad_games)}")
print(f"  Other: {len(other_games)}")

if hd_games:
    print(f"\nSample HD competitions: {list(set(hd_games))[:5]}")
if ad_games:
    print(f"Sample AD competitions: {list(set(ad_games))[:5]}")
if other_games:
    print(f"Sample Other competitions: {list(set(other_games))[:5]}")

# Check what columns exist in games
print("\n\nChecking for raw_data column...")
try:
    result2 = db.table('games').select('raw_data').limit(1).execute()
    if result2.data and result2.data[0].get('raw_data'):
        print("raw_data EXISTS and has data")
        print(f"Sample: {result2.data[0]['raw_data']}")
    elif result2.data:
        print("raw_data column exists but is NULL")
    else:
        print("No games found")
except Exception as e:
    print(f"raw_data column check failed: {e}")


