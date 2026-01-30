#!/usr/bin/env python3
"""Analyze team merge patterns from team_merge_map table."""
import os
import re
from collections import Counter, defaultdict
from dotenv import load_dotenv
from supabase import create_client

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Get all merges
all_merges = []
for start in range(0, 10000, 1000):
    batch = supabase.table('team_merge_map').select('*').range(start, start+999).execute()
    if not batch.data:
        break
    all_merges.extend(batch.data)

print(f'=== MERGE ANALYSIS: {len(all_merges)} total merges ===\n')

# Basic stats
by_user = Counter()
confidence_levels = Counter()

for m in all_merges:
    by_user[m.get('merged_by') or 'unknown'] += 1
    reason = m.get('merge_reason') or ''
    conf_match = re.search(r'(\d+)% confidence', str(reason))
    if conf_match:
        confidence_levels[int(conf_match.group(1))] += 1

print('BY USER:')
for user, count in by_user.most_common():
    print(f'  {user}: {count}')

print('\nCONFIDENCE DISTRIBUTION:')
for conf, count in sorted(confidence_levels.items(), reverse=True)[:10]:
    print(f'  {conf}%: {count}')

# Sample merges for pattern analysis
print('\n=== ANALYZING PATTERNS (sampling 100 merges) ===')
sample = all_merges[:100]

patterns = Counter()
examples = defaultdict(list)

for m in sample:
    dep = supabase.table('teams').select('team_name, club_name, state_code').eq('team_id_master', m['deprecated_team_id']).limit(1).execute()
    can = supabase.table('teams').select('team_name, club_name, state_code').eq('team_id_master', m['canonical_team_id']).limit(1).execute()
    
    if not dep.data or not can.data:
        continue
    
    dep_name = dep.data[0].get('team_name', '')
    can_name = can.data[0].get('team_name', '')
    state = dep.data[0].get('state_code', '')
    
    if not dep_name or not can_name:
        continue
    
    # Classify pattern
    if dep_name.lower() == can_name.lower() and dep_name != can_name:
        pat = 'CAPS_DIFFERENCE'
    elif re.sub(r'[^a-zA-Z0-9]', '', dep_name) == re.sub(r'[^a-zA-Z0-9]', '', can_name):
        pat = 'PUNCTUATION_SPACING'
    elif abs(len(dep_name) - len(can_name)) <= 2 and dep_name[:-2].lower() == can_name[:-2].lower():
        pat = 'TRAILING_CHARS'
    else:
        pat = 'NAME_VARIATION'
    
    patterns[pat] += 1
    if len(examples[pat]) < 5:
        examples[pat].append((dep_name, can_name, state))

print('\nPATTERN BREAKDOWN:')
for pat, count in patterns.most_common():
    print(f'\n### {pat}: {count} ###')
    for dep, can, state in examples[pat]:
        print(f'  "{dep}"')
        print(f'    → "{can}" ({state})')

# Analyze "OTHER" patterns more deeply
print('\n=== NAME_VARIATION DETAILS ===')
for dep, can, state in examples.get('NAME_VARIATION', []):
    # Show character-level diff
    print(f'\nDEP: {dep}')
    print(f'CAN: {can}')
    print(f'State: {state}')
