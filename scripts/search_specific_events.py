#!/usr/bin/env python3
"""
Search for specific GotSport events by name to check why they weren't scraped
"""
import sys
from pathlib import Path
from datetime import date, timedelta
import re
from urllib.parse import urlencode

sys.path.append(str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
import requests

def search_for_event(event_name: str, search_date: date = None):
    """Search for a specific event by name"""
    if search_date is None:
        search_date = date.today()
    
    BASE_URL = "https://home.gotsoccer.com"
    EVENTS_SEARCH_URL = "https://home.gotsoccer.com/events.aspx"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    
    # Try searching by name first
    print(f"\n{'='*60}")
    print(f"Searching for: {event_name}")
    print(f"{'='*60}\n")
    
    # Search by name
    params = {
        'search': event_name,
        'type': 'Tournament',
        'date': '',
        'age': '',
        'featured': ''
    }
    
    try:
        response = session.get(EVENTS_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for event links
        event_links = soup.find_all('a', href=re.compile(r'EventID=', re.I))
        print(f"Found {len(event_links)} event links with name search")
        
        for link in event_links[:10]:  # Show first 10
            href = link.get('href', '')
            link_text = link.get_text(strip=True)
            match = re.search(r'EventID=(\d+)', href, re.I)
            if match:
                event_id = match.group(1)
                print(f"  - Event ID: {event_id}, Name: {link_text[:60]}")
        
        # Also try searching by date range (last 30 days)
        print(f"\nSearching by date range (last 30 days)...")
        start_date = date.today() - timedelta(days=30)
        current_date = start_date
        
        found_events = []
        while current_date <= date.today():
            date_str = f"{current_date.month}/{current_date.day}/{current_date.year}"
            params = {
                'search': '',
                'type': 'Tournament',
                'date': date_str,
                'age': '',
                'featured': ''
            }
            
            response = session.get(EVENTS_SEARCH_URL, params=params, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Check all text for the event name
            page_text = soup.get_text()
            if event_name.lower() in page_text.lower():
                print(f"  ✓ Found '{event_name}' on date {date_str}")
                found_events.append((current_date, date_str))
                
                # Find the event link
                event_links = soup.find_all('a', href=re.compile(r'EventID=', re.I))
                for link in event_links:
                    link_text = link.get_text(strip=True)
                    if event_name.lower() in link_text.lower():
                        href = link.get('href', '')
                        match = re.search(r'EventID=(\d+)', href, re.I)
                        if match:
                            event_id = match.group(1)
                            print(f"    Event ID: {event_id}, Name: {link_text[:60]}")
            
            current_date += timedelta(days=1)
        
        if not found_events:
            print(f"  ✗ '{event_name}' not found in last 30 days")
        
    except Exception as e:
        print(f"Error searching: {e}")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Search for specific GotSport events')
    parser.add_argument('event_names', nargs='+', help='Event names to search for')
    parser.add_argument('--date', type=str, help='Search date (MM/DD/YYYY)')
    
    args = parser.parse_args()
    
    search_date = None
    if args.date:
        from datetime import datetime
        search_date = datetime.strptime(args.date, '%m/%d/%Y').date()
    
    for event_name in args.event_names:
        search_for_event(event_name, search_date)








