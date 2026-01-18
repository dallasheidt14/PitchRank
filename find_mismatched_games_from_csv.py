#!/usr/bin/env python3
"""
Find incorrectly matched games by comparing CSV data with database matches.

This script:
1. Reads the original CSV to get expected age groups
2. Compares with what was actually matched in the database
3. Identifies mismatches
"""
import os
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
from collections import defaultdict

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)
console = Console()

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    console.print("[red]Error: Modular11 provider not found[/red]")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

def normalize_age_group(age_str: str) -> str:
    """Normalize age group to lowercase format"""
    if not age_str:
        return ''
    age_str = str(age_str).strip().lower()
    if not age_str.startswith('u'):
        age_str = f"u{age_str}"
    return age_str

def generate_game_uid(provider, game_date, team1_id, team2_id):
    """Generate game UID same way as import script"""
    from src.models.game_matcher import GameHistoryMatcher
    from src.utils.enhanced_validators import parse_game_date
    
    try:
        date_obj = parse_game_date(game_date)
        game_date_normalized = date_obj.strftime('%Y-%m-%d')
    except ValueError:
        game_date_normalized = game_date
    
    return GameHistoryMatcher.generate_game_uid(
        provider=provider,
        game_date=game_date_normalized,
        team1_id=str(team1_id),
        team2_id=str(team2_id)
    )

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]FINDING MISMATCHED GAMES FROM CSV[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Read CSV
    csv_path = Path(r"C:\PitchRank\mod11 u14 results.csv")
    if not csv_path.exists():
        console.print(f"[red]Error: CSV file not found: {csv_path}[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold]Step 1:[/bold] Reading CSV: {csv_path}")
    
    csv_games = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_games.append({
                'team_id': row.get('team_id', '').strip(),
                'opponent_id': row.get('opponent_id', '').strip(),
                'team_name': row.get('team_name', '').strip(),
                'age_group': normalize_age_group(row.get('age_group', '')),
                'game_date': row.get('game_date', '').strip(),
                'mls_division': row.get('mls_division', '').strip(),
            })
    
    console.print(f"[green]Found {len(csv_games)} games in CSV[/green]")
    
    # Get teams from database
    console.print("\n[bold]Step 2:[/bold] Fetching teams from database...")
    teams_result = supabase.table('teams').select('team_id_master, age_group, team_name').execute()
    teams_by_id = {team['team_id_master']: team for team in teams_result.data}
    console.print(f"[green]Found {len(teams_by_id)} teams[/green]")
    
    # Analyze mismatches
    console.print("\n[bold]Step 3:[/bold] Comparing CSV with database matches...")
    
    mismatches = []
    checked_count = 0
    found_count = 0
    
    for csv_game in csv_games:
        # Generate game UID
        game_uid = generate_game_uid(
            'modular11',
            csv_game['game_date'],
            csv_game['team_id'],
            csv_game['opponent_id']
        )
        
        # Get game from database
        db_game = supabase.table('games').select(
            'id, game_uid, home_provider_id, away_provider_id, '
            'home_team_master_id, away_team_master_id'
        ).eq('provider_id', modular11_provider_id).eq('game_uid', game_uid).execute()
        
        checked_count += 1
        
        if not db_game.data:
            continue  # Game not in database
        
        found_count += 1
        
        db_game = db_game.data[0]
        expected_age = csv_game['age_group']
        
        # Check home team (team_id from CSV perspective)
        # The CSV row represents team_id's perspective, so check if it's home or away
        home_provider_id = str(db_game.get('home_provider_id', ''))
        away_provider_id = str(db_game.get('away_provider_id', ''))
        
        # Debug: Check first few games with team_id 456
        debug_this = csv_game['team_id'] == '456' and len(mismatches) < 3
        
        # Check if team_id matches home
        if home_provider_id == csv_game['team_id']:
            matched_team_id = db_game.get('home_team_master_id')
            if matched_team_id:
                matched_team = teams_by_id.get(matched_team_id)
                if matched_team:
                    matched_age = normalize_age_group(matched_team.get('age_group', ''))
                    if debug_this:
                        print(f"DEBUG: {csv_game['team_name']} - Expected: {expected_age}, Matched: {matched_age}")
                    if matched_age != expected_age:
                        mismatches.append({
                            'game_uid': game_uid,
                            'game_date': csv_game['game_date'],
                            'team_type': 'home',
                            'provider_id': csv_game['team_id'],
                            'team_name': csv_game['team_name'],
                            'expected_age': expected_age,
                            'matched_age': matched_age,
                            'matched_team_id': matched_team_id,
                            'matched_team_name': matched_team.get('team_name', 'Unknown'),
                            'division': csv_game['mls_division']
                        })
        
        # Check if team_id matches away (opponent's perspective in CSV)
        elif away_provider_id == csv_game['team_id']:
            matched_team_id = db_game.get('away_team_master_id')
            if matched_team_id:
                matched_team = teams_by_id.get(matched_team_id)
                if matched_team:
                    matched_age = normalize_age_group(matched_team.get('age_group', ''))
                    if debug_this:
                        print(f"DEBUG: {csv_game['team_name']} - Expected: {expected_age}, Matched: {matched_age}")
                    if matched_age != expected_age:
                        mismatches.append({
                            'game_uid': game_uid,
                            'game_date': csv_game['game_date'],
                            'team_type': 'away',
                            'provider_id': csv_game['team_id'],
                            'team_name': csv_game['team_name'],
                            'expected_age': expected_age,
                            'matched_age': matched_age,
                            'matched_team_id': matched_team_id,
                            'matched_team_name': matched_team.get('team_name', 'Unknown'),
                            'division': csv_game['mls_division']
                        })
    
    # Display results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    console.print(f"\n[bold]Checked: {checked_count} games, Found in DB: {found_count}[/bold]")
    console.print(f"[bold]Total mismatches: {len(mismatches)}[/bold]")
    
    if mismatches:
        # Group by mismatch type
        by_mismatch = defaultdict(list)
        for item in mismatches:
            key = f"{item['expected_age']} → {item['matched_age']}"
            by_mismatch[key].append(item)
        
        console.print("\n[bold]Mismatches by age group:[/bold]")
        for mismatch_type, items in sorted(by_mismatch.items()):
            console.print(f"  {mismatch_type}: {len(items)} games")
        
        # Show sample
        console.print("\n[bold]Sample mismatches (first 20):[/bold]")
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Date", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Provider ID", style="magenta")
        table.add_column("Team Name", style="green", max_width=25)
        table.add_column("Expected", style="green")
        table.add_column("Matched", style="red")
        table.add_column("Matched Team", style="red", max_width=25)
        
        for item in mismatches[:20]:
            table.add_row(
                str(item['game_date'])[:10] if item['game_date'] else 'N/A',
                item['team_type'].upper(),
                item['provider_id'],
                item['team_name'][:23],
                item['expected_age'],
                item['matched_age'],
                item['matched_team_name'][:23]
            )
        
        console.print(table)
        
        # Export to CSV
        import csv as csv_module
        csv_path = Path('mismatched_games_from_csv.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv_module.DictWriter(f, fieldnames=[
                'game_uid', 'game_date', 'team_type', 'provider_id', 'team_name',
                'expected_age', 'matched_age', 'matched_team_id', 'matched_team_name', 'division'
            ])
            writer.writeheader()
            writer.writerows(mismatches)
        
        console.print(f"\n[green]✅ Exported to: {csv_path}[/green]")
    else:
        console.print("\n[green]✅ No mismatches found![/green]")
    
    console.print("\n[bold cyan]=" * 80)

if __name__ == '__main__':
    main()

