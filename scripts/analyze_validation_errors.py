#!/usr/bin/env python3
"""
Analyze validation errors from game import to understand why games are quarantined
"""
import csv
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List

sys.path.append(str(Path(__file__).parent.parent))

from src.utils.enhanced_validators import EnhancedDataValidator
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
validator = EnhancedDataValidator()


def validate_game_from_csv_row(row: Dict) -> tuple:
    """Convert CSV row to game dict and validate"""
    game = {
        'provider': row.get('provider', '').strip(),
        'team_id': row.get('team_id') or row.get('team_id_source', ''),
        'team_id_source': row.get('team_id_source', ''),
        'team_name': row.get('team_name', '').strip(),
        'club_name': row.get('club_name') or row.get('team_club_name', '').strip(),
        'opponent_id': row.get('opponent_id') or row.get('opponent_id_source', ''),
        'opponent_id_source': row.get('opponent_id_source', ''),
        'opponent_name': row.get('opponent_name', '').strip(),
        'opponent_club_name': row.get('opponent_club_name', '').strip(),
        'age_group': row.get('age_group', '').strip(),
        'gender': row.get('gender', '').strip(),
        'state': row.get('state', '').strip(),
        'game_date': row.get('game_date', '').strip(),
        'home_away': row.get('home_away', '').strip(),
        'goals_for': row.get('goals_for', ''),
        'goals_against': row.get('goals_against', ''),
        'result': row.get('result', '').strip(),
    }
    
    # Convert numeric fields
    try:
        if game['goals_for']:
            game['goals_for'] = float(game['goals_for']) if '.' in str(game['goals_for']) else int(game['goals_for'])
        if game['goals_against']:
            game['goals_against'] = float(game['goals_against']) if '.' in str(game['goals_against']) else int(game['goals_against'])
    except (ValueError, TypeError):
        pass
    
    is_valid, errors = validator.validate_game(game)
    return is_valid, errors, game


def analyze_validation_errors(csv_file: str, limit: int = None):
    """Analyze validation errors from CSV file"""
    console.print(f"[bold]Analyzing validation errors from: {csv_file}[/bold]")
    
    error_counts = Counter()
    error_examples = defaultdict(list)
    total_games = 0
    valid_games = 0
    invalid_games = 0
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 1):
            if limit and row_num > limit:
                break
            
            total_games += 1
            is_valid, errors, game = validate_game_from_csv_row(row)
            
            if is_valid:
                valid_games += 1
            else:
                invalid_games += 1
                # Count each error type
                for error in errors:
                    error_counts[error] += 1
                    # Store example games for each error type (max 3)
                    if len(error_examples[error]) < 3:
                        error_examples[error].append({
                            'row': row_num,
                            'game': game,
                            'all_errors': errors
                        })
            
            # Progress indicator
            if row_num % 1000 == 0:
                console.print(f"[cyan]Processed {row_num:,} games...[/cyan]")
    
    # Display results
    console.print(f"\n[bold green]Validation Analysis Complete[/bold green]")
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Total games analyzed: {total_games:,}")
    console.print(f"  [green]Valid: {valid_games:,} ({valid_games/total_games*100:.1f}%)[/green]")
    console.print(f"  [red]Invalid: {invalid_games:,} ({invalid_games/total_games*100:.1f}%)[/red]")
    
    if error_counts:
        console.print(f"\n[bold]Error Types (sorted by frequency):[/bold]")
        
        # Create table
        table = Table(title="Validation Error Analysis", box=box.ROUNDED)
        table.add_column("Error Type", style="cyan", no_wrap=False)
        table.add_column("Count", style="magenta", justify="right")
        table.add_column("Percentage", style="yellow", justify="right")
        
        total_errors = sum(error_counts.values())
        for error, count in error_counts.most_common():
            percentage = (count / invalid_games * 100) if invalid_games > 0 else 0
            table.add_row(
                error,
                f"{count:,}",
                f"{percentage:.1f}%"
            )
        
        console.print(table)
        
        # Show examples
        console.print(f"\n[bold]Example Games with Errors:[/bold]")
        for error_type, examples in error_examples.items():
            console.print(f"\n[yellow]{error_type}[/yellow]")
            for example in examples:
                game = example['game']
                console.print(f"  Row {example['row']}:")
                console.print(f"    Team: {game.get('team_name', 'N/A')} vs {game.get('opponent_name', 'N/A')}")
                console.print(f"    Date: {game.get('game_date', 'N/A')}")
                console.print(f"    Scores: {game.get('goals_for', 'N/A')} - {game.get('goals_against', 'N/A')}")
                console.print(f"    All errors: {'; '.join(example['all_errors'])}")
    else:
        console.print("\n[green]No validation errors found![/green]")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze validation errors from game CSV')
    parser.add_argument('file', help='CSV file containing games')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of games to analyze')
    
    args = parser.parse_args()
    
    if not Path(args.file).exists():
        console.print(f"[red]Error: File not found: {args.file}[/red]")
        sys.exit(1)
    
    analyze_validation_errors(args.file, args.limit)

