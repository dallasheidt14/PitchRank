"""
Test why event 3951 teams aren't being created.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import csv
from src.utils.team_utils import calculate_age_group_from_birth_year

csv_file = 'data/raw/tgs/tgs_events_3951_3951_2025-12-12T17-00-08-071039+00-00.csv'

print("Testing age_group conversion and required fields:\n")

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 5:
            break
        
        age_year = row.get('age_year', '').strip()
        team_name = row.get('team_name', '').strip()
        gender = row.get('gender', '').strip()
        club_name = row.get('club_name', '').strip()
        
        # Convert age_year to age_group
        age_group = None
        if age_year:
            try:
                birth_year = int(age_year)
                age_group = calculate_age_group_from_birth_year(birth_year)
                if age_group:
                    age_group = age_group.lower()
            except (ValueError, TypeError):
                pass
        
        # Normalize gender
        gender_normalized = gender
        if gender:
            if gender.lower() == 'boys':
                gender_normalized = 'Male'
            elif gender.lower() == 'girls':
                gender_normalized = 'Female'
        
        print(f"Row {i+1}:")
        print(f"  team_name: {team_name} ({bool(team_name)})")
        print(f"  age_year: {age_year} -> age_group: {age_group} ({bool(age_group)})")
        print(f"  gender: {gender} -> {gender_normalized} ({bool(gender_normalized)})")
        print(f"  club_name: {club_name}")
        print(f"  All required fields present: {bool(team_name and age_group and gender_normalized)}")
        print()

