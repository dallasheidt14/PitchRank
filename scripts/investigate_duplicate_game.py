#!/usr/bin/env python3
"""
Investigate duplicate games for team afead932-0b7d-427f-a486-a50aa0b6ba1a

This script queries Supabase to find and analyze the two suspect games:
  - Feb 14, 2026 | W 9-0 | City of Las Vegas Mayor's Cup
  - Feb 14, 2026 | W 9-0 | 2014 Chapman Auto Group

One of these is legitimate, one appears to be a duplicate.

Root cause analysis: The frontend displays `game.competition || game.division_name`
as the competition column. "City of Las Vegas Mayor's Cup" comes from the `competition`
field, while "2014 Chapman Auto Group" comes from `division_name` fallback when
`competition` is NULL. This means both records are likely the same game imported
through different paths with different field population.

Usage:
    python scripts/investigate_duplicate_game.py
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

TEAM_ID = 'afead932-0b7d-427f-a486-a50aa0b6ba1a'


def main():
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )

    print("=" * 80)
    print(f"INVESTIGATING TEAM: {TEAM_ID}")
    print("=" * 80)

    # 1. Team info
    print("\n--- TEAM INFO ---")
    team = supabase.table('teams').select(
        'team_name, club_name, age_group, gender, state_code, provider_team_id, birth_year'
    ).eq('team_id_master', TEAM_ID).execute()
    if team.data:
        for t in team.data:
            print(f"  Name: {t['team_name']}")
            print(f"  Club: {t.get('club_name')}")
            print(f"  Age: {t['age_group']}, Gender: {t['gender']}")
            print(f"  State: {t.get('state_code')}")
            print(f"  Provider Team ID: {t['provider_team_id']}")
            print(f"  Birth Year: {t.get('birth_year')}")
    else:
        print(f"  NOT FOUND!")
        return

    # 2. Aliases
    print("\n--- ALIASES ---")
    aliases = supabase.table('team_alias_map').select(
        'provider_team_id, match_method, match_confidence, provider_id'
    ).eq('team_id_master', TEAM_ID).execute()
    for a in aliases.data:
        print(f"  Provider ID: {a['provider_team_id']}, Method: {a['match_method']}, "
              f"Confidence: {a['match_confidence']}, Provider: {a['provider_id']}")

    # 3. All games
    print("\n--- ALL GAMES ---")
    games = supabase.table('games').select(
        'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
        'home_provider_id, away_provider_id, home_score, away_score, result, '
        'competition, division_name, event_name, venue, provider_id, is_excluded, '
        'scraped_at, created_at, source_url'
    ).or_(
        f'home_team_master_id.eq.{TEAM_ID},away_team_master_id.eq.{TEAM_ID}'
    ).order('game_date').execute()

    print(f"  Total games: {len(games.data)}")

    # 4. Identify the suspect games
    suspect_games = []
    print("\n--- FULL GAME LIST ---")
    for g in games.data:
        is_home = g['home_team_master_id'] == TEAM_ID
        role = 'HOME' if is_home else 'AWAY'
        score = f"{g['home_score']}-{g['away_score']}"
        opp_master = g['away_team_master_id'] if is_home else g['home_team_master_id']

        display_comp = g.get('competition') or g.get('division_name') or '—'
        print(f"  {g['game_date']} | {role} | {score} | comp_display=\"{display_comp}\" | excluded={g.get('is_excluded')}")
        print(f"    game_uid={g['game_uid']}")
        print(f"    home_pid={g['home_provider_id']} | away_pid={g['away_provider_id']}")
        print(f"    competition={g.get('competition')}")
        print(f"    division_name={g.get('division_name')}")
        print(f"    event_name={g.get('event_name')}")
        print(f"    provider_id={g.get('provider_id')}")
        print(f"    scraped_at={g.get('scraped_at')}")
        print(f"    opp_master_id={opp_master}")
        print()

        # Check if this is a 9-0 game around Feb 14
        if g['game_date'] and '2026-02' in g['game_date']:
            h_score = g.get('home_score') or 0
            a_score = g.get('away_score') or 0
            if (is_home and h_score == 9 and a_score == 0) or \
               (not is_home and a_score == 9 and h_score == 0):
                suspect_games.append(g)

    # 5. Analyze suspect games
    if len(suspect_games) >= 2:
        print("=" * 80)
        print("SUSPECT DUPLICATE GAMES FOUND:")
        print("=" * 80)
        for i, g in enumerate(suspect_games):
            print(f"\n  Game {i+1}:")
            print(f"    ID: {g['id']}")
            print(f"    Date: {g['game_date']}")
            print(f"    game_uid: {g['game_uid']}")
            print(f"    Score: {g['home_score']}-{g['away_score']}")
            print(f"    home_provider_id: {g['home_provider_id']}")
            print(f"    away_provider_id: {g['away_provider_id']}")
            print(f"    competition: {g.get('competition')}")
            print(f"    division_name: {g.get('division_name')}")
            print(f"    event_name: {g.get('event_name')}")
            print(f"    provider_id: {g.get('provider_id')}")
            print(f"    scraped_at: {g.get('scraped_at')}")
            print(f"    created_at: {g.get('created_at')}")
            print(f"    source_url: {g.get('source_url')}")

        # Compare the two
        print("\n--- COMPARISON ---")
        g1, g2 = suspect_games[0], suspect_games[1]

        same_uid = g1['game_uid'] == g2['game_uid']
        same_provider = g1.get('provider_id') == g2.get('provider_id')
        same_home_pid = g1['home_provider_id'] == g2['home_provider_id']
        same_away_pid = g1['away_provider_id'] == g2['away_provider_id']
        swapped_pids = (g1['home_provider_id'] == g2['away_provider_id'] and
                        g1['away_provider_id'] == g2['home_provider_id'])

        print(f"  Same game_uid? {same_uid}")
        print(f"  Same provider? {same_provider}")
        print(f"  Same home_provider_id? {same_home_pid}")
        print(f"  Same away_provider_id? {same_away_pid}")
        print(f"  Swapped provider IDs? {swapped_pids}")

        if not same_uid:
            print("\n  >>> DIFFERENT game_uids! This means different provider team IDs were used.")
            print("  >>> ROOT CAUSE: Likely scraped from both team scraper (rankings IDs)")
            print("  >>>   AND event scraper (registration IDs), producing different game_uids.")
            print("  >>>   The dedup logic only catches duplicates with matching game_uids.")
        elif same_uid and not same_provider:
            print("\n  >>> Same game_uid but different providers!")
            print("  >>> ROOT CAUSE: Cross-provider duplicate (game_uid prefix differs).")
        else:
            print("\n  >>> Same game_uid AND same provider. This should have been caught by dedup.")
            print("  >>> Check if there's a bug in the composite key or game_uid check logic.")

        # Determine which to keep
        print("\n--- RECOMMENDATION ---")
        # Prefer the one with more complete metadata (competition field populated)
        g1_has_comp = bool(g1.get('competition'))
        g2_has_comp = bool(g2.get('competition'))

        if g1_has_comp and not g2_has_comp:
            keep, remove = g1, g2
        elif g2_has_comp and not g1_has_comp:
            keep, remove = g2, g1
        else:
            # Both have or neither has competition — keep the earlier one
            keep, remove = g1, g2

        print(f"  KEEP game: {keep['id']}")
        print(f"    Reason: {'Has competition field populated' if (keep.get('competition')) else 'Earlier import'}")
        print(f"    competition={keep.get('competition')}, division={keep.get('division_name')}")
        print(f"  EXCLUDE game: {remove['id']}")
        print(f"    competition={remove.get('competition')}, division={remove.get('division_name')}")
        print()
        print(f"  To exclude the duplicate, run:")
        print(f"    UPDATE games SET is_excluded = true WHERE id = '{remove['id']}';")
        print()
        print(f"  Or via Supabase client:")
        print(f"    supabase.table('games').update({{'is_excluded': True}}).eq('id', '{remove['id']}').execute()")

    elif len(suspect_games) == 1:
        print("\n  Only one 9-0 game found in Feb 2026. Expanding search...")
        # Search more broadly
        feb_games = [g for g in games.data if g.get('game_date', '').startswith('2026-02')]
        print(f"  All Feb 2026 games: {len(feb_games)}")
        for g in feb_games:
            print(f"    {g['game_date']} | {g['home_score']}-{g['away_score']} | "
                  f"comp={g.get('competition')} | div={g.get('division_name')}")
    else:
        print("\n  No 9-0 games found in Feb 2026. The games may have different dates than expected.")
        print("  Showing all games with 9-0 score:")
        for g in games.data:
            h, a = g.get('home_score', 0) or 0, g.get('away_score', 0) or 0
            if (h == 9 and a == 0) or (h == 0 and a == 9):
                is_home = g['home_team_master_id'] == TEAM_ID
                role = 'HOME' if is_home else 'AWAY'
                print(f"    {g['game_date']} | {role} | {h}-{a} | "
                      f"comp={g.get('competition')} | div={g.get('division_name')}")
                print(f"      game_uid={g['game_uid']}")

    # 6. Check for broader duplicate patterns
    print("\n--- BROADER DUPLICATE CHECK ---")
    game_dates = {}
    for g in games.data:
        key = g['game_date']
        if key not in game_dates:
            game_dates[key] = []
        game_dates[key].append(g)

    dupes = {k: v for k, v in game_dates.items() if len(v) > 2}
    if dupes:
        print(f"  Dates with >2 games (possible duplicates):")
        for date, date_games in sorted(dupes.items()):
            print(f"    {date}: {len(date_games)} games")
            for g in date_games:
                print(f"      {g['home_score']}-{g['away_score']} | uid={g['game_uid'][:40]}... | "
                      f"comp={g.get('competition')}")
    else:
        print("  No dates with >2 games found.")

    # Also check for same game_date + similar score combinations
    print("\n--- SAME DATE + SCORE PAIRS ---")
    for date, date_games in sorted(game_dates.items()):
        if len(date_games) < 2:
            continue
        # Check for same scores
        score_groups = {}
        for g in date_games:
            is_home = g['home_team_master_id'] == TEAM_ID
            if is_home:
                score_key = f"{g['home_score']}-{g['away_score']}"
            else:
                score_key = f"{g['away_score']}-{g['home_score']}"
            if score_key not in score_groups:
                score_groups[score_key] = []
            score_groups[score_key].append(g)

        for score, score_games in score_groups.items():
            if len(score_games) > 1:
                print(f"  {date} | Score {score} appears {len(score_games)} times:")
                for g in score_games:
                    print(f"    game_uid={g['game_uid']}")
                    print(f"    comp={g.get('competition')} | div={g.get('division_name')}")
                    print(f"    home_pid={g['home_provider_id']} | away_pid={g['away_provider_id']}")
                    print()


if __name__ == '__main__':
    main()
