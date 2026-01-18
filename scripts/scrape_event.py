#!/usr/bin/env python3
"""
Scrape games from a GotSport event/tournament
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime
import json
import logging

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from src.scrapers.gotsport_event import GotSportEventScraper

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def scrape_event(
    event_id: str = None,
    event_url: str = None,
    event_name: str = None,
    output_file: str = None,
    since_date: str = None
):
    """
    Scrape games from a GotSport event
    
    Args:
        event_id: GotSport event ID (e.g., "40550")
        event_url: Full URL to event page (alternative to event_id)
        event_name: Optional event name for filtering
        output_file: Output file path (default: auto-generated)
        since_date: Only scrape games after this date (YYYY-MM-DD format)
    """
    if not event_id and not event_url:
        console.print("[bold red]Error: Must provide either event_id or event_url[/bold red]")
        return None
    
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Initialize scraper
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Parse since_date if provided
    since_date_obj = None
    if since_date:
        try:
            since_date_obj = datetime.strptime(since_date, '%Y-%m-%d')
        except ValueError:
            console.print(f"[bold red]Error: Invalid date format: {since_date}. Use YYYY-MM-DD[/bold red]")
            return None
    
    # Scrape games
    console.print(f"[bold cyan]Scraping event...[/bold cyan]")
    if event_url:
        console.print(f"[dim]Event URL: {event_url}[/dim]")
        games = scraper.scrape_event_by_url(event_url, event_name, since_date_obj)
    else:
        console.print(f"[dim]Event ID: {event_id}[/dim]")
        # If no since_date provided, pass None to get all games (not just after Oct 17, 2025)
        if since_date_obj is None:
            console.print(f"[dim]No date filter - scraping all games from event teams[/dim]")
        games = scraper.scrape_event_games(event_id, event_name, since_date_obj)
    
    if not games:
        console.print("[bold yellow]No games found for this event[/bold yellow]")
        return None
    
    console.print(f"[bold green]Found {len(games)} games[/bold green]")
    
    # Convert to dict format for export
    games_data = []
    for game in games:
        game_dict = {
            'provider': 'gotsport',
            'team_id': game.team_id,
            'team_id_source': game.team_id,
            'opponent_id': game.opponent_id,
            'opponent_id_source': game.opponent_id,
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
            'scraped_at': game.meta.get('scraped_at', datetime.now().isoformat()) if game.meta else datetime.now().isoformat(),
            'club_name': game.meta.get('club_name', '') if game.meta else '',
            'opponent_club_name': game.meta.get('opponent_club_name', '') if game.meta else '',
            'age_group': game.meta.get('age_group') if game.meta else None,
            'gender': game.meta.get('gender') if game.meta else None,
        }
        games_data.append(game_dict)
    
    # Generate output filename if not provided
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        event_slug = event_id or 'event'
        output_file = f"data/raw/scraped_event_{event_slug}_{timestamp}.jsonl"
    
    # Ensure output directory exists
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to JSONL file
    console.print(f"[dim]Writing to {output_file}...[/dim]")
    with open(output_file, 'w', encoding='utf-8') as f:
        for game in games_data:
            f.write(json.dumps(game) + '\n')
    
    console.print(f"[bold green]✅ Scraped {len(games_data)} games to {output_file}[/bold green]")
    
    # Print summary
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Games scraped: {len(games_data)}")
    console.print(f"  Output file: {output_file}")
    
    return output_file


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Scrape games from a GotSport event/tournament',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape by event ID
  python scripts/scrape_event.py --event-id 40550
  
  # Scrape by URL
  python scripts/scrape_event.py --event-url "https://system.gotsport.com/org_event/events/40550"
  
  # Scrape with event name filter
  python scripts/scrape_event.py --event-id 40550 --event-name "Desert Super Cup"
  
  # Scrape only games after a specific date
  python scripts/scrape_event.py --event-id 40550 --since-date 2025-11-01
  
  # Specify output file
  python scripts/scrape_event.py --event-id 40550 --output data/raw/desert_super_cup.jsonl
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--event-id', type=str, help='GotSport event ID (e.g., 40550)')
    group.add_argument('--event-url', type=str, help='Full URL to event page')
    
    parser.add_argument('--event-name', type=str, help='Event name for filtering games (optional)')
    parser.add_argument('--output', type=str, help='Output file path (default: auto-generated)')
    parser.add_argument('--since-date', type=str, help='Only scrape games after this date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    scrape_event(
        event_id=args.event_id,
        event_url=args.event_url,
        event_name=args.event_name,
        output_file=args.output,
        since_date=args.since_date
    )

