#!/usr/bin/env python3
"""
Find incorrectly matched Modular11 games by comparing matched teams with available aliases.

Since games store base provider_ids (like "456"), we need to:
1. Check what team was matched for each provider_id
2. Check what aliases exist for that provider_id
3. Identify cases where a wrong age group was matched when a correct one exists
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

def extract_age_from_alias(alias_id: str) -> str:
    """Extract age group from alias format like '456_U14_AD'"""
    parts = str(alias_id).split('_')
    for part in parts:
        part_upper = part.upper()
        if part_upper.startswith('U') and len(part_upper) <= 4:
            return normalize_age_group(part)
    return ''

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]FINDING INCORRECTLY MATCHED MODULAR11 GAMES[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Step 1: Get all Modular11 games
    console.print("\n[bold]Step 1:[/bold] Fetching Modular11 games...")
    
    all_games = []
    offset = 0
    batch_size = 1000
    
    while True:
        result = supabase.table('games').select(
            'id, game_uid, game_date, home_provider_id, away_provider_id, '
            'home_team_master_id, away_team_master_id'
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
    
    # Step 3: Get all Modular11 aliases grouped by base provider_id
    console.print("\n[bold]Step 3:[/bold] Fetching Modular11 aliases...")
    
    aliases_result = supabase.table('team_alias_map').select(
        'provider_team_id, team_id_master, review_status'
    ).eq('provider_id', modular11_provider_id).eq('review_status', 'approved').execute()
    
    # Group aliases by base provider_id (e.g., "456" -> ["456_U13_AD", "456_U14_AD", ...])
    aliases_by_base_id = defaultdict(list)
    for alias in aliases_result.data:
        provider_id = str(alias['provider_team_id'])
        # Extract base ID (everything before first underscore, or whole thing if no underscore)
        base_id = provider_id.split('_')[0]
        aliases_by_base_id[base_id].append({
            'full_alias': provider_id,
            'team_id': alias['team_id_master'],
            'age': extract_age_from_alias(provider_id)
        })
    
    console.print(f"[green]Found {len(aliases_by_base_id)} base provider IDs with aliases[/green]")
    
    # Step 4: Analyze games for mismatches
    console.print("\n[bold]Step 4:[/bold] Analyzing games for age mismatches...")
    
    incorrectly_matched = []
    
    for game in track(all_games, description="Checking games..."):
        home_provider_id = str(game.get('home_provider_id', ''))
        away_provider_id = str(game.get('away_provider_id', ''))
        home_team_master_id = game.get('home_team_master_id')
        away_team_master_id = game.get('away_team_master_id')
        
        # Check home team
        if home_provider_id and home_provider_id.isdigit() and home_team_master_id:
            home_team = teams_by_id.get(home_team_master_id)
            if home_team:
                matched_age = normalize_age_group(home_team.get('age_group', ''))
                
                # Get all aliases for this base provider_id
                base_id = home_provider_id
                available_aliases = aliases_by_base_id.get(base_id, [])
                
                if available_aliases:
                    # Check if there are aliases with different ages
                    ages_available = set(a['age'] for a in available_aliases if a['age'])
                    
                    # If matched age doesn't match any available alias, or if there are multiple ages
                    # and we matched to the wrong one, flag it
                    if matched_age not in ages_available and ages_available:
                        # Find the most common age (likely the correct one)
                        age_counts = defaultdict(int)
                        for alias in available_aliases:
                            if alias['age']:
                                age_counts[alias['age']] += 1
                        
                        most_common_age = max(age_counts.items(), key=lambda x: x[1])[0] if age_counts else None
                        
                        # Find correct team for most common age
                        correct_alias = None
                        correct_team_id = None
                        for alias in available_aliases:
                            if alias['age'] == most_common_age:
                                correct_alias = alias['full_alias']
                                correct_team_id = alias['team_id']
                                break
                        
                        incorrectly_matched.append({
                            'game_id': game['id'],
                            'game_uid': game['game_uid'],
                            'game_date': game.get('game_date'),
                            'team_type': 'home',
                            'provider_id': home_provider_id,
                            'current_team_id': home_team_master_id,
                            'current_team_name': home_team.get('team_name', 'Unknown'),
                            'current_age': matched_age,
                            'available_ages': ', '.join(sorted(ages_available)),
                            'correct_alias': correct_alias,
                            'correct_team_id': correct_team_id,
                            'correct_team_name': teams_by_id.get(correct_team_id, {}).get('team_name', 'Unknown') if correct_team_id else None
                        })
        
        # Check away team
        if away_provider_id and away_provider_id.isdigit() and away_team_master_id:
            away_team = teams_by_id.get(away_team_master_id)
            if away_team:
                matched_age = normalize_age_group(away_team.get('age_group', ''))
                
                base_id = away_provider_id
                available_aliases = aliases_by_base_id.get(base_id, [])
                
                if available_aliases:
                    ages_available = set(a['age'] for a in available_aliases if a['age'])
                    
                    if matched_age not in ages_available and ages_available:
                        age_counts = defaultdict(int)
                        for alias in available_aliases:
                            if alias['age']:
                                age_counts[alias['age']] += 1
                        
                        most_common_age = max(age_counts.items(), key=lambda x: x[1])[0] if age_counts else None
                        
                        correct_alias = None
                        correct_team_id = None
                        for alias in available_aliases:
                            if alias['age'] == most_common_age:
                                correct_alias = alias['full_alias']
                                correct_team_id = alias['team_id']
                                break
                        
                        incorrectly_matched.append({
                            'game_id': game['id'],
                            'game_uid': game['game_uid'],
                            'game_date': game.get('game_date'),
                            'team_type': 'away',
                            'provider_id': away_provider_id,
                            'current_team_id': away_team_master_id,
                            'current_team_name': away_team.get('team_name', 'Unknown'),
                            'current_age': matched_age,
                            'available_ages': ', '.join(sorted(ages_available)),
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
        # Group by mismatch type
        by_mismatch = defaultdict(list)
        for item in incorrectly_matched:
            key = f"{item['current_age']} (should be one of: {item['available_ages']})"
            by_mismatch[key].append(item)
        
        console.print("\n[bold]Mismatches by age group:[/bold]")
        for mismatch_type, items in sorted(by_mismatch.items()):
            console.print(f"  {mismatch_type}: {len(items)} games")
        
        # Show sample
        console.print("\n[bold]Sample of incorrectly matched games (first 20):[/bold]")
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Game Date", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Provider ID", style="magenta")
        table.add_column("Current Team", style="red", max_width=25)
        table.add_column("Current Age", style="red")
        table.add_column("Available Ages", style="yellow")
        table.add_column("Correct Team", style="green", max_width=25)
        table.add_column("Has Fix?", style="yellow")
        
        for item in incorrectly_matched[:20]:
            has_fix = "✅" if item['correct_team_id'] else "❌"
            table.add_row(
                str(item['game_date'])[:10] if item['game_date'] else 'N/A',
                item['team_type'].upper(),
                item['provider_id'],
                item['current_team_name'][:23],
                item['current_age'],
                item['available_ages'],
                item['correct_team_name'][:23] if item['correct_team_name'] else 'N/A',
                has_fix
            )
        
        console.print(table)
        
        if len(incorrectly_matched) > 20:
            console.print(f"\n[dim]... and {len(incorrectly_matched) - 20} more[/dim]")
        
        # Export to CSV
        import csv
        csv_path = Path('incorrectly_matched_games.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'game_id', 'game_uid', 'game_date', 'team_type', 'provider_id',
                'current_team_id', 'current_team_name', 'current_age',
                'available_ages', 'correct_alias', 'correct_team_id', 'correct_team_name'
            ])
            writer.writeheader()
            writer.writerows(incorrectly_matched)
        
        console.print(f"\n[green]✅ Exported to: {csv_path}[/green]")
        
        fixable_count = sum(1 for item in incorrectly_matched if item['correct_team_id'])
        console.print(f"\n[bold]Fixability:[/bold]")
        console.print(f"  [green]Can be fixed: {fixable_count} games[/green]")
        console.print(f"  [red]Cannot be fixed: {len(incorrectly_matched) - fixable_count} games[/red]")
    else:
        console.print("\n[green]✅ No incorrectly matched games found![/green]")
    
    console.print("\n[bold cyan]=" * 80)

if __name__ == '__main__':
    main()



