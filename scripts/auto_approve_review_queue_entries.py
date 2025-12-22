#!/usr/bin/env python3
"""
Auto-approve review queue entries that should have been created as teams.

These entries were likely created when team creation failed or when the old
code path was used. Since they don't have aliases, we should:
1. Create the teams if they don't exist
2. Create aliases for them
3. Approve the review queue entries
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MODULAR11_PROVIDER_CODE = 'modular11'

def build_aliased_provider_team_id(base_id, age_group, division):
    """Build aliased provider_team_id format"""
    if not base_id:
        return ""
    
    aliased_id = str(base_id).strip()
    suffix_parts = []
    
    if age_group:
        age_normalized = str(age_group).strip().upper()
        if age_normalized and not age_normalized.startswith('U'):
            age_normalized = f"U{age_normalized}"
        if age_normalized:
            suffix_parts.append(age_normalized)
    
    if division and str(division).strip().upper() in ('HD', 'AD'):
        suffix_parts.append(str(division).strip().upper())
    
    if suffix_parts:
        aliased_id = f"{aliased_id}_{'_'.join(suffix_parts)}"
    
    return aliased_id

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    db = create_client(supabase_url, supabase_key)
    
    print("=" * 80)
    print("AUTO-APPROVE REVIEW QUEUE ENTRIES")
    print("=" * 80)
    
    # Get all pending entries
    entries_result = db.table('team_match_review_queue').select('*').eq(
        'provider_id', MODULAR11_PROVIDER_CODE
    ).eq('status', 'pending').execute()
    
    entries = entries_result.data or []
    print(f"\nFound {len(entries)} pending entries")
    
    if not entries:
        print("\n✅ No entries to process!")
        return
    
    created_teams = 0
    created_aliases = 0
    approved_entries = 0
    errors = []
    
    for entry in entries:
        provider_team_id = entry.get('provider_team_id')
        provider_team_name = entry.get('provider_team_name', 'Unknown')
        match_details = entry.get('match_details', {})
        age_group = match_details.get('age_group', '')
        gender = match_details.get('gender', 'M')
        division = match_details.get('division')
        
        if not age_group:
            # Try to extract from name
            if 'U13' in provider_team_name.upper():
                age_group = 'U13'
            elif 'U14' in provider_team_name.upper():
                age_group = 'U14'
            elif 'U15' in provider_team_name.upper():
                age_group = 'U15'
            elif 'U16' in provider_team_name.upper():
                age_group = 'U16'
            elif 'U17' in provider_team_name.upper():
                age_group = 'U17'
        
        if not division:
            # Try to extract from name
            if provider_team_name.upper().endswith(' AD'):
                division = 'AD'
            elif provider_team_name.upper().endswith(' HD'):
                division = 'HD'
        
        # Normalize
        age_group_normalized = age_group.lower() if age_group else None
        gender_normalized = 'Male' if gender.upper() in ('M', 'MALE', 'BOYS') else 'Female'
        
        # Clean team name
        clean_team_name = provider_team_name
        if clean_team_name.upper().endswith(' HD') or clean_team_name.upper().endswith(' AD'):
            clean_team_name = clean_team_name[:-3].strip()
        
        # Build aliased provider_team_id
        aliased_provider_team_id = build_aliased_provider_team_id(
            provider_team_id, age_group, division
        )
        
        if not aliased_provider_team_id:
            errors.append(f"{provider_team_name}: Could not build aliased provider_team_id")
            continue
        
        try:
            # Check if team already exists
            existing_team = db.table('teams').select('team_id_master').eq(
                'provider_id', MODULAR11_PROVIDER_ID
            ).eq('provider_team_id', aliased_provider_team_id).execute()
            
            if existing_team.data:
                team_id_master = existing_team.data[0]['team_id_master']
                print(f"✅ Team exists: {clean_team_name} ({aliased_provider_team_id})")
            else:
                # Create team
                team_id_master = str(uuid.uuid4())
                team_data = {
                    'team_id_master': team_id_master,
                    'team_name': clean_team_name,
                    'club_name': clean_team_name,
                    'age_group': age_group_normalized,
                    'gender': gender_normalized,
                    'provider_id': MODULAR11_PROVIDER_ID,
                    'provider_team_id': aliased_provider_team_id,
                    'created_at': datetime.utcnow().isoformat() + 'Z'
                }
                
                db.table('teams').insert(team_data).execute()
                created_teams += 1
                print(f"✅ Created team: {clean_team_name} ({aliased_provider_team_id})")
            
            # Check if alias exists
            existing_alias = db.table('team_alias_map').select('id').eq(
                'provider_id', MODULAR11_PROVIDER_ID
            ).eq('provider_team_id', aliased_provider_team_id).execute()
            
            if not existing_alias.data:
                # Create alias
                alias_data = {
                    'provider_id': MODULAR11_PROVIDER_ID,
                    'provider_team_id': aliased_provider_team_id,
                    'team_id_master': team_id_master,
                    'match_method': 'import',
                    'match_confidence': 1.0,
                    'review_status': 'approved',
                    'division': division,
                    'created_at': datetime.utcnow().isoformat() + 'Z'
                }
                
                db.table('team_alias_map').insert(alias_data).execute()
                created_aliases += 1
                print(f"  ✅ Created alias: {aliased_provider_team_id} → {team_id_master}")
            
            # Approve review queue entry
            db.table('team_match_review_queue').update({
                'status': 'approved'
            }).eq('id', entry['id']).execute()
            approved_entries += 1
            
        except Exception as e:
            error_msg = f"{provider_team_name}: {str(e)}"
            errors.append(error_msg)
            print(f"❌ Error: {error_msg}")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Teams created: {created_teams}")
    print(f"Aliases created: {created_aliases}")
    print(f"Entries approved: {approved_entries}")
    if errors:
        print(f"\nErrors: {len(errors)}")
        for error in errors[:10]:
            print(f"  - {error}")

if __name__ == '__main__':
    main()

