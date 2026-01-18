#!/usr/bin/env python3
"""Verify what data is being extracted"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from src.scrapers.sincsports import SincSportsScraper
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create a minimal scraper instance
session = requests.Session()
adapter = HTTPAdapter(max_retries=Retry(total=3))
session.mount('https://', adapter)
session.headers.update({'User-Agent': 'Mozilla/5.0'})

scraper = SincSportsScraper.__new__(SincSportsScraper)
scraper.provider_code = 'sincsports'
scraper.BASE_URL = 'https://soccer.sincsports.com'
scraper.session = session
scraper.club_cache = {}
scraper.max_retries = 3
scraper.retry_delay = 2.0
scraper.delay_min = 2.0
scraper.delay_max = 3.0
scraper.timeout = 30

# Scrape games
games = scraper.scrape_team_games('NCM14762', since_date=datetime.now() - timedelta(days=365))

print(f'\n✅ Extracted {len(games)} games\n')
print('=' * 80)

for i, game in enumerate(games[:4], 1):
    print(f'\nGame {i}:')
    print(f'  Team Name: {game.team_name}')
    print(f'  Team Club: {game.meta.get("club_name") if game.meta else "N/A"}')
    print(f'  Opponent Name: {game.opponent_name}')
    print(f'  Opponent ID: {game.opponent_id}')
    print(f'  Opponent Club: {game.meta.get("opponent_club_name") if game.meta else "N/A"}')
    print(f'  Score: {game.goals_for}-{game.goals_against}')
    print(f'  Date: {game.game_date}')

print('\n' + '=' * 80)
print('\nSummary:')
print(f'  ✓ Team names extracted: {sum(1 for g in games if g.team_name)}/{len(games)}')
print(f'  ✓ Team club names extracted: {sum(1 for g in games if g.meta and g.meta.get("club_name"))}/{len(games)}')
print(f'  ✓ Opponent names extracted: {sum(1 for g in games if g.opponent_name and g.opponent_name != "Unknown")}/{len(games)}')
print(f'  ✓ Opponent club names extracted: {sum(1 for g in games if g.meta and g.meta.get("opponent_club_name"))}/{len(games)}')


















