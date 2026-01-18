#!/usr/bin/env python3
"""
Scrape games from a list of known event IDs (for weekly workflow)
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List
import json
import logging

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

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


def scrape_known_events(
    event_ids: List[str],
    lookback_days: int = 30,
    output_file: str = None
):
    """
    Scrape games from a list of known event IDs
    
    Args:
        event_ids: List of event IDs to scrape
        lookback_days: How many days of games to scrape (default: 30)
        output_file: Output file path (default: auto-generated)
    """
    console.print(Panel.fit(
        f"[bold green]Scraping Known Events[/bold green]\n"
        f"[dim]{len(event_ids)} events[/dim]\n"
        f"[dim]Scraping games from last {lookback_days} days[/dim]",
        style="green"
    ))
    
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Calculate since_date (lookback_days ago)
    since_date = datetime.now() - timedelta(days=lookback_days)
    
    all_games = []
    event_results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Scraping events...", total=len(event_ids))
        
        for i, event_id in enumerate(event_ids, 1):
            progress.update(task, description=f"[cyan]Scraping event {event_id}... ({i}/{len(event_ids)})")
            
            try:
                # Extract teams from event
                team_ids = scraper.extract_event_teams(event_id)
                
                if not team_ids:
                    event_results.append({
                        'event_id': event_id,
                        'teams_count': 0,
                        'games_count': 0,
                        'status': 'no_teams'
                    })
                    progress.advance(task)
                    continue
                
                # Scrape games from those teams (last N days)
                games = scraper.scrape_event_games(
                    event_id,
                    event_name=None,  # Don't filter by name
                    since_date=since_date
                )
                
                event_results.append({
                    'event_id': event_id,
                    'teams_count': len(team_ids),
                    'games_count': len(games),
                    'status': 'success'
                })
                
                all_games.extend(games)
                console.print(f"  [dim]Event {event_id}: {len(team_ids)} teams, {len(games)} games[/dim]")
                
            except Exception as e:
                logger.error(f"Error scraping event {event_id}: {e}")
                event_results.append({
                    'event_id': event_id,
                    'teams_count': 0,
                    'games_count': 0,
                    'status': 'error',
                    'error': str(e)
                })
            
            progress.advance(task)
            time.sleep(2)  # Rate limiting
    
    console.print(f"\n[bold green]✅ Scraped {len(all_games)} total games from {len(event_ids)} events[/bold green]\n")
    
    # Summary
    summary_table = Table(title="Scraping Summary", box=box.ROUNDED, show_header=True)
    summary_table.add_column("Event ID", style="cyan")
    summary_table.add_column("Teams", style="green", justify="right")
    summary_table.add_column("Games", style="yellow", justify="right")
    summary_table.add_column("Status", style="blue")
    
    for result in event_results:
        status_icon = {
            'success': '✅',
            'no_teams': '⚠️',
            'error': '❌'
        }.get(result['status'], '?')
        
        summary_table.add_row(
            result['event_id'],
            str(result['teams_count']),
            str(result['games_count']),
            status_icon
        )
    
    console.print(summary_table)
    
    # Save games
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/known_events_{timestamp}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for game in all_games:
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
            }
            f.write(json.dumps(game_dict) + '\n')
    
    console.print(f"\n[bold green]✅ Saved to {output_file}[/bold green]")
    
    return output_file


if __name__ == '__main__':
    import time
    
    parser = argparse.ArgumentParser(
        description='Scrape games from a list of known event IDs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape specific events
  python scripts/scrape_known_events.py --event-ids 40550,40551,40552
  
  # From a JSON file
  python scripts/scrape_known_events.py --events-file events.json
  
  # Last 60 days of games
  python scripts/scrape_known_events.py --event-ids 40550 --lookback-days 60
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--event-ids', type=str,
                      help='Comma-separated list of event IDs (e.g., "40550,40551")')
    group.add_argument('--events-file', type=str,
                      help='JSON file with list of event IDs')
    
    parser.add_argument('--lookback-days', type=int, default=30,
                       help='How many days of games to scrape (default: 30)')
    parser.add_argument('--output', type=str, default=None,
                       help='Output file path (default: auto-generated)')
    
    args = parser.parse_args()
    
    # Get event IDs
    if args.event_ids:
        event_ids = [eid.strip() for eid in args.event_ids.split(',')]
    else:
        with open(args.events_file, 'r') as f:
            data = json.load(f)
            event_ids = data.get('event_ids', [])
    
    scrape_known_events(
        event_ids=event_ids,
        lookback_days=args.lookback_days,
        output_file=args.output
    )

