"""Check the 2 fuzzy matches in detail"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

print("="*80)
print("CHECKING 2 FUZZY MATCHES IN DETAIL")
print("="*80)

# Team 1: Sporting CA USA ECNL RL S.Cal G09
print("\n" + "="*80)
print("TEAM 1: Sporting CA USA ECNL RL S.Cal G09")
print("="*80)
print("TGS Team ID: 95275")
print("Matched to: Sporting California Perris G09 (ID: 520930)")

provider_name = "Sporting CA USA ECNL RL S.Cal G09"
master_name = "Sporting California Perris G09"

provider_upper = provider_name.upper()
master_upper = master_name.upper()

print(f"\nProvider: {provider_name}")
print(f"  Has ECNL: {'ECNL' in provider_upper}")
print(f"  Has RL: {'RL' in provider_upper}")
print(f"  Has ECRL: {'ECRL' in provider_upper}")
print(f"  League Type: {'ECNL RL' if ('ECNL' in provider_upper and 'RL' in provider_upper) else ('ECNL' if 'ECNL' in provider_upper else 'Unknown')}")

print(f"\nMaster: {master_name}")
print(f"  Has ECNL: {'ECNL' in master_upper}")
print(f"  Has RL: {'RL' in master_upper}")
print(f"  Has ECRL: {'ECRL' in master_upper}")
print(f"  League Type: {'ECNL RL' if ('ECNL' in master_upper and 'RL' in master_upper) else ('ECNL' if 'ECNL' in master_upper else 'Unknown')}")

# Check if this is a valid match
provider_has_ecnl_rl = 'ECNL' in provider_upper and ('RL' in provider_upper or 'ECRL' in provider_upper)
master_has_ecnl_rl = 'ECNL' in master_upper and ('RL' in master_upper or 'ECRL' in master_upper)
master_has_ecnl_only = 'ECNL' in master_upper and 'RL' not in master_upper and 'ECRL' not in master_upper

if provider_has_ecnl_rl and master_has_ecnl_rl:
    print(f"\n✅ VALID MATCH: Both are ECNL RL")
elif provider_has_ecnl_rl and master_has_ecnl_only:
    print(f"\n❌ INVALID MATCH: Provider is ECNL RL, Master is ECNL only")
else:
    print(f"\n⚠️  NEEDS REVIEW: League types don't clearly match")

# Team 2: Rebels SC ECNL RL S.Cal G11
print("\n" + "="*80)
print("TEAM 2: Rebels SC ECNL RL S.Cal G11")
print("="*80)
print("TGS Team ID: 97427")
print("Matched to: Rebels SC ECNL RL G11 (ID: 133132)")

provider_name2 = "Rebels SC ECNL RL S.Cal G11"
master_name2 = "Rebels SC ECNL RL G11"

provider_upper2 = provider_name2.upper()
master_upper2 = master_name2.upper()

print(f"\nProvider: {provider_name2}")
print(f"  Has ECNL: {'ECNL' in provider_upper2}")
print(f"  Has RL: {'RL' in provider_upper2}")
print(f"  Has ECRL: {'ECRL' in provider_upper2}")
print(f"  League Type: {'ECNL RL' if ('ECNL' in provider_upper2 and 'RL' in provider_upper2) else ('ECNL' if 'ECNL' in provider_upper2 else 'Unknown')}")

print(f"\nMaster: {master_name2}")
print(f"  Has ECNL: {'ECNL' in master_upper2}")
print(f"  Has RL: {'RL' in master_upper2}")
print(f"  Has ECRL: {'ECRL' in master_upper2}")
print(f"  League Type: {'ECNL RL' if ('ECNL' in master_upper2 and 'RL' in master_upper2) else ('ECNL' if 'ECNL' in master_upper2 else 'Unknown')}")

# Check if this is a valid match
provider_has_ecnl_rl2 = 'ECNL' in provider_upper2 and ('RL' in provider_upper2 or 'ECRL' in provider_upper2)
master_has_ecnl_rl2 = 'ECNL' in master_upper2 and ('RL' in master_upper2 or 'ECRL' in master_upper2)

if provider_has_ecnl_rl2 and master_has_ecnl_rl2:
    print(f"\n✅ VALID MATCH: Both are ECNL RL")
else:
    print(f"\n❌ INVALID MATCH: League types don't match")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")
print(f"\n✅ 9 teams correctly created as new teams (direct ID matches)")
print(f"⚠️  2 teams fuzzy matched - need to verify league compatibility")









