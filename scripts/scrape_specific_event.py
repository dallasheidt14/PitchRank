#!/usr/bin/env python3
"""
Manually scrape a specific GotSport event by ID

Use this when you know an event ID that was missed by the automatic scraper.
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from src.scrapers.gotsport_event import GotSportEventScraper
from scripts.scrape_new_gotsport_events import save_scraped_event, load_scraped_events

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)


def scrape_specific_event(event_id: str, lookback_days: int = 30, auto_import: bool = True, force: bool = False):
    """Scrape a specific event by ID"""
    console.print(Panel.fit(
        f"[bold green]Scraping Specific Event[/bold green]\n"
        f"[dim]Event ID: {event_id}[/dim]\n"
        f"[dim]Scraping games from last {lookback_days} days[/dim]",
        style="green"
    ))
    
    # Check if already scraped
    scraped_events_file = "data/raw/scraped_events.json"
    scraped_events_path = Path(scraped_events_file)
    scraped_event_ids = load_scraped_events(scraped_events_path)
    
    if event_id in scraped_event_ids:
        console.print(f"[yellow]⚠️  Event {event_id} has already been scraped[/yellow]")
        # Skip prompt in non-interactive environments (CI, GitHub Actions)
        if not force and sys.stdin.isatty():
            response = console.input("[cyan]Continue anyway? (y/N): [/cyan]")
            if response.lower() != 'y':
                return
        else:
            console.print("[cyan]Continuing anyway (non-interactive mode or --force flag)[/cyan]")
    
    # Initialize scraper
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Get event name
    try:
        event_url = f"https://system.gotsport.com/org_event/events/{event_id}"
        response = scraper.session.get(event_url, timeout=10, allow_redirects=True)
        if 'org_event/events' not in response.url or response.url == 'https://home.gotsport.com/':
            console.print(f"[red]❌ Event {event_id} not accessible (may be archived or invalid)[/red]")
            return
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.find('title')
        event_name = title.get_text(strip=True) if title else f"Event {event_id}"
        console.print(f"[cyan]Event: {event_name}[/cyan]\n")
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not get event name: {e}[/yellow]")
        event_name = f"Event {event_id}"
    
    # Scrape games
    console.print(f"[cyan]Scraping games from event {event_id}...[/cyan]")
    
    since_date = datetime.now() - timedelta(days=lookback_days)
    
    try:
        games = scraper.scrape_event_games(
            event_id,
            event_name=event_name,
            since_date=since_date
        )
        
        console.print(f"[green]✅ Found {len(games)} games[/green]\n")
        
        if not games:
            console.print("[yellow]No games found. Event may not have any games yet or may be using a different format.[/yellow]")
            return
        
        # Save games to file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/manual_event_{event_id}_{timestamp}.jsonl"
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        import json
        with open(output_file, 'w', encoding='utf-8') as f:
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
                f.write(json.dumps(game_dict) + '\n')
        
        console.print(f"[green]✅ Saved to {output_file}[/green]")
        
        # Mark as scraped
        save_scraped_event(scraped_events_path, event_id)
        console.print(f"[green]✅ Event {event_id} marked as scraped[/green]")
        
        # Import if requested
        if auto_import:
            console.print("\n[cyan]Importing games...[/cyan]")
            from scripts.scrape_new_gotsport_events import import_games
            import_success = import_games(output_file, 'gotsport')
            if import_success:
                console.print("[bold green]✅ All done! Games scraped and imported.[/bold green]")
            else:
                console.print("[yellow]⚠️  Games scraped but import failed. You can import manually later.[/yellow]")
        else:
            console.print(f"\n[dim]To import games, run:[/dim]")
            console.print(f"[dim]python scripts/import_games_enhanced.py {output_file} gotsport --stream --batch-size 500 --concurrency 4 --checkpoint[/dim]")
        
    except Exception as e:
        console.print(f"[red]❌ Error scraping event: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Manually scrape a specific GotSport event by ID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape event 45163
  python scripts/scrape_specific_event.py 45163
  
  # Scrape without auto-import
  python scripts/scrape_specific_event.py 45163 --no-auto-import
  
  # Scrape with custom lookback
  python scripts/scrape_specific_event.py 45163 --lookback-days 60
        """
    )
    
    parser.add_argument('event_id', type=str,
                       help='GotSport event ID to scrape')
    parser.add_argument('--lookback-days', type=int, default=30,
                       help='How many days of games to scrape (default: 30)')
    parser.add_argument('--no-auto-import', dest='auto_import', action='store_false',
                       help='Skip automatic import after scraping (default: auto-import is enabled)')
    parser.add_argument('--force', action='store_true',
                       help='Force scraping even if event was already scraped (useful for CI/GitHub Actions)')
    
    args = parser.parse_args()
    
    # Default to True if --no-auto-import was not specified
    auto_import = getattr(args, 'auto_import', True)
    
    scrape_specific_event(
        event_id=args.event_id,
        lookback_days=args.lookback_days,
        auto_import=auto_import,
        force=args.force
    )












