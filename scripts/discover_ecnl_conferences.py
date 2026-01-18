#!/usr/bin/env python3
"""
Discover ECNL conferences and map them to AthleteOne event/flight IDs

This script helps identify all available ECNL conferences and their corresponding
AthleteOne API parameters (org_id, org_season_id, event_id, flight_id).

Usage:
    python scripts/discover_ecnl_conferences.py
"""
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ECNLDiscovery:
    """Discover ECNL conferences and their API parameters"""
    
    BASE_URL = "https://theecnl.com"
    SCHEDULE_URL = "https://theecnl.com/sports/2023/8/8/ECNLG_0808235238.aspx"
    API_BASE = "https://api.athleteone.com"
    
    # Known ECNL parameters
    ORG_ID = "9"
    ORG_SEASON_ID = "69"  # 2025-26 season
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def get_initial_page(self) -> str:
        """Load the ECNL schedule page"""
        logger.info(f"Loading ECNL schedule page: {self.SCHEDULE_URL}")
        response = self.session.get(self.SCHEDULE_URL, timeout=30)
        response.raise_for_status()
        return response.text
    
    def extract_conferences_from_page(self, html: str) -> List[Dict[str, str]]:
        """Extract conference options from the page HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        conferences = []
        
        # Find the conference select dropdown
        # Look for select element with conference options
        selects = soup.find_all('select')
        for select in selects:
            options = select.find_all('option')
            for option in options:
                text = option.get_text(strip=True)
                value = option.get('value', '')
                
                # Filter for ECNL conference options (skip "--- Select ---")
                if text and text != "--- Select ---" and "ECNL" in text:
                    conferences.append({
                        'name': text,
                        'value': value if value else text,
                        'display_name': text
                    })
        
        logger.info(f"Found {len(conferences)} conferences")
        return conferences
    
    def get_event_list(self, event_id: str = "0") -> str:
        """Get event list from AthleteOne API"""
        url = f"{self.API_BASE}/api/Script/get-event-list-by-season-id/{self.ORG_SEASON_ID}/{event_id}"
        logger.debug(f"Fetching event list: {url}")
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    
    def get_division_list(self, event_id: str, schedule_id: str = "0", flight_id: str = "0") -> str:
        """Get division/flight list from AthleteOne API"""
        url = f"{self.API_BASE}/api/Script/get-division-list-by-event-id/{self.ORG_ID}/{event_id}/{schedule_id}/{flight_id}"
        logger.debug(f"Fetching division list: {url}")
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    
    def parse_event_list_response(self, response_text: str) -> List[Dict]:
        """Parse event list API response"""
        # The response is typically HTML or JSON
        # Try to parse as JSON first
        try:
            data = json.loads(response_text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'events' in data:
                return data['events']
        except json.JSONDecodeError:
            pass
        
        # If not JSON, try parsing as HTML
        soup = BeautifulSoup(response_text, 'html.parser')
        events = []
        
        # Look for option elements or other event indicators
        options = soup.find_all('option')
        for option in options:
            value = option.get('value', '')
            text = option.get_text(strip=True)
            if value and value != "0" and value != "":
                events.append({
                    'id': value,
                    'name': text
                })
        
        return events
    
    def parse_division_list_response(self, response_text: str) -> List[Dict]:
        """Parse division/flight list API response"""
        # Similar to event list parsing
        try:
            data = json.loads(response_text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'divisions' in data:
                return data['divisions']
        except json.JSONDecodeError:
            pass
        
        soup = BeautifulSoup(response_text, 'html.parser')
        divisions = []
        
        options = soup.find_all('option')
        for option in options:
            value = option.get('value', '')
            text = option.get_text(strip=True)
            if value and value != "0" and value != "":
                divisions.append({
                    'id': value,
                    'name': text
                })
        
        return divisions
    
    def discover_all_conferences(self) -> List[Dict]:
        """
        Discover all ECNL conferences and their parameters
        
        Returns:
            List of conference dictionaries with API parameters
        """
        console.print("[bold cyan]Discovering ECNL Conferences[/bold cyan]")
        
        # Step 1: Load initial page
        html = self.get_initial_page()
        
        # Step 2: Extract conference names from page
        conferences = self.extract_conferences_from_page(html)
        
        if not conferences:
            console.print("[yellow]No conferences found in page HTML. May need browser automation.[/yellow]")
            return []
        
        # Step 3: Get event list to map conferences to event IDs
        console.print(f"[cyan]Fetching event list for org_season_id={self.ORG_SEASON_ID}[/cyan]")
        event_list_response = self.get_event_list()
        events = self.parse_event_list_response(event_list_response)
        
        console.print(f"[green]Found {len(events)} events[/green]")
        
        # Step 4: For each event, get division list (age groups)
        discovered = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Discovering conferences...", total=len(events))
            
            for event in events[:10]:  # Limit to first 10 for testing
                event_id = event.get('id', '')
                event_name = event.get('name', '')
                
                # Get divisions/flights for this event
                try:
                    division_response = self.get_division_list(event_id)
                    divisions = self.parse_division_list_response(division_response)
                    
                    discovered.append({
                        'conference_name': event_name,
                        'org_id': self.ORG_ID,
                        'org_season_id': self.ORG_SEASON_ID,
                        'event_id': event_id,
                        'divisions': divisions,
                        'source': 'ecnl'
                    })
                    
                    progress.update(task, advance=1)
                except Exception as e:
                    logger.warning(f"Error getting divisions for event {event_id}: {e}")
                    progress.update(task, advance=1)
        
        return discovered


def main():
    """Main discovery function"""
    discovery = ECNLDiscovery()
    
    try:
        conferences = discovery.discover_all_conferences()
        
        if not conferences:
            console.print("[red]No conferences discovered. May need browser automation.[/red]")
            console.print("[yellow]Consider using Selenium or Playwright for dynamic content.[/yellow]")
            return
        
        # Display results
        table = Table(title="Discovered ECNL Conferences")
        table.add_column("Conference", style="cyan")
        table.add_column("Event ID", style="green")
        table.add_column("Divisions", style="yellow")
        
        for conf in conferences:
            divisions_str = ", ".join([d.get('name', d.get('id', '')) for d in conf.get('divisions', [])[:3]])
            if len(conf.get('divisions', [])) > 3:
                divisions_str += "..."
            table.add_row(
                conf['conference_name'],
                conf['event_id'],
                divisions_str or "None"
            )
        
        console.print(table)
        
        # Save to file
        output_file = Path("data/raw/ecnl_conferences.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(conferences, f, indent=2)
        
        console.print(f"[green]Saved {len(conferences)} conferences to {output_file}[/green]")
        
        # Also save a simplified version for easy reference
        simplified = []
        for conf in conferences:
            for div in conf.get('divisions', []):
                simplified.append({
                    'conference': conf['conference_name'],
                    'age_group': div.get('name', div.get('id', '')),
                    'org_id': conf['org_id'],
                    'org_season_id': conf['org_season_id'],
                    'event_id': conf['event_id'],
                    'flight_id': div.get('id', '0')
                })
        
        simplified_file = Path("data/raw/ecnl_conferences_simplified.json")
        with open(simplified_file, 'w') as f:
            json.dump(simplified, f, indent=2)
        
        console.print(f"[green]Saved simplified mapping to {simplified_file}[/green]")
        
    except Exception as e:
        console.print(f"[red]Error during discovery: {e}[/red]")
        logger.exception("Discovery failed")
        raise


if __name__ == "__main__":
    main()












