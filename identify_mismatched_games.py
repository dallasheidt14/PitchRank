#!/usr/bin/env python3
"""
Identify incorrectly matched games by comparing CSV source data with database matches.

This is the definitive way to find mismatches - we compare what the CSV says
the age should be vs what was actually matched in the database.
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
from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import parse_game_date

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

def generate_game_uid_from_csv_row(row):
    """Generate game UID from CSV row"""
    game_date = row.get('game_date', '').strip()
    team_id = row.get('team_id', '').strip()
    opponent_id = row.get('opponent_id', '').strip()
    
    try:
        date_obj = parse_game_date(game_date)
        game_date_normalized = date_obj.strftime('%Y-%m-%d')
    except ValueError:
        game_date_normalized = game_date
    
    return GameHistoryMatcher.generate_game_uid(
        provider='modular11',
        game_date=game_date_normalized,
        team1_id=team_id,
        team2_id=opponent_id
    )

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]IDENTIFYING INCORRECTLY MATCHED GAMES FROM CSV[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Read CSV
    csv_path = Path(r"C:\PitchRank\mod11 u14 results.csv")
    if not csv_path.exists():
        console.print(f"[red]Error: CSV file not found: {csv_path}[/red]")
        sys.exit(1)
    
    console.print(f"\n[bold]Step 1:[/bold] Reading CSV: {csv_path}")
    
    csv_rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_rows.append(row)
    
    console.print(f"[green]Found {len(csv_rows)} rows in CSV[/green]")
    
    # Get teams from database (fetch all, not just first 1000)
    console.print("\n[bold]Step 2:[/bold] Fetching teams from database...")
    teams_by_id = {}
    offset = 0
    batch_size = 1000
    
    while True:
        teams_result = supabase.table('teams').select('team_id_master, age_group, team_name').range(
            offset, offset + batch_size - 1
        ).execute()
        
        if not teams_result.data:
            break
        
        for team in teams_result.data:
            teams_by_id[team['team_id_master']] = team
        
        if len(teams_result.data) < batch_size:
            break
        
        offset += batch_size
    
    console.print(f"[green]Found {len(teams_by_id)} teams[/green]")
    
    # Get aliases to find correct teams (with pagination to get all)
    console.print("\n[bold]Step 3:[/bold] Fetching aliases...")
    aliases_by_provider_id = {}
    offset = 0
    batch_size = 1000
    
    while True:
        aliases_result = supabase.table('team_alias_map').select(
            'provider_team_id, team_id_master'
        ).eq('provider_id', modular11_provider_id).eq('review_status', 'approved').range(
            offset, offset + batch_size - 1
        ).execute()
        
        if not aliases_result.data:
            break
        
        for alias in aliases_result.data:
            aliases_by_provider_id[str(alias['provider_team_id'])] = alias['team_id_master']
        
        if len(aliases_result.data) < batch_size:
            break
        
        offset += batch_size
    
    console.print(f"[green]Found {len(aliases_by_provider_id)} aliases[/green]")
    
    # Analyze mismatches
    console.print("\n[bold]Step 4:[/bold] Comparing CSV with database...")
    
    mismatches = []
    checked_games = set()  # Track unique games to avoid duplicates
    
    for row in csv_rows:
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        game_date = row.get('game_date', '').strip()
        age_group_raw = row.get('age_group', '').strip()
        expected_age = normalize_age_group(age_group_raw)
        team_name = row.get('team_name', '').strip()
        mls_division = row.get('mls_division', '').strip()
        
        if not team_id or not opponent_id or not game_date:
            continue
        
        # Generate game UID
        game_uid = generate_game_uid_from_csv_row(row)
        
        # Skip if we've already checked this game
        if game_uid in checked_games:
            continue
        checked_games.add(game_uid)
        
        # Get game from database
        db_game_result = supabase.table('games').select(
            'id, game_uid, home_provider_id, away_provider_id, '
            'home_team_master_id, away_team_master_id'
        ).eq('provider_id', modular11_provider_id).eq('game_uid', game_uid).execute()
        
        if not db_game_result.data:
            continue  # Game not in database
        
        db_game = db_game_result.data[0]
        
        # Check both teams in the database game, regardless of CSV row perspective
        home_provider_id = str(db_game.get('home_provider_id', ''))
        away_provider_id = str(db_game.get('away_provider_id', ''))
        
        # Get opponent info from CSV (for away team checks)
        opponent_name = row.get('opponent_name', '').strip()
        opponent_age_group_raw = row.get('opponent_age_group', '') or age_group_raw  # Fallback to team age if not specified
        opponent_expected_age = normalize_age_group(opponent_age_group_raw)
        
        # Check home team in database
        home_matched_team_id = db_game.get('home_team_master_id')
        if home_matched_team_id:
            home_matched_team = teams_by_id.get(home_matched_team_id)
            if home_matched_team:
                home_matched_age = normalize_age_group(home_matched_team.get('age_group', ''))
                # Determine expected age for home team (could be team_id or opponent_id from CSV)
                if home_provider_id == team_id:
                    home_expected_age = expected_age
                    home_expected_provider_id = team_id
                    home_expected_name = team_name
                elif home_provider_id == opponent_id:
                    home_expected_age = opponent_expected_age
                    home_expected_provider_id = opponent_id
                    home_expected_name = opponent_name
                else:
                    home_expected_age = None  # Skip if provider_id doesn't match CSV
                    home_expected_provider_id = None
                    home_expected_name = None
                
                if home_expected_age and home_matched_age != home_expected_age:
                    # Build expected alias for home team
                    expected_alias = f"{home_expected_provider_id}_{home_expected_age.upper()}_{mls_division}" if mls_division else f"{home_expected_provider_id}_{home_expected_age.upper()}"
                    # Find correct team
                    correct_team_id = aliases_by_provider_id.get(expected_alias)
                    correct_team_name = None
                    if correct_team_id:
                        correct_team = teams_by_id.get(correct_team_id)
                        correct_team_name = correct_team.get('team_name', 'Unknown') if correct_team else None
                    
                    mismatches.append({
                        'game_id': db_game['id'],
                        'game_uid': game_uid,
                        'game_date': game_date,
                        'team_type': 'home',
                        'provider_id': home_expected_provider_id,
                        'team_name': home_expected_name,
                        'expected_age': home_expected_age,
                        'expected_alias': expected_alias,
                        'matched_age': home_matched_age,
                        'matched_team_id': home_matched_team_id,
                        'matched_team_name': home_matched_team.get('team_name', 'Unknown'),
                        'correct_alias': expected_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': correct_team_name,
                        'division': mls_division
                    })
        
        # Check away team in database
        away_matched_team_id = db_game.get('away_team_master_id')
        if away_matched_team_id:
            away_matched_team = teams_by_id.get(away_matched_team_id)
            if away_matched_team:
                away_matched_age = normalize_age_group(away_matched_team.get('age_group', ''))
                # Determine expected age for away team (could be team_id or opponent_id from CSV)
                if away_provider_id == opponent_id:
                    away_expected_age = opponent_expected_age
                    away_expected_provider_id = opponent_id
                    away_expected_name = opponent_name
                elif away_provider_id == team_id:
                    away_expected_age = expected_age
                    away_expected_provider_id = team_id
                    away_expected_name = team_name
                else:
                    away_expected_age = None  # Skip if provider_id doesn't match CSV
                    away_expected_provider_id = None
                    away_expected_name = None
                
                if away_expected_age and away_matched_age != away_expected_age:
                    # Build expected alias for away team
                    expected_alias = f"{away_expected_provider_id}_{away_expected_age.upper()}_{mls_division}" if mls_division else f"{away_expected_provider_id}_{away_expected_age.upper()}"
                    # Find correct team
                    correct_team_id = aliases_by_provider_id.get(expected_alias)
                    correct_team_name = None
                    if correct_team_id:
                        correct_team = teams_by_id.get(correct_team_id)
                        correct_team_name = correct_team.get('team_name', 'Unknown') if correct_team else None
                    
                    mismatches.append({
                        'game_id': db_game['id'],
                        'game_uid': game_uid,
                        'game_date': game_date,
                        'team_type': 'away',
                        'provider_id': away_expected_provider_id,
                        'team_name': away_expected_name,
                        'expected_age': away_expected_age,
                        'expected_alias': expected_alias,
                        'matched_age': away_matched_age,
                        'matched_team_id': away_matched_team_id,
                        'matched_team_name': away_matched_team.get('team_name', 'Unknown'),
                        'correct_alias': expected_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': correct_team_name,
                        'division': mls_division
                    })
    
    # Display results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    console.print(f"\n[bold]Total mismatches: {len(mismatches)}[/bold]")
    
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
        console.print("\n[bold]Sample mismatches:[/bold]")
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Date", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Provider ID", style="magenta")
        table.add_column("Team Name", style="green", max_width=25)
        table.add_column("Expected", style="green")
        table.add_column("Matched", style="red")
        table.add_column("Matched Team", style="red", max_width=25)
        table.add_column("Correct Team", style="green", max_width=25)
        table.add_column("Fix?", style="yellow")
        
        for item in mismatches[:30]:
            has_fix = "✅" if item['correct_team_id'] else "❌"
            table.add_row(
                str(item['game_date'])[:10] if item['game_date'] else 'N/A',
                item['team_type'].upper(),
                item['provider_id'],
                item['team_name'][:23],
                item['expected_age'],
                item['matched_age'],
                item['matched_team_name'][:23],
                item['correct_team_name'][:23] if item['correct_team_name'] else 'N/A',
                has_fix
            )
        
        console.print(table)
        
        if len(mismatches) > 30:
            console.print(f"\n[dim]... and {len(mismatches) - 30} more[/dim]")
        
        # Export to CSV
        csv_output_path = Path('incorrectly_matched_games.csv')
        with open(csv_output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'game_id', 'game_uid', 'game_date', 'team_type', 'provider_id', 'team_name',
                'expected_age', 'expected_alias', 'matched_age', 'matched_team_id', 
                'matched_team_name', 'correct_alias', 'correct_team_id', 'correct_team_name', 'division'
            ])
            writer.writeheader()
            writer.writerows(mismatches)
        
        console.print(f"\n[green]✅ Exported to: {csv_output_path}[/green]")
        
        fixable_count = sum(1 for item in mismatches if item['correct_team_id'])
        console.print(f"\n[bold]Fixability:[/bold]")
        console.print(f"  [green]Can be fixed: {fixable_count} games[/green] ({fixable_count/len(mismatches)*100:.1f}%)")
        console.print(f"  [red]Cannot be fixed: {len(mismatches) - fixable_count} games[/red]")
    else:
        console.print("\n[green]✅ No mismatches found![/green]")
    
    console.print("\n[bold cyan]=" * 80)

if __name__ == '__main__':
    main()

