"""Check if missing games have scores"""
import csv
from pathlib import Path

csv_file = Path('data/raw/tgs/tgs_events_3952_3952_2025-12-12T17-33-46-839280+00-00.csv')
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Missing UIDs from previous check
missing_uids = [
    'tgs:2025-09-06:57557:57566',
    'tgs:2025-09-20:109207:46537',
    'tgs:2025-12-13:113760:46561',
    'tgs:2025-12-13:109207:46537',
    'tgs:2025-12-14:46537:46561'
]

print("="*80)
print("CHECKING MISSING GAMES FOR SCORES")
print("="*80)

for row in rows:
    game_date = row.get('game_date')
    team_id = row.get('team_id')
    opponent_id = row.get('opponent_id')
    
    if game_date and team_id and opponent_id:
        uid1 = f"tgs:{game_date}:{team_id}:{opponent_id}"
        uid2 = f"tgs:{game_date}:{opponent_id}:{team_id}"
        
        if uid1 in missing_uids or uid2 in missing_uids:
            goals_for = row.get('goals_for', '').strip()
            goals_against = row.get('goals_against', '').strip()
            
            print(f"\n{uid1}")
            print(f"  Team: {row.get('team_name')}")
            print(f"  Opponent: {row.get('opponent_name')}")
            print(f"  Date: {game_date}")
            print(f"  Goals For: {repr(goals_for)}")
            print(f"  Goals Against: {repr(goals_against)}")
            print(f"  Both Empty: {not goals_for and not goals_against}")









