#!/usr/bin/env python3
"""
Validate team name normalizer against historical merges.
Tests if the normalizer would have correctly identified the same merges.
"""

import os
import time
from collections import Counter, defaultdict
from dotenv import load_dotenv
from supabase import create_client
from team_name_normalizer import parse_team_name, teams_match

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))


def safe_query(query_fn, retries=3, delay=2):
    """Execute query with retry logic."""
    for attempt in range(retries):
        try:
            return query_fn()
        except Exception as e:
            if attempt < retries - 1:
                print(f"    Query failed, retrying in {delay}s... ({e})")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                raise


def main():
    # Get all merges
    print("Fetching merge history...")
    all_merges = []
    for start in range(0, 10000, 1000):
        batch = safe_query(
            lambda s=start: supabase.table('team_merge_map').select('*').range(s, s+999).execute()
        )
        if not batch.data:
            break
        all_merges.extend(batch.data)
    
    print(f"Total merges: {len(all_merges)}")
    
    # Pre-fetch ALL team data to avoid per-merge queries
    print("\nPre-fetching team data (this avoids rate limits)...")
    team_ids = set()
    for m in all_merges:
        team_ids.add(m['deprecated_team_id'])
        team_ids.add(m['canonical_team_id'])
    
    print(f"  Need {len(team_ids)} unique teams...")
    
    teams_cache = {}
    team_ids_list = list(team_ids)
    
    for i in range(0, len(team_ids_list), 50):
        batch_ids = team_ids_list[i:i+50]
        if i % 200 == 0:
            print(f"  Fetched {i}/{len(team_ids_list)} teams...")
        
        for tid in batch_ids:
            try:
                result = safe_query(
                    lambda t=tid: supabase.table('teams').select('team_name, club_name, state_code, gender, age_group').eq('team_id_master', t).limit(1).execute()
                )
                if result.data:
                    teams_cache[tid] = result.data[0]
            except Exception as e:
                print(f"    Failed to fetch team {tid}: {e}")
        
        # Small delay to avoid rate limiting
        time.sleep(0.1)
    
    print(f"  Cached {len(teams_cache)} teams")
    
    # Track results
    results = {
        'correct_match': [],      # Normalizer agrees these should merge
        'missed_match': [],       # Normalizer says don't merge (but human did)
        'no_parse': [],           # Couldn't parse one or both teams
    }
    
    reasons = Counter()
    
    print("\nValidating merges...")
    
    for i, merge in enumerate(all_merges):
        if i % 200 == 0:
            print(f"  Processing {i}/{len(all_merges)}...")
        
        dep_id = merge['deprecated_team_id']
        can_id = merge['canonical_team_id']
        
        dep = teams_cache.get(dep_id)
        can = teams_cache.get(can_id)
        
        if not dep or not can:
            results['no_parse'].append({
                'merge_id': merge['id'],
                'reason': 'Team not found in database'
            })
            continue
        
        # Parse team names
        parsed_dep = parse_team_name(dep['team_name'], dep['club_name'])
        parsed_can = parse_team_name(can['team_name'], can['club_name'])
        
        # Check if normalizer would match
        match, reason = teams_match(parsed_dep, parsed_can)
        
        merge_info = {
            'merge_id': merge['id'],
            'deprecated_name': dep['team_name'],
            'deprecated_club': dep['club_name'],
            'canonical_name': can['team_name'],
            'canonical_club': can['club_name'],
            'state': dep.get('state_code'),
            'parsed_dep': parsed_dep,
            'parsed_can': parsed_can,
            'reason': reason
        }
        
        if match:
            results['correct_match'].append(merge_info)
        else:
            if parsed_dep['age'] is None or parsed_can['age'] is None:
                results['no_parse'].append(merge_info)
            else:
                results['missed_match'].append(merge_info)
                reasons[reason] += 1
    
    # Print summary
    print("\n" + "="*60)
    print("VALIDATION RESULTS")
    print("="*60)
    
    total = len(all_merges)
    correct = len(results['correct_match'])
    missed = len(results['missed_match'])
    no_parse = len(results['no_parse'])
    
    print(f"\nTotal merges tested: {total}")
    print(f"  ✅ Correctly matched:  {correct} ({100*correct/total:.1f}%)")
    print(f"  ❌ Missed (need human): {missed} ({100*missed/total:.1f}%)")
    print(f"  ⚠️  Could not parse:   {no_parse} ({100*no_parse/total:.1f}%)")
    
    print("\n" + "-"*60)
    print("REASONS FOR MISSED MATCHES")
    print("-"*60)
    for reason, count in reasons.most_common(20):
        print(f"  {count:4d} | {reason}")
    
    print("\n" + "-"*60)
    print("SAMPLE MISSED MATCHES (first 30)")
    print("-"*60)
    for m in results['missed_match'][:30]:
        print(f"\n  Deprecated: {m['deprecated_name']}")
        print(f"    Parsed: {m['parsed_dep']['normalized']}")
        print(f"  Canonical: {m['canonical_name']}")
        print(f"    Parsed: {m['parsed_can']['normalized']}")
        print(f"  Reason: {m['reason']}")
    
    print("\n" + "-"*60)
    print("SAMPLE UNPARSED (first 10)")
    print("-"*60)
    for m in results['no_parse'][:10]:
        if 'deprecated_name' in m:
            print(f"\n  Deprecated: {m.get('deprecated_name')} ({m.get('deprecated_club')})")
            print(f"    Parsed age: {m['parsed_dep']['age']}")
            print(f"  Canonical: {m.get('canonical_name')} ({m.get('canonical_club')})")
            print(f"    Parsed age: {m['parsed_can']['age']}")
        else:
            print(f"\n  {m['reason']}")


if __name__ == '__main__':
    main()
