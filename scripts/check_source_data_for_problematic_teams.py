"""Check the original scraped CSV data for problematic teams"""
import csv
from pathlib import Path

print("=" * 70)
print("CHECKING SOURCE CSV DATA FOR PROBLEMATIC TEAMS")
print("=" * 70)

# Check U16 CSV for team_id 371 (Achilles) and 45 (Sacramento Republic)
csv_path = Path('scrapers/modular11_scraper/output/modular11_u16.csv')

if csv_path.exists():
    print(f"\nChecking U16 CSV: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        games_371 = []
        games_45 = []
        
        for row in reader:
            team_id = row.get('team_id', '')
            opponent_id = row.get('opponent_id', '')
            age_group = row.get('age_group', '')
            
            if '371' in str(team_id) or '371' in str(opponent_id):
                games_371.append(row)
            if '45' in str(team_id) or '45' in str(opponent_id):
                games_45.append(row)
    
    print(f"\nFound {len(games_371)} games involving team_id 371 (Achilles)")
    print(f"Found {len(games_45)} games involving team_id 45 (Sacramento Republic)")
    
    if games_371:
        print("\nSample games with team_id 371:")
        for g in games_371[:5]:
            print(f"  Date: {g.get('game_date')}")
            print(f"    Team: {g.get('team_name')} (ID: {g.get('team_id')}, Age: {g.get('age_group')})")
            print(f"    Opponent: {g.get('opponent_name')} (ID: {g.get('opponent_id')}, Age: {g.get('age_group')})")
            print()
    
    if games_45:
        print("\nSample games with team_id 45:")
        for g in games_45[:5]:
            print(f"  Date: {g.get('game_date')}")
            print(f"    Team: {g.get('team_name')} (ID: {g.get('team_id')}, Age: {g.get('age_group')})")
            print(f"    Opponent: {g.get('opponent_name')} (ID: {g.get('opponent_id')}, Age: {g.get('age_group')})")
            print()

# Check U13 CSV for these same team IDs (to see if they appear there too)
csv_path_u13 = Path('scrapers/modular11_scraper/output/modular11_u13.csv')

if csv_path_u13.exists():
    print("\n" + "=" * 70)
    print("CHECKING U13 CSV FOR SAME TEAM IDs")
    print("=" * 70)
    
    with open(csv_path_u13, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        games_371_u13 = []
        games_45_u13 = []
        
        for row in reader:
            team_id = row.get('team_id', '')
            opponent_id = row.get('opponent_id', '')
            
            if '371' in str(team_id) or '371' in str(opponent_id):
                games_371_u13.append(row)
            if '45' in str(team_id) or '45' in str(opponent_id):
                games_45_u13.append(row)
    
    print(f"\nFound {len(games_371_u13)} U13 games involving team_id 371")
    print(f"Found {len(games_45_u13)} U13 games involving team_id 45")
    
    if games_371_u13:
        print("\n⚠️  Team ID 371 appears in U13 CSV!")
        print("Sample:")
        for g in games_371_u13[:3]:
            print(f"  Date: {g.get('game_date')}, Team: {g.get('team_name')}, Opponent: {g.get('opponent_name')}")
    
    if games_45_u13:
        print("\n⚠️  Team ID 45 appears in U13 CSV!")
        print("Sample:")
        for g in games_45_u13[:3]:
            print(f"  Date: {g.get('game_date')}, Team: {g.get('team_name')}, Opponent: {g.get('opponent_name')}")

print("\n" + "=" * 70)
print("ROOT CAUSE ANALYSIS")
print("=" * 70)
print("""
If team_id 371 or 45 appears in BOTH U13 and U16 CSVs, this indicates:

1. Modular11 uses the SAME provider_team_id for multiple age groups
2. The scraper correctly scraped games from both age brackets
3. During import, the system created teams with the age_group from the CSV
4. But some games from U13 CSV were matched to U16 teams (or vice versa)

This is the EXACT problem we fixed with age validation in _match_by_provider_id,
but these games were imported BEFORE that fix was in place.
""")













