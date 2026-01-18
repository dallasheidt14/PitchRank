"""Check match methods for TGS teams"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client
from collections import Counter

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# Get all TGS team aliases
result = supabase.table('team_alias_map').select(
    'match_method,review_status,created_at'
).eq('provider_id', tgs_provider_id).execute()

print("="*80)
print("TGS TEAM MATCH METHOD BREAKDOWN")
print("="*80)

# Count by match_method and review_status
counts = Counter((r['match_method'], r['review_status']) for r in result.data)

print(f"\nTotal TGS team aliases: {len(result.data)}")
print("\nBreakdown by match method:")
for (method, status), count in sorted(counts.items()):
    print(f"  {method:20s} ({status:10s}): {count:4d}")

# Check for direct_id matches
direct_id_count = sum(1 for r in result.data if r['match_method'] == 'direct_id')
print(f"\nDirect ID matches: {direct_id_count}")

# Check recent imports (last 2 hours)
from datetime import datetime, timedelta
recent_cutoff = (datetime.now() - timedelta(hours=2)).isoformat()

recent_aliases = [
    r for r in result.data 
    if r.get('created_at') and r['created_at'] >= recent_cutoff
]

print(f"\nRecent aliases (last 2 hours): {len(recent_aliases)}")
if recent_aliases:
    recent_counts = Counter((r['match_method'], r['review_status']) for r in recent_aliases)
    for (method, status), count in sorted(recent_counts.items()):
        print(f"  {method:20s} ({status:10s}): {count:4d}")

# Get latest build log
build_result = supabase.table('build_logs').select('*').order('started_at', desc=True).limit(1).execute()
if build_result.data:
    build = build_result.data[0]
    metrics = build.get('metrics', {})
    print("\n" + "="*80)
    print("LATEST BUILD LOG METRICS")
    print("="*80)
    print(f"Build ID: {build.get('build_id', 'N/A')}")
    print(f"Provider: {build.get('provider', 'N/A')}")
    print(f"Stage: {build.get('stage', 'N/A')}")
    print(f"\nTeam Matching:")
    print(f"  Teams matched: {metrics.get('teams_matched', 0)}")
    print(f"  Teams created: {metrics.get('teams_created', 0)}")
    print(f"  Fuzzy auto: {metrics.get('fuzzy_matches_auto', 0)}")
    print(f"  Fuzzy manual: {metrics.get('fuzzy_matches_manual', 0)}")
    print(f"  Fuzzy rejected: {metrics.get('fuzzy_matches_rejected', 0)}")

