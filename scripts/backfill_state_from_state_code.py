"""Backfill state (full name) from state_code for all teams"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
    exit(1)

supabase = create_client(supabase_url, supabase_key)

# State code to state name mapping
STATE_CODE_TO_NAME = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
}

def main():
    print("="*80)
    print("Backfilling state (full name) from state_code")
    print("="*80)
    print()
    
    # Find teams with state_code but no state
    print("Finding teams with state_code but no state...")
    teams_to_update = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('teams').select(
            'team_id_master, team_name, state_code, state'
        ).not_.is_('state_code', 'null').is_('state', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        for team in result.data:
            state_code = team.get('state_code')
            if state_code and state_code.upper() in STATE_CODE_TO_NAME:
                teams_to_update.append({
                    'team_id_master': team['team_id_master'],
                    'team_name': team['team_name'],
                    'state_code': state_code,
                    'state': STATE_CODE_TO_NAME[state_code.upper()]
                })
        
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    print(f"Found {len(teams_to_update)} teams to update")
    print()
    
    if not teams_to_update:
        print("No teams need updating!")
        return
    
    # Group by state_code for batch updates
    updates_by_state = defaultdict(list)
    for team in teams_to_update:
        updates_by_state[team['state_code']].append(team['team_id_master'])
    
    # Update in batches
    print("Updating teams...")
    batch_size = 100
    updated_count = 0
    error_count = 0
    
    for state_code, team_ids in updates_by_state.items():
        state_name = STATE_CODE_TO_NAME[state_code.upper()]
        
        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i:i + batch_size]
            try:
                result = supabase.table('teams').update({
                    'state': state_name
                }).in_('team_id_master', batch).execute()
                
                updated_count += len(batch)
                print(f"  Updated {updated_count}/{len(teams_to_update)} teams...")
                
            except Exception as e:
                print(f"Error updating batch: {e}")
                error_count += len(batch)
    
    print("\n" + "="*80)
    print("Update complete!")
    print(f"  Successfully updated: {updated_count}")
    print(f"  Errors: {error_count}")
    print()

if __name__ == '__main__':
    main()

