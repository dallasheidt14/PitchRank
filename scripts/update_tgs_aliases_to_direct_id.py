#!/usr/bin/env python3
"""Update existing TGS team aliases to use direct_id match_method

This script updates TGS team aliases that have provider_team_id values
to use match_method='direct_id' instead of 'import' or 'fuzzy_auto'.
This ensures they're treated as direct matches (Tier 1) during game imports,
just like GotSport and Modular11 teams.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get TGS provider UUID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

print("="*60)
print("Update TGS Aliases to direct_id Match Method")
print("="*60)

# Find all TGS aliases that have provider_team_id but aren't direct_id
print("\nFinding TGS aliases to update...")

result = supabase.table('team_alias_map').select(
    'id,provider_team_id,match_method,review_status,team_id_master'
).eq('provider_id', tgs_provider_id).eq(
    'review_status', 'approved'
).not_.is_('provider_team_id', 'null').execute()

print(f"Found {len(result.data)} approved TGS aliases with provider_team_id")

# Filter to those that aren't already direct_id
aliases_to_update = [
    r for r in result.data 
    if r['match_method'] != 'direct_id' and r.get('provider_team_id')
]

print(f"Found {len(aliases_to_update)} aliases to update to direct_id")

if not aliases_to_update:
    print("\n✅ All TGS aliases already use direct_id match_method!")
    sys.exit(0)

# Show breakdown by current match_method
from collections import Counter
current_methods = Counter(r['match_method'] for r in aliases_to_update)
print("\nCurrent match_method breakdown:")
for method, count in sorted(current_methods.items()):
    print(f"  {method:20s}: {count:4d}")

# Ask for confirmation
print(f"\n⚠️  This will update {len(aliases_to_update)} aliases to match_method='direct_id'")
response = input("Continue? (yes/no): ").strip().lower()

if response not in ('yes', 'y'):
    print("Cancelled.")
    sys.exit(0)

# Update aliases
print(f"\nUpdating {len(aliases_to_update)} aliases...")
updated_count = 0
error_count = 0

for alias in aliases_to_update:
    try:
        supabase.table('team_alias_map').update({
            'match_method': 'direct_id',
            'match_confidence': 1.0  # Direct ID matches have perfect confidence
        }).eq('id', alias['id']).execute()
        
        updated_count += 1
        
        if updated_count % 100 == 0:
            print(f"  Updated {updated_count}/{len(aliases_to_update)}...")
            
    except Exception as e:
        error_str = str(e).lower()
        if 'unique' not in error_str and 'duplicate' not in error_str:
            print(f"  Error updating alias {alias['id']}: {e}")
            error_count += 1

print(f"\n✅ Updated {updated_count} aliases to direct_id")
if error_count > 0:
    print(f"⚠️  {error_count} errors encountered")

# Verify results
print("\nVerifying updates...")
verify_result = supabase.table('team_alias_map').select(
    'match_method'
).eq('provider_id', tgs_provider_id).eq(
    'review_status', 'approved'
).not_.is_('provider_team_id', 'null').execute()

final_methods = Counter(r['match_method'] for r in verify_result.data)
print("\nFinal match_method breakdown:")
for method, count in sorted(final_methods.items()):
    print(f"  {method:20s}: {count:4d}")

direct_id_count = final_methods.get('direct_id', 0)
total_count = len(verify_result.data)
print(f"\n✅ {direct_id_count}/{total_count} ({direct_id_count/total_count*100:.1f}%) aliases now use direct_id")

