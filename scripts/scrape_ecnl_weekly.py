#!/usr/bin/env python3
"""
Weekly incremental scraper for ECNL games

Scrapes games from ECNL conferences, checking for new games in the last 7 days.
This is designed to run weekly to keep game data up-to-date incrementally.

Usage:
    # Basic usage (last 7 days)
    python scripts/scrape_ecnl_weekly.py
    
    # Custom date range
    python scripts/scrape_ecnl_weekly.py --days-back 14
    
    # Auto-import to database
    python scripts/scrape_ecnl_weekly.py --auto-import
"""
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

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
        logger.warning(f"Conferences file not found: {conferences_file}")
        return []
    
    try:
        with open(conferences_file, 'r') as f:
            conferences = json.load(f)
        logger.info(f"Loaded {len(conferences)} ECNL conference/age group combinations")
        return conferences
    except Exception as e:
        logger.error(f"Error loading conferences file: {e}")
        return []


def load_scraped_conferences(scraped_file: Path) -> Set[str]:
    """
    Load set of already-scraped conference/age group combinations
    
    Format: Set of "{event_id}/{flight_id}"
    
    Returns:
        Set of conference identifiers
    """
    if not scraped_file.exists():
        return set()
    
    try:
        with open(scraped_file, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'conferences' in data:
                return set(data['conferences'])
            elif isinstance(data, list):
                return set(data)
            else:
                return set()
    except Exception as e:
        logger.error(f"Error loading scraped conferences: {e}")
        return set()


def save_scraped_conference(scraped_file: Path, conference_key: str):
    """
    Save a conference/age group combination as scraped
    
    Args:
        scraped_file: Path to JSON file
        conference_key: Conference identifier "{event_id}/{flight_id}"
    """
    scraped_file.parent.mkdir(parents=True, exist_ok=True)
    
    scraped_conferences = load_scraped_conferences(scraped_file)
    scraped_conferences.add(conference_key)
    
    data = {
        'conferences': list(scraped_conferences),
        'last_updated': datetime.now().isoformat()
    }
    
    with open(scraped_file, 'w') as f:
        json.dump(data, f, indent=2)


def get_conference_key(conf: Dict) -> str:
    """Generate unique key for a conference/age group combination"""
    return f"{conf['event_id']}/{conf['flight_id']}"


def scrape_weekly_games(
    days_back: int = 7,
    conferences_file: str = None,
    scraped_conferences_file: str = None,
    output_file: str = None,
    auto_import: bool = False
):
    """
    Scrape games from ECNL conferences for the last N days
    
    Args:
        days_back: How many days back to scrape games (default: 7 = last week)
        conferences_file: Path to JSON file with ECNL conferences (default: data/raw/ecnl_conferences_simplified.json)
        scraped_conferences_file: Path to track scraped conferences (default: data/raw/ecnl_scraped_conferences.json)
        output_file: Output file path (default: auto-generated)
        auto_import: If True, automatically import games to database
    """
    console.print(Panel.fit(
        "[bold cyan]ECNL Weekly Scraper[/bold cyan]\n"
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
        console.print("[yellow]Run scripts/discover_ecnl_conferences.py first[/yellow]")
        return None
    
    console.print(f"[green]Found {len(conferences)} conference/age group combinations[/green]")
    
    # Load scraped conferences
    if scraped_conferences_file is None:
        scraped_conferences_file = "data/raw/ecnl_scraped_conferences.json"
    
    scraped_path = Path(scraped_conferences_file)
    scraped_conference_keys = load_scraped_conferences(scraped_path)
    
    console.print(f"[dim]Already scraped: {len(scraped_conference_keys)} conferences[/dim]")
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    console.print(f"[cyan]Date range: {start_date.date()} to {end_date.date()}[/cyan]")
    
    # Initialize scraper
    scraper = AthleteOneScraper()
    
    # Scrape conferences
    all_games: List[GameData] = []
    new_conferences_scraped = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
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
            conference_key = get_conference_key(conf)
            
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
                    progress.update(
                        task,
                        advance=1,
                        description=f"[green]✓ {display_name}: {len(filtered_games)} games[/green]"
                    )
                    
                    # Mark as scraped
                    if conference_key not in scraped_conference_keys:
                        save_scraped_conference(scraped_path, conference_key)
                        new_conferences_scraped.append(display_name)
                else:
                    progress.update(
                        task,
                        advance=1,
                        description=f"[dim]{display_name}: No games[/dim]"
                    )
                    
            except Exception as e:
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
    console.print(f"  New conferences scraped: {len(new_conferences_scraped)}")
    
    if not all_games:
        console.print("\n[yellow]No games found in date range![/yellow]")
        return None
    
    # Remove duplicates (same game from home/away perspectives)
    unique_games = {}
    for game in all_games:
        key = (game.game_date, game.team_name, game.opponent_name)
        if key not in unique_games:
            unique_games[key] = game
    
    console.print(f"  Unique games (after deduplication): {len(unique_games)}")
    
    # Save games to file
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/ecnl_weekly_{timestamp}.jsonl"
    
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
        description='Weekly incremental scraper for ECNL games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (last 7 days)
  python scripts/scrape_ecnl_weekly.py
  
  # Custom date range (last 14 days)
  python scripts/scrape_ecnl_weekly.py --days-back 14
  
  # Auto-import to database
  python scripts/scrape_ecnl_weekly.py --auto-import
  
  # Custom file paths
  python scripts/scrape_ecnl_weekly.py \\
    --conferences-file data/raw/ecnl_conferences.json \\
    --output data/raw/ecnl_this_week.jsonl
        """
    )
    
    parser.add_argument(
        '--days-back',
        type=int,
        default=7,
        help='How many days back to scrape games (default: 7)'
    )
    
    parser.add_argument(
        '--conferences-file',
        type=str,
        default='data/raw/ecnl_conferences_simplified.json',
        help='Path to ECNL conferences JSON file (default: data/raw/ecnl_conferences_simplified.json)'
    )
    
    parser.add_argument(
        '--scraped-conferences-file',
        type=str,
        default='data/raw/ecnl_scraped_conferences.json',
        help='Path to track scraped conferences (default: data/raw/ecnl_scraped_conferences.json)'
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
    
    args = parser.parse_args()
    
    try:
        scrape_weekly_games(
            days_back=args.days_back,
            conferences_file=args.conferences_file,
            scraped_conferences_file=args.scraped_conferences_file,
            output_file=args.output,
            auto_import=args.auto_import
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












