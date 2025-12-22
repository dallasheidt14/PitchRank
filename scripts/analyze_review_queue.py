#!/usr/bin/env python3
"""Analyze Modular11 review queue entries to understand why they're there"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MODULAR11_PROVIDER_CODE = 'modular11'

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    db = create_client(supabase_url, supabase_key)
    
    print("=" * 80)
    print("MODULAR11 REVIEW QUEUE ANALYSIS")
    print("=" * 80)
    
    # Get all pending review queue entries
    print("\nFetching review queue entries...")
    queue_result = db.table('team_match_review_queue').select('*').eq(
        'provider_id', MODULAR11_PROVIDER_CODE
    ).eq('status', 'pending').order('created_at', desc=True).execute()
    
    entries = queue_result.data or []
    print(f"Found {len(entries)} pending entries")
    
    if not entries:
        print("\n✅ No entries in review queue!")
        return
    
    # Check if these entries have aliases (they shouldn't be in queue if they do)
    print("\nChecking if entries already have aliases...")
    entries_with_aliases = []
    entries_without_aliases = []
    
    for entry in entries:
        provider_team_id = entry.get('provider_team_id')
        if not provider_team_id:
            entries_without_aliases.append(entry)
            continue
        
        # Check if alias exists
        alias_result = db.table('team_alias_map').select('id').eq(
            'provider_id', MODULAR11_PROVIDER_ID
        ).eq('provider_team_id', provider_team_id).execute()
        
        if alias_result.data:
            entries_with_aliases.append(entry)
        else:
            entries_without_aliases.append(entry)
    
    print(f"  ✅ Entries WITH aliases (should be removed): {len(entries_with_aliases)}")
    print(f"  ⚠️  Entries WITHOUT aliases (legitimate): {len(entries_without_aliases)}")
    
    if entries_with_aliases:
        print("\n" + "=" * 80)
        print("ENTRIES THAT SHOULD BE REMOVED (have aliases)")
        print("=" * 80)
        print("\nThese entries have aliases and shouldn't be in the review queue.")
        print("They were likely added before the fix or during a failed import.\n")
        
        for entry in entries_with_aliases[:10]:
            print(f"  - {entry.get('provider_team_name', 'Unknown')}")
            print(f"    provider_team_id: {entry.get('provider_team_id')}")
            print(f"    Created: {entry.get('created_at', 'unknown')[:10]}")
            
            # Get the alias
            alias_result = db.table('team_alias_map').select('team_id_master, match_method').eq(
                'provider_id', MODULAR11_PROVIDER_ID
            ).eq('provider_team_id', entry.get('provider_team_id')).single().execute()
            
            if alias_result.data:
                print(f"    ✅ Has alias -> team_id_master: {alias_result.data['team_id_master'][:8]}...")
                print(f"       Match method: {alias_result.data.get('match_method')}")
            print()
    
    if entries_without_aliases:
        print("\n" + "=" * 80)
        print("LEGITIMATE ENTRIES (no aliases - need manual review)")
        print("=" * 80)
        print("\nThese entries don't have aliases and legitimately need review.\n")
        
        # Group by reason
        by_reason = defaultdict(list)
        for entry in entries_without_aliases:
            details = entry.get('match_details') or {}
            suggested_id = entry.get('suggested_master_team_id')
            confidence = entry.get('confidence_score', 0)
            
            if suggested_id:
                reason = f"Has suggestion (confidence: {confidence:.2f})"
            else:
                reason = "No suggestion - needs manual creation"
            
            by_reason[reason].append(entry)
        
        for reason, entries_list in sorted(by_reason.items()):
            print(f"\n{reason}: {len(entries_list)} entries")
            for entry in entries_list[:5]:
                print(f"  - {entry.get('provider_team_name', 'Unknown')}")
                print(f"    provider_team_id: {entry.get('provider_team_id')}")
                details = entry.get('match_details') or {}
                print(f"    Age: {details.get('age_group', 'N/A')}, Division: {details.get('division', 'N/A')}")
                print(f"    Created: {entry.get('created_at', 'unknown')[:10]}")
    
    # Check when entries were created
    print("\n" + "=" * 80)
    print("TIMELINE ANALYSIS")
    print("=" * 80)
    
    from datetime import datetime, timedelta
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    
    today_count = 0
    yesterday_count = 0
    week_ago_count = 0
    older_count = 0
    
    for entry in entries:
        created_str = entry.get('created_at', '')
        if not created_str:
            older_count += 1
            continue
        
        try:
            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00')).date()
            if created_date == today:
                today_count += 1
            elif created_date == yesterday:
                yesterday_count += 1
            elif created_date >= week_ago:
                week_ago_count += 1
            else:
                older_count += 1
        except:
            older_count += 1
    
    print(f"\nCreated today: {today_count}")
    print(f"Created yesterday: {yesterday_count}")
    print(f"Created this week: {week_ago_count}")
    print(f"Older than a week: {older_count}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 80)
    
    if entries_with_aliases:
        print(f"\n⚠️  {len(entries_with_aliases)} entries have aliases and should be auto-approved")
        print("   Recommendation: Run cleanup script to approve these entries")
    
    if entries_without_aliases:
        print(f"\n✅ {len(entries_without_aliases)} entries legitimately need review")
        print("   These are teams that couldn't be matched/created automatically")
        print("   Recommendation: Review manually in dashboard or create teams")
    
    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()

