#!/usr/bin/env python3
"""
Analyze teams that are missing state information.
These teams are potentially excluded from state rankings filters.
"""
import sys
import os
import json
import requests
from collections import Counter


def fetch_paginated(url, headers, select_fields, batch_size=1000):
    """Fetch all records using pagination via REST API."""
    all_records = []
    offset = 0

    while True:
        params = {
            'select': select_fields,
            'offset': str(offset),
            'limit': str(batch_size)
        }
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        all_records.extend(data)
        offset += batch_size

        if len(data) < batch_size:
            break

    return all_records


def main():
    # Initialize Supabase REST API
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)

    rest_url = f"{supabase_url}/rest/v1/teams"
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'application/json'
    }

    print("=" * 70)
    print("  Missing Team States Analysis")
    print("  Investigating teams excluded from state rankings")
    print("=" * 70)

    # 1. Count total teams and teams with missing state
    print("\nStep 1: Fetching team state distribution...")

    all_teams = fetch_paginated(
        rest_url, headers,
        'team_id_master,team_name,club_name,state,state_code,age_group,gender,is_deprecated'
    )

    if not all_teams:
        print("No teams found in database!")
        return

    print(f"  Total teams in database: {len(all_teams):,}")

    # Filter out deprecated teams
    active_teams = [t for t in all_teams if not t.get('is_deprecated')]
    print(f"  Active (non-deprecated) teams: {len(active_teams):,}")

    # 2. Analyze state_code distribution
    print("\nStep 2: Analyzing state_code distribution...")

    teams_null_state = [t for t in active_teams if t.get('state_code') is None]
    teams_empty_state = [t for t in active_teams if t.get('state_code') == '']
    teams_unknown_state = [t for t in active_teams if (t.get('state_code') or '').upper() == 'UNKNOWN']
    teams_valid_state = [t for t in active_teams
                         if t.get('state_code') is not None
                         and t.get('state_code') != ''
                         and (t.get('state_code') or '').upper() != 'UNKNOWN']

    total_active = len(active_teams)
    print(f"\n  State Code Status:")
    print(f"    ✅ Valid state code: {len(teams_valid_state):,} ({100*len(teams_valid_state)/total_active:.1f}%)")
    print(f"    ❌ NULL state code: {len(teams_null_state):,} ({100*len(teams_null_state)/total_active:.1f}%)")
    print(f"    ❌ Empty state code: {len(teams_empty_state):,} ({100*len(teams_empty_state)/total_active:.1f}%)")
    print(f"    ⚠️  UNKNOWN state code: {len(teams_unknown_state):,} ({100*len(teams_unknown_state)/total_active:.1f}%)")

    # 3. Teams potentially excluded from state rankings
    excluded_ids = set()
    excluded_teams = []
    for t in teams_null_state + teams_empty_state:
        if t.get('team_id_master') not in excluded_ids:
            excluded_ids.add(t.get('team_id_master'))
            excluded_teams.append(t)

    print(f"\n  *** Teams EXCLUDED from state rankings: {len(excluded_teams):,} ***")

    # 4. Breakdown by age group and gender
    if excluded_teams:
        print("\nStep 3: Breakdown of excluded teams by age group and gender...")

        age_gender_counts = Counter((t.get('age_group', 'Unknown'), t.get('gender', 'Unknown'))
                                    for t in excluded_teams)
        sorted_counts = sorted(age_gender_counts.items(), key=lambda x: -x[1])

        print(f"\n  {'Age Group':<12} {'Gender':<10} {'Count':>10}")
        print(f"  {'-'*12} {'-'*10} {'-'*10}")
        for (age, gender), count in sorted_counts[:20]:
            print(f"  {str(age):<12} {str(gender):<10} {count:>10,}")

        # 5. Sample of teams missing state
        print("\nStep 4: Sample of teams missing state_code...")
        print(f"\n  {'Team Name':<40} {'Club Name':<25} {'Age':<8} {'Gender':<8} {'State Field':<12}")
        print(f"  {'-'*40} {'-'*25} {'-'*8} {'-'*8} {'-'*12}")

        for t in excluded_teams[:25]:
            team_name = (t.get('team_name') or 'N/A')[:40]
            club_name = (t.get('club_name') or 'N/A')[:25]
            age = str(t.get('age_group', 'N/A'))[:8]
            gender = str(t.get('gender', 'N/A'))[:8]
            state_field = str(t.get('state') or 'NULL')[:12]
            print(f"  {team_name:<40} {club_name:<25} {age:<8} {gender:<8} {state_field:<12}")

        # 6. Check if these teams have games and rankings
        print("\nStep 5: Checking if excluded teams have rankings...")

        rankings_url = f"{supabase_url}/rest/v1/rankings_full"
        excluded_id_list = list(excluded_ids)[:500]  # Check first 500

        rankings_count = 0
        batch_size = 50
        for i in range(0, len(excluded_id_list), batch_size):
            batch = excluded_id_list[i:i + batch_size]
            # Use PostgREST's in filter
            filter_param = f"team_id=in.({','.join(batch)})"
            params = {
                'select': 'team_id',
                filter_param.split('=')[0]: filter_param.split('=')[1]
            }
            try:
                resp = requests.get(rankings_url, headers=headers, params=params)
                if resp.status_code == 200:
                    rankings_count += len(resp.json())
            except:
                pass

        print(f"  Teams without state that have rankings: {rankings_count:,}")

        if rankings_count > 0:
            print(f"  ⚠️  {rankings_count:,} ranked teams are excluded from state rankings!")

    # 7. State distribution of valid teams
    print("\nStep 6: State distribution of teams with valid state codes...")

    state_counts = Counter(t.get('state_code') for t in teams_valid_state)
    sorted_states = sorted(state_counts.items(), key=lambda x: -x[1])

    print(f"\n  {'State':<8} {'Team Count':>12} {'Percentage':>12}")
    print(f"  {'-'*8} {'-'*12} {'-'*12}")
    for state, count in sorted_states[:15]:
        pct = 100 * count / len(teams_valid_state)
        print(f"  {str(state):<8} {count:>12,} {pct:>11.1f}%")

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"""
  Total Active Teams: {total_active:,}
  Teams with valid state: {len(teams_valid_state):,} ({100*len(teams_valid_state)/total_active:.1f}%)
  Teams MISSING state (excluded): {len(excluded_teams):,} ({100*len(excluded_teams)/total_active:.1f}%)

  Impact:
  These {len(excluded_teams):,} teams will:
    - NOT appear when users filter by any state
    - Only appear in national rankings
    - Have no state_rank calculated

  Recommendation:
  Consider enriching team data by:
    1. Parsing state from team/club names
    2. Looking up state from provider data
    3. Using location data from tournaments/events
""")


if __name__ == '__main__':
    main()
