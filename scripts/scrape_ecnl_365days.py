#!/usr/bin/env python3
"""
One-time scraper for ECNL games in the last 365 days

This script scrapes all ECNL games from the last 365 days across all conferences
and age groups. This is a one-time operation to populate the initial dataset.

Usage:
    # Basic usage
    python scripts/scrape_ecnl_365days.py
    
    # Custom output file
    python scripts/scrape_ecnl_365days.py --output data/raw/ecnl_365days.jsonl
    
    # Auto-import to database
    python scripts/scrape_ecnl_365days.py --auto-import
"""
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from src.scrapers.athleteone_scraper import AthleteOneScraper
from src.base import GameData

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ECNL constants
ECNL_ORG_ID = "9"
ECNL_ORG_SEASON_ID = "69"  # 2025-26 season


def load_ecnl_conferences(conferences_file: Path) -> List[Dict]:
    """
    Load ECNL conference mappings
    
    Expected format from discover_ecnl_conferences.py:
    [
        {
            "conference": "ECNL Girls Mid-Atlantic 2025-26",
            "age_group": "G2010",
            "org_id": "9",
            "org_season_id": "69",
            "event_id": "3925",
            "flight_id": "0"
        }
    ]
    
    Returns:
        List of conference dictionaries
    """
    if not conferences_file.exists():
        console.print(f"[red]Conferences file not found: {conferences_file}[/red]")
        console.print("[yellow]Run scripts/discover_ecnl_conferences.py first to discover conferences[/yellow]")
        return []
    
    try:
        with open(conferences_file, 'r') as f:
            conferences = json.load(f)
        logger.info(f"Loaded {len(conferences)} ECNL conference/age group combinations")
        return conferences
    except Exception as e:
        logger.error(f"Error loading conferences file: {e}")
        return []


def scrape_ecnl_365days(
    conferences_file: str = None,
    output_file: str = None,
    auto_import: bool = False,
    days_back: int = 365
):
    """
    Scrape all ECNL games from the last 365 days
    
    Args:
        conferences_file: Path to JSON file with ECNL conferences (default: data/raw/ecnl_conferences_simplified.json)
        output_file: Output file path (default: auto-generated)
        auto_import: If True, automatically import games to database
        days_back: Number of days to look back (default: 365)
    """
    console.print(Panel.fit(
        "[bold cyan]ECNL 365-Day Scraper[/bold cyan]\n"
        f"Scraping games from the last {days_back} days",
        border_style="cyan"
    ))
    
    # Load conferences
    if conferences_file is None:
        conferences_file = "data/raw/ecnl_conferences_simplified.json"
    
    conf_path = Path(conferences_file)
    conferences = load_ecnl_conferences(conf_path)
    
    if not conferences:
        console.print("[red]No conferences found. Cannot proceed.[/red]")
        return None
    
    console.print(f"[green]Found {len(conferences)} conference/age group combinations[/green]")
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    console.print(f"[cyan]Date range: {start_date.date()} to {end_date.date()}[/cyan]")
    
    # Initialize scraper
    scraper = AthleteOneScraper()
    
    # Scrape all conferences
    all_games: List[GameData] = []
    successful = 0
    failed = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(
            f"Scraping {len(conferences)} conferences...",
            total=len(conferences)
        )
        
        for conf in conferences:
            conference_name = conf.get('conference', 'Unknown')
            age_group = conf.get('age_group', 'Unknown')
            event_id = conf.get('event_id', '')
            flight_id = conf.get('flight_id', '0')
            
            display_name = f"{conference_name} - {age_group}"
            
            try:
                # Scrape games for this conference/age group
                games = scraper.scrape_conference_games(
                    org_id=conf.get('org_id', ECNL_ORG_ID),
                    org_season_id=conf.get('org_season_id', ECNL_ORG_SEASON_ID),
                    event_id=event_id,
                    flight_id=flight_id,
                    since_date=start_date
                )
                
                # Filter games by date range
                filtered_games = []
                for game in games:
                    if game.game_date:
                        try:
                            game_date = datetime.strptime(game.game_date, '%Y-%m-%d').date()
                            if start_date.date() <= game_date <= end_date.date():
                                filtered_games.append(game)
                        except ValueError:
                            # Invalid date format, include it anyway
                            filtered_games.append(game)
                    else:
                        # No date, include it (might be scheduled)
                        filtered_games.append(game)
                
                if filtered_games:
                    all_games.extend(filtered_games)
                    successful += 1
                    progress.update(
                        task,
                        advance=1,
                        description=f"[green]✓ {display_name}: {len(filtered_games)} games[/green]"
                    )
                else:
                    progress.update(
                        task,
                        advance=1,
                        description=f"[dim]{display_name}: No games[/dim]"
                    )
                    
            except Exception as e:
                failed += 1
                logger.error(f"Error scraping {display_name}: {e}", exc_info=True)
                progress.update(
                    task,
                    advance=1,
                    description=f"[red]✗ {display_name}: Error[/red]"
                )
                continue
    
    # Summary
    console.print("\n[bold cyan]Summary[/bold cyan]")
    console.print(f"  Total games scraped: {len(all_games)}")
    console.print(f"  Conferences processed: {len(conferences)}")
    console.print(f"  Successful: {successful}")
    console.print(f"  Failed: {failed}")
    
    if not all_games:
        console.print("\n[yellow]No games found![/yellow]")
        return None
    
    # Remove duplicates (same game from home/away perspectives)
    # Keep unique games based on game_date, team_name, opponent_name
    unique_games = {}
    for game in all_games:
        key = (game.game_date, game.team_name, game.opponent_name)
        if key not in unique_games:
            unique_games[key] = game
    
    console.print(f"  Unique games (after deduplication): {len(unique_games)}")
    
    # Save games to file
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/ecnl_365days_{timestamp}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    console.print(f"\n[cyan]Saving games to: {output_path}[/cyan]")
    
    # Convert GameData to dict format for JSONL
    games_dict = []
    for game in unique_games.values():
        game_dict = {
            'provider': 'ecnl',
            'team_id': game.team_id,
            'team_id_source': game.team_id,
            'opponent_id': game.opponent_id or '',
            'opponent_id_source': game.opponent_id or '',
            'team_name': game.team_name or '',
            'opponent_name': game.opponent_name or '',
            'game_date': game.game_date,
            'home_away': game.home_away,
            'goals_for': game.goals_for,
            'goals_against': game.goals_against,
            'result': game.result or 'U',
            'competition': game.competition or '',
            'venue': game.venue or '',
            'source_url': game.meta.get('source_url', '') if game.meta else '',
            'scraped_at': game.meta.get('scraped_at', datetime.now().isoformat()) if game.meta else datetime.now().isoformat()
        }
        games_dict.append(game_dict)
    
    # Write JSONL file
    with open(output_path, 'w') as f:
        for game_dict in games_dict:
            f.write(json.dumps(game_dict) + '\n')
    
    console.print(f"[green]Saved {len(games_dict)} games to {output_path}[/green]")
    
    # Auto-import if requested
    if auto_import:
        console.print("\n[cyan]Auto-importing games to database...[/cyan]")
        try:
            from scripts.import_games import import_games_from_file
            import_games_from_file(str(output_path))
            console.print("[green]Import completed![/green]")
        except Exception as e:
            console.print(f"[red]Import failed: {e}[/red]")
            logger.exception("Import failed")
    
    return output_path


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='One-time scraper for ECNL games in the last 365 days',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python scripts/scrape_ecnl_365days.py
  
  # Custom output file
  python scripts/scrape_ecnl_365days.py --output data/raw/ecnl_all_games.jsonl
  
  # Auto-import to database
  python scripts/scrape_ecnl_365days.py --auto-import
  
  # Custom date range (e.g., last 180 days)
  python scripts/scrape_ecnl_365days.py --days-back 180
        """
    )
    
    parser.add_argument(
        '--conferences-file',
        type=str,
        default='data/raw/ecnl_conferences_simplified.json',
        help='Path to ECNL conferences JSON file (default: data/raw/ecnl_conferences_simplified.json)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output file path (default: auto-generated timestamp)'
    )
    
    parser.add_argument(
        '--auto-import',
        action='store_true',
        help='Automatically import games to database after scraping'
    )
    
    parser.add_argument(
        '--days-back',
        type=int,
        default=365,
        help='Number of days to look back (default: 365)'
    )
    
    args = parser.parse_args()
    
    try:
        scrape_ecnl_365days(
            conferences_file=args.conferences_file,
            output_file=args.output,
            auto_import=args.auto_import,
            days_back=args.days_back
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Scraper failed")
        sys.exit(1)


if __name__ == "__main__":
    main()












