import csv
from pathlib import Path

csv_path = Path('scrapers/modular11_scraper/output/modular11_results_20260116_151234.csv')

print("Checking CSV for game between teams 14 and 249 on 2025-09-06:\n")

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        game_date = row.get('game_date', '').strip()
        
        # Check if this is the game we're looking for
        if game_date == '2025-09-06' and ((team_id == '14' and opponent_id == '249') or (team_id == '249' and opponent_id == '14')):
            print(f"Found CSV row:")
            print(f"  team_id={team_id}, opponent_id={opponent_id}")
            print(f"  game_date={game_date}")
            print(f"  goals_for={row.get('goals_for')}, goals_against={row.get('goals_against')}")
            print(f"  home_away={row.get('home_away')}")
            print(f"  team_name={row.get('team_name')}")
            print(f"  opponent_name={row.get('opponent_name')}")
            
            # Determine actual scores
            if row.get('home_away') == 'H':
                # Team is home
                home_id = team_id
                away_id = opponent_id
                home_score = int(row.get('goals_for', 0))
                away_score = int(row.get('goals_against', 0))
            else:
                # Team is away
                home_id = opponent_id
                away_id = team_id
                home_score = int(row.get('goals_against', 0))
                away_score = int(row.get('goals_for', 0))
            
            print(f"\n  After perspective transformation:")
            print(f"  home={home_id}, away={away_id}")
            print(f"  home_score={home_score}, away_score={away_score}")
            print()
