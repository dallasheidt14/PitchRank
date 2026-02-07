#!/usr/bin/env python3
"""List the aliases that need to be created for unfixable games"""
import csv
from collections import defaultdict

with open('incorrectly_matched_games.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

unfixable = [r for r in rows if not r.get('correct_team_id')]

print(f"\nUnfixable games: {len(unfixable)}")
print("\n" + "="*80)
print("ALIASES THAT NEED TO BE CREATED:")
print("="*80)

# Group by expected alias
aliases_needed = {}
for r in unfixable:
    expected_alias = r.get('expected_alias')
    if expected_alias:
        if expected_alias not in aliases_needed:
            aliases_needed[expected_alias] = {
                'provider_id': r['provider_id'],
                'team_name': r['team_name'],
                'expected_age': r['expected_age'],
                'division': r.get('division', 'N/A'),
                'matched_team_name': r.get('matched_team_name', 'N/A'),
                'matched_age': r.get('matched_age', 'N/A'),
                'count': 0
            }
        aliases_needed[expected_alias]['count'] += 1

print(f"\nTotal unique aliases needed: {len(aliases_needed)}\n")

for alias, info in sorted(aliases_needed.items()):
    print(f"Alias: {alias}")
    print(f"  Provider ID: {info['provider_id']}")
    print(f"  Team Name: {info['team_name']}")
    print(f"  Expected Age: {info['expected_age']}")
    print(f"  Division: {info['division']}")
    print(f"  Currently Matched To: {info['matched_team_name']} (age: {info['matched_age']})")
    print(f"  Games Affected: {info['count']}")
    print()



