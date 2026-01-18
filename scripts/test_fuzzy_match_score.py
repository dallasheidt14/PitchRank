#!/usr/bin/env python3
"""Test why fuzzy matching failed for Eastside FC ECNL B12"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Import the TGS matcher
from src.models.tgs_matcher import TGSGameMatcher

# Get TGS provider ID
tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_provider_id = tgs_provider.data[0]['id'] if tgs_provider.data else None

# Get target GotSport team
target_team_uuid = "148edffd-4319-4f21-8b2b-524ad82fb0d3"
target_team = supabase.table('teams').select('*').eq('team_id_master', target_team_uuid).execute()
target_team_data = target_team.data[0]

print("="*70)
print("TESTING FUZZY MATCH SCORE")
print("="*70)

print(f"\nTGS Team (from CSV):")
print(f"  Name: Eastside FC ECNL B12")
print(f"  Club: Eastside FC")
print(f"  Age Group: u14")
print(f"  Gender: Boys")

print(f"\nGotSport Team (existing):")
print(f"  Name: {target_team_data.get('team_name')}")
print(f"  Club: {target_team_data.get('club_name')}")
print(f"  Age Group: {target_team_data.get('age_group')}")
print(f"  Gender: {target_team_data.get('gender')}")

# Create TGS matcher
matcher = TGSGameMatcher(supabase, provider_id=tgs_provider_id)

# Prepare provider team dict (what TGS import would have)
provider_team = {
    'team_name': 'Eastside FC ECNL B12',
    'club_name': 'Eastside FC',
    'age_group': 'u14',
    'gender': 'Male'  # Normalized from 'Boys'
}

# Prepare candidate team dict (existing GotSport team)
candidate_team = {
    'team_name': target_team_data.get('team_name'),
    'club_name': target_team_data.get('club_name'),
    'age_group': target_team_data.get('age_group'),
    'gender': target_team_data.get('gender')
}

# Calculate match score
score = matcher._calculate_match_score(provider_team, candidate_team)

print(f"\n" + "="*70)
print("MATCH SCORE CALCULATION")
print("="*70)
print(f"\nScore: {score:.4f}")
print(f"TGS Fuzzy Threshold: {matcher.fuzzy_threshold}")
print(f"Auto-approve Threshold: {matcher.auto_approve_threshold}")
print(f"Review Threshold: {matcher.review_threshold}")

if score >= matcher.auto_approve_threshold:
    print(f"\n✅ Score >= {matcher.auto_approve_threshold} → Would auto-approve")
elif score >= matcher.fuzzy_threshold:
    if score >= matcher.review_threshold:
        print(f"\n⚠️ Score >= {matcher.review_threshold} → Would queue for review")
    else:
        print(f"\n⚠️ Score >= {matcher.fuzzy_threshold} but < {matcher.review_threshold} → Would reject")
else:
    print(f"\n❌ Score < {matcher.fuzzy_threshold} → Would reject (below threshold)")

# Test what the normalized names look like
print(f"\n" + "="*70)
print("NORMALIZED NAMES")
print("="*70)

provider_normalized = matcher._normalize_team_name('Eastside FC ECNL B12', 'Eastside FC')
candidate_normalized = matcher._normalize_team_name(target_team_data.get('team_name'), target_team_data.get('club_name'))

print(f"\nTGS Team Normalized: '{provider_normalized}'")
print(f"GotSport Team Normalized: '{candidate_normalized}'")

# Check age tokens
provider_tokens = matcher._extract_age_tokens(provider_normalized)
candidate_tokens = matcher._extract_age_tokens(candidate_normalized)

print(f"\nTGS Age Tokens: {provider_tokens}")
print(f"GotSport Age Tokens: {candidate_tokens}")
print(f"Overlap: {provider_tokens & candidate_tokens}")

# Check club name matching
provider_club = 'Eastside FC'.lower().strip()
candidate_club = (target_team_data.get('club_name') or '').lower().strip()
print(f"\nClub Match: '{provider_club}' == '{candidate_club}': {provider_club == candidate_club}")

print(f"\n" + "="*70)
print("CONCLUSION")
print("="*70)

if score < matcher.fuzzy_threshold:
    print(f"\n❌ Fuzzy matching FAILED because score ({score:.4f}) < threshold ({matcher.fuzzy_threshold})")
    print(f"   This caused the system to create a NEW team instead of matching.")
    print(f"\n   The TGS matcher behavior:")
    print(f"   1. Tries base matching (direct ID, alias, fuzzy)")
    print(f"   2. If no match found → Creates NEW team")
    print(f"   3. Creates alias for NEW team (not existing team)")
    print(f"\n   This is why there's no alias linking TGS 79561 to GotSport team.")
else:
    print(f"\n✅ Fuzzy matching SHOULD have worked (score: {score:.4f})")
    print(f"   But something else prevented the match.")







