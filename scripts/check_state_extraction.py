#!/usr/bin/env python3
"""Check state extraction from scraped CSV"""
import csv
import sys
from pathlib import Path

csv_file = Path('data/raw/tgs/tgs_events_3900_3910_2025-12-11T23-21-07-272257+00-00.csv')

if not csv_file.exists():
    # Find the most recent file
    files = sorted(Path('data/raw/tgs').glob('tgs_events_3900_3910_*.csv'), reverse=True)
    if files:
        csv_file = files[0]
    else:
        print("No CSV file found")
        sys.exit(1)

print(f"Checking: {csv_file.name}\n")

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    
print(f"Total rows: {len(rows)}\n")
print("Columns:", list(rows[0].keys()) if rows else "No rows")
print("\nSample rows with state:")
for i, row in enumerate(rows[:10]):
    state = row.get('state', 'MISSING')
    state_code = row.get('state_code', 'MISSING')
    venue = row.get('venue', '')[:50]
    print(f"Row {i+1}: state='{state}', state_code='{state_code}', venue='{venue}'")

print("\nUnique states found:")
states = set(r.get('state_code', '') for r in rows if r.get('state_code'))
print(f"State codes: {sorted(states)}")
print(f"\nTotal rows with state_code: {sum(1 for r in rows if r.get('state_code'))}")
print(f"Total rows without state_code: {sum(1 for r in rows if not r.get('state_code'))}")









