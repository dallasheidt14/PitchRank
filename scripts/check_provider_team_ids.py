"""Check if provider_team_id values match between aliases and CSV"""
import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

print("=" * 70)
print("CHECKING PROVIDER_TEAM_ID MATCHING")
print("=" * 70)

# Get all approved aliases
print("\nFetching approved aliases...")
alias_result = supabase.table('team_alias_map').select('provider_team_id, team_id_master, match_method').eq('provider_id', modular11_provider_id).eq('review_status', 'approved').execute()

print(f"Total approved aliases: {len(alias_result.data)}")

# Get unique provider_team_ids from aliases
alias_provider_ids = set()
for alias in alias_result.data:
    pid = alias.get('provider_team_id')
    if pid:
        alias_provider_ids.add(str(pid))

print(f"Unique provider_team_ids in aliases: {len(alias_provider_ids)}")

# Check CSV file
csv_path = Path('scrapers/modular11_scraper/output/modular11_u13.csv')
if not csv_path.exists():
    print(f"\nError: CSV file not found: {csv_path}")
    sys.exit(1)

print(f"\nReading CSV: {csv_path}")
csv_provider_ids = set()
csv_team_names = {}

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id') or row.get('team_id_source')
        team_name = row.get('team_name', '')
        if team_id:
            csv_provider_ids.add(str(team_id))
            csv_team_names[str(team_id)] = team_name

print(f"Unique provider_team_ids in CSV: {len(csv_provider_ids)}")

# Check overlap
overlap = alias_provider_ids & csv_provider_ids
missing_in_csv = alias_provider_ids - csv_provider_ids
missing_in_aliases = csv_provider_ids - alias_provider_ids

print(f"\nOverlap (IDs in both): {len(overlap)}")
print(f"IDs in aliases but NOT in CSV: {len(missing_in_csv)}")
print(f"IDs in CSV but NOT in aliases: {len(missing_in_aliases)}")

if missing_in_csv:
    print(f"\n⚠️  Sample IDs in aliases but missing from CSV (first 10):")
    for pid in list(missing_in_csv)[:10]:
        print(f"  - {pid}")

if missing_in_aliases:
    print(f"\n⚠️  Sample IDs in CSV but missing from aliases (first 10):")
    for pid in list(missing_in_aliases)[:10]:
        team_name = csv_team_names.get(pid, 'Unknown')
        print(f"  - {pid} ({team_name})")

# Check if CSV has team_id column
print("\n" + "=" * 70)
print("CSV COLUMN CHECK")
print("=" * 70)
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    first_row = next(reader, None)
    if first_row:
        print("\nCSV columns found:")
        for col in first_row.keys():
            print(f"  - {col}")
        
        if 'team_id' in first_row or 'team_id_source' in first_row:
            print("\n✓ CSV has team_id column")
        else:
            print("\n⚠️  CSV does NOT have team_id column!")
            print("   This means provider_team_id will be None during import")
            print("   and alias lookup will be skipped!")

print("\n" + "=" * 70)













