#!/usr/bin/env python3
"""Create team_alias_map entries for existing GotSport teams that don't have them"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Get GotSport provider UUID
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']
print(f"GotSport provider_id: {provider_id}")

# Find all GotSport teams that don't have alias map entries
print("\nFinding GotSport teams without alias map entries...")

# Get all GotSport teams
teams_result = supabase.table('teams').select('team_id_master, provider_team_id, team_name').eq('provider_id', provider_id).not_.is_('provider_team_id', 'null').execute()

print(f"Found {len(teams_result.data)} GotSport teams")

# Check which ones don't have alias map entries
teams_without_aliases = []
for team in teams_result.data:
    provider_team_id = team['provider_team_id']
    if not provider_team_id:
        continue
    
    # Check if alias exists
    alias_check = supabase.table('team_alias_map').select('id').eq(
        'provider_id', provider_id
    ).eq('provider_team_id', str(provider_team_id)).execute()
    
    if not alias_check.data:
        teams_without_aliases.append(team)

print(f"Found {len(teams_without_aliases)} teams without alias map entries")

if not teams_without_aliases:
    print("✅ All teams already have alias map entries!")
    sys.exit(0)

# Create alias map entries
print(f"\nCreating alias map entries for {len(teams_without_aliases)} teams...")
created_count = 0
error_count = 0

for team in teams_without_aliases:
    try:
        alias_record = {
            'provider_id': provider_id,
            'provider_team_id': str(team['provider_team_id']),
            'team_id_master': team['team_id_master'],
            'match_method': 'direct_id',
            'match_confidence': 1.0,
            'review_status': 'approved',
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('team_alias_map').insert(alias_record).execute()
        created_count += 1
        
        if created_count % 100 == 0:
            print(f"  Created {created_count} alias entries...")
            
    except Exception as e:
        error_str = str(e).lower()
        if 'unique' not in error_str and 'duplicate' not in error_str:
            print(f"  Error creating alias for {team['team_name']}: {e}")
            error_count += 1

print(f"\n✅ Created {created_count} alias map entries")
if error_count > 0:
    print(f"⚠️  {error_count} errors encountered")








