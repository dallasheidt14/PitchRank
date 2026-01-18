"""
Analyze why event 3951 teams weren't matched - check if TGS IDs exist in alias map.
"""
import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from collections import defaultdict

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

# Get TGS provider ID
providers = supabase.table('providers').select('id, code').eq('code', 'tgs').execute()
if not providers.data:
    print("❌ TGS provider not found")
    sys.exit(1)

provider_id = providers.data[0]['id']
print(f"✅ Found TGS provider: {provider_id}")

# Read the scraped CSV
csv_file = Path('data/raw/tgs/tgs_events_3951_3951_2025-12-12T17-00-08-071039+00-00.csv')
if not csv_file.exists():
    print(f"❌ CSV file not found: {csv_file}")
    sys.exit(1)

print(f"\n📊 Reading CSV: {csv_file}")

# Extract unique team IDs from CSV
team_ids = set()
opponent_ids = set()
teams_info = {}

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        
        if team_id:
            team_ids.add(team_id)
            if team_id not in teams_info:
                teams_info[team_id] = {
                    'team_name': row.get('team_name', ''),
                    'club_name': row.get('club_name', ''),
                    'age_year': row.get('age_year', ''),
                    'gender': row.get('gender', '')
                }
        
        if opponent_id:
            opponent_ids.add(opponent_id)
            if opponent_id not in teams_info:
                teams_info[opponent_id] = {
                    'team_name': row.get('opponent_name', ''),
                    'club_name': row.get('opponent_club_name', ''),
                    'age_year': row.get('age_year', ''),  # Same age for both teams in a game
                    'gender': row.get('gender', '')
                }

all_ids = team_ids | opponent_ids
print(f"\n📈 Found {len(all_ids)} unique TGS team IDs in CSV")
print(f"   Team IDs: {len(team_ids)}")
print(f"   Opponent IDs: {len(opponent_ids)}")

# Check which ones exist in team_alias_map
print(f"\n🔍 Checking which TGS IDs exist in team_alias_map...")

# Query in batches (Supabase has limits)
ids_list = list(all_ids)
batch_size = 100
found_ids = set()
missing_ids = set()

for i in range(0, len(ids_list), batch_size):
    batch = ids_list[i:i+batch_size]
    
    result = supabase.table('team_alias_map').select(
        'provider_team_id, match_method, team_id_master'
    ).eq('provider_id', provider_id).in_(
        'provider_team_id', batch
    ).execute()
    
    found_in_batch = set()
    for entry in result.data:
        found_in_batch.add(entry['provider_team_id'])
        found_ids.add(entry['provider_team_id'])
    
    missing_in_batch = set(batch) - found_in_batch
    missing_ids.update(missing_in_batch)

print(f"\n✅ Found in team_alias_map: {len(found_ids)} ({len(found_ids)/len(all_ids)*100:.1f}%)")
print(f"❌ Missing from team_alias_map: {len(missing_ids)} ({len(missing_ids)/len(all_ids)*100:.1f}%)")

# Show sample missing IDs
if missing_ids:
    print(f"\n⚠️  Sample missing TGS IDs:")
    for tgs_id in list(missing_ids)[:10]:
        info = teams_info.get(tgs_id, {})
        print(f"   - TGS ID: {tgs_id} - {info.get('team_name', 'N/A')} ({info.get('age_year', 'N/A')}, {info.get('gender', 'N/A')})")

# Check match methods for found IDs
if found_ids:
    print(f"\n📊 Match methods for found IDs:")
    match_methods = defaultdict(int)
    
    for i in range(0, len(list(found_ids)), batch_size):
        batch = list(found_ids)[i:i+batch_size]
        result = supabase.table('team_alias_map').select(
            'provider_team_id, match_method'
        ).eq('provider_id', provider_id).in_(
            'provider_team_id', batch
        ).execute()
        
        for entry in result.data:
            match_methods[entry['match_method']] += 1
    
    for method, count in match_methods.items():
        print(f"   - {method}: {count}")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Total unique TGS IDs in event 3951: {len(all_ids)}")
print(f"IDs found in team_alias_map: {len(found_ids)}")
print(f"IDs missing from team_alias_map: {len(missing_ids)}")

if len(found_ids) > 0:
    print(f"\n✅ {len(found_ids)} teams should have been direct matched!")
else:
    print(f"\n❌ No teams from event 3951 exist in our database yet")









