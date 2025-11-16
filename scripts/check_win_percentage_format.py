#!/usr/bin/env python3
"""
Check the format of win_percentage in the database
Determines if it's stored as decimal (0.0-1.0) or percentage (0-100)
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return 1

    supabase = create_client(supabase_url, supabase_key)

    print("=" * 70)
    print("WIN_PERCENTAGE FORMAT DIAGNOSTIC")
    print("=" * 70)

    # Check rankings_view
    print("\n1. Checking rankings_view...")
    result = supabase.table('rankings_view').select(
        'team_name, wins, losses, games_played, win_percentage'
    ).not_.is_('win_percentage', 'null').limit(10).execute()

    if result.data:
        print(f"\nFound {len(result.data)} teams with win_percentage")
        print(f"\n{'Team':<40} {'W-L':<10} {'Games':<8} {'Win %':<15} {'Format'}")
        print("-" * 85)

        for row in result.data:
            w = row.get('wins', 0)
            l = row.get('losses', 0)
            gp = row.get('games_played', 0)
            win_pct = row.get('win_percentage')

            # Determine format
            if win_pct is not None:
                if win_pct <= 1.0:
                    format_type = "DECIMAL (0-1)"
                    expected = f"{win_pct * 100:.1f}%"
                else:
                    format_type = "PERCENTAGE (0-100)"
                    expected = f"{win_pct:.1f}%"
            else:
                format_type = "NULL"
                expected = "—"

            print(f"{row['team_name']:<40} {w}-{l:<8} {gp:<8} {win_pct:<15} {format_type}")

        # Determine overall format
        sample_value = result.data[0].get('win_percentage')
        if sample_value and sample_value <= 1.0:
            print("\n" + "="*70)
            print("RESULT: win_percentage is stored as DECIMAL (0.0-1.0)")
            print("Frontend should multiply by 100 before displaying")
            print("Current code: teamRanking.win_percentage.toFixed(1)% ❌ WRONG")
            print("Should be: (teamRanking.win_percentage * 100).toFixed(1)% ✅ CORRECT")
        elif sample_value:
            print("\n" + "="*70)
            print("RESULT: win_percentage is stored as PERCENTAGE (0-100)")
            print("Frontend can display directly")
            print("Current code: teamRanking.win_percentage.toFixed(1)% ✅ CORRECT")
        print("="*70)
    else:
        print("No data found with win_percentage")

    # Check current_rankings table for comparison
    print("\n2. Checking current_rankings table (for comparison)...")
    result2 = supabase.table('current_rankings').select(
        'team_id, wins, losses, games_played, win_percentage'
    ).not_.is_('win_percentage', 'null').limit(5).execute()

    if result2.data:
        print(f"\nFound {len(result2.data)} records")
        for row in result2.data:
            win_pct = row.get('win_percentage')
            if win_pct is not None:
                if win_pct <= 1.0:
                    print(f"  Team: {row['team_id'][:8]}... | win_percentage: {win_pct:.4f} (DECIMAL)")
                else:
                    print(f"  Team: {row['team_id'][:8]}... | win_percentage: {win_pct:.2f} (PERCENTAGE)")

    return 0

if __name__ == '__main__':
    exit(main())
