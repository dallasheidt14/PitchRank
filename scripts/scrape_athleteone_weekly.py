#!/usr/bin/env python3
"""
Weekly incremental scraper for AthleteOne/TGS events

Scrapes games from known AthleteOne events, checking for new games in the last 7 days.
This is designed to run weekly to keep game data up-to-date.

Usage:
    # Basic usage (last 7 days)
    python scripts/scrape_athleteone_weekly.py
    
    # Custom date range
    python scripts/scrape_athleteone_weekly.py --days-back 14
    
    # Auto-import to database
    python scripts/scrape_athleteone_weekly.py --auto-import
"""
import sys
import json
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.scrapers.athleteone_event import AthleteOneEventScraper
from src.base import GameData

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_known_events(events_file: Path) -> List[Dict]:
    """
    Load list of known AthleteOne events to scrape
    
    Expected format:
    [
        {
            "org_id": "12",
            "org_season_id": "70",
            "event_id": "3890",
            "flight_id": "32381",
            "name": "ECNL Boys Texas 2025-26 - B2010",
            ...
        }
    ]
    
    Returns:
        List of event dictionaries
    """
    if not events_file.exists():
        logger.warning(f"Events file not found: {events_file}")
        return []
    
    try:
        with open(events_file, 'r') as f:
            events = json.load(f)
        logger.info(f"Loaded {len(events)} known events from {events_file}")
        return events
    except Exception as e:
        logger.error(f"Error loading events file: {e}")
        return []


def load_scraped_events(scraped_file: Path) -> Set[str]:
    """
    Load set of already-scraped event/flight combinations
    
    Format: Set of "{org_id}/{org_season_id}/{event_id}/{flight_id}"
    
    Returns:
        Set of event identifiers
    """
    if not scraped_file.exists():
        return set()
    
    try:
        with open(scraped_file, 'r') as f:
            data = json.load(f)
            # Handle both old format (list of IDs) and new format (dict with events)
            if isinstance(data, dict) and 'events' in data:
                return set(data['events'])
            elif isinstance(data, list):
                return set(data)
            else:
                return set()
    except Exception as e:
        logger.error(f"Error loading scraped events: {e}")
        return set()


def save_scraped_event(scraped_file: Path, event_key: str):
    """
    Save an event/flight combination as scraped
    
    Args:
        scraped_file: Path to JSON file
        event_key: Event identifier "{org_id}/{org_season_id}/{event_id}/{flight_id}"
    """
    scraped_file.parent.mkdir(parents=True, exist_ok=True)
    
    scraped_events = load_scraped_events(scraped_file)
    scraped_events.add(event_key)
    
    data = {
        'events': list(scraped_events),
        'last_updated': datetime.now().isoformat()
    }
    
    with open(scraped_file, 'w') as f:
        json.dump(data, f, indent=2)


def get_event_key(event: Dict) -> str:
    """Generate unique key for an event/flight combination"""
    return f"{event['org_id']}/{event['org_season_id']}/{event['event_id']}/{event['flight_id']}"


def scrape_weekly_games(
    days_back: int = 7,
    events_file: str = None,
    scraped_events_file: str = None,
    output_file: str = None,
    auto_import: bool = False,
    use_saved_html: bool = False,
    html_cache_dir: str = None
):
    """
    Scrape games from AthleteOne events for the last N days
    
    Args:
        days_back: How many days back to scrape games (default: 7 = last week)
        events_file: Path to JSON file with known events (default: data/raw/athleteone_november_events.json)
        scraped_events_file: Path to track scraped events (default: data/raw/athleteone_scraped_events.json)
        output_file: Output file path (default: auto-generated)
        auto_import: If True, automatically import games to database
    """
    console.print(Panel.fit(
        f"[bold green]Weekly AthleteOne Event Scraper[/bold green]\n"
        f"[dim]Scraping games from last {days_back} days[/dim]"
        + (f"\n[dim]Using saved HTML files from cache[/dim]" if use_saved_html else ""),
        style="green"
    ))
    
    if not use_saved_html:
        console.print("[yellow]⚠ Note: API may block direct requests. Use --use-saved-html for testing.[/yellow]")
        console.print("[dim]For production, browser automation or cached HTML files are recommended.[/dim]\n")
    
    # Setup file paths
    if events_file is None:
        events_file = "data/raw/athleteone_november_events.json"
    
    if scraped_events_file is None:
        scraped_events_file = "data/raw/athleteone_scraped_events.json"
    
    events_path = Path(events_file)
    scraped_path = Path(scraped_events_file)
    
    # Load known events
    console.print("[bold cyan]Loading Known Events[/bold cyan]")
    known_events = load_known_events(events_path)
    
    if not known_events:
        console.print(f"[yellow]No events found in {events_file}[/yellow]")
        console.print("[cyan]Run scripts/discover_athleteone_november_events.py first to discover events[/cyan]")
        return None
    
    console.print(f"[green]Loaded {len(known_events)} known events[/green]\n")
    
    # Load already-scraped events
    scraped_event_keys = load_scraped_events(scraped_path)
    console.print(f"[dim]Already scraped {len(scraped_event_keys)} event/flight combinations[/dim]\n")
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    console.print(f"[cyan]Scraping games from {start_date.date()} to {end_date.date()}[/cyan]\n")
    
    # Initialize scraper
    scraper = AthleteOneEventScraper()
    
    all_games = []
    new_events_scraped = []
    
    # Scrape each event
    console.print("[bold cyan]Scraping Events[/bold cyan]")
    for i, event in enumerate(known_events, 1):
        event_key = get_event_key(event)
        event_name = event.get('name', f"Event {event['event_id']}")
        
        console.print(f"\n[{i}/{len(known_events)}] {event_name}")
        console.print(f"  Event: {event['event_id']}, Flight: {event['flight_id']}")
        
        try:
            # Check for saved HTML file if use_saved_html is enabled
            load_from_file = None
            if use_saved_html and html_cache_dir:
                html_cache_path = Path(html_cache_dir)
                # Try multiple possible file names
                possible_files = [
                    html_cache_path / f"athleteone_{event['event_id']}_{event['flight_id']}.html",
                    html_cache_path / f"athleteone_november_2025.html",  # Generic fallback
                    html_cache_path / "athleteone_november_2025.html",  # Direct name
                ]
                for html_file in possible_files:
                    if html_file.exists():
                        load_from_file = str(html_file)
                        console.print(f"  [dim]Using cached HTML: {html_file.name}[/dim]")
                        break
            
            # Scrape games from last N days
            games = scraper.scrape_event_games(
                org_id=event['org_id'],
                org_season_id=event['org_season_id'],
                event_id=event['event_id'],
                flight_id=event['flight_id'],
                since_date=start_date,
                load_from_file=load_from_file,
            )
            
            # Filter to only games in date range
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
                console.print(f"  [green]✓ Found {len(filtered_games)} games[/green]")
                
                # Mark as scraped
                if event_key not in scraped_event_keys:
                    save_scraped_event(scraped_path, event_key)
                    new_events_scraped.append(event_name)
            else:
                console.print(f"  [dim]No games found in date range[/dim]")
                
        except Exception as e:
            logger.error(f"Error scraping event {event['event_id']}: {e}", exc_info=True)
            console.print(f"  [red]✗ Error: {e}[/red]")
            continue
    
    # Summary
    console.print("\n[bold cyan]Summary[/bold cyan]")
    console.print(f"  Total games scraped: {len(all_games)}")
    console.print(f"  Events processed: {len(known_events)}")
    console.print(f"  New events scraped: {len(new_events_scraped)}")
    
    if not all_games:
        console.print("\n[yellow]No games found in date range![/yellow]")
        return None
    
    # Save games to file
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/athleteone_weekly_{timestamp}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    console.print(f"\n[cyan]Saving games to: {output_path}[/cyan]")
    
    with open(output_path, 'w') as f:
        for game in all_games:
            # Convert GameData to dict for JSON serialization
            game_dict = {
                'provider': game.provider_id,
                'team_id': game.team_id,
                'opponent_id': game.opponent_id,
                'team_name': game.team_name,
                'opponent_name': game.opponent_name,
                'game_date': game.game_date,
                'home_away': game.home_away,
                'goals_for': game.goals_for,
                'goals_against': game.goals_against,
                'result': game.result,
                'competition': game.competition,
                'venue': game.venue,
                'meta': game.meta or {},
            }
            f.write(json.dumps(game_dict) + '\n')
    
    console.print(f"[green]✅ Saved {len(all_games)} games to {output_path}[/green]")
    
    # Display sample games
    if all_games:
        console.print("\n[bold cyan]Sample Games[/bold cyan]")
        table = Table()
        table.add_column("Team", style="cyan")
        table.add_column("Opponent", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Score", style="yellow")
        
        for game in all_games[:5]:
            score = f"{game.goals_for or '-'} - {game.goals_against or '-'}"
            table.add_row(
                game.team_name or '',
                game.opponent_name or '',
                game.game_date or '',
                score
            )
        
        console.print(table)
    
    # Auto-import if requested
    if auto_import:
        console.print("\n[bold yellow]Auto-import not yet implemented[/bold yellow]")
        console.print("[dim]Use scripts/import_games.py to import manually[/dim]")
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Weekly incremental scraper for AthleteOne/TGS events'
    )
    parser.add_argument(
        '--days-back',
        type=int,
        default=7,
        help='How many days back to scrape games (default: 7)'
    )
    parser.add_argument(
        '--events-file',
        type=str,
        default=None,
        help='Path to JSON file with known events (default: data/raw/athleteone_november_events.json)'
    )
    parser.add_argument(
        '--scraped-events-file',
        type=str,
        default=None,
        help='Path to track scraped events (default: data/raw/athleteone_scraped_events.json)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output file path (default: auto-generated)'
    )
    parser.add_argument(
        '--auto-import',
        action='store_true',
        help='Automatically import games to database (not yet implemented)'
    )
    parser.add_argument(
        '--use-saved-html',
        action='store_true',
        help='Use saved HTML files from html-cache-dir instead of API calls'
    )
    parser.add_argument(
        '--html-cache-dir',
        type=str,
        default='data/raw/athleteone_cache',
        help='Directory containing cached HTML files (default: data/raw/athleteone_cache)'
    )
    
    args = parser.parse_args()
    
    try:
        scrape_weekly_games(
            days_back=args.days_back,
            events_file=args.events_file,
            scraped_events_file=args.scraped_events_file,
            output_file=args.output,
            auto_import=args.auto_import,
            use_saved_html=args.use_saved_html,
            html_cache_dir=args.html_cache_dir
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        logger.error(f"Error in weekly scraper: {e}", exc_info=True)
        console.print(f"[red]Error: {e}[/red]")
        raise


if __name__ == '__main__':
    main()

