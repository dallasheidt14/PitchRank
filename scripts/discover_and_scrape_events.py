#!/usr/bin/env python3
"""
Discover GotSport events for a given month and scrape games from all of them
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, date
import json
import logging
import re
import time
from typing import List, Dict, Set
from urllib.parse import urlencode, urlparse, parse_qs

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich import box
from bs4 import BeautifulSoup
import requests

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


class EventDiscovery:
    """Discover GotSport events by searching their events page"""
    
    BASE_URL = "https://home.gotsoccer.com"
    EVENTS_SEARCH_URL = "https://home.gotsoccer.com/events.aspx"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def _find_max_page_number(self, soup: BeautifulSoup) -> int:
        """
        Find the maximum page number from pagination links
        
        Args:
            soup: BeautifulSoup object of the page
        
        Returns:
            Maximum page number found, or 1 if no pagination found
        """
        max_page = 1
        
        # Look for pagination links with Page parameter
        pagination_links = soup.find_all('a', href=re.compile(r'Page=', re.I))
        for link in pagination_links:
            href = link.get('href', '')
            # Extract page number from href like "Page=2" or "Page=4"
            match = re.search(r'Page=(\d+)', href, re.I)
            if match:
                page_num = int(match.group(1))
                if page_num > max_page:
                    max_page = page_num
        
        # Also check for pagination text like "Page 1 of 5" or "1 of 5"
        pagination_text = soup.find_all(string=re.compile(r'page\s+\d+\s+of\s+\d+', re.I))
        for text in pagination_text:
            match = re.search(r'page\s+\d+\s+of\s+(\d+)', text, re.I)
            if match:
                page_num = int(match.group(1))
                if page_num > max_page:
                    max_page = page_num
        
        # Check for pagination in text content
        page_text = soup.get_text()
        match = re.search(r'page\s+\d+\s+of\s+(\d+)', page_text, re.I)
        if match:
            page_num = int(match.group(1))
            if page_num > max_page:
                max_page = page_num
        
        return max_page
    
    def discover_events_by_month(self, year: int, month: int) -> List[Dict[str, str]]:
        """
        Discover events in a specific month (with pagination support)
        
        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)
        
        Returns:
            List of dicts with 'event_id', 'event_name', 'event_url', 'date'
        """
        all_events = []
        
        # GotSport events search URL format
        # https://home.gotsoccer.com/events.aspx?search=&type=Tournament&state=&date=11%2F1%2F2025&age=&featured=
        
        # Try different date formats and states
        # Start with first day of month
        search_date = f"{month}/1/{year}"
        
        console.print(f"[cyan]Searching for events in {month}/{year}...[/cyan]")
        
        # Method 1: Search by date on events page
        base_params = {
            'search': '',
            'type': 'Tournament',
            'date': search_date,
            'age': '',
            'featured': ''
        }
        
        seen_event_ids = set()
        
        try:
            # Start with page 1 (or no Page parameter)
            page = 1
            max_pages = 1  # Will be updated after first page
            
            while page <= max_pages:
                params = base_params.copy()
                if page > 1:
                    params['Page'] = str(page)
                
                response = self.session.get(self.EVENTS_SEARCH_URL, params=params, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # On first page, determine max pages
                if page == 1:
                    max_pages = self._find_max_page_number(soup)
                    logger.info(f"Found pagination: {max_pages} total pages")
                    if max_pages > 1:
                        console.print(f"[cyan]Found {max_pages} pages of results, fetching all pages...[/cyan]")
                
                # Look for event links
                # GotSport search page uses /rankings/event.aspx?EventID=12345
                # We need to extract EventID and try to access via system.gotsport.com/org_event/events/12345
                event_links = soup.find_all('a', href=re.compile(r'(EventID=|/org_event/events/|event_id=)', re.I))
                
                page_events = []
                
                for link in event_links:
                href = link.get('href', '')
                
                # Extract event ID from URL
                event_id = None
                event_url = None
                
                # Pattern 1: /rankings/event.aspx?EventID=12345 (from search page)
                # Note: These EventIDs may not directly map to system.gotsport.com event IDs
                # We'll try both formats
                match = re.search(r'EventID=(\d+)', href, re.I)
                if match:
                    event_id = match.group(1)
                    # Try system.gotsport.com format first (this is what our scraper expects)
                    event_url = f"https://system.gotsport.com/org_event/events/{event_id}"
                    # Also store the rankings URL as backup
                    rankings_url = f"https://home.gotsoccer.com{href}" if not href.startswith('http') else href
                
                # Pattern 2: /events.aspx?event_id=12345
                if not event_id:
                    match = re.search(r'event_id=(\d+)', href, re.I)
                    if match:
                        event_id = match.group(1)
                        event_url = f"https://system.gotsport.com/org_event/events/{event_id}"
                
                # Pattern 3: /org_event/events/12345
                if not event_id:
                    match = re.search(r'/org_event/events/(\d+)', href)
                    if match:
                        event_id = match.group(1)
                        if href.startswith('http'):
                            event_url = href
                        else:
                            event_url = f"https://system.gotsport.com{href}" if href.startswith('/') else f"https://system.gotsport.com/{href}"
                
                if event_id and event_id not in seen_event_ids:
                    # Get event name from link text or nearby text
                    event_name = link.get_text(strip=True)
                    if not event_name or len(event_name) < 3:
                        # Try to get from title attribute or parent
                        event_name = link.get('title', '') or link.get('aria-label', '')
                        if not event_name:
                            # Look for heading or paragraph nearby
                            parent = link.find_parent(['div', 'article', 'section'])
                            if parent:
                                # Look for heading in parent
                                heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                                if heading:
                                    event_name = heading.get_text(strip=True)
                                else:
                                    # Get text from parent, limit length
                                    event_name = parent.get_text(strip=True)[:100]
                    
                    if not event_name:
                        event_name = f"Event {event_id}"
                    
                    event_data = {
                        'event_id': event_id,
                        'event_name': event_name,
                        'event_url': event_url or f"https://system.gotsport.com/org_event/events/{event_id}",
                        'date': f"{year}-{month:02d}"
                    }
                    # Add rankings URL if we found one
                    if 'rankings_url' in locals():
                        event_data['rankings_url'] = rankings_url
                    
                    page_events.append(event_data)
                    seen_event_ids.add(event_id)
                
                # Method 2: Look for event IDs in JavaScript/data attributes
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        # Look for event IDs in JavaScript
                        matches = re.findall(r'event[_-]?id["\']?\s*[:=]\s*["\']?(\d+)', script.string, re.IGNORECASE)
                        for event_id in matches:
                            if event_id not in seen_event_ids:
                                page_events.append({
                                    'event_id': event_id,
                                    'event_name': f"Event {event_id}",
                                    'event_url': f"https://system.gotsport.com/org_event/events/{event_id}",
                                    'date': f"{year}-{month:02d}"
                                })
                                seen_event_ids.add(event_id)
                
                all_events.extend(page_events)
                logger.info(f"Page {page}: Found {len(page_events)} events (total so far: {len(all_events)})")
                
                # If no events found on this page and we're past page 1, stop
                if len(page_events) == 0 and page > 1:
                    logger.info(f"No events found on page {page}, stopping pagination")
                    break
                
                page += 1
                
                # Rate limiting between pages
                if page <= max_pages:
                    time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error discovering events: {e}")
            console.print(f"[red]Error discovering events: {e}[/red]")
        
        console.print(f"[green]Found {len(all_events)} events in search results[/green]")
        return all_events
    
    def discover_events_by_date_range(self, start_date: date, end_date: date) -> List[Dict[str, str]]:
        """
        Discover events in a date range by checking each month
        
        Args:
            start_date: Start date
            end_date: End date
        
        Returns:
            List of events
        """
        all_events = []
        seen_event_ids = set()
        
        # Iterate through months
        current = start_date.replace(day=1)
        while current <= end_date:
            month_events = self.discover_events_by_month(current.year, current.month)
            
            for event in month_events:
                if event['event_id'] not in seen_event_ids:
                    all_events.append(event)
                    seen_event_ids.add(event['event_id'])
            
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
            
            # Rate limiting
            time.sleep(1)
        
        return all_events


def discover_and_scrape_events(
    year: int,
    month: int,
    output_file: str = None,
    since_date: str = None
):
    """
    Discover all events in a month and scrape games from them
    
    Args:
        year: Year (e.g., 2025)
        month: Month (1-12)
        output_file: Output file path (default: auto-generated)
        since_date: Only scrape games after this date (YYYY-MM-DD format)
    """
    console.print(Panel.fit(
        f"[bold green]Discovering & Scraping Events - {month}/{year}[/bold green]",
        style="green"
    ))
    
    # Step 1: Discover events
    console.print("\n[bold cyan]Step 1: Discovering Events[/bold cyan]")
    discovery = EventDiscovery()
    events = discovery.discover_events_by_month(year, month)
    
    if not events:
        console.print("[yellow]No events found. Trying alternative discovery method...[/yellow]")
        # Alternative: Try a range of event IDs (less efficient but might find more)
        # For now, we'll just report what we found
        console.print("[red]No events discovered. You may need to manually provide event IDs.[/red]")
        return None
    
    console.print(f"[green]✅ Found {len(events)} events[/green]\n")
    
    # Display events table
    table = Table(title="Discovered Events", box=box.ROUNDED, show_header=True)
    table.add_column("Event ID", style="cyan")
    table.add_column("Event Name", style="yellow")
    table.add_column("URL", style="dim")
    
    for event in events[:20]:  # Show first 20
        table.add_row(
            event['event_id'],
            event['event_name'][:50] + "..." if len(event['event_name']) > 50 else event['event_name'],
            event['event_url']
        )
    
    if len(events) > 20:
        table.add_row("...", f"... and {len(events) - 20} more", "...")
    
    console.print(table)
    console.print()
    
    # Step 2: Scrape games from each event
    console.print("[bold cyan]Step 2: Scraping Games from Events[/bold cyan]")
    
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Parse since_date if provided
    since_date_obj = None
    if since_date:
        try:
            since_date_obj = datetime.strptime(since_date, '%Y-%m-%d')
        except ValueError:
            console.print(f"[red]Invalid date format: {since_date}. Use YYYY-MM-DD[/red]")
            return None
    
    all_games = []
    event_results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Scraping events...", total=len(events))
        
        for i, event in enumerate(events, 1):
            event_id = event['event_id']
            event_name = event['event_name']
            
            progress.update(task, description=f"[cyan]Scraping {event_name[:40]}... ({i}/{len(events)})")
            
            try:
                games = scraper.scrape_event_games(
                    event_id,
                    event_name=event_name,
                    since_date=since_date_obj
                )
                
                event_results.append({
                    'event_id': event_id,
                    'event_name': event_name,
                    'games_count': len(games),
                    'status': 'success'
                })
                
                all_games.extend(games)
                console.print(f"  [dim]{event_name}: {len(games)} games[/dim]")
                
            except Exception as e:
                logger.error(f"Error scraping event {event_id}: {e}")
                event_results.append({
                    'event_id': event_id,
                    'event_name': event_name,
                    'games_count': 0,
                    'status': 'error',
                    'error': str(e)
                })
                console.print(f"  [red]Error scraping {event_name}: {e}[/red]")
            
            progress.advance(task)
            
            # Rate limiting between events
            time.sleep(2)
    
    console.print(f"\n[bold green]✅ Scraped {len(all_games)} total games from {len(events)} events[/bold green]\n")
    
    # Summary table
    summary_table = Table(title="Scraping Summary", box=box.ROUNDED, show_header=True)
    summary_table.add_column("Event", style="cyan")
    summary_table.add_column("Games", style="green", justify="right")
    summary_table.add_column("Status", style="yellow")
    
    for result in event_results:
        status_icon = "✅" if result['status'] == 'success' else "❌"
        summary_table.add_row(
            result['event_name'][:40],
            str(result['games_count']),
            status_icon
        )
    
    console.print(summary_table)
    console.print()
    
    # Save games to file
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/events_{year}{month:02d}_{timestamp}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    console.print(f"[dim]Writing {len(all_games)} games to {output_file}...[/dim]")
    
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
    
    console.print(f"[bold green]✅ Saved to {output_file}[/bold green]")
    
    # Save event results summary
    summary_file = output_file.replace('.jsonl', '_summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            'year': year,
            'month': month,
            'total_events': len(events),
            'total_games': len(all_games),
            'events': event_results
        }, f, indent=2)
    
    console.print(f"[dim]Summary saved to {summary_file}[/dim]")
    
    return output_file


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Discover and scrape all GotSport events for a given month',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover and scrape all events in November 2025
  python scripts/discover_and_scrape_events.py --year 2025 --month 11
  
  # With output file
  python scripts/discover_and_scrape_events.py --year 2025 --month 11 --output data/raw/nov_2025_events.jsonl
  
  # Only games after a specific date
  python scripts/discover_and_scrape_events.py --year 2025 --month 11 --since-date 2025-11-01
        """
    )
    
    parser.add_argument('--year', type=int, required=True, help='Year (e.g., 2025)')
    parser.add_argument('--month', type=int, required=True, help='Month (1-12)')
    parser.add_argument('--output', type=str, default=None, help='Output file path (default: auto-generated)')
    parser.add_argument('--since-date', type=str, default=None, help='Only scrape games after this date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    if not (1 <= args.month <= 12):
        console.print("[red]Month must be between 1 and 12[/red]")
        sys.exit(1)
    
    discover_and_scrape_events(
        year=args.year,
        month=args.month,
        output_file=args.output,
        since_date=args.since_date
    )

