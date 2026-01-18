#!/usr/bin/env python3
"""
Analyze the impact of changing the minimum games threshold from 5 to 4 games.

This script queries the database to see how many teams would become Active
if we change MIN_GAMES_PROVISIONAL from 5 to 4.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

def main():
    """Analyze threshold impact"""
    load_dotenv()
    
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    
    print("=" * 70)
    print("Analyzing Impact of Changing Threshold from 5 to 4 Games")
    print("=" * 70)
    print()
    
    # Get all teams with their status and games_played
    print("Fetching team data from rankings_view...")
    all_teams = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('rankings_view').select(
            'games_played, status, age, gender, state'
        ).range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        all_teams.extend(result.data)
        
        if len(result.data) < page_size:
            break
        
        offset += page_size
        if offset % 10000 == 0:
            print(f"  Fetched {len(all_teams):,} teams...")
    
    print(f"Total teams analyzed: {len(all_teams):,}")
    print()
    
    df = pd.DataFrame(all_teams)
    
    # Current status distribution
    print("Current Status Distribution:")
    print("-" * 70)
    current_status = df['status'].value_counts()
    for status, count in current_status.items():
        pct = count / len(df) * 100
        print(f"  {status:30s}: {count:6,} ({pct:5.1f}%)")
    print()
    
    # Teams with exactly 4 games
    teams_with_4 = df[df['games_played'] == 4]
    print(f"Teams with exactly 4 ranked games: {len(teams_with_4):,}")
    print("-" * 70)
    
    if len(teams_with_4) > 0:
        status_4 = teams_with_4['status'].value_counts()
        for status, count in status_4.items():
            pct = count / len(teams_with_4) * 100
            print(f"  {status:30s}: {count:6,} ({pct:5.1f}%)")
        print()
        
        # These teams would become Active
        would_become_active = teams_with_4[teams_with_4['status'] == 'Not Enough Ranked Games']
        print(f"Teams that would become Active: {len(would_become_active):,}")
        print()
        
        # Breakdown by age group
        print("Breakdown by Age Group:")
        print("-" * 70)
        age_breakdown = would_become_active.groupby('age').size().sort_index()
        for age, count in age_breakdown.items():
            print(f"  U{age:2d}: {count:6,} teams")
        print()
        
        # Breakdown by gender
        print("Breakdown by Gender:")
        print("-" * 70)
        gender_breakdown = would_become_active.groupby('gender').size()
        for gender, count in gender_breakdown.items():
            print(f"  {gender:6s}: {count:6,} teams")
        print()
        
        # Top states
        print("Top 10 States:")
        print("-" * 70)
        state_breakdown = would_become_active[would_become_active['state'].notna()].groupby('state').size().sort_values(ascending=False).head(10)
        for state, count in state_breakdown.items():
            print(f"  {state:2s}: {count:6,} teams")
        print()
    
    # Projected status distribution if threshold = 4
    print("Projected Status Distribution (if threshold = 4):")
    print("-" * 70)
    
    # Simulate: teams with 4+ games become Active (if not Inactive)
    df_projected = df.copy()
    df_projected['projected_status'] = df_projected.apply(
        lambda row: 'Active' if row['games_played'] >= 4 and row['status'] != 'Inactive' 
                   else row['status'],
        axis=1
    )
    
    projected_status = df_projected['projected_status'].value_counts()
    for status, count in projected_status.items():
        pct = count / len(df_projected) * 100
        change = count - current_status.get(status, 0)
        change_pct = (change / current_status.get(status, 1)) * 100 if status in current_status else 0
        print(f"  {status:30s}: {count:6,} ({pct:5.1f}%)  [Change: {change:+,} ({change_pct:+.1f}%)]")
    print()
    
    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Current Active teams: {current_status.get('Active', 0):,}")
    print(f"Would become Active: {len(would_become_active):,}")
    print(f"New Active total: {projected_status.get('Active', 0):,}")
    print(f"Increase: {projected_status.get('Active', 0) - current_status.get('Active', 0):+,} teams")
    print()
    print(f"Current 'Not Enough Ranked Games': {current_status.get('Not Enough Ranked Games', 0):,}")
    print(f"Would remain 'Not Enough': {projected_status.get('Not Enough Ranked Games', 0):,}")
    print(f"Decrease: {projected_status.get('Not Enough Ranked Games', 0) - current_status.get('Not Enough Ranked Games', 0):,} teams")
    print()

if __name__ == '__main__':
    main()


















