"""Match teams without state_code to clubs that have state codes"""
import os
import sys
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

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

def normalize_club_name(name):
    """Normalize club name for matching"""
    if not name:
        return None
    # Remove common suffixes and normalize
    name = name.strip()
    # Remove common variations
    name = name.replace(' FC', '').replace(' F.C.', '').replace(' FC.', '')
    name = name.replace(' Soccer Club', '').replace(' SC', '').replace(' S.C.', '')
    return name.strip().upper()

def main(dry_run=False, auto_yes=False):
    print("="*80)
    print("Matching teams without state_code to clubs with state codes")
    if dry_run:
        print("DRY RUN MODE - No updates will be made")
    print("="*80)
    print()
    
    # Step 1: Get all teams without state_code
    print("Step 1: Fetching teams without state_code...")
    teams_no_state = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, state, state_code'
        ).is_('state_code', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        teams_no_state.extend(result.data)
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    print(f"Found {len(teams_no_state)} teams without state_code")
    print()
    
    # Step 2: Build a lookup of club_name -> state_code from teams that HAVE state_code
    print("Step 2: Building club name to state_code lookup...")
    club_state_lookup = defaultdict(set)  # club_name -> set of state_codes
    club_state_full = defaultdict(dict)  # club_name -> {state_code: count}
    
    offset = 0
    while True:
        result = supabase.table('teams').select(
            'club_name, state_code'
        ).not_.is_('state_code', 'null').not_.is_('club_name', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        for team in result.data:
            club_name = team.get('club_name')
            state_code = team.get('state_code')
            if club_name and state_code:
                normalized = normalize_club_name(club_name)
                if normalized:
                    club_state_lookup[normalized].add(state_code)
                    if normalized not in club_state_full:
                        club_state_full[normalized] = defaultdict(int)
                    club_state_full[normalized][state_code] += 1
        
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    print(f"Found {len(club_state_lookup)} unique clubs with state codes")
    print()
    
    # Step 3: Match teams without state_code to clubs
    print("Step 3: Matching teams to clubs...")
    matches = []
    no_club_name = []
    no_match = []
    multiple_states = []
    
    # Also build a lookup by exact club_name (not normalized) to catch multi-state clubs
    exact_club_states = defaultdict(set)
    offset = 0
    while True:
        result = supabase.table('teams').select(
            'club_name, state_code'
        ).not_.is_('state_code', 'null').not_.is_('club_name', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        for team in result.data:
            club_name = team.get('club_name')
            state_code = team.get('state_code')
            if club_name and state_code:
                exact_club_states[club_name].add(state_code)
        
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    for team in teams_no_state:
        team_id = team['team_id_master']
        team_name = team['team_name']
        club_name = team.get('club_name')
        
        if not club_name:
            no_club_name.append(team)
            continue
        
        # Special handling: Check if team name contains "Ventura" - this is Ventura County, CA
        # We need to handle this before normalization because "VC Fusion" might match "KC Fusion"
        is_ventura_county = 'ventura' in team_name.lower()
        
        normalized_club = normalize_club_name(club_name)
        if not normalized_club:
            no_club_name.append(team)
            continue
        
        # Special case: If team name has "Ventura", try to find Ventura County Fusion club with CA
        if is_ventura_county:
            # Look for clubs with "ventura" and "fusion" that have CA state code
            ventura_fusion_result = supabase.table('teams').select(
                'club_name, state_code'
            ).ilike('club_name', '%fusion%').ilike('club_name', '%ventura%').eq('state_code', 'CA').limit(1).execute()
            
            if ventura_fusion_result.data:
                # Found Ventura County Fusion with CA - use that
                matches.append({
                    'team_id_master': team_id,
                    'team_name': team_name,
                    'club_name': club_name,
                    'matched_state_code': 'CA',
                    'all_state_codes': ['CA'],
                    'confidence': 'single_state'
                })
                print(f"  Fixed: {team_name} → CA (Ventura County)")
                continue
        
        # Check if we have this club in our lookup
        if normalized_club not in club_state_lookup:
            no_match.append(team)
            continue
        
        # Also check exact club_name for multiple states (more accurate)
        exact_club_name = club_name.strip()
        exact_states = exact_club_states.get(exact_club_name, set())
        
        # Get the state codes for this club (normalized)
        state_codes = club_state_lookup[normalized_club]
        
        # If club has multiple state codes (either normalized or exact), exclude it
        all_states = state_codes | exact_states
        if len(all_states) > 1:
            multiple_states.append({
                'team': team,
                'state_codes': list(all_states),
                'selected': None
            })
            no_match.append(team)  # Exclude from matches
            continue
        
        # Single state_code - high confidence match
        state_code = list(state_codes)[0]
        
        # Additional safety check: If team name contains "Ventura" but matched to KS, force CA
        if is_ventura_county and state_code == 'KS':
            # This is Ventura County, CA - force CA
            state_code = 'CA'
            print(f"  Fixed: {team_name} → CA (was incorrectly matched to KS)")
        
        matches.append({
            'team_id_master': team_id,
            'team_name': team_name,
            'club_name': club_name,
            'matched_state_code': state_code,
            'all_state_codes': [state_code],
            'confidence': 'single_state'
        })
    
    print(f"  Matched (single state only): {len(matches)} teams")
    print(f"  No club name: {len(no_club_name)} teams")
    print(f"  No match found: {len(no_match)} teams")
    print(f"  Excluded (multiple states): {len(multiple_states)} teams")
    print()
    
    # Step 4: Show summary
    print("="*80)
    print("MATCH SUMMARY")
    print("="*80)
    print(f"Total teams without state_code: {len(teams_no_state)}")
    print(f"  ✓ Can be matched via club name: {len(matches)}")
    print(f"  ✗ No club name: {len(no_club_name)}")
    print(f"  ✗ Club not found in database: {len(no_match)}")
    print()
    
    # All matches are now single-state only (high confidence)
    print(f"Match confidence:")
    print(f"  High (single state): {len(matches)}")
    print(f"  Excluded (multiple states): {len(multiple_states)}")
    print()
    
    # Show sample matches
    print("Sample matches (first 20):")
    print("-" * 80)
    for i, match in enumerate(matches[:20], 1):
        print(f"{i:2d}. ✓ {match['team_name'][:40]:<40} | Club: {match['club_name'][:25]:<25} | → {match['matched_state_code']}")
    print()
    
    # Show teams with no club name
    if no_club_name:
        print("Teams with no club name (first 10):")
        print("-" * 80)
        for i, team in enumerate(no_club_name[:10], 1):
            print(f"{i:2d}. {team['team_name'][:60]}")
        print()
    
    # Show teams with no match
    if no_match:
        print("Teams with club name but no match (first 10):")
        print("-" * 80)
        for i, team in enumerate(no_match[:10], 1):
            print(f"{i:2d}. {team['team_name'][:40]:<40} | Club: {team.get('club_name', 'N/A')[:30]}")
        print()
    
    # Step 5: Export matches to CSV for review
    if matches:
        output_dir = Path('data/exports')
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f'state_code_matches_{timestamp}.csv'
        
        print("="*80)
        print("Exporting matches to CSV for review...")
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'team_id_master',
                'team_name',
                'club_name',
                'age_group',
                'gender',
                'matched_state_code',
                'confidence',
                'all_state_codes',
                'state_code_count',
                'review_notes'
            ])
            writer.writeheader()
            
            for match in matches:
                writer.writerow({
                    'team_id_master': match['team_id_master'],
                    'team_name': match['team_name'],
                    'club_name': match['club_name'],
                    'age_group': '',  # Will be filled from team data
                    'gender': '',  # Will be filled from team data
                    'matched_state_code': match['matched_state_code'],
                    'confidence': match['confidence'],
                    'all_state_codes': ', '.join(match['all_state_codes']),
                    'state_code_count': len(match['all_state_codes']),
                    'review_notes': ''
                })
        
        # Fill in age_group and gender from team data
        print("Enriching CSV with team details...")
        team_ids = [m['team_id_master'] for m in matches]
        team_details = {}
        offset = 0
        while offset < len(team_ids):
            batch = team_ids[offset:offset + 100]
            result = supabase.table('teams').select(
                'team_id_master, age_group, gender'
            ).in_('team_id_master', batch).execute()
            
            for team in result.data:
                team_details[team['team_id_master']] = {
                    'age_group': team.get('age_group', ''),
                    'gender': team.get('gender', '')
                }
            offset += 100
        
        # Update CSV with team details
        rows = []
        with open(output_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                team_id = row['team_id_master']
                if team_id in team_details:
                    row['age_group'] = team_details[team_id]['age_group']
                    row['gender'] = team_details[team_id]['gender']
                rows.append(row)
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'team_id_master',
                'team_name',
                'club_name',
                'age_group',
                'gender',
                'matched_state_code',
                'confidence',
                'all_state_codes',
                'state_code_count',
                'review_notes'
            ])
            writer.writeheader()
            writer.writerows(rows)
        
        print(f"✓ Exported {len(matches)} matches to: {output_file}")
        print()
        
        # Also export unmatched teams
        if no_match:
            unmatched_file = output_dir / f'state_code_unmatched_{timestamp}.csv'
            with open(unmatched_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'team_id_master',
                    'team_name',
                    'club_name',
                    'age_group',
                    'gender',
                    'notes'
                ])
                writer.writeheader()
                for team in no_match:
                    writer.writerow({
                        'team_id_master': team['team_id_master'],
                        'team_name': team['team_name'],
                        'club_name': team.get('club_name', ''),
                        'age_group': team.get('age_group', ''),
                        'gender': team.get('gender', ''),
                        'notes': 'Club not found in database or club has no state_code'
                    })
            print(f"✓ Exported {len(no_match)} unmatched teams to: {unmatched_file}")
            print()
    
    # Step 6: Ask if user wants to update
    if matches:
        print("="*80)
        if dry_run:
            print(f"DRY RUN: Would update {len(matches)} teams with matched state codes")
            print("Run without --dry-run to apply updates")
        else:
            if auto_yes:
                response = 'yes'
            else:
                response = input(f"Update {len(matches)} teams with matched state codes? (yes/no): ").strip().lower()
            
            if response == 'yes':
                print("\nUpdating teams...")
                updated_count = 0
                error_count = 0
                
                # Group by state_code for batch updates
                updates_by_state = defaultdict(list)
                for match in matches:
                    updates_by_state[match['matched_state_code']].append(match['team_id_master'])
                
                # Update in batches
                batch_size = 100
                for state_code, team_ids in updates_by_state.items():
                    # Get full state name from state code
                    state_name = STATE_CODE_TO_NAME.get(state_code.upper())
                    
                    for i in range(0, len(team_ids), batch_size):
                        batch = team_ids[i:i + batch_size]
                        try:
                            # Update all teams in this batch with both state_code and state
                            update_data = {
                                'state_code': state_code
                            }
                            if state_name:
                                update_data['state'] = state_name
                            
                            result = supabase.table('teams').update(update_data).in_('team_id_master', batch).execute()
                            
                            updated_count += len(batch)
                            print(f"  Updated {updated_count}/{len(matches)} teams...")
                            
                        except Exception as e:
                            print(f"Error updating batch: {e}")
                            error_count += len(batch)
                
                print("\n" + "="*80)
                print("Update complete!")
                print(f"  Successfully updated: {updated_count}")
                print(f"  Errors: {error_count}")
            else:
                print("Update cancelled.")
    else:
        print("No matches found to update.")
    
    print("\n" + "="*80)
    print("Analysis complete!")

if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    auto_yes = '--yes' in sys.argv or '-y' in sys.argv
    
    main(dry_run=dry_run, auto_yes=auto_yes)

