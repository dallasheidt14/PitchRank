#!/usr/bin/env python3
"""
Quick diagnostic: Check if a Modular11 team's games are correctly linked
in the database and will appear in rankings.

Usage:
    python scripts/verify_modular11_team.py 391 U14 HD
    python scripts/verify_modular11_team.py --uuid 5feee4c8-b532-4ba9-bad7-7f01c4ca28fe
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='Verify Modular11 team in pipeline')
    parser.add_argument('provider_team_id', nargs='?', help='Modular11 provider team ID (e.g., 391)')
    parser.add_argument('age_group', nargs='?', help='Age group (e.g., U14)')
    parser.add_argument('division', nargs='?', help='Division (e.g., HD)')
    parser.add_argument('--uuid', help='Directly check a team UUID')
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
        print("ERROR: Modular11 provider not found in providers table")
        sys.exit(1)
    provider_uuid = provider_result.data['id']

    print(f"\n{'='*60}")
    print("MODULAR11 TEAM PIPELINE DIAGNOSTIC")
    print(f"{'='*60}")

    # --- Step 1: Check aliases ---
    if args.provider_team_id:
        pid = args.provider_team_id
        age = (args.age_group or '').upper()
        div = (args.division or '').upper()

        # Try all alias formats
        alias_keys = []
        if age and div:
            alias_keys.append(f"{pid}_{age}_{div}")
        if age:
            alias_keys.append(f"{pid}_{age}")
        if div:
            alias_keys.append(f"{pid}_{div}")
        alias_keys.append(pid)

        print(f"\n1. ALIAS LOOKUP (provider_team_id={pid}, age={age}, div={div})")
        print(f"   Trying keys: {alias_keys}")

        found_aliases = []
        for key in alias_keys:
            result = sb.table('team_alias_map').select(
                'provider_team_id, team_id_master, match_method, review_status, division'
            ).eq('provider_id', provider_uuid).eq('provider_team_id', key).execute()

            if result.data:
                for row in result.data:
                    status_icon = "+" if row['review_status'] == 'approved' else "!"
                    print(f"   [{status_icon}] {key} -> {row['team_id_master']} "
                          f"(method={row['match_method']}, status={row['review_status']}, "
                          f"division={row.get('division', 'N/A')})")
                    found_aliases.append(row)
            else:
                print(f"   [ ] {key} -> NOT FOUND")

        if not found_aliases:
            print("   WARNING: No aliases found! Games will create new teams on import.")

        # Also look for any alias with this base ID
        print(f"\n   All aliases with base ID '{pid}':")
        all_aliases = sb.table('team_alias_map').select(
            'provider_team_id, team_id_master, match_method, review_status'
        ).eq('provider_id', provider_uuid).like('provider_team_id', f'{pid}%').execute()

        if all_aliases.data:
            for row in all_aliases.data:
                print(f"   - {row['provider_team_id']} -> {row['team_id_master']} "
                      f"({row['review_status']})")
        else:
            print(f"   None found.")

    # --- Step 2: Check team in teams table ---
    team_uuids_to_check = set()

    if args.uuid:
        team_uuids_to_check.add(args.uuid)

    if args.provider_team_id and found_aliases:
        for alias in found_aliases:
            team_uuids_to_check.add(alias['team_id_master'])

    # Also search by name
    print(f"\n2. TEAMS TABLE SEARCH")
    if args.provider_team_id:
        # Search for teams with "RSL" or similar in name + matching age
        name_result = sb.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, is_deprecated'
        ).ilike('club_name', '%RSL%').execute()

        if name_result.data:
            age_filter = (args.age_group or '').lower()
            for team in name_result.data:
                team_age = (team.get('age_group') or '').lower()
                if not age_filter or team_age == age_filter:
                    dep = " [DEPRECATED]" if team.get('is_deprecated') else ""
                    print(f"   {team['team_id_master']} | {team['team_name']} | "
                          f"age={team['age_group']} | gender={team['gender']}{dep}")
                    team_uuids_to_check.add(team['team_id_master'])

    for uuid_val in team_uuids_to_check:
        team_result = sb.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, is_deprecated, provider_team_id'
        ).eq('team_id_master', uuid_val).execute()

        if team_result.data:
            t = team_result.data[0]
            dep = " [DEPRECATED]" if t.get('is_deprecated') else ""
            print(f"   UUID: {t['team_id_master']}")
            print(f"   Name: {t['team_name']}{dep}")
            print(f"   Club: {t.get('club_name', 'N/A')}")
            print(f"   Age: {t.get('age_group', 'N/A')} | Gender: {t.get('gender', 'N/A')}")
            print(f"   Provider ID: {t.get('provider_team_id', 'N/A')}")
        else:
            print(f"   UUID {uuid_val}: NOT FOUND in teams table")

    # --- Step 3: Check games ---
    print(f"\n3. GAMES IN DATABASE")
    for uuid_val in team_uuids_to_check:
        home_games = sb.table('games').select(
            'id', count='exact'
        ).eq('home_team_master_id', uuid_val).execute()

        away_games = sb.table('games').select(
            'id', count='exact'
        ).eq('away_team_master_id', uuid_val).execute()

        home_count = home_games.count if home_games.count is not None else len(home_games.data or [])
        away_count = away_games.count if away_games.count is not None else len(away_games.data or [])
        total = home_count + away_count

        # Also check by provider
        mod_home = sb.table('games').select(
            'id', count='exact'
        ).eq('home_team_master_id', uuid_val).eq('provider_id', provider_uuid).execute()

        mod_away = sb.table('games').select(
            'id', count='exact'
        ).eq('away_team_master_id', uuid_val).eq('provider_id', provider_uuid).execute()

        mod_home_count = mod_home.count if mod_home.count is not None else len(mod_home.data or [])
        mod_away_count = mod_away.count if mod_away.count is not None else len(mod_away.data or [])
        mod_total = mod_home_count + mod_away_count

        print(f"   {uuid_val}:")
        print(f"     Total games: {total} (home={home_count}, away={away_count})")
        print(f"     Modular11 games: {mod_total} (home={mod_home_count}, away={mod_away_count})")

        if total == 0:
            print(f"     >>> NO GAMES - this team will NOT appear in rankings")

    # --- Step 4: Check rankings ---
    print(f"\n4. CURRENT RANKINGS")
    for uuid_val in team_uuids_to_check:
        ranking_result = sb.table('rankings_full').select(
            'team_id, age_group, gender, games_played, national_power_score, '
            'rank_in_cohort, power_score_final, sos'
        ).eq('team_id', uuid_val).execute()

        if ranking_result.data:
            r = ranking_result.data[0]
            print(f"   {uuid_val}:")
            print(f"     Rank: #{r.get('rank_in_cohort', 'N/A')}")
            print(f"     PowerScore: {r.get('national_power_score', 'N/A')}")
            print(f"     Final: {r.get('power_score_final', 'N/A')}")
            print(f"     Games: {r.get('games_played', 0)} | SOS: {r.get('sos', 'N/A')}")
        else:
            print(f"   {uuid_val}: NOT IN RANKINGS")

    print(f"\n{'='*60}")
    print("DIAGNOSIS SUMMARY")
    print(f"{'='*60}")
    print("If a team has games but no ranking -> run calculate_rankings.py")
    print("If a team has 0 games -> alias may be missing/wrong age, check Step 1")
    print("If duplicate teams exist -> merge via team_merge_map")


if __name__ == '__main__':
    main()
