"""Check if the fuzzy match is correct"""
import sys
sys.path.append('.')
from src.models.tgs_matcher import TGSGameMatcher
from supabase import create_client
import os
from dotenv import load_dotenv
from pathlib import Path

env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
matcher = TGSGameMatcher(supabase)

provider_name = 'Internationals SC ECNL RL G08/07'
master_name = 'Internationals SC ECNL RL G08'

score = matcher._calculate_match_score({'team_name': provider_name}, {'team_name': master_name})

print(f"Provider: {provider_name}")
print(f"Master: {master_name}")
print(f"Match Score: {score}")

# Check league compatibility
provider_upper = provider_name.upper()
master_upper = master_name.upper()

provider_has_ecnl_rl = 'ECNL' in provider_upper and ('RL' in provider_upper or 'ECRL' in provider_upper)
master_has_ecnl_rl = 'ECNL' in master_upper and ('RL' in master_upper or 'ECRL' in master_upper)

print(f"\nProvider has ECNL RL: {provider_has_ecnl_rl}")
print(f"Master has ECNL RL: {master_has_ecnl_rl}")

if provider_has_ecnl_rl and master_has_ecnl_rl:
    print("\n✅ VALID MATCH: Both are ECNL RL")
elif score == 0.0:
    print("\n✅ CORRECTLY REJECTED: League mismatch prevented match")
else:
    print("\n⚠️  NEEDS REVIEW")









