#!/usr/bin/env python3
"""
Diagnostic script to trace game count discrepancy for a specific team.
This replicates the filtering logic from data_adapter.py to identify which games are excluded.
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.backup')

def main():
    # Connect to Supabase
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY')

    if not supabase_url or not supabase_key:
        print("❌ Error: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env.backup")
        return

    print(f"🔗 Connecting to Supabase...")
    supabase = create_client(supabase_url, supabase_key)

    # 1. Find the team
    print(f"\n{'='*80}")
    print("STEP 1: Finding team '2014 Elite Phoenix United Futbol ClubAZ'")
    print(f"{'='*80}")

    team_result = supabase.table('teams_master').select(
        'team_id_master, team_name, state_code'
    ).ilike('team_name', '%2014 Elite Phoenix United%').execute()

    if not team_result.data:
        print("❌ Team not found")
        return

    team = team_result.data[0]
    team_id = team['team_id_master']
    team_name = team['team_name']

    print(f"✅ Found team:")
    print(f"   ID: {team_id}")
    print(f"   Name: {team_name}")
    print(f"   State: {team.get('state_code', 'N/A')}")

    # 2. Check rankings_full table
    print(f"\n{'='*80}")
    print("STEP 2: Checking rankings_full table")
    print(f"{'='*80}")

    rankings_result = supabase.table('rankings_full').select(
        'team_id, age_group, gender, games_played, wins, losses, draws, power_score_final'
    ).eq('team_id', team_id).execute()

    if rankings_result.data:
        for ranking in rankings_result.data:
            print(f"✅ Rankings data:")
            print(f"   Age Group: {ranking.get('age_group')}")
            print(f"   Gender: {ranking.get('gender')}")
            print(f"   Games Played (in rankings): {ranking.get('games_played')}")
            print(f"   Record: {ranking.get('wins', 0)}-{ranking.get('losses', 0)}-{ranking.get('draws', 0)}")
            print(f"   Power Score: {ranking.get('power_score_final', 0):.3f}")
    else:
        print("⚠️  No ranking data found for this team")

    # 3. Query all games for this team
    print(f"\n{'='*80}")
    print("STEP 3: Querying all games from database")
    print(f"{'='*80}")

    games_result = supabase.table('games').select(
        'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
        'home_score, away_score, home_team_id, away_team_id'
    ).or_(f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}').order(
        'game_date', desc=True
    ).execute()

    total_games = len(games_result.data)
    print(f"📊 Total games in database: {total_games}")

    if not games_result.data:
        print("❌ No games found")
        return

    # 4. Analyze games
    print(f"\n{'='*80}")
    print("STEP 4: Analyzing game data quality")
    print(f"{'='*80}")

    games_df = pd.DataFrame(games_result.data)
    games_df['game_date'] = pd.to_datetime(games_df['game_date'])

    # Check for missing scores
    missing_scores = games_df[
        games_df['home_score'].isna() | games_df['away_score'].isna()
    ]
    print(f"\n🔍 Games with missing scores: {len(missing_scores)}")
    if len(missing_scores) > 0:
        for _, game in missing_scores.iterrows():
            print(f"   - {game['game_date'].strftime('%Y-%m-%d')}: "
                  f"home_score={game['home_score']}, away_score={game['away_score']}")

    # Get valid games (with scores)
    valid_games = games_df[
        games_df['home_score'].notna() & games_df['away_score'].notna()
    ].copy()
    print(f"✅ Games with valid scores: {len(valid_games)}")

    # 5. Check team metadata for opponents
    print(f"\n{'='*80}")
    print("STEP 5: Checking opponent team metadata")
    print(f"{'='*80}")

    # Get all opponent team IDs
    opponent_ids = set()
    for _, game in valid_games.iterrows():
        if game['home_team_master_id'] == team_id:
            opponent_ids.add(game['away_team_master_id'])
        else:
            opponent_ids.add(game['home_team_master_id'])

    print(f"👥 Unique opponents: {len(opponent_ids)}")

    # Fetch team metadata for all teams (our team + opponents)
    all_team_ids = list(opponent_ids) + [team_id]
    teams_result = supabase.table('teams').select(
        'team_id_master, age_group, gender'
    ).in_('team_id_master', all_team_ids).execute()

    teams_metadata = pd.DataFrame(teams_result.data) if teams_result.data else pd.DataFrame()

    if not teams_metadata.empty:
        print(f"✅ Found metadata for {len(teams_metadata)} teams")

        # Check which teams are missing metadata
        missing_metadata_ids = set(all_team_ids) - set(teams_metadata['team_id_master'].tolist())
        if missing_metadata_ids:
            print(f"\n⚠️  Teams missing from teams table: {len(missing_metadata_ids)}")
            for tid in missing_metadata_ids:
                print(f"   - {tid}")

        # Check for teams with incomplete metadata
        incomplete_metadata = teams_metadata[
            teams_metadata['age_group'].isna() | teams_metadata['gender'].isna()
        ]
        if len(incomplete_metadata) > 0:
            print(f"\n⚠️  Teams with incomplete metadata: {len(incomplete_metadata)}")
            for _, team_meta in incomplete_metadata.iterrows():
                print(f"   - {team_meta['team_id_master']}: "
                      f"age_group={team_meta['age_group']}, gender={team_meta['gender']}")
    else:
        print("❌ No team metadata found")
        return

    # 6. Simulate data_adapter.py filtering
    print(f"\n{'='*80}")
    print("STEP 6: Simulating data_adapter.py filtering logic")
    print(f"{'='*80}")

    # Create lookup maps
    team_age_map = dict(zip(teams_metadata['team_id_master'], teams_metadata['age_group']))
    team_gender_map = dict(zip(teams_metadata['team_id_master'], teams_metadata['gender']))

    filtered_games = []
    excluded_games = []

    for _, game in valid_games.iterrows():
        home_id = game['home_team_master_id']
        away_id = game['away_team_master_id']

        home_age = team_age_map.get(home_id)
        home_gender = team_gender_map.get(home_id)
        away_age = team_age_map.get(away_id)
        away_gender = team_gender_map.get(away_id)

        # Check if all metadata is present (data_adapter.py lines 203-205)
        if not home_age or not home_gender or not away_age or not away_gender:
            excluded_games.append({
                'date': game['game_date'],
                'game_id': game['id'],
                'reason': 'Missing age/gender metadata',
                'home_age': home_age,
                'home_gender': home_gender,
                'away_age': away_age,
                'away_gender': away_gender,
                'home_id': home_id,
                'away_id': away_id,
            })
        else:
            filtered_games.append(game)

    print(f"\n✅ Games passing filter: {len(filtered_games)}")
    print(f"❌ Games excluded by filter: {len(excluded_games)}")

    if excluded_games:
        print(f"\n📋 Excluded games details:")
        for i, ex in enumerate(excluded_games, 1):
            print(f"\n   {i}. Date: {ex['date'].strftime('%Y-%m-%d')}")
            print(f"      Reason: {ex['reason']}")
            print(f"      Home team ({ex['home_id']}): age={ex['home_age']}, gender={ex['home_gender']}")
            print(f"      Away team ({ex['away_id']}): age={ex['away_age']}, gender={ex['away_gender']}")

    # 7. Check 365-day window
    print(f"\n{'='*80}")
    print("STEP 7: Checking 365-day time window filter")
    print(f"{'='*80}")

    today = datetime.now()
    cutoff_date = today - timedelta(days=365)

    print(f"Today: {today.strftime('%Y-%m-%d')}")
    print(f"365-day cutoff: {cutoff_date.strftime('%Y-%m-%d')}")

    within_window = [g for g in filtered_games if g['game_date'] >= cutoff_date]
    outside_window = [g for g in filtered_games if g['game_date'] < cutoff_date]

    print(f"✅ Games within 365-day window: {len(within_window)}")
    print(f"❌ Games outside 365-day window: {len(outside_window)}")

    if outside_window:
        print("\n   Games older than 365 days:")
        for game in outside_window:
            print(f"   - {game['game_date'].strftime('%Y-%m-%d')}")

    # 8. Check 30-game cap
    print(f"\n{'='*80}")
    print("STEP 8: Checking 30-game cap")
    print(f"{'='*80}")

    if len(within_window) > 30:
        print(f"⚠️  Team has {len(within_window)} games within 365 days")
        print(f"   Only most recent 30 will be used for rankings")
        ranked_games = len(within_window[:30])
        excluded_by_cap = len(within_window[30:])
    else:
        ranked_games = len(within_window)
        excluded_by_cap = 0

    print(f"✅ Games used for rankings: {ranked_games}")
    if excluded_by_cap > 0:
        print(f"❌ Games excluded by 30-game cap: {excluded_by_cap}")

    # 9. Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"\nTotal games in database: {total_games}")
    print(f"├─ Missing scores: {len(missing_scores)}")
    print(f"├─ Missing team metadata: {len(excluded_games)}")
    print(f"├─ Outside 365-day window: {len(outside_window)}")
    print(f"└─ Beyond 30-game cap: {excluded_by_cap}")
    print(f"\n✅ Games used for rankings: {ranked_games}")
    print(f"❌ Total excluded: {total_games - ranked_games}")

    if rankings_result.data:
        stored_games_played = rankings_result.data[0].get('games_played', 0)
        print(f"\n🎯 games_played in rankings_full table: {stored_games_played}")
        if stored_games_played != ranked_games:
            print(f"⚠️  MISMATCH: Expected {ranked_games}, found {stored_games_played}")
        else:
            print(f"✅ MATCH: Calculated value matches stored value")


if __name__ == '__main__':
    main()
