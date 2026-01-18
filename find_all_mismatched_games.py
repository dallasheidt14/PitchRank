#!/usr/bin/env python3
"""
Comprehensive script to find ALL incorrectly matched Modular11 games.

This script:
1. Gets all Modular11 games from database
2. For each provider_id, checks if there are multiple age groups available
3. Identifies games where the matched team's age doesn't match available aliases
4. Uses heuristics to determine the correct age (most common, or from game date context)
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
from datetime import datetime

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
    console.print("[bold cyan]FINDING ALL INCORRECTLY MATCHED MODULAR11 GAMES[/bold cyan]")
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
    
    # Step 2: Get all teams
    console.print("\n[bold]Step 2:[/bold] Fetching teams...")
    teams_result = supabase.table('teams').select('team_id_master, age_group, team_name').execute()
    teams_by_id = {team['team_id_master']: team for team in teams_result.data}
    console.print(f"[green]Found {len(teams_by_id)} teams[/green]")
    
    # Step 3: Get all aliases grouped by base provider_id
    console.print("\n[bold]Step 3:[/bold] Fetching aliases...")
    aliases_result = supabase.table('team_alias_map').select(
        'provider_team_id, team_id_master'
    ).eq('provider_id', modular11_provider_id).eq('review_status', 'approved').execute()
    
    # Group by base ID and track age distribution
    aliases_by_base = defaultdict(lambda: {'aliases': [], 'age_counts': defaultdict(int)})
    for alias in aliases_result.data:
        provider_id = str(alias['provider_team_id'])
        base_id = provider_id.split('_')[0]
        
        # Only process numeric base IDs (real provider IDs)
        if base_id.isdigit():
            age = extract_age_from_alias(provider_id)
            aliases_by_base[base_id]['aliases'].append({
                'full_alias': provider_id,
                'team_id': alias['team_id_master'],
                'age': age
            })
            if age:
                aliases_by_base[base_id]['age_counts'][age] += 1
    
    console.print(f"[green]Found {len(aliases_by_base)} base provider IDs with multiple age groups[/green]")
    
    # Step 4: Find mismatches
    console.print("\n[bold]Step 4:[/bold] Analyzing games for mismatches...")
    
    mismatches = []
    
    for game in track(all_games, description="Checking games..."):
        home_provider_id = str(game.get('home_provider_id', ''))
        away_provider_id = str(game.get('away_provider_id', ''))
        home_team_id = game.get('home_team_master_id')
        away_team_id = game.get('away_team_master_id')
        
        # Check home team
        if home_provider_id.isdigit() and home_team_id and home_provider_id in aliases_by_base:
            home_team = teams_by_id.get(home_team_id)
            if home_team:
                matched_age = normalize_age_group(home_team.get('age_group', ''))
                base_info = aliases_by_base[home_provider_id]
                available_ages = set(base_info['age_counts'].keys())
                
                # If matched age is not in available ages, or if there are multiple ages
                # and this is a less common match, flag it
                if matched_age not in available_ages and available_ages:
                    # Find most common age (likely correct)
                    most_common_age = max(base_info['age_counts'].items(), key=lambda x: x[1])[0]
                    
                    # Find correct team
                    correct_alias = None
                    correct_team_id = None
                    for alias in base_info['aliases']:
                        if alias['age'] == most_common_age:
                            correct_alias = alias['full_alias']
                            correct_team_id = alias['team_id']
                            break
                    
                    mismatches.append({
                        'game_id': game['id'],
                        'game_uid': game['game_uid'],
                        'game_date': game.get('game_date'),
                        'team_type': 'home',
                        'provider_id': home_provider_id,
                        'current_team_id': home_team_id,
                        'current_team_name': home_team.get('team_name', 'Unknown'),
                        'current_age': matched_age,
                        'available_ages': ', '.join(sorted(available_ages)),
                        'most_common_age': most_common_age,
                        'correct_alias': correct_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': teams_by_id.get(correct_team_id, {}).get('team_name', 'Unknown') if correct_team_id else None
                    })
        
        # Check away team
        if away_provider_id.isdigit() and away_team_id and away_provider_id in aliases_by_base:
            away_team = teams_by_id.get(away_team_id)
            if away_team:
                matched_age = normalize_age_group(away_team.get('age_group', ''))
                base_info = aliases_by_base[away_provider_id]
                available_ages = set(base_info['age_counts'].keys())
                
                if matched_age not in available_ages and available_ages:
                    most_common_age = max(base_info['age_counts'].items(), key=lambda x: x[1])[0]
                    
                    correct_alias = None
                    correct_team_id = None
                    for alias in base_info['aliases']:
                        if alias['age'] == most_common_age:
                            correct_alias = alias['full_alias']
                            correct_team_id = alias['team_id']
                            break
                    
                    mismatches.append({
                        'game_id': game['id'],
                        'game_uid': game['game_uid'],
                        'game_date': game.get('game_date'),
                        'team_type': 'away',
                        'provider_id': away_provider_id,
                        'current_team_id': away_team_id,
                        'current_team_name': away_team.get('team_name', 'Unknown'),
                        'current_age': matched_age,
                        'available_ages': ', '.join(sorted(available_ages)),
                        'most_common_age': most_common_age,
                        'correct_alias': correct_alias,
                        'correct_team_id': correct_team_id,
                        'correct_team_name': teams_by_id.get(correct_team_id, {}).get('team_name', 'Unknown') if correct_team_id else None
                    })
    
    # Step 5: Display results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    console.print(f"\n[bold]Total incorrectly matched games: {len(mismatches)}[/bold]")
    
    if mismatches:
        # Group by mismatch type
        by_mismatch = defaultdict(list)
        for item in mismatches:
            key = f"{item['current_age']} (should be {item['most_common_age']})"
            by_mismatch[key].append(item)
        
        console.print("\n[bold]Mismatches by age group:[/bold]")
        for mismatch_type, items in sorted(by_mismatch.items()):
            console.print(f"  {mismatch_type}: {len(items)} games")
        
        # Show sample
        console.print("\n[bold]Sample mismatches (first 30):[/bold]")
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Date", style="cyan", max_width=12)
        table.add_column("Type", style="yellow", max_width=5)
        table.add_column("Provider ID", style="magenta", max_width=12)
        table.add_column("Current Team", style="red", max_width=20)
        table.add_column("Current Age", style="red", max_width=10)
        table.add_column("Should Be", style="green", max_width=10)
        table.add_column("Correct Team", style="green", max_width=20)
        table.add_column("Has Fix?", style="yellow", max_width=8)
        
        for item in mismatches[:30]:
            has_fix = "✅" if item['correct_team_id'] else "❌"
            date_str = str(item['game_date'])[:10] if item['game_date'] else 'N/A'
            table.add_row(
                date_str,
                item['team_type'].upper(),
                item['provider_id'],
                item['current_team_name'][:18],
                item['current_age'],
                item['most_common_age'],
                item['correct_team_name'][:18] if item['correct_team_name'] else 'N/A',
                has_fix
            )
        
        console.print(table)
        
        if len(mismatches) > 30:
            console.print(f"\n[dim]... and {len(mismatches) - 30} more[/dim]")
        
        # Export to CSV
        import csv
        csv_path = Path('incorrectly_matched_games_comprehensive.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'game_id', 'game_uid', 'game_date', 'team_type', 'provider_id',
                'current_team_id', 'current_team_name', 'current_age',
                'available_ages', 'most_common_age', 'correct_alias', 
                'correct_team_id', 'correct_team_name'
            ])
            writer.writeheader()
            writer.writerows(mismatches)
        
        console.print(f"\n[green]✅ Exported to: {csv_path}[/green]")
        
        fixable_count = sum(1 for item in mismatches if item['correct_team_id'])
        console.print(f"\n[bold]Fixability:[/bold]")
        console.print(f"  [green]Can be fixed: {fixable_count} games[/green] ({fixable_count/len(mismatches)*100:.1f}%)")
        console.print(f"  [red]Cannot be fixed: {len(mismatches) - fixable_count} games[/red]")
    else:
        console.print("\n[green]✅ No incorrectly matched games found![/green]")
    
    console.print("\n[bold cyan]=" * 80)

if __name__ == '__main__':
    main()



