"""Scrape all boys games from Surf Sports tournament"""
import sys
import os
import json
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.scrapers.surfsports import SurfSportsScraper

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Mock supabase client (not needed for scraping)
class MockSupabase:
    def table(self, name):
        return self
    def select(self, *args):
        return self
    def eq(self, *args):
        return self
    def execute(self):
        return type('obj', (object,), {'data': []})()

def scrape_boys_games():
    """Scrape all boys games from event 4067"""
    print("Scraping all boys games from Surf College Cup Youngers (Event 4067)...")
    print("=" * 70)
    
    # Initialize scraper
    scraper = SurfSportsScraper(MockSupabase(), 'surfsports')
    
    # Scrape all boys games from event 4067
    games = scraper.scrape_tournament_games(
        event_id='4067',
        gender_filter='B'
    )
    
    print(f"\n✓ Found {len(games)} total game records ({len(games)//2} unique games)")
    print(f"  (Each game creates 2 records: one for home team, one for away team)\n")
    
    # Group by age group
    age_groups = {}
    for game in games:
        # Extract age group from competition or team name
        age_group = None
        if 'B2012' in game.competition or 'B2012' in game.team_name:
            age_group = 'B2012'
        elif 'B2013' in game.competition or 'B2013' in game.team_name:
            age_group = 'B2013'
        elif 'B2014' in game.competition or 'B2014' in game.team_name:
            age_group = 'B2014'
        elif 'B2015' in game.competition or 'B2015' in game.team_name:
            age_group = 'B2015'
        elif 'B2016' in game.competition or 'B2016' in game.team_name:
            age_group = 'B2016'
        elif 'B2017' in game.competition or 'B2017' in game.team_name:
            age_group = 'B2017'
        elif 'B2018' in game.competition or 'B2018' in game.team_name:
            age_group = 'B2018'
        
        if age_group:
            if age_group not in age_groups:
                age_groups[age_group] = []
            age_groups[age_group].append(game)
    
    # Print summary by age group
    print("Games by age group:")
    for age_group in sorted(age_groups.keys()):
        games_count = len(age_groups[age_group])
        unique_games = games_count // 2
        print(f"  {age_group}: {unique_games} games ({games_count} records)")
    
    # Save to JSON file
    output_file = f"data/exports/surfsports_boys_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    games_data = []
    for game in games:
        games_data.append({
            'team_name': game.team_name,
            'opponent_name': game.opponent_name,
            'game_date': game.game_date,
            'home_away': game.home_away,
            'goals_for': game.goals_for,
            'goals_against': game.goals_against,
            'result': game.result,
            'competition': game.competition,
            'venue': game.venue,
            'source_url': game.meta.get('source_url', '') if game.meta else '',
            'event_id': game.meta.get('event_id', '') if game.meta else '',
            'schedule_id': game.meta.get('schedule_id', '') if game.meta else '',
        })
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(games_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Saved {len(games_data)} game records to: {output_file}")
    
    # Print sample games
    print("\nSample games:")
    print("-" * 70)
    for i, game in enumerate(games[:10]):
        score_str = f"{game.goals_for}-{game.goals_against}" if game.goals_for is not None else "TBD"
        print(f"{i+1}. {game.team_name} vs {game.opponent_name}")
        print(f"   Date: {game.game_date}, Score: {score_str}, Result: {game.result}")
        print(f"   Venue: {game.venue}")
        print()
    
    return games

if __name__ == '__main__':
    scrape_boys_games()

