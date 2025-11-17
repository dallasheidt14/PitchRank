#!/usr/bin/env python3
"""
Simple diagnostic to check game counts using the views accessible to the frontend.
"""

import os
import sys
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.backup')

def main():
    # Use ANON key like the frontend does
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')  # Frontend uses anon key

    if not supabase_url or not supabase_key:
        print("❌ Error: Missing credentials")
        return

    print(f"🔗 Connecting to Supabase (as frontend)...")
    supabase = create_client(supabase_url, supabase_key)

    # Query rankings_view for teams matching the name
    print(f"\n{'='*80}")
    print("Searching rankings_view for '2014 Elite Phoenix United'")
    print(f"{'='*80}")

    result = supabase.table('rankings_view').select('*').ilike(
        'team_name', '%2014 Elite Phoenix United%'
    ).execute()

    if not result.data:
        print("❌ Team not found in rankings_view")
        return

    for team in result.data:
        print(f"\n✅ Found team in rankings:")
        print(f"   Team Name: {team.get('team_name')}")
        print(f"   Team ID: {team.get('team_id_master')}")
        print(f"   Age: {team.get('age')}")
        print(f"   Gender: {team.get('gender')}")
        print(f"   State: {team.get('state')}")
        print(f"   🎯 games_played (ranked): {team.get('games_played')}")
        print(f"   Record: {team.get('wins', 0)}-{team.get('losses', 0)}-{team.get('draws', 0)}")
        print(f"   Win %: {team.get('win_percentage', 0):.1f}%")
        print(f"   Power Score: {team.get('power_score_final', 0):.3f}")
        print(f"   Rank: #{team.get('rank_in_cohort_final')}")

        team_id = team.get('team_id_master')

        # Now count ALL games for this team (like frontend does)
        print(f"\n{'='*80}")
        print("Counting ALL games in database (like team details page)")
        print(f"{'='*80}")

        games_result = supabase.table('games').select(
            'id, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
        ).or_(f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}').execute()

        total_games = len(games_result.data) if games_result.data else 0
        print(f"   🎯 total_games_played (all time): {total_games}")

        # Check for games with missing scores
        if games_result.data:
            missing_scores = [g for g in games_result.data if g.get('home_score') is None or g.get('away_score') is None]
            print(f"   Games with valid scores: {total_games - len(missing_scores)}")
            print(f"   Games with missing scores: {len(missing_scores)}")

        # Show discrepancy
        ranked_games = team.get('games_played', 0)
        print(f"\n{'='*80}")
        print("DISCREPANCY ANALYSIS")
        print(f"{'='*80}")
        print(f"   Ranked games (from rankings): {ranked_games}")
        print(f"   Total games (from database): {total_games}")
        print(f"   ❌ DIFFERENCE: {total_games - ranked_games} games")

        # Check dates of games
        if games_result.data:
            games_sorted = sorted(games_result.data, key=lambda x: x.get('game_date', ''), reverse=True)
            print(f"\n   Date range of all games:")
            print(f"      Newest: {games_sorted[0].get('game_date')}")
            print(f"      Oldest: {games_sorted[-1].get('game_date')}")

            # Show all game dates
            print(f"\n   All {total_games} game dates:")
            for i, game in enumerate(games_sorted, 1):
                score_str = f"{game.get('home_score', '?')}-{game.get('away_score', '?')}" if game.get('home_score') is not None else "NO SCORE"
                print(f"      {i:2d}. {game.get('game_date')} - {score_str}")


if __name__ == '__main__':
    main()
