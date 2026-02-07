#!/usr/bin/env python3
"""
Find incorrectly matched Modular11 games where teams were matched to wrong age groups.

This script identifies games where:
1. The game's age_group doesn't match the team's age_group
2. There exists a correct alias that should have matched instead
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
from rich.progress import track
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
    """Normalize age group to lowercase format (e.g., 'U14' -> 'u14')"""
    if not age_str:
        return ''
    age_str = str(age_str).strip().lower()
    if not age_str.startswith('u'):
        age_str = f"u{age_str}"
    return age_str

def extract_age_from_provider_id(provider_team_id: str) -> str:
    """Extract age group from provider_team_id format like '456_U14_AD'"""
    parts = str(provider_team_id).split('_')
    for part in parts:
        if part.upper().startswith('U') and len(part) <= 4:
            return normalize_age_group(part)
    return ''

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]FINDING INCORRECTLY MATCHED MODULAR11 GAMES[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Step 1: Get all Modular11 games with team matches
    console.print("\n[bold]Step 1:[/bold] Fetching Modular11 games...")
    
    all_games = []
    offset = 0
    batch_size = 1000
    
    while True:
        result = supabase.table('games').select(
            'id, game_uid, game_date, home_provider_id, away_provider_id, '
            'home_team_master_id, away_team_master_id, provider_id'
        ).eq('provider_id', modular11_provider_id).range(
            offset, offset + batch_size - 1
        ).execute()
        
        if not result.data:
            break
        
        all_games.extend(result.data)
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
    
    console.print(f"[green]Found {len(all_games)} Modular11 games[/green]")
    
    # Step 2: Get all teams with their age groups
    console.print("\n[bold]Step 2:[/bold] Fetching team age groups...")
    
    teams_result = supabase.table('teams').select('team_id_master, age_group, team_name').execute()
    teams_by_id = {team['team_id_master']: team for team in teams_result.data}
    
    console.print(f"[green]Found {len(teams_by_id)} teams[/green]")
    
    # Step 3: Get all Modular11 aliases to find correct matches
    console.print("\n[bold]Step 3:[/bold] Fetching Modular11 aliases...")
    
    aliases_result = supabase.table('team_alias_map').select(
        'provider_team_id, team_id_master, review_status'
    ).eq('provider_id', modular11_provider_id).eq('review_status', 'approved').execute()
    
    # Build lookup: provider_team_id -> team_id_master
    aliases_by_provider_id = {}
    for alias in aliases_result.data:
        provider_id = str(alias['provider_team_id'])
        aliases_by_provider_id[provider_id] = alias['team_id_master']
    
    # Also build reverse lookup: team_id_master -> list of provider_ids
    provider_ids_by_team = defaultdict(list)
    for alias in aliases_result.data:
        provider_id = str(alias['provider_team_id'])
        team_id = alias['team_id_master']
        provider_ids_by_team[team_id].append(provider_id)
    
    console.print(f"[green]Found {len(aliases_by_provider_id)} aliases[/green]")
    
    # Step 4: Analyze games for age mismatches
    console.print("\n[bold]Step 4:[/bold] Analyzing games for age mismatches...")
    
    incorrectly_matched = []
    
    for game in track(all_games, description="Checking games..."):
        home_provider_id = str(game.get('home_provider_id', ''))
        away_provider_id = str(game.get('away_provider_id', ''))
        home_team_master_id = game.get('home_team_master_id')
        away_team_master_id = game.get('away_team_master_id')
        
        # Check home team
        if home_provider_id and home_team_master_id:
            home_team = teams_by_id.get(home_team_master_id)
            if home_team:
                team_age = normalize_age_group(home_team.get('age_group', ''))
                
                # Extract expected age from provider_id (e.g., "456_U14_AD" -> "u14")
                expected_age = extract_age_from_provider_id(home_provider_id)
                
                # Also check if there's a correct alias
                correct_alias = None
                correct_team_id = None
                
                # Try to find correct alias with expected age
                if expected_age:
                    # Try different formats: {id}_{age}_{div}, {id}_{age}, etc.
                    base_id = home_provider_id.split('_')[0]
                    division = None
                    if '_' in home_provider_id:
                        parts = home_provider_id.split('_')
                        if len(parts) >= 3 and parts[-1].upper() in ('HD', 'AD'):
                            division = parts[-1].upper()
                    
                    # Try full format first
                    if division:
                        correct_provider_id = f"{base_id}_{expected_age.upper()}_{division}"
                        if correct_provider_id in aliases_by_provider_id:
                            correct_team_id = aliases_by_provider_id[correct_provider_id]
                            correct_alias = correct_provider_id
                    
                    # If no match, try without division
                    if not correct_alias:
                        correct_provider_id = f"{base_id}_{expected_age.upper()}"
                        if correct_provider_id in aliases_by_provider_id:
                            correct_team_id = aliases_by_provider_id[correct_provider_id]
                            correct_alias = correct_provider_id
                
                # Check if age matches
                if expected_age and team_age != expected_age:
                    incorrectly_matched.append({
                        'game_id': game['id'],
                        'game_uid': game['game_uid'],
                        'game_date': game.get('game_date'),
                        'team_type': 'home',
                        'provider_id': home_provider_id,
                        'current_team_id': home_team_master_id,
                        'current_team_name': home_team.get('team_name', 'Unknown'),
                        'current_age': team_age,
                        'expected_age': expected_age,
                        'correct_alias': correct_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': teams_by_id.get(correct_team_id, {}).get('team_name', 'Unknown') if correct_team_id else None
                    })
        
        # Check away team
        if away_provider_id and away_team_master_id:
            away_team = teams_by_id.get(away_team_master_id)
            if away_team:
                team_age = normalize_age_group(away_team.get('age_group', ''))
                
                # Extract expected age from provider_id
                expected_age = extract_age_from_provider_id(away_provider_id)
                
                # Find correct alias
                correct_alias = None
                correct_team_id = None
                
                if expected_age:
                    base_id = away_provider_id.split('_')[0]
                    division = None
                    if '_' in away_provider_id:
                        parts = away_provider_id.split('_')
                        if len(parts) >= 3 and parts[-1].upper() in ('HD', 'AD'):
                            division = parts[-1].upper()
                    
                    if division:
                        correct_provider_id = f"{base_id}_{expected_age.upper()}_{division}"
                        if correct_provider_id in aliases_by_provider_id:
                            correct_team_id = aliases_by_provider_id[correct_provider_id]
                            correct_alias = correct_provider_id
                    
                    if not correct_alias:
                        correct_provider_id = f"{base_id}_{expected_age.upper()}"
                        if correct_provider_id in aliases_by_provider_id:
                            correct_team_id = aliases_by_provider_id[correct_provider_id]
                            correct_alias = correct_provider_id
                
                # Check if age matches
                if expected_age and team_age != expected_age:
                    incorrectly_matched.append({
                        'game_id': game['id'],
                        'game_uid': game['game_uid'],
                        'game_date': game.get('game_date'),
                        'team_type': 'away',
                        'provider_id': away_provider_id,
                        'current_team_id': away_team_master_id,
                        'current_team_name': away_team.get('team_name', 'Unknown'),
                        'current_age': team_age,
                        'expected_age': expected_age,
                        'correct_alias': correct_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': teams_by_id.get(correct_team_id, {}).get('team_name', 'Unknown') if correct_team_id else None
                    })
    
    # Step 5: Display results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    console.print(f"\n[bold]Total incorrectly matched games: {len(incorrectly_matched)}[/bold]")
    
    if incorrectly_matched:
        # Group by expected age vs current age
        by_mismatch = defaultdict(list)
        for item in incorrectly_matched:
            key = f"{item['expected_age']} → {item['current_age']}"
            by_mismatch[key].append(item)
        
        console.print("\n[bold]Mismatches by age group:[/bold]")
        for mismatch_type, items in sorted(by_mismatch.items()):
            console.print(f"  {mismatch_type}: {len(items)} games")
        
        # Show sample of incorrectly matched games
        console.print("\n[bold]Sample of incorrectly matched games (first 20):[/bold]")
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Game Date", style="cyan")
        table.add_column("Team Type", style="yellow")
        table.add_column("Provider ID", style="magenta")
        table.add_column("Current Team", style="red", max_width=30)
        table.add_column("Current Age", style="red")
        table.add_column("Expected Age", style="green")
        table.add_column("Correct Team", style="green", max_width=30)
        table.add_column("Has Fix?", style="yellow")
        
        for item in incorrectly_matched[:20]:
            has_fix = "✅" if item['correct_team_id'] else "❌"
            table.add_row(
                str(item['game_date'])[:10] if item['game_date'] else 'N/A',
                item['team_type'].upper(),
                item['provider_id'],
                item['current_team_name'][:28],
                item['current_age'],
                item['expected_age'],
                item['correct_team_name'][:28] if item['correct_team_name'] else 'N/A',
                has_fix
            )
        
        console.print(table)
        
        if len(incorrectly_matched) > 20:
            console.print(f"\n[dim]... and {len(incorrectly_matched) - 20} more[/dim]")
        
        # Count how many have fixes available
        fixable_count = sum(1 for item in incorrectly_matched if item['correct_team_id'])
        unfixable_count = len(incorrectly_matched) - fixable_count
        
        console.print(f"\n[bold]Fixability:[/bold]")
        console.print(f"  [green]Can be fixed: {fixable_count} games[/green] (correct alias exists)")
        console.print(f"  [red]Cannot be fixed: {unfixable_count} games[/red] (no correct alias found)")
        
        # Export to CSV for further analysis
        import csv
        csv_path = Path('incorrectly_matched_games.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'game_id', 'game_uid', 'game_date', 'team_type', 'provider_id',
                'current_team_id', 'current_team_name', 'current_age',
                'expected_age', 'correct_alias', 'correct_team_id', 'correct_team_name'
            ])
            writer.writeheader()
            writer.writerows(incorrectly_matched)
        
        console.print(f"\n[green]✅ Exported to: {csv_path}[/green]")
    else:
        console.print("\n[green]✅ No incorrectly matched games found![/green]")
    
    console.print("\n[bold cyan]=" * 80)

if __name__ == '__main__':
    main()



