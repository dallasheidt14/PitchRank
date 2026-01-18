"""
Check what format age_group is in our CSV vs what the system expects.
"""
import csv
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))
from src.utils.team_utils import calculate_age_group_from_birth_year

# Check the newly scraped CSV
csv_file = Path('data/raw/tgs/tgs_events_3951_3951_2025-12-12T17-22-22-166384+00-00.csv')

print("="*80)
print("CHECKING AGE_GROUP FORMAT")
print("="*80)

if csv_file.exists():
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = [next(reader) for _ in range(10)]
    
    print(f"\n📊 Sample rows from CSV:")
    for i, row in enumerate(rows, 1):
        age_year = row.get('age_year', '').strip()
        age_group_csv = row.get('age_group', '').strip()
        
        # Calculate what it should be
        age_group_expected = ""
        if age_year:
            try:
                birth_year = int(age_year)
                age_group_calc = calculate_age_group_from_birth_year(birth_year)
                if age_group_calc:
                    age_group_expected = age_group_calc.lower()
            except:
                pass
        
        print(f"\nRow {i}:")
        print(f"  age_year: {age_year}")
        print(f"  age_group (CSV): {repr(age_group_csv)}")
        print(f"  age_group (expected): {repr(age_group_expected)}")
        print(f"  Match: {'✅' if age_group_csv == age_group_expected else '❌'}")
else:
    print(f"❌ CSV file not found: {csv_file}")

# Check what the database schema expects
print("\n" + "="*80)
print("DATABASE SCHEMA EXPECTATIONS")
print("="*80)
print("\nFrom migrations, age_group is stored as TEXT and accepts:")
print("  - 'u12' (lowercase)")
print("  - 'U12' (uppercase)")
print("  - '12' (number only)")
print("\nThe system normalizes all formats, but prefers lowercase 'u12' format.")

# Check what calculate_age_group_from_birth_year returns
print("\n" + "="*80)
print("calculate_age_group_from_birth_year OUTPUT")
print("="*80)
test_years = [2008, 2009, 2010, 2011, 2012, 2013]
for year in test_years:
    result = calculate_age_group_from_birth_year(year)
    print(f"  {year} -> {result}")









