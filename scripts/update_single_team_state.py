"""Update a single team's state code"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

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

def update_team_state(team_id: str, state_code: str):
    """Update a team's state_code and state"""
    state_name = STATE_CODE_TO_NAME.get(state_code.upper())
    
    if not state_name:
        print(f"Error: Invalid state code '{state_code}'")
        return False
    
    # First, get the team to show current state
    result = supabase.table('teams').select('team_id_master, team_name, state_code, state').eq('team_id_master', team_id).single().execute()
    
    if not result.data:
        print(f"Error: Team with ID {team_id} not found")
        return False
    
    team = result.data
    print(f"Current state:")
    print(f"  Team: {team['team_name']}")
    print(f"  State Code: {team.get('state_code', 'NULL')}")
    print(f"  State: {team.get('state', 'NULL')}")
    print()
    
    # Update the team
    update_result = supabase.table('teams').update({
        'state_code': state_code.upper(),
        'state': state_name
    }).eq('team_id_master', team_id).execute()
    
    if update_result.data:
        print(f"✅ Successfully updated team to:")
        print(f"  State Code: {state_code.upper()}")
        print(f"  State: {state_name}")
        return True
    else:
        print("Error: Update failed")
        return False

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python scripts/update_single_team_state.py <team_id> <state_code>")
        print("Example: python scripts/update_single_team_state.py a2126cb2-409e-4dce-896f-8928cdfea485 AZ")
        exit(1)
    
    team_id = sys.argv[1]
    state_code = sys.argv[2]
    
    update_team_state(team_id, state_code)

