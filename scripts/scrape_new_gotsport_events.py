#!/usr/bin/env python3
"""
Weekly GotSport event scraper - finds new GotSport events and scrapes games from their teams
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
import json
import logging
import time
import re
import subprocess
import sys
from typing import List, Dict, Set
from urllib.parse import urlencode

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
    
    def resolve_event_id(self, rankings_event_id: str) -> str:
        """
        Resolve the actual system.gotsport.com event ID from a rankings page EventID
        
        The rankings page redirects to rankings.gotsport.com/events/{id}, which contains
        the actual event ID we need for system.gotsport.com/org_event/events/{id}
        
        Args:
            rankings_event_id: EventID from rankings page (e.g., "97871")
        
        Returns:
            Actual event ID for system.gotsport.com (e.g., "42498"), or rankings_event_id if not found
        """
        rankings_url = f"https://home.gotsoccer.com/rankings/event.aspx?EventID={rankings_event_id}"
        
        try:
            response = self.session.get(rankings_url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # The rankings page redirects to rankings.gotsport.com/events/{id}
            # Extract the event ID from the redirected URL
            final_url = response.url
            
            # Pattern 1: rankings.gotsport.com/events/{id}
            match = re.search(r'rankings\.gotsport\.com/events/(\d+)', final_url, re.I)
            if match:
                return match.group(1)
            
            # Pattern 2: system.gotsport.com/org_event/events/{id} (direct redirect)
            match = re.search(r'system\.gotsport\.com/org_event/events/(\d+)', final_url, re.I)
            if match:
                return match.group(1)
            
            # Pattern 3: Look for event ID in the URL path
            match = re.search(r'/events?/(\d+)', final_url, re.I)
            if match:
                return match.group(1)
            
            # Look for "Event Home" button or other links to system.gotsport.com
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for links to system.gotsport.com/org_event/events/
            event_links = soup.find_all('a', href=re.compile(r'system\.gotsport\.com/org_event/events/\d+', re.I))
            for link in event_links:
                href = link.get('href', '')
                match = re.search(r'/org_event/events/(\d+)', href)
                if match:
                    return match.group(1)
            
            # Look for button with onclick or data attributes that might contain the event ID
            buttons = soup.find_all(['button', 'a'], attrs={'onclick': True})
            for button in buttons:
                onclick = button.get('onclick', '')
                match = re.search(r'/org_event/events/(\d+)', onclick, re.I)
                if match:
                    return match.group(1)
            
        except Exception as e:
            logger.debug(f"Error resolving event ID {rankings_event_id}: {e}")
        
        # Fallback: return the original ID (might work, might not)
        return rankings_event_id
    
    def discover_events_by_date(self, search_date: date) -> List[Dict[str, str]]:
        """
        Discover events for a specific date
        
        Args:
            search_date: Date to search for events
        
        Returns:
            List of dicts with 'event_id', 'event_name', 'event_url', 'date'
        """
        events = []
        events_found_count = 0
        events_filtered_future = 0
        events_filtered_archived = 0
        event_links = []
        
        # Format date as MM/DD/YYYY for GotSport
        # Use format that works on Windows (no leading zero removal)
        date_str = f"{search_date.month}/{search_date.day}/{search_date.year}"  # e.g., "11/1/2025"
        
        console.print(f"[dim]Searching for events on {date_str}...[/dim]")
        
        params = {
            'search': '',
            'type': 'Tournament',
            'date': date_str,
            'age': '',
            'featured': ''
        }
        
        try:
            full_url = f"{self.EVENTS_SEARCH_URL}?{urlencode(params)}"
            logger.info(f"Fetching: {full_url}")
            response = self.session.get(self.EVENTS_SEARCH_URL, params=params, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Log search results for debugging
            logger.info(f"Searching GotSport events page for {date_str}, response status: {response.status_code}, content length: {len(response.text)}")
            
            # Initialize seen_event_ids before processing
            seen_event_ids = set()
            
            # Look for event links with EventID
            event_links = soup.find_all('a', href=re.compile(r'EventID=', re.I))
            logger.info(f"Found {len(event_links)} event links in search results for {date_str}")
            
            # Additional debugging: check for alternative link patterns
            if len(event_links) == 0:
                # Try alternative patterns - GotSport may have changed their link format
                all_links = soup.find_all('a', href=True)
                event_links_alt = [link for link in all_links if 'event' in link.get('href', '').lower()]
                logger.info(f"Found {len(event_links_alt)} links with 'event' in href")
                
                # Try to extract event IDs from alternative patterns
                # Pattern 1: /events.aspx?event_id=12345 or /events.aspx?id=12345
                # Pattern 2: /events/12345
                # Pattern 3: /event/12345
                # Pattern 4: /rankings/event.aspx?EventID=12345 (original pattern)
                for alt_link in event_links_alt[:20]:  # Check first 20 to avoid too many
                    href = alt_link.get('href', '')
                    event_id_match = None
                    
                    # Try various patterns
                    patterns = [
                        r'EventID=(\d+)',  # Original pattern
                        r'event_id=(\d+)',  # Lowercase variant
                        r'[?&]id=(\d+)',   # Generic id parameter
                        r'/events/(\d+)',   # /events/12345
                        r'/event/(\d+)',    # /event/12345
                        r'/events\.aspx[?&].*?(\d{4,})',  # /events.aspx with numeric ID
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, href, re.I)
                        if match:
                            potential_id = match.group(1)
                            # Validate it looks like an event ID (at least 4 digits)
                            if potential_id.isdigit() and len(potential_id) >= 4:
                                event_id_match = potential_id
                                logger.info(f"Found potential event ID {event_id_match} in link: {href[:100]}")
                                break
                    
                    if event_id_match and event_id_match not in seen_event_ids:
                        # Found a potential event ID via alternative pattern
                        # Add it to event_links so it gets processed below
                        event_links.append(alt_link)
                        logger.info(f"Added alternative link with event ID {event_id_match}")
                
                # Log a sample of the HTML structure for debugging if still no events
                if len(event_links) == 0:
                    if len(response.text) < 50000:  # Only log if reasonable size
                        logger.debug(f"Sample HTML structure (first 2000 chars): {response.text[:2000]}")
                    else:
                        # Try to find event-related content
                        event_divs = soup.find_all(['div', 'article', 'section'], class_=re.compile(r'event', re.I))
                        logger.info(f"Found {len(event_divs)} divs/articles/sections with 'event' in class name")
                        
                        # Log sample of alternative links for debugging
                        if event_links_alt:
                            logger.info(f"Sample alternative links (first 5):")
                            for link in event_links_alt[:5]:
                                logger.info(f"  - {link.get('href', '')[:100]}")
            
            for link in event_links:
                href = link.get('href', '')
                
                # Try multiple patterns to extract event ID
                rankings_event_id = None
                patterns = [
                    r'EventID=(\d+)',      # Original pattern: EventID=12345
                    r'event_id=(\d+)',     # Lowercase: event_id=12345
                    r'[?&]id=(\d+)',       # Generic: ?id=12345 or &id=12345
                    r'/events/(\d+)',      # Path: /events/12345
                    r'/event/(\d+)',       # Path: /event/12345
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, href, re.I)
                    if match:
                        potential_id = match.group(1)
                        # Validate it looks like an event ID (at least 4 digits)
                        if potential_id.isdigit() and len(potential_id) >= 4:
                            rankings_event_id = potential_id
                            break
                
                if rankings_event_id and rankings_event_id not in seen_event_ids:
                    events_found_count += 1
                    # Get event name
                    event_name = link.get_text(strip=True)
                    if not event_name or len(event_name) < 3:
                        parent = link.find_parent(['div', 'article', 'section'])
                        if parent:
                            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if heading:
                                event_name = heading.get_text(strip=True)
                            else:
                                event_name = parent.get_text(strip=True)[:100]
                    
                    if not event_name:
                        event_name = f"Event {rankings_event_id}"
                    
                    # Resolve the actual event ID
                    console.print(f"[dim]Resolving event ID for {event_name}...[/dim]")
                    actual_event_id = self.resolve_event_id(rankings_event_id)
                    
                    # Verify event page is accessible (not redirected to home page)
                    event_url = f"https://system.gotsport.com/org_event/events/{actual_event_id}"
                    try:
                        test_response = self.session.get(event_url, timeout=10, allow_redirects=True)
                        if 'org_event/events' not in test_response.url or test_response.url == 'https://home.gotsport.com/':
                            logger.info(f"Skipping event {event_name} ({actual_event_id}) - page redirects to home (event may be archived)")
                            events_filtered_archived += 1
                            continue
                    except Exception as e:
                        logger.debug(f"Could not verify event page accessibility: {e}")
                        # Continue anyway - might be a temporary issue
                    
                    # Try to extract actual event dates (will use search_date as fallback)
                    event_date = search_date.isoformat()
                    event_start_date = None
                    event_end_date = None
                    try:
                        from src.scrapers.gotsport_event import GotSportEventScraper
                        from supabase import create_client
                        supabase = create_client(
                            os.getenv('SUPABASE_URL'),
                            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
                        )
                        scraper = GotSportEventScraper(supabase, 'gotsport')
                        event_dates = scraper.extract_event_dates(actual_event_id)
                        if event_dates:
                            event_start_date, event_end_date = event_dates
                            # Use start date for display, but store both
                            event_date = event_start_date.isoformat()
                            logger.debug(f"Found actual event dates: {event_start_date} to {event_end_date}")
                    except Exception as e:
                        logger.debug(f"Could not extract event dates, using search date: {e}")
                    
                    # Only include events that have already ended (or end today)
                    # Filter out future events
                    today = date.today()
                    if event_end_date:
                        # Event has actual dates - only include if it ended today or earlier
                        # Allow events ending today (>= instead of >)
                        if event_end_date >= today:
                            # Include if ending today, skip if in future
                            if event_end_date > today:
                                logger.info(f"Skipping future event {event_name} (ends {event_end_date}, today is {today})")
                                events_filtered_future += 1
                                continue
                    else:
                        # No event dates found - use search_date as proxy
                        # Only include if search_date is today or earlier
                        if search_date > today:
                            logger.info(f"Skipping event {event_name} (search date {search_date} is in future, today is {today})")
                            events_filtered_future += 1
                            continue
                    
                    events.append({
                        'event_id': actual_event_id,
                        'event_name': event_name,
                        'event_url': event_url,
                        'date': event_date,
                        'start_date': event_start_date.isoformat() if event_start_date else None,
                        'end_date': event_end_date.isoformat() if event_end_date else None,
                        'rankings_event_id': rankings_event_id  # Keep original for reference
                    })
                    seen_event_ids.add(rankings_event_id)
                    seen_event_ids.add(actual_event_id)  # Also track resolved ID
                    
                    time.sleep(0.5)  # Rate limiting between resolutions
            
            # Also check JavaScript for event IDs
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    matches = re.findall(r'EventID["\']?\s*[:=]\s*["\']?(\d+)', script.string, re.IGNORECASE)
                    for rankings_event_id in matches:
                        if rankings_event_id not in seen_event_ids:
                            actual_event_id = self.resolve_event_id(rankings_event_id)
                            
                            # Try to extract actual event dates (will use search_date as fallback)
                            event_date = search_date.isoformat()
                            event_start_date = None
                            event_end_date = None
                            try:
                                from src.scrapers.gotsport_event import GotSportEventScraper
                                from supabase import create_client
                                supabase = create_client(
                                    os.getenv('SUPABASE_URL'),
                                    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
                                )
                                scraper = GotSportEventScraper(supabase, 'gotsport')
                                event_dates = scraper.extract_event_dates(actual_event_id)
                                if event_dates:
                                    event_start_date, event_end_date = event_dates
                                    event_date = event_start_date.isoformat()
                                    logger.debug(f"Found actual event dates: {event_start_date} to {event_end_date}")
                            except Exception as e:
                                logger.debug(f"Could not extract event dates, using search date: {e}")
                            
                            # Only include events that have already ended (or end today)
                            # Filter out future events
                            today = date.today()
                            event_name_js = f"Event {rankings_event_id}"  # Default name for JS-discovered events
                            if event_end_date:
                                # Event has actual dates - only include if it ended today or earlier
                                # Allow events ending today (>= instead of >)
                                if event_end_date >= today:
                                    # Include if ending today, skip if in future
                                    if event_end_date > today:
                                        logger.debug(f"Skipping future event {event_name_js} (ends {event_end_date})")
                                        continue
                            else:
                                # No event dates found - use search_date as proxy
                                # Only include if search_date is today or earlier
                                if search_date > today:
                                    logger.debug(f"Skipping event {event_name_js} (search date {search_date} is in future)")
                                    continue
                            
                            # Try to get event name from the page
                            event_name_js = f"Event {rankings_event_id}"
                            try:
                                event_url_test = f"https://system.gotsport.com/org_event/events/{actual_event_id}"
                                test_response = self.session.get(event_url_test, timeout=10, allow_redirects=True)
                                if 'org_event/events' in test_response.url:
                                    test_soup = BeautifulSoup(test_response.text, 'html.parser')
                                    title = test_soup.find('title')
                                    if title:
                                        event_name_js = title.get_text(strip=True)
                            except:
                                pass  # Use default name if we can't get it
                            
                            events.append({
                                'event_id': actual_event_id,
                                'event_name': event_name_js,
                                'event_url': f"https://system.gotsport.com/org_event/events/{actual_event_id}",
                                'date': event_date,
                                'start_date': event_start_date.isoformat() if event_start_date else None,
                                'end_date': event_end_date.isoformat() if event_end_date else None,
                                'rankings_event_id': rankings_event_id
                            })
                            seen_event_ids.add(rankings_event_id)
                            seen_event_ids.add(actual_event_id)
                            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error discovering events for {search_date}: {e}", exc_info=True)
        
        # Log summary
        if events_found_count > 0:
            logger.info(f"Date {date_str}: Found {events_found_count} events, {len(events)} included, {events_filtered_future} filtered (future), {events_filtered_archived} filtered (archived)")
            if events_filtered_future > 0:
                console.print(f"[yellow]  ⚠️  {events_filtered_future} events filtered (future dates)[/yellow]")
        elif len(event_links) == 0:
            logger.warning(f"Date {date_str}: No event links found in search results. GotSport may have changed their page structure or no events exist for this date.")
            console.print(f"[yellow]  ⚠️  No events found for {date_str}[/yellow]")
        
        return events
    
    def discover_events_in_range(self, start_date: date, end_date: date) -> List[Dict[str, str]]:
        """
        Discover events in a date range
        
        Args:
            start_date: Start date
            end_date: End date
        
        Returns:
            List of events (deduplicated by event_id)
        """
        all_events = []
        seen_event_ids = set()
        
        current_date = start_date
        while current_date <= end_date:
            date_events = self.discover_events_by_date(current_date)
            
            for event in date_events:
                if event['event_id'] not in seen_event_ids:
                    all_events.append(event)
                    seen_event_ids.add(event['event_id'])
            
            current_date += timedelta(days=1)
            time.sleep(0.5)  # Rate limiting
        
        return all_events


def load_scraped_events(file_path: Path) -> Set[str]:
    """Load list of already-scraped event IDs"""
    if not file_path.exists():
        return set()
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            return set(data.get('scraped_event_ids', []))
    except Exception as e:
        logger.warning(f"Error loading scraped events: {e}")
        return set()


def save_scraped_event(file_path: Path, event_id: str):
    """Save an event ID to the scraped events file"""
    scraped = load_scraped_events(file_path)
    scraped.add(event_id)
    
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump({
            'scraped_event_ids': list(scraped),
            'last_updated': datetime.now().isoformat()
        }, f, indent=2)


def scrape_new_events(
    days_back: int = 10,
    lookback_days: int = 30,
    output_file: str = None,
    scraped_events_file: str = None,
    auto_import: bool = True,
    manual_event_ids: List[str] = None
):
    """
    Scrape games from new events
    
    Args:
        days_back: How many days back to look for events (default: 7 = last week)
        lookback_days: How many days of games to scrape from event teams (default: 30)
        output_file: Output file path (default: auto-generated)
        scraped_events_file: File to track scraped events (default: data/raw/scraped_events.json)
        manual_event_ids: List of event IDs to scrape manually (for known missed events)
    """
    console.print(Panel.fit(
        f"[bold green]Weekly GotSport Event Scraper[/bold green]\n"
        f"[dim]Looking for events in last {days_back} days[/dim]\n"
        f"[dim]Scraping games from last {lookback_days} days[/dim]",
        style="green"
    ))
    
    # Setup
    if scraped_events_file is None:
        scraped_events_file = "data/raw/scraped_events.json"
    
    scraped_events_path = Path(scraped_events_file)
    scraped_event_ids = load_scraped_events(scraped_events_path)
    
    console.print(f"[dim]Already scraped {len(scraped_event_ids)} events[/dim]\n")
    
    # Step 1: Discover new events
    console.print("[bold cyan]Step 1: Discovering New Events[/bold cyan]")
    
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    # Ensure we don't search future dates (shouldn't happen, but safety check)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    
    console.print(f"[cyan]Searching for events from {start_date} to {end_date}...[/cyan]")
    console.print(f"[dim]Today is {date.today()}, searching {days_back} days back[/dim]")
    
    discovery = EventDiscovery()
    all_events = discovery.discover_events_in_range(start_date, end_date)
    
    logger.info(f"Discovery complete: Found {len(all_events)} total events in date range {start_date} to {end_date}")
    
    # Add manually specified event IDs
    if manual_event_ids:
        console.print(f"[cyan]Adding {len(manual_event_ids)} manually specified event IDs...[/cyan]")
        supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        scraper = GotSportEventScraper(supabase, 'gotsport')
        
        for event_id in manual_event_ids:
            if event_id not in scraped_event_ids:
                # Try to get event info
                try:
                    event_url = f"https://system.gotsport.com/org_event/events/{event_id}"
                    response = scraper.session.get(event_url, timeout=10, allow_redirects=True)
                    if 'org_event/events' in response.url and response.url != 'https://home.gotsport.com/':
                        # Extract event name from page
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(response.text, 'html.parser')
                        title = soup.find('title')
                        event_name = title.get_text(strip=True) if title else f"Event {event_id}"
                        
                        # Try to get event dates
                        event_dates = scraper.extract_event_dates(event_id)
                        event_start_date = None
                        event_end_date = None
                        if event_dates:
                            event_start_date, event_end_date = event_dates
                        
                        # Only add if event has ended or ends today
                        today = date.today()
                        if event_end_date and event_end_date > today:
                            console.print(f"  [yellow]Skipping {event_name} - ends in future ({event_end_date})[/yellow]")
                            continue
                        
                        manual_event = {
                            'event_id': event_id,
                            'event_name': event_name,
                            'event_url': event_url,
                            'date': event_start_date.isoformat() if event_start_date else date.today().isoformat(),
                            'start_date': event_start_date.isoformat() if event_start_date else None,
                            'end_date': event_end_date.isoformat() if event_end_date else None,
                            'rankings_event_id': None,
                            'manual': True  # Mark as manually added
                        }
                        
                        # Check if already in all_events
                        if not any(e['event_id'] == event_id for e in all_events):
                            all_events.append(manual_event)
                            console.print(f"  [green]✅ Added manual event: {event_name} ({event_id})[/green]")
                        else:
                            console.print(f"  [dim]Event {event_id} already discovered[/dim]")
                    else:
                        console.print(f"  [yellow]⚠️  Event {event_id} not accessible (may be archived or invalid)[/yellow]")
                except Exception as e:
                    logger.warning(f"Error adding manual event {event_id}: {e}")
                    console.print(f"  [red]❌ Error adding event {event_id}: {e}[/red]")
    
    # Filter to only new events
    new_events = [e for e in all_events if e['event_id'] not in scraped_event_ids]
    
    console.print(f"[green]✅ Found {len(new_events)} new events (out of {len(all_events)} total)[/green]\n")
    
    if not new_events:
        console.print("[yellow]No new events to scrape![/yellow]")
        return None
    
    # Display new events
    table = Table(title="New Events Found", box=box.ROUNDED, show_header=True)
    table.add_column("Event ID", style="cyan")
    table.add_column("Event Name", style="yellow")
    table.add_column("Date", style="green")
    
    for event in new_events[:20]:  # Show first 20
        table.add_row(
            event['event_id'],
            event['event_name'][:50] + "..." if len(event['event_name']) > 50 else event['event_name'],
            event['date']
        )
    
    if len(new_events) > 20:
        table.add_row("...", f"... and {len(new_events) - 20} more", "...")
    
    console.print(table)
    console.print()
    
    # Step 2: Scrape games from new events
    console.print("[bold cyan]Step 2: Scraping Games from Event Teams[/bold cyan]")
    
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
        task = progress.add_task("[cyan]Scraping events...", total=len(new_events))
        
        for i, event in enumerate(new_events, 1):
            event_id = event['event_id']
            event_name = event['event_name']
            
            progress.update(task, description=f"[cyan]Scraping {event_name[:40]}... ({i}/{len(new_events)})")
            
            try:
                # Extract teams from event
                # Note: The EventID from search page may not match system.gotsport.com event ID
                # We'll try it anyway - if it doesn't work, we'll skip it
                team_ids = scraper.extract_event_teams(event_id)
                
                if not team_ids:
                    # Try alternative method: scrape directly from schedule pages
                    # This bypasses team extraction and works even if event ID doesn't match
                    logger.info(f"Event {event_id} has no teams via extract_event_teams, trying schedule page method...")
                    try:
                        games = scraper.scrape_games_from_schedule_pages(
                            event_id,
                            event_name=event_name,
                            since_date=since_date
                        )
                        
                        if games:
                            event_results.append({
                                'event_id': event_id,
                                'event_name': event_name,
                                'teams_count': len(set(g.team_id for g in games if g.team_id)),
                                'games_count': len(games),
                                'status': 'success',
                                'note': 'Scraped via schedule pages (bypassed team extraction)'
                            })
                            all_games.extend(games)
                            console.print(f"  [green]✅ {event_name}: {len(games)} games (via schedule pages)[/green]")
                            # Mark as scraped since we got games
                            save_scraped_event(scraped_events_path, event_id)
                            progress.advance(task)
                            continue
                    except Exception as e:
                        logger.debug(f"Schedule page method also failed: {e}")
                    
                    # If schedule page method also fails, mark as no_teams
                    event_results.append({
                        'event_id': event_id,
                        'event_name': event_name,
                        'teams_count': 0,
                        'games_count': 0,
                        'status': 'no_teams',
                        'note': 'EventID may not match system.gotsport.com format, schedule page method also failed'
                    })
                    console.print(f"  [yellow]⚠️  {event_name}: No teams found (EventID may not match)[/yellow]")
                    # Don't mark as scraped - allow retry on next run
                    progress.advance(task)
                    continue
                
                # Scrape games directly from schedule pages (uses team ID resolution)
                # This method resolves event registration IDs to API team IDs automatically
                games = scraper.scrape_event_games(
                    event_id,
                    event_name=event_name,
                    since_date=since_date
                )
                
                event_results.append({
                    'event_id': event_id,
                    'event_name': event_name,
                    'teams_count': len(team_ids),
                    'games_count': len(games),
                    'status': 'success'
                })
                
                all_games.extend(games)
                console.print(f"  [dim]{event_name}: {len(team_ids)} teams, {len(games)} games[/dim]")
                
                # Mark as scraped
                save_scraped_event(scraped_events_path, event_id)
                
            except Exception as e:
                logger.error(f"Error scraping event {event_id}: {e}")
                event_results.append({
                    'event_id': event_id,
                    'event_name': event_name,
                    'teams_count': 0,
                    'games_count': 0,
                    'status': 'error',
                    'error': str(e)
                })
                console.print(f"  [red]Error scraping {event_name}: {e}[/red]")
            
            progress.advance(task)
            
            # Rate limiting between events
            time.sleep(2)
    
    console.print(f"\n[bold green]✅ Scraped {len(all_games)} total games from {len(new_events)} events[/bold green]\n")
    
    # Summary table
    summary_table = Table(title="Scraping Summary", box=box.ROUNDED, show_header=True)
    summary_table.add_column("Event", style="cyan")
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
            result['event_name'][:40],
            str(result['teams_count']),
            str(result['games_count']),
            status_icon
        )
    
    console.print(summary_table)
    console.print()
    
    # Save games to file
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/new_events_{timestamp}.jsonl"
    
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
                'age_group': game.meta.get('age_group') if game.meta else None,
                'gender': game.meta.get('gender') if game.meta else None,
            }
            f.write(json.dumps(game_dict) + '\n')
    
    console.print(f"[bold green]✅ Saved to {output_file}[/bold green]")
    
    # Save summary
    summary_file = output_file.replace('.jsonl', '_summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            'scrape_date': datetime.now().isoformat(),
            'days_back': days_back,
            'lookback_days': lookback_days,
            'total_events': len(new_events),
            'total_games': len(all_games),
            'events': event_results
        }, f, indent=2)
    
    console.print(f"[dim]Summary saved to {summary_file}[/dim]")
    
    # Step 3: Import games if requested
    if auto_import and len(all_games) > 0:
        console.print("\n[bold cyan]Step 3: Importing Games[/bold cyan]")
        import_success = import_games(output_file, 'gotsport')
        if import_success:
            console.print("[bold green]✅ All done! Games scraped and imported.[/bold green]")
        else:
            console.print("[yellow]⚠️  Games scraped but import failed. You can import manually later.[/yellow]")
    elif len(all_games) > 0:
        console.print(f"\n[dim]To import games, run:[/dim]")
        console.print(f"[dim]python scripts/import_games_enhanced.py {output_file} gotsport --stream --batch-size 500 --concurrency 4 --checkpoint[/dim]")
    
    return output_file


def import_games(games_file: str, provider: str) -> bool:
    """
    Import games to database using import_games_enhanced.py
    
    Args:
        games_file: Path to JSONL file with games
        provider: Provider ID (e.g., 'gotsport')
    
    Returns:
        True if import succeeded, False otherwise
    """
    if not games_file or not Path(games_file).exists():
        console.print("[yellow]No games file to import. Skipping import step.[/yellow]")
        return False
    
    try:
        console.print(f"[green]Importing games from {games_file}...[/green]")
        
        # Call import script via subprocess
        script_path = Path(__file__).parent / "import_games_enhanced.py"
        cmd = [
            sys.executable,
            str(script_path),
            games_file,
            provider,
            '--stream',
            '--batch-size', '500',
            '--concurrency', '4',
            '--checkpoint'
        ]
        
        # Run import script and capture output to parse metrics
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Print the import script output (includes metrics)
        if result.stdout:
            console.print(result.stdout)
        
        if result.returncode == 0:
            # Parse metrics from output for summary
            import re
            games_processed = None
            games_accepted = None
            duplicates_skipped = None
            
            if result.stdout:
                # Extract metrics from output
                processed_match = re.search(r'Games processed:\s*([\d,]+)', result.stdout)
                accepted_match = re.search(r'Games accepted:\s*([\d,]+)', result.stdout)
                duplicates_match = re.search(r'Duplicates skipped:\s*([\d,]+)', result.stdout)
                
                if processed_match:
                    games_processed = int(processed_match.group(1).replace(',', ''))
                if accepted_match:
                    games_accepted = int(accepted_match.group(1).replace(',', ''))
                if duplicates_match:
                    duplicates_skipped = int(duplicates_match.group(1).replace(',', ''))
            
            # Display summary
            if games_processed is not None:
                console.print(f"\n[bold cyan]Import Summary:[/bold cyan]")
                console.print(f"  [green]Games processed: {games_processed:,}[/green]")
                if games_accepted is not None:
                    console.print(f"  [green]New games imported: {games_accepted:,}[/green]")
                if duplicates_skipped is not None:
                    dedup_rate = (duplicates_skipped / games_processed * 100) if games_processed > 0 else 0
                    console.print(f"  [yellow]Duplicates skipped: {duplicates_skipped:,} ({dedup_rate:.1f}%)[/yellow]")
            
            console.print("[green]✅ Games imported successfully[/green]")
            return True
        else:
            console.print(f"[red]❌ Import failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Import stderr: {result.stderr}")
                console.print(f"[dim]{result.stderr[:500]}[/dim]")
            return False
        
    except Exception as e:
        console.print(f"[red]❌ Error importing games: {e}[/red]")
        logger.error(f"Import error: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Scrape games from new GotSport events (weekly workflow)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: Last 7 days of events, scrape last 30 days of games, auto-import enabled
  python scripts/scrape_new_gotsport_events.py
  
  # Skip automatic import
  python scripts/scrape_new_gotsport_events.py --no-auto-import
  
  # Last 14 days of events, scrape last 60 days of games
  python scripts/scrape_new_gotsport_events.py --days-back 14 --lookback-days 60
  
  # Custom output and tracking files
  python scripts/scrape_new_gotsport_events.py --output data/raw/weekly_events.jsonl --scraped-events data/raw/events_tracked.json
        """
    )
    
    parser.add_argument('--days-back', type=int, default=10,
                       help='How many days back to look for events (default: 10)')
    parser.add_argument('--lookback-days', type=int, default=30,
                       help='How many days of games to scrape from event teams (default: 30)')
    parser.add_argument('--output', type=str, default=None,
                       help='Output file path (default: auto-generated)')
    parser.add_argument('--scraped-events', type=str, default=None,
                       help='File to track scraped events (default: data/raw/scraped_events.json)')
    parser.add_argument('--no-auto-import', dest='auto_import', action='store_false',
                       help='Skip automatic import after scraping (default: auto-import is enabled)')
    parser.add_argument('--manual-event-ids', type=str, nargs='+',
                       help='Manually specify event IDs to scrape (for known missed events, e.g., --manual-event-ids 45163 45164)')
    
    args = parser.parse_args()
    
    # Default to True if --no-auto-import was not specified
    auto_import = getattr(args, 'auto_import', True)
    
    scrape_new_events(
        days_back=args.days_back,
        lookback_days=args.lookback_days,
        output_file=args.output,
        scraped_events_file=args.scraped_events,
        auto_import=auto_import,
        manual_event_ids=args.manual_event_ids
    )

