#!/usr/bin/env python3
"""
Backfill state_code for Modular11 teams that were created without it.

The SCF (Schedule Connectivity Factor) in the ranking engine uses state_code
to detect regional bubbles and compute bridge games. Without state_code,
all Modular11 teams are treated as being from the same state ('UNKNOWN'),
which triggers the isolation penalty and caps their SOS at 0.70.

This script:
1. Finds all Modular11 teams missing state_code
2. Looks up their state from game data (the 'state' column in games table
   or from the original CSV data)
3. Updates the teams table with the correct state_code

Usage:
    python scripts/backfill_modular11_state_codes.py          # Preview changes
    python scripts/backfill_modular11_state_codes.py --apply  # Apply changes
"""
import argparse
import os
import sys
from pathlib import Path
from collections import Counter

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


# Known MLS NEXT club state mappings
# These are the primary states for major MLS NEXT clubs
MLS_NEXT_CLUB_STATES = {
    # Arizona
    'rsl arizona': 'AZ', 'rsl az': 'AZ', 'rsl arizona mesa': 'AZ',
    'phoenix rising': 'AZ', 'sc del sol': 'AZ', 'total futbol academy': 'AZ',
    'real salt lake arizona': 'AZ',
    # California
    'la galaxy': 'CA', 'lafc': 'CA', 'los angeles fc': 'CA',
    'los angeles football club': 'CA', 'la bulls': 'CA',
    'los angeles bulls': 'CA', 'albion sc': 'CA',
    'albion sc san diego': 'CA', 'albion sc los angeles': 'CA',
    'san jose earthquakes': 'CA', 'la surf': 'CA', 'los angeles surf': 'CA',
    'la surf soccer': 'CA', 'strikers fc': 'CA', 'fc golden state': 'CA',
    'real so cal': 'CA', 'socal reds': 'CA', 'ventura county fusion': 'CA',
    'sacramento republic': 'CA', 'san diego fc': 'CA', 'bay area surf': 'CA',
    'de anza force': 'CA', 'la premier': 'CA',
    # Colorado
    'colorado rapids': 'CO', 'real colorado': 'CO',
    # Connecticut
    'new york red bulls': 'NJ', 'new york city fc': 'NY',
    # Florida
    'inter miami': 'FL', 'orlando city': 'FL',
    # Georgia
    'atlanta united': 'GA',
    # Illinois
    'chicago fire': 'IL',
    # Indiana
    'indy eleven': 'IN',
    # Kansas
    'sporting kansas city': 'KS',
    # Massachusetts
    'new england revolution': 'MA', 'fc greater boston bolts': 'MA',
    'fc boston bolts': 'MA',
    # Michigan
    'detroit city': 'MI',
    # Minnesota
    'minnesota united': 'MN',
    # Missouri
    'st. louis city': 'MO', 'st louis city': 'MO',
    # North Carolina
    'charlotte fc': 'NC', 'triangle united': 'NC',
    # New York
    'new york city': 'NY',
    # Ohio
    'columbus crew': 'OH', 'fc cincinnati': 'OH',
    'cincinnati united': 'OH', 'cincinnati united premier': 'OH',
    # Oregon
    'portland timbers': 'OR',
    # Pennsylvania
    'philadelphia union': 'PA',
    # Tennessee
    'nashville sc': 'TN',
    # Texas
    'fc dallas': 'TX', 'houston dynamo': 'TX', 'austin fc': 'TX',
    'dallas hornets': 'TX', 'solar sc': 'TX',
    # Utah
    'real salt lake': 'UT',
    # Virginia
    'dc united': 'DC', 'loudoun united': 'VA',
    # Washington
    'seattle sounders': 'WA',
    # Wisconsin
    'milwaukee torrent': 'WI',
}


def infer_state_from_club_name(club_name: str) -> str:
    """Try to infer state from club/team name using known MLS NEXT clubs."""
    if not club_name:
        return None
    name_lower = club_name.lower().strip()
    for club_pattern, state in MLS_NEXT_CLUB_STATES.items():
        if club_pattern in name_lower:
            return state
    return None


def main():
    parser = argparse.ArgumentParser(description='Backfill state_code for Modular11 teams')
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes (default is preview/dry-run)')
    args = parser.parse_args()

    supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

    if not supabase_url or not supabase_key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    sb = create_client(supabase_url, supabase_key)

    # Get Modular11 provider UUID
    provider_result = sb.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("ERROR: Modular11 provider not found")
        sys.exit(1)
    provider_uuid = provider_result.data['id']

    print(f"{'=' * 60}")
    print("MODULAR11 STATE_CODE BACKFILL")
    print(f"{'=' * 60}")
    print(f"Mode: {'APPLY' if args.apply else 'PREVIEW (dry-run)'}")
    print()

    # Find all Modular11 teams missing state_code
    print("1. Finding Modular11 teams without state_code...")
    teams_missing_state = []
    offset = 0
    page_size = 1000

    while True:
        result = sb.table('teams').select(
            'team_id_master, team_name, club_name, age_group, state_code'
        ).eq('provider_id', provider_uuid).is_('state_code', 'null').range(
            offset, offset + page_size - 1
        ).execute()

        if not result.data:
            break
        teams_missing_state.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    # Also check for empty string state_code
    offset = 0
    while True:
        result = sb.table('teams').select(
            'team_id_master, team_name, club_name, age_group, state_code'
        ).eq('provider_id', provider_uuid).eq('state_code', '').range(
            offset, offset + page_size - 1
        ).execute()

        if not result.data:
            break
        teams_missing_state.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    print(f"   Found {len(teams_missing_state)} Modular11 teams without state_code")

    if not teams_missing_state:
        print("\n   All Modular11 teams already have state_code!")
        return

    # Try to infer state from club name
    print("\n2. Inferring state from club/team names...")
    updates = []
    unresolved = []

    for team in teams_missing_state:
        team_id = team['team_id_master']
        team_name = team.get('team_name', '')
        club_name = team.get('club_name', '')

        # Try club_name first, then team_name
        state = infer_state_from_club_name(club_name)
        if not state:
            state = infer_state_from_club_name(team_name)

        if state:
            updates.append({
                'team_id': team_id,
                'team_name': team_name,
                'club_name': club_name,
                'state_code': state
            })
        else:
            unresolved.append({
                'team_id': team_id,
                'team_name': team_name,
                'club_name': club_name
            })

    # Report
    print(f"   Resolved: {len(updates)} teams")
    print(f"   Unresolved: {len(unresolved)} teams")

    if updates:
        # Show state distribution
        state_counts = Counter(u['state_code'] for u in updates)
        print(f"\n   State distribution:")
        for state, count in sorted(state_counts.items()):
            print(f"     {state}: {count} teams")

    if unresolved:
        print(f"\n   Unresolved teams (first 20):")
        for team in unresolved[:20]:
            print(f"     {team['team_name']} ({team['club_name']})")
        if len(unresolved) > 20:
            print(f"     ... and {len(unresolved) - 20} more")

    # Apply updates
    if args.apply and updates:
        print(f"\n3. Applying {len(updates)} state_code updates...")
        success = 0
        failed = 0

        for update in updates:
            try:
                sb.table('teams').update(
                    {'state_code': update['state_code']}
                ).eq('team_id_master', update['team_id']).execute()
                success += 1
            except Exception as e:
                failed += 1
                print(f"   ERROR updating {update['team_name']}: {e}")

        print(f"   Updated: {success}")
        if failed:
            print(f"   Failed: {failed}")
    elif not args.apply:
        print(f"\n   Run with --apply to update these teams")

    print(f"\n{'=' * 60}")
    print("DONE")
    print(f"{'=' * 60}")
    if updates and args.apply:
        print("Next step: Re-run calculate_rankings to see updated SOS values")


if __name__ == '__main__':
    main()
