import csv
from pathlib import Path

csv_path = Path('scrapers/modular11_scraper/output/modular11_results_20260116_151234.csv')

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    row = next(reader)
    
    print('Sample CSV row:')
    print(f'  age_group: {row.get("age_group")}')
    print(f'  mls_division: {row.get("mls_division")}')
    print(f'  team_id: {row.get("team_id")}')
    print(f'  opponent_id: {row.get("opponent_id")}')
    print(f'  game_date: {row.get("game_date")}')
    
    # Generate game_uid like the matcher does
    age_group = row.get('age_group', '').upper() if row.get('age_group') else None
    division = row.get('mls_division', '').upper() if row.get('mls_division') else None
    
    def normalize_team_id(team_id):
        if not team_id or team_id == '' or str(team_id).strip().lower() == 'none':
            return ''
        try:
            return str(int(float(str(team_id))))
        except (ValueError, TypeError):
            return str(team_id).strip()
    
    team1 = normalize_team_id(row.get('team_id', ''))
    team2 = normalize_team_id(row.get('opponent_id', ''))
    sorted_teams = sorted([team1, team2])
    
    if age_group and division:
        game_uid = f"modular11:{row.get('game_date')}:{sorted_teams[0]}:{sorted_teams[1]}:{age_group}:{division}"
    elif age_group:
        game_uid = f"modular11:{row.get('game_date')}:{sorted_teams[0]}:{sorted_teams[1]}:{age_group}"
    else:
        game_uid = f"modular11:{row.get('game_date')}:{sorted_teams[0]}:{sorted_teams[1]}"
    
    print(f'\nGenerated game_uid: {game_uid}')
