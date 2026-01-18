"""Export teams with no state to CSV for manual state entry"""
import os
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

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

print("Exporting teams with no state information...\n")

# Fetch all teams with no state (both state and state_code are NULL)
all_teams = []
page_size = 1000
offset = 0

while True:
    result = supabase.table('teams').select(
        'team_id_master, team_name, club_name, age_group, gender, state, state_code, provider_team_id'
    ).is_('state', 'null').is_('state_code', 'null').range(offset, offset + page_size - 1).execute()
    
    if not result.data:
        break
    
    all_teams.extend(result.data)
    offset += page_size
    
    if len(result.data) < page_size:
        break

print(f"Found {len(all_teams)} teams with no state information")

# Create output directory if it doesn't exist
output_dir = Path('data/exports')
output_dir.mkdir(parents=True, exist_ok=True)

# Generate filename with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = output_dir / f'teams_no_state_{timestamp}.csv'

# Write to CSV
with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'team_id_master',
        'team_name',
        'club_name',
        'age_group',
        'gender',
        'state',  # User will fill this in
        'state_code',  # User will fill this in (2-letter code)
        'provider_team_id',
        'notes'  # Optional column for user notes
    ])
    
    writer.writeheader()
    
    for team in all_teams:
        writer.writerow({
            'team_id_master': team.get('team_id_master', ''),
            'team_name': team.get('team_name', ''),
            'club_name': team.get('club_name', ''),
            'age_group': team.get('age_group', ''),
            'gender': team.get('gender', ''),
            'state': '',  # Empty for user to fill
            'state_code': '',  # Empty for user to fill
            'provider_team_id': team.get('provider_team_id', ''),
            'notes': ''  # Optional
        })

print(f"\nExported {len(all_teams)} teams to: {output_file}")
print("\nPlease fill in the 'state' and 'state_code' columns:")
print("  - state: Full state name (e.g., 'North Carolina', 'South Carolina')")
print("  - state_code: 2-letter state code (e.g., 'NC', 'SC')")
print("  - notes: Optional notes for your reference")
print(f"\nAfter filling in the states, run: python scripts/update_teams_state.py {output_file.name}")












