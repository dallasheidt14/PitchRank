#!/usr/bin/env python3
"""Check teams with NULL last_scraped_at"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv('.env.local')

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').execute()
if not provider_result.data:
    print("Provider not found")
    sys.exit(1)
provider_id = provider_result.data[0]['id']

# Get teams with NULL last_scraped_at
print("Fetching teams with NULL last_scraped_at...")
all_teams = []
page = 0
page_size = 1000

while True:
    offset = page * page_size
    result = supabase.table('teams').select('team_id_master, team_name, last_scraped_at').eq(
        'provider_id', provider_id
    ).is_('last_scraped_at', 'null').range(offset, offset + page_size - 1).execute()
    
    if not result.data:
        break
    
    all_teams.extend(result.data)
    print(f"  Fetched {len(all_teams)} teams so far...")
    
    if len(result.data) < page_size:
        break
    
    page += 1

print(f"\n✅ Total teams with NULL last_scraped_at: {len(all_teams):,}")

# Also get total teams for comparison
total_result = supabase.table('teams').select('team_id_master', count='exact').eq('provider_id', provider_id).limit(1).execute()
total_teams = total_result.count if hasattr(total_result, 'count') else 0

# Count teams with non-null last_scraped_at
if total_teams > 0:
    teams_with_date = total_teams - len(all_teams)
    print(f"Total teams: {total_teams:,}")
    print(f"Teams with last_scraped_at set: {teams_with_date:,}")
    print(f"Teams with NULL last_scraped_at: {len(all_teams):,} ({len(all_teams)/total_teams*100:.1f}%)")



