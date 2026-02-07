#!/usr/bin/env python3
"""
Fix incorrectly matched Modular11 games by updating them to use the correct teams.

This script reads the incorrectly_matched_games.csv file and updates games
to use the correct team_id_master based on the correct_alias.
"""
import os
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
from rich.progress import track

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

def main():
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]FIXING INCORRECTLY MATCHED MODULAR11 GAMES[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    # Read CSV
    csv_path = Path('incorrectly_matched_games.csv')
    if not csv_path.exists():
        console.print(f"[red]Error: CSV file not found: {csv_path}[/red]")
        console.print("[yellow]Run identify_mismatched_games.py first to generate the CSV[/yellow]")
        sys.exit(1)
    
    console.print(f"\n[bold]Step 1:[/bold] Reading {csv_path}...")
    
    mismatches = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mismatches.append(row)
    
    console.print(f"[green]Found {len(mismatches)} mismatched games[/green]")
    
    # Filter to fixable games (those with correct_team_id)
    fixable = [m for m in mismatches if m.get('correct_team_id')]
    unfixable = [m for m in mismatches if not m.get('correct_team_id')]
    
    console.print(f"\n[bold]Step 2:[/bold] Analyzing fixability...")
    console.print(f"  [green]Fixable: {len(fixable)} games[/green]")
    console.print(f"  [red]Unfixable: {len(unfixable)} games[/red] (no correct alias exists)")
    
    if not fixable:
        console.print("\n[yellow]No fixable games found![/yellow]")
        return
    
    # Show what will be fixed
    console.print("\n[bold]Step 3:[/bold] Games to fix (first 10):")
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Game UID", style="cyan", max_width=35)
    table.add_column("Date", style="yellow", max_width=12)
    table.add_column("Type", style="yellow", max_width=5)
    table.add_column("Current Team", style="red", max_width=20)
    table.add_column("Correct Team", style="green", max_width=20)
    
    for item in fixable[:10]:
        table.add_row(
            item['game_uid'][:33],
            str(item['game_date'])[:10] if item['game_date'] else 'N/A',
            item['team_type'].upper(),
            item['matched_team_name'][:18],
            item['correct_team_name'][:18] if item['correct_team_name'] else 'N/A'
        )
    
    console.print(table)
    
    if len(fixable) > 10:
        console.print(f"\n[dim]... and {len(fixable) - 10} more[/dim]")
    
    # Confirm
    dry_run = '--dry-run' in sys.argv
    auto_yes = '--yes' in sys.argv or '-y' in sys.argv
    
    if dry_run:
        console.print("\n[bold cyan]DRY RUN MODE - No changes will be made[/bold cyan]")
    elif auto_yes:
        console.print("\n[bold green]Auto-confirming fixes (--yes flag)[/bold green]")
    else:
        console.print(f"\n[bold yellow]Ready to fix {len(fixable)} games[/bold yellow]")
        response = input("Proceed with fixes? (yes/no): ")
        if response.lower() != 'yes':
            console.print("[yellow]Cancelled.[/yellow]")
            return
    
    # Fix games using game_corrections table
    console.print("\n[bold]Step 4:[/bold] Creating game corrections...")
    
    fixed_count = 0
    failed_count = 0
    errors = []
    correction_ids = []
    
    for item in track(fixable, description="Creating corrections..."):
        game_uid = item['game_uid']
        game_id = item['game_id']
        team_type = item['team_type']
        correct_team_id = item['correct_team_id']
        
        if dry_run:
            fixed_count += 1
            continue
        
        try:
            # Get current game data
            game_result = supabase.table('games').select(
                'home_team_master_id, away_team_master_id'
            ).eq('id', game_id).execute()
            
            if not game_result.data:
                failed_count += 1
                errors.append(f"{game_uid}: Game not found")
                continue
            
            current_game = game_result.data[0]
            current_home_id = current_game.get('home_team_master_id')
            current_away_id = current_game.get('away_team_master_id')
            
            # Prepare corrected values
            corrected_home_id = current_home_id
            corrected_away_id = current_away_id
            
            if team_type.lower() == 'home':
                corrected_home_id = correct_team_id
            else:  # away
                corrected_away_id = correct_team_id
            
            # Create correction record
            correction_data = {
                'original_game_uid': game_uid,
                'correction_type': 'teams',
                'original_values': {
                    'home_team_master_id': str(current_home_id) if current_home_id else None,
                    'away_team_master_id': str(current_away_id) if current_away_id else None
                },
                'corrected_values': {
                    'home_team_master_id': str(corrected_home_id) if corrected_home_id else None,
                    'away_team_master_id': str(corrected_away_id) if corrected_away_id else None
                },
                'reason': f'Fix incorrect team match: {item.get("matched_team_name", "Unknown")} (age {item.get("matched_age", "?")}) should be {item.get("correct_team_name", "Unknown")} (age {item.get("expected_age", "?")})',
                'status': 'pending',
                'submitted_by': 'system'
            }
            
            correction_result = supabase.table('game_corrections').insert(correction_data).execute()
            
            if correction_result.data:
                correction_id = correction_result.data[0]['id']
                correction_ids.append((correction_id, game_uid))
                fixed_count += 1
            else:
                failed_count += 1
                errors.append(f"{game_uid}: Failed to create correction")
        except Exception as e:
            failed_count += 1
            errors.append(f"{game_uid}: {str(e)}")
    
    # Apply corrections
    if not dry_run and correction_ids:
        console.print(f"\n[bold]Step 5:[/bold] Applying {len(correction_ids)} corrections...")
        
        applied_count = 0
        apply_failed_count = 0
        
        for correction_id, game_uid in track(correction_ids, description="Applying..."):
            try:
                # Call the apply_game_correction function via RPC
                result = supabase.rpc('apply_game_correction', {
                    'correction_id': correction_id,
                    'approver_name': 'system'
                }).execute()
                
                applied_count += 1
            except Exception as e:
                apply_failed_count += 1
                errors.append(f"{game_uid} (correction {correction_id}): Apply failed - {str(e)}")
        
        console.print(f"  [green]Applied: {applied_count}[/green]")
        if apply_failed_count > 0:
            console.print(f"  [red]Failed to apply: {apply_failed_count}[/red]")
    
    # Display results
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]RESULTS[/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    if dry_run:
        console.print(f"\n[green]Would fix: {fixed_count} games[/green]")
    else:
        console.print(f"\n[green]✅ Fixed: {fixed_count} games[/green]")
        if failed_count > 0:
            console.print(f"[red]❌ Failed: {failed_count} games[/red]")
            if errors:
                console.print("\n[yellow]Errors (first 5):[/yellow]")
                for error in errors[:5]:
                    console.print(f"  - {error}")
                if len(errors) > 5:
                    console.print(f"  ... and {len(errors) - 5} more")
    
    # Verify fixes
    if not dry_run and fixed_count > 0:
        console.print("\n[bold]Step 6:[/bold] Verifying fixes...")
        
        # Check a few random games
        sample_items = fixable[:5]
        
        for original_item in sample_items:
            game_id = original_item['game_id']
            verify_result = supabase.table('games').select(
                'game_uid, home_team_master_id, away_team_master_id'
            ).eq('id', game_id).execute()
            
            if verify_result.data:
                game = verify_result.data[0]
                if original_item['team_type'].lower() == 'home':
                    current_team_id = str(game.get('home_team_master_id'))
                    expected_team_id = original_item['correct_team_id']
                else:
                    current_team_id = str(game.get('away_team_master_id'))
                    expected_team_id = original_item['correct_team_id']
                
                if current_team_id == expected_team_id:
                    console.print(f"  [green]✅[/green] {original_item['game_uid']}: Fixed")
                else:
                    console.print(f"  [red]❌[/red] {original_item['game_uid']}: Still incorrect (got {current_team_id}, expected {expected_team_id})")
    
    console.print("\n[bold cyan]=" * 80)
    console.print("[bold cyan]DONE![/bold cyan]")
    console.print("[bold cyan]=" * 80)
    
    if not dry_run:
        console.print("\n[yellow]Note:[/yellow] The unfixable games need correct aliases to be created first.")
        console.print("[yellow]Note:[/yellow] You may want to re-run identify_mismatched_games.py to verify fixes.")

if __name__ == '__main__':
    main()

