#!/usr/bin/env python3
"""
Discover all AthleteOne/TGS events with games in November 2025

Uses browser automation to navigate ECNL schedules and find events with November games.
"""
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set
from bs4 import BeautifulSoup
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table

console = Console()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_event_params_from_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parse AthleteOne API URL to extract parameters
    
    Example URL:
    https://api.athleteone.com/api/Script/get-conference-schedules/12/70/3890/32381/0
    
    Returns:
        Dict with org_id, org_season_id, event_id, flight_id, or None if parsing fails
    """
    pattern = r'/get-conference-schedules/(\d+)/(\d+)/(\d+)/(\d+)/'
    match = re.search(pattern, url)
    if match:
        return {
            'org_id': match.group(1),
            'org_season_id': match.group(2),
            'event_id': match.group(3),
            'flight_id': match.group(4),
        }
    return None


def extract_november_dates_from_html(html: str) -> List[str]:
    """
    Extract all November 2025 dates from HTML
    
    Looks for date patterns like:
    - "Nov 01, 2025" in date headers
    - "11/1/2025" in date options
    - "November" text
    
    Returns:
        List of date strings found
    """
    november_dates = []
    
    # Pattern 1: "Nov 01, 2025" or "Nov 1, 2025"
    pattern1 = re.compile(r'Nov\s+(\d{1,2}),\s+2025', re.IGNORECASE)
    matches = pattern1.findall(html)
    for match in matches:
        november_dates.append(f"Nov {match}, 2025")
    
    # Pattern 2: "11/1/2025" or "11/01/2025" in date options
    pattern2 = re.compile(r'11/(\d{1,2})/2025')
    matches = pattern2.findall(html)
    for match in matches:
        november_dates.append(f"11/{match}/2025")
    
    # Pattern 3: Check for November in text
    if 'November' in html or 'Nov' in html:
        # Try to extract more specific dates
        soup = BeautifulSoup(html, 'html.parser')
        # Look for date headers
        date_headers = soup.find_all(text=re.compile(r'Nov.*2025', re.IGNORECASE))
        for header in date_headers:
            november_dates.append(header.strip())
    
    return list(set(november_dates))  # Remove duplicates


def check_html_has_november_games(html: str) -> bool:
    """
    Check if HTML contains November 2025 games
    
    Returns:
        True if HTML contains November dates/games
    """
    november_patterns = [
        r'Nov\s+\d{1,2},\s+2025',
        r'11/\d{1,2}/2025',
        r'November.*2025',
    ]
    
    for pattern in november_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            return True
    
    return False


def discover_november_events_via_browser() -> List[Dict]:
    """
    Discover November events by navigating ECNL website with browser automation
    
    Uses browser automation to:
    1. Navigate to ECNL schedules page
    2. Select different conferences
    3. Select different age groups
    4. Capture network requests for get-conference-schedules
    5. Check each schedule for November dates
    
    Returns:
        List of event dictionaries with parameters
    """
    console.print("[yellow]Note: Browser automation requires MCP browser extension[/yellow]")
    console.print("[cyan]For now, using manual discovery method...[/cyan]")
    
    # Known events we've discovered
    known_events = [
        {
            'org_id': '12',
            'org_season_id': '70',
            'event_id': '3890',
            'flight_id': '32381',
            'name': 'ECNL Boys Texas 2025-26 - B2010',
            'source': 'manually_discovered',
        }
    ]
    
    return known_events


def discover_events_from_network_logs() -> List[Dict]:
    """
    Discover events by analyzing network requests from ECNL page
    
    This would require capturing network logs, but provides a pattern
    for how to discover events programmatically.
    """
    console.print("[cyan]To discover events programmatically:[/cyan]")
    console.print("1. Navigate to: https://theecnl.com/sports/2023/8/8/ECNLB_0808235510.aspx")
    console.print("2. Open DevTools → Network tab")
    console.print("3. Filter for 'get-conference-schedules'")
    console.print("4. Select different conferences and age groups")
    console.print("5. Capture API URLs and extract parameters")
    console.print("6. Check each schedule HTML for November dates")
    
    return []


def test_event_for_november_games(
    org_id: str,
    org_season_id: str,
    event_id: str,
    flight_id: str,
    html_file: Optional[str] = None,
    use_browser: bool = False
) -> Optional[Dict]:
    """
    Test if an event has November games by fetching its schedule
    
    Args:
        org_id: Organization ID
        org_season_id: Organization season ID
        event_id: Event ID
        flight_id: Flight ID
        html_file: Optional path to HTML file to load (bypasses API)
        use_browser: If True, use browser to fetch (bypasses API restrictions)
    
    Returns:
        Dict with event info and November dates if found, None otherwise
    """
    from src.providers.athleteone_client import AthleteOneClient
    
    client = AthleteOneClient()
    
    try:
        if html_file:
            # Load from saved HTML file
            html, url = client.get_conference_schedule_html(
                org_id=org_id,
                org_season_id=org_season_id,
                event_id=event_id,
                flight_id=flight_id,
                load_from_file=html_file,
            )
        elif use_browser:
            # Use browser automation to fetch HTML
            console.print(f"[yellow]Browser automation not implemented in this script[/yellow]")
            console.print(f"[dim]Use browser tools manually or provide HTML file[/dim]")
            return None
        else:
            # Try direct API (may fail due to CORS)
            html, url = client.get_conference_schedule_html(
                org_id=org_id,
                org_season_id=org_season_id,
                event_id=event_id,
                flight_id=flight_id,
            )
        
        if check_html_has_november_games(html):
            november_dates = extract_november_dates_from_html(html)
            return {
                'org_id': org_id,
                'org_season_id': org_season_id,
                'event_id': event_id,
                'flight_id': flight_id,
                'url': url,
                'november_dates': november_dates,
                'has_november_games': True,
            }
        else:
            return None
            
    except Exception as e:
        logger.debug(f"Error testing event {event_id}/{flight_id}: {e}")
        # If API fails, try using saved HTML if available
        if not html_file:
            saved_html = Path("data/raw/athleteone_november_2025.html")
            if saved_html.exists():
                console.print(f"[dim]API failed, trying saved HTML file...[/dim]")
                return test_event_for_november_games(
                    org_id, org_season_id, event_id, flight_id,
                    html_file=str(saved_html)
                )
        return None


def discover_events_from_ecnl_schedules() -> List[Dict]:
    """
    Discover events by systematically exploring ECNL schedules page
    
    Strategy:
    1. Navigate to schedules page
    2. Try different conferences
    3. Try different age groups
    4. Capture API calls and check for November games
    
    Returns:
        List of event dictionaries
    """
    console.print("[cyan]To discover events systematically:[/cyan]")
    console.print("1. Navigate to ECNL schedules")
    console.print("2. For each conference:")
    console.print("   - Select conference from dropdown")
    console.print("   - For each age group:")
    console.print("     - Select age group")
    console.print("     - Capture get-conference-schedules API call")
    console.print("     - Check HTML for November dates")
    console.print("     - If found, save event parameters")
    
    return []


def main():
    """Main discovery function"""
    console.print("[bold cyan]Discovering AthleteOne/TGS Events with November 2025 Games[/bold cyan]")
    console.print()
    
    # Known ECNL organizations/seasons to check
    # These are examples - you'd need to discover more by exploring the site
    test_events = [
        {'org_id': '12', 'org_season_id': '70', 'event_id': '3890', 'flight_id': '32381'},
        # Add more known events here as discovered
        # Common ECNL org_ids: 12 (ECNL Boys), 16 (ECNL RL), etc.
        # You can discover these by checking network requests on the ECNL site
    ]
    
    november_events = []
    
    # Check if we have a saved HTML file to use
    saved_html = Path("data/raw/athleteone_november_2025.html")
    html_file = str(saved_html) if saved_html.exists() else None
    
    if html_file:
        console.print(f"[cyan]Using saved HTML file: {html_file}[/cyan]")
    
    console.print("[cyan]Testing known events for November games...[/cyan]")
    for event in test_events:
        console.print(f"  Testing: Event {event['event_id']}, Flight {event['flight_id']}")
        try:
            result = test_event_for_november_games(
                **event,
                html_file=html_file
            )
            if result:
                november_events.append(result)
                console.print(f"    [green]✓ Found November games![/green]")
                if result['november_dates']:
                    console.print(f"    Dates: {', '.join(result['november_dates'][:5])}")
            else:
                console.print(f"    [dim]No November games found[/dim]")
        except Exception as e:
            logger.error(f"Error testing event: {e}")
            console.print(f"    [red]Error: {e}[/red]")
    
    if november_events:
        console.print()
        console.print(f"[green]Found {len(november_events)} events with November games:[/green]")
        
        # Display results table
        table = Table(title="November 2025 Events")
        table.add_column("Org ID", style="cyan")
        table.add_column("Season ID", style="cyan")
        table.add_column("Event ID", style="cyan")
        table.add_column("Flight ID", style="cyan")
        table.add_column("November Dates", style="green")
        
        for event in november_events:
            dates_str = ', '.join(event['november_dates'][:3])
            if len(event['november_dates']) > 3:
                dates_str += f" (+{len(event['november_dates']) - 3} more)"
            
            table.add_row(
                event['org_id'],
                event['org_season_id'],
                event['event_id'],
                event['flight_id'],
                dates_str
            )
        
        console.print(table)
        
        # Save to JSON file
        output_file = Path("data/raw/athleteone_november_events.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(november_events, f, indent=2)
        
        console.print(f"\n[green]Saved results to: {output_file}[/green]")
    else:
        console.print("[yellow]No November events found. Try expanding the search.[/yellow]")
        console.print()
        console.print("[cyan]To discover more events:[/cyan]")
        console.print("1. Visit: https://theecnl.com/sports/2023/8/8/ECNLB_0808235510.aspx")
        console.print("2. Use browser DevTools to capture API calls")
        console.print("3. Extract org_id, org_season_id, event_id, flight_id from URLs")
        console.print("4. Add them to the test_events list in this script")


if __name__ == '__main__':
    main()

