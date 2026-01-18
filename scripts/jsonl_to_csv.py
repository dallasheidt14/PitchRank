#!/usr/bin/env python3
"""
Convert JSONL file to CSV format.
"""
import json
import csv
import sys
from pathlib import Path
from typing import List, Dict


def jsonl_to_csv(jsonl_path: str, csv_path: str = None):
    """Convert JSONL file to CSV."""
    jsonl_file = Path(jsonl_path)
    
    if not jsonl_file.exists():
        print(f"Error: File not found: {jsonl_path}")
        sys.exit(1)
    
    # Determine output CSV path
    if csv_path is None:
        csv_path = jsonl_file.with_suffix('.csv')
    else:
        csv_path = Path(csv_path)
    
    # Read all JSON objects from JSONL
    records = []
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON on line {line_num}: {e}")
                continue
    
    if not records:
        print("Error: No valid records found in JSONL file")
        sys.exit(1)
    
    # Get all unique fieldnames from all records
    fieldnames = set()
    for record in records:
        fieldnames.update(record.keys())
    
    # Sort fieldnames for consistent column order
    # Put common fields first
    common_fields = [
        'provider', 'team_id', 'team_id_source', 'opponent_id', 'opponent_id_source',
        'team_name', 'opponent_name', 'game_date', 'home_away',
        'goals_for', 'goals_against', 'result', 'competition', 'venue',
        'source_url', 'scraped_at', 'club_name', 'opponent_club_name',
        'age_group', 'gender'
    ]
    
    # Order: common fields first, then any remaining fields alphabetically
    ordered_fieldnames = []
    for field in common_fields:
        if field in fieldnames:
            ordered_fieldnames.append(field)
            fieldnames.remove(field)
    
    ordered_fieldnames.extend(sorted(fieldnames))
    
    # Write CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fieldnames)
        writer.writeheader()
        
        for record in records:
            # Ensure all fields are present (fill missing with empty string)
            row = {field: record.get(field, '') for field in ordered_fieldnames}
            writer.writerow(row)
    
    print(f"✅ Successfully converted {len(records):,} records")
    print(f"📄 Output file: {csv_path}")
    print(f"📊 Columns: {len(ordered_fieldnames)}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python jsonl_to_csv.py <input.jsonl> [output.csv]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    jsonl_to_csv(input_file, output_file)








