"""
Test TGS team creation to see if it's working.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from supabase import create_client
from src.models.tgs_matcher import TGSGameMatcher
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("❌ Missing environment variables")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get TGS provider ID
providers = supabase.table('providers').select('id').eq('code', 'tgs').single().execute()
provider_id = providers.data['id']
print(f"✅ TGS Provider ID: {provider_id}\n")

# Create matcher
matcher = TGSGameMatcher(supabase, provider_id=provider_id)

# Test with a team that doesn't exist (use a unique ID)
test_team_id = '999999999'  # Should not exist
test_team_name = 'Test Team Creation'
test_age_group = 'u13'
test_gender = 'Female'
test_club = 'Test Club'

print(f"Testing team creation with:")
print(f"  TGS ID: {test_team_id}")
print(f"  Team Name: {test_team_name}")
print(f"  Age Group: {test_age_group}")
print(f"  Gender: {test_gender}")
print(f"  Club: {test_club}\n")

try:
    result = matcher._match_team(
        provider_id=provider_id,
        provider_team_id=test_team_id,
        team_name=test_team_name,
        age_group=test_age_group,
        gender=test_gender,
        club_name=test_club
    )
    
    print(f"✅ Match result:")
    print(f"  Matched: {result.get('matched')}")
    print(f"  Team ID: {result.get('team_id')}")
    print(f"  Method: {result.get('method')}")
    print(f"  Confidence: {result.get('confidence')}")
    
    if result.get('matched'):
        print(f"\n✅ SUCCESS: Team was created!")
    else:
        print(f"\n❌ FAILED: Team was not created")
        print(f"   This explains why event 3951 import failed")
        
except Exception as e:
    print(f"\n❌ ERROR during team matching: {e}")
    import traceback
    traceback.print_exc()









