"""Update teams with state information from CSV file"""
import os
import csv
import sys
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

def update_teams_from_csv(csv_path: str, auto_yes: bool = False):
    """Update teams with state information from CSV"""
    
    csv_file = Path('data/exports') / csv_path if not Path(csv_path).is_absolute() else Path(csv_path)
    
    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        print(f"Looking for file at: {csv_file.absolute()}")
        return
    
    print(f"Reading teams from: {csv_file}")
    
    updates = []
    skipped = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            team_id = row.get('team_id_master', '').strip()
            state = row.get('state', '').strip()
            state_code = row.get('state_code', '').strip()
            
            if not team_id:
                skipped.append({'row': row, 'reason': 'Missing team_id_master'})
                continue
            
            # Skip rows where state is still empty
            if not state and not state_code:
                skipped.append({'row': row, 'reason': 'State fields empty'})
                continue
            
            # Validate state_code is 2 characters if provided
            if state_code and len(state_code) != 2:
                print(f"Warning: Invalid state_code '{state_code}' for team {team_id}, skipping...")
                skipped.append({'row': row, 'reason': f'Invalid state_code: {state_code}'})
                continue
            
            updates.append({
                'team_id_master': team_id,
                'state': state if state else None,
                'state_code': state_code.upper() if state_code else None,
                'team_name': row.get('team_name', '')
            })
    
    print(f"\nFound {len(updates)} teams to update")
    print(f"Skipped {len(skipped)} rows (empty or invalid)")
    
    if not updates:
        print("No teams to update. Exiting.")
        return
    
    # Show preview
    print("\nPreview of updates (first 10):")
    print("-" * 80)
    for i, update in enumerate(updates[:10], 1):
        print(f"{i:2d}. {update['team_name'][:50]:<50} | State: {update['state'] or 'N/A':<20} | Code: {update['state_code'] or 'N/A'}")
    
    if len(updates) > 10:
        print(f"... and {len(updates) - 10} more")
    
    # Confirm before updating
    print("\n" + "="*80)
    if not auto_yes:
        response = input(f"Update {len(updates)} teams in the database? (yes/no): ").strip().lower()
        
        if response != 'yes':
            print("Update cancelled.")
            return
    else:
        print(f"Auto-confirming: Updating {len(updates)} teams in the database...")
    
    # Update teams in batches
    print("\nUpdating teams...")
    batch_size = 100
    updated_count = 0
    error_count = 0
    
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        
        for update in batch:
            try:
                # Update the team
                result = supabase.table('teams').update({
                    'state': update['state'],
                    'state_code': update['state_code']
                }).eq('team_id_master', update['team_id_master']).execute()
                
                if result.data:
                    updated_count += 1
                else:
                    print(f"Warning: No team found with ID {update['team_id_master']}")
                    error_count += 1
                    
            except Exception as e:
                print(f"Error updating team {update['team_id_master']}: {e}")
                error_count += 1
        
        print(f"  Processed {min(i + batch_size, len(updates))}/{len(updates)} teams...")
    
    print("\n" + "="*80)
    print(f"Update complete!")
    print(f"  Successfully updated: {updated_count}")
    print(f"  Errors: {error_count}")
    
    if skipped:
        print(f"\nSkipped rows: {len(skipped)}")
        print("Reasons:")
        reasons = {}
        for skip in skipped:
            reason = skip['reason']
            reasons[reason] = reasons.get(reason, 0) + 1
        for reason, count in reasons.items():
            print(f"  - {reason}: {count}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/update_teams_state.py <csv_filename> [--yes]")
        print("\nExample:")
        print("  python scripts/update_teams_state.py teams_no_state_20250120_120000.csv")
        print("  python scripts/update_teams_state.py teams_no_state_20250120_120000.csv --yes")
        print("\nThe CSV file should be in the data/exports/ directory")
        exit(1)
    
    csv_filename = sys.argv[1]
    auto_yes = '--yes' in sys.argv or '-y' in sys.argv
    update_teams_from_csv(csv_filename, auto_yes=auto_yes)












