#!/usr/bin/env python3
"""
Discover U12 team IDs by following opponent links from games
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time

sys.path.append(str(Path(__file__).parent.parent))

from src.scrapers.sincsports import SincSportsScraper

# Initialize scraper
scraper = SincSportsScraper(None, 'sincsports')

# Start with known U12 teams
start_teams = [
    "NCM14762",  # NC Fusion U12 PRE ECNL BOYS RED
    "SCM14140",  # FCC 2014 Boys Gold - BA
    "NCM143BE",  # 14 (12U) CSA UM Elite
    "NCM143B5",  # 14 (12U) CSA North Elite
    "NCM1473B",  # 14 (12U) CSA CLT Pre-ECNL Yellow
    "NCM14761",  # 14 (12u) Acfc Wolverines
    "NCM14763",  # U12 PRE ECNL BOYS WHITE
    "NCM143BC",  # 14 (12U) CSA Uptown King
    "NCM143BF",  # 14 (12U) CSA York King
    "SCM14141",  # RH Surge 2014 Boys Navy
]

all_team_ids = set(start_teams)
processed = set()
to_process = set(start_teams)
max_iterations = 8  # Go deeper to find more teams
target_count = 50

print(f"Starting discovery with {len(start_teams)} seed teams...")
print(f"Target: {target_count} unique U12 teams\n")

iteration = 0
while to_process and iteration < max_iterations and len(all_team_ids) < target_count:
    iteration += 1
    current_batch = list(to_process)[:15]  # Process up to 15 at a time
    to_process.clear()
    
    print(f"Iteration {iteration}: Processing {len(current_batch)} teams...")
    
    for team_id in current_batch:
        if team_id in processed:
            continue
        processed.add(team_id)
        
        try:
            games = scraper.scrape_team_games(team_id, since_date=datetime.now() - timedelta(days=365))
            
            new_opponents = 0
            for game in games:
                if game.opponent_id and game.opponent_id not in processed and game.opponent_id not in all_team_ids:
                    all_team_ids.add(game.opponent_id)
                    to_process.add(game.opponent_id)
                    new_opponents += 1
            
            print(f"  {team_id}: Found {len(games)} games, {new_opponents} new opponents (Total: {len(all_team_ids)})")
            
            # Rate limiting
            time.sleep(1)
            
        except Exception as e:
            print(f"  {team_id}: Error - {e}")
    
    print(f"  Total unique teams: {len(all_team_ids)}\n")
    
    if len(all_team_ids) >= target_count:
        break

print(f"\n✅ Discovery complete!")
print(f"Found {len(all_team_ids)} unique U12 team IDs\n")

# Output as list for easy copy-paste
print("Team IDs for import:")
team_list = sorted(all_team_ids)[:target_count]  # Limit to target count
for i, team_id in enumerate(team_list, 1):
    print(f'  "{team_id}",', end='')
    if i % 10 == 0:
        print()  # New line every 10 teams
if len(team_list) % 10 != 0:
    print()  # Final newline

print(f"\nTotal: {len(team_list)} teams")

