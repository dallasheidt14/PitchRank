#!/usr/bin/env python3
"""
Quick diagnostic: Check if a Modular11 team's games are correctly linked
in the database and will appear in rankings. Also checks opponent data
to diagnose SOS issues.

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

    found_aliases = []

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

    print(f"\n2. TEAMS TABLE")
    for uuid_val in team_uuids_to_check:
        team_result = sb.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, '
            'is_deprecated, provider_team_id, state_code'
        ).eq('team_id_master', uuid_val).execute()

        if team_result.data:
            t = team_result.data[0]
            dep = " [DEPRECATED]" if t.get('is_deprecated') else ""
            print(f"   UUID: {t['team_id_master']}")
            print(f"   Name: {t['team_name']}{dep}")
            print(f"   Club: {t.get('club_name', 'N/A')}")
            print(f"   Age: {t.get('age_group', 'N/A')} | Gender: {t.get('gender', 'N/A')}")
            print(f"   State: {t.get('state_code', 'NULL/MISSING')}")
            print(f"   Provider ID: {t.get('provider_team_id', 'N/A')}")
        else:
            print(f"   UUID {uuid_val}: NOT FOUND in teams table")

    # --- Step 3: Check games ---
    print(f"\n3. GAMES IN DATABASE")
    opponent_uuids = set()  # Collect opponent UUIDs for step 5

    for uuid_val in team_uuids_to_check:
        home_games = sb.table('games').select(
            'id, away_team_master_id', count='exact'
        ).eq('home_team_master_id', uuid_val).execute()

        away_games = sb.table('games').select(
            'id, home_team_master_id', count='exact'
        ).eq('away_team_master_id', uuid_val).execute()

        home_count = home_games.count if home_games.count is not None else len(home_games.data or [])
        away_count = away_games.count if away_games.count is not None else len(away_games.data or [])
        total = home_count + away_count

        # Collect opponent UUIDs
        if home_games.data:
            for g in home_games.data:
                if g.get('away_team_master_id'):
                    opponent_uuids.add(g['away_team_master_id'])
        if away_games.data:
            for g in away_games.data:
                if g.get('home_team_master_id'):
                    opponent_uuids.add(g['home_team_master_id'])

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
            'rank_in_cohort, rank_in_cohort_ml, power_score_final, sos, sos_raw, '
            'sos_norm, sos_norm_national, sos_rank_national, off_norm, def_norm, '
            'powerscore_ml, powerscore_adj'
        ).eq('team_id', uuid_val).execute()

        if ranking_result.data:
            r = ranking_result.data[0]
            print(f"   {uuid_val}:")
            print(f"     Rank (ML): #{r.get('rank_in_cohort_ml', 'N/A')}")
            print(f"     Rank (base): #{r.get('rank_in_cohort', 'N/A')}")
            print(f"     PowerScore ML: {r.get('powerscore_ml', 'N/A')}")
            print(f"     PowerScore Adj: {r.get('powerscore_adj', 'N/A')}")
            print(f"     PowerScore Final: {r.get('power_score_final', 'N/A')}")
            print(f"     Games: {r.get('games_played', 0)}")
            print(f"     OFF norm: {r.get('off_norm', 'N/A')}")
            print(f"     DEF norm: {r.get('def_norm', 'N/A')}")
            print(f"     SOS raw: {r.get('sos_raw', 'N/A')}")
            print(f"     SOS norm (cohort): {r.get('sos_norm', 'N/A')}")
            print(f"     SOS norm (national): {r.get('sos_norm_national', 'N/A')}")
            print(f"     SOS rank (national): #{r.get('sos_rank_national', 'N/A')}")
        else:
            print(f"   {uuid_val}: NOT IN RANKINGS")

    # --- Step 5: Check opponents ---
    # Remove self from opponents
    opponent_uuids -= team_uuids_to_check

    if opponent_uuids:
        print(f"\n5. OPPONENT ANALYSIS ({len(opponent_uuids)} unique opponents)")

        # Check opponent team metadata
        opp_with_state = 0
        opp_without_state = 0
        opp_with_age = 0
        opp_without_age = 0
        opp_in_rankings = 0
        opp_not_in_rankings = 0
        opp_games_total = 0
        opp_sos_values = []
        opp_details = []

        for opp_uuid in opponent_uuids:
            # Get team info
            opp_team = sb.table('teams').select(
                'team_id_master, team_name, age_group, gender, state_code'
            ).eq('team_id_master', opp_uuid).execute()

            team_name = 'UNKNOWN'
            has_state = False
            has_age = False
            if opp_team.data:
                t = opp_team.data[0]
                team_name = t.get('team_name', 'UNKNOWN')
                has_state = bool(t.get('state_code'))
                has_age = bool(t.get('age_group'))
                if has_state:
                    opp_with_state += 1
                else:
                    opp_without_state += 1
                if has_age:
                    opp_with_age += 1
                else:
                    opp_without_age += 1

            # Count opponent's games
            opp_home = sb.table('games').select('id', count='exact').eq('home_team_master_id', opp_uuid).execute()
            opp_away = sb.table('games').select('id', count='exact').eq('away_team_master_id', opp_uuid).execute()
            opp_game_count = (opp_home.count or 0) + (opp_away.count or 0)
            opp_games_total += opp_game_count

            # Check rankings
            opp_ranking = sb.table('rankings_full').select(
                'games_played, sos_raw, sos_norm, off_norm, def_norm, '
                'powerscore_ml, rank_in_cohort_ml'
            ).eq('team_id', opp_uuid).execute()

            opp_sos = None
            opp_off = None
            opp_def = None
            opp_ps = None
            opp_rank = None
            if opp_ranking.data:
                opp_in_rankings += 1
                r = opp_ranking.data[0]
                opp_sos = r.get('sos_raw')
                opp_off = r.get('off_norm')
                opp_def = r.get('def_norm')
                opp_ps = r.get('powerscore_ml')
                opp_rank = r.get('rank_in_cohort_ml')
                if opp_sos is not None:
                    opp_sos_values.append(opp_sos)
            else:
                opp_not_in_rankings += 1

            opp_details.append({
                'uuid': opp_uuid,
                'name': team_name,
                'games': opp_game_count,
                'has_state': has_state,
                'has_age': has_age,
                'in_rankings': bool(opp_ranking.data),
                'sos': opp_sos,
                'off': opp_off,
                'def': opp_def,
                'ps': opp_ps,
                'rank': opp_rank
            })

        # Summary
        print(f"\n   OPPONENT METADATA:")
        print(f"     With state_code: {opp_with_state}/{len(opponent_uuids)}")
        print(f"     With age_group: {opp_with_age}/{len(opponent_uuids)}")
        print(f"     In rankings: {opp_in_rankings}/{len(opponent_uuids)}")
        print(f"     NOT in rankings: {opp_not_in_rankings}/{len(opponent_uuids)}")
        print(f"     Avg games per opponent: {opp_games_total / len(opponent_uuids):.1f}")

        if opp_not_in_rankings > 0:
            print(f"\n   >>> WARNING: {opp_not_in_rankings} opponents NOT in rankings!")
            print(f"       These default to UNRANKED_SOS_BASE=0.35 in SOS calculation")
            print(f"       This DRAMATICALLY lowers SOS for this team")

        if opp_sos_values:
            avg_opp_sos = sum(opp_sos_values) / len(opp_sos_values)
            print(f"\n   OPPONENT SOS VALUES (from rankings_full):")
            print(f"     Avg opponent SOS_raw: {avg_opp_sos:.4f}")
            print(f"     Min: {min(opp_sos_values):.4f}")
            print(f"     Max: {max(opp_sos_values):.4f}")

        # Per-opponent detail
        print(f"\n   OPPONENT DETAILS:")
        opp_details.sort(key=lambda x: x.get('ps') or 0, reverse=True)
        for opp in opp_details:
            state_str = "S" if opp['has_state'] else "!"
            rank_str = f"#{opp['rank']}" if opp['rank'] else "UNRANKED"
            off_str = f"{opp['off']:.2f}" if opp['off'] is not None else "N/A"
            def_str = f"{opp['def']:.2f}" if opp['def'] is not None else "N/A"
            sos_str = f"{opp['sos']:.4f}" if opp['sos'] is not None else "N/A"
            ps_str = f"{opp['ps']:.4f}" if opp['ps'] is not None else "N/A"
            print(f"     [{state_str}] {opp['name'][:35]:35s} | games={opp['games']:3d} | "
                  f"off={off_str} def={def_str} sos={sos_str} ps={ps_str} {rank_str}")

    print(f"\n{'='*60}")
    print("DIAGNOSIS GUIDE")
    print(f"{'='*60}")
    print("If opponents are NOT IN RANKINGS -> their games may be missing")
    print("  or their team metadata (age/gender) is missing")
    print("If opponents have NO state_code -> SCF treats them as isolated")
    print("If opponent SOS_raw is low -> isolated cluster effect")
    print("  (HD teams only play each other, no external benchmark)")
    print("If a team has games but no ranking -> run calculate_rankings.py")
    print("If a team has 0 games -> alias may be missing/wrong age")


if __name__ == '__main__':
    main()
