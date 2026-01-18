#!/usr/bin/env python3
"""
Debug event search to see why specific events aren't being found
"""
import sys
from pathlib import Path
from datetime import date
import re
from urllib.parse import urlencode

sys.path.append(str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
import requests

def debug_date_search(search_date: date, event_names: list):
    """Debug search for a specific date"""
    BASE_URL = "https://home.gotsoccer.com"
    EVENTS_SEARCH_URL = "https://home.gotsoccer.com/events.aspx"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    
    date_str = f"{search_date.month}/{search_date.day}/{search_date.year}"
    print(f"\n{'='*60}")
    print(f"Debugging search for date: {date_str}")
    print(f"Looking for events: {event_names}")
    print(f"{'='*60}\n")
    
    base_params = {
        'search': '',
        'type': 'Tournament',
        'date': date_str,
        'age': '',
        'featured': ''
    }
    
    # Check pagination
    page = 1
    max_pages = 1
    
    while page <= max_pages:
        params = base_params.copy()
        if page > 1:
            params['Page'] = str(page)
        
        full_url = f"{EVENTS_SEARCH_URL}?{urlencode(params)}"
        print(f"Fetching page {page}: {full_url}")
        
        response = session.get(EVENTS_SEARCH_URL, params=params, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find max pages
        if page == 1:
            pagination_links = soup.find_all('a', href=re.compile(r'Page=', re.I))
            max_page = 1
            for link in pagination_links:
                href = link.get('href', '')
                match = re.search(r'Page=(\d+)', href, re.I)
                if match:
                    page_num = int(match.group(1))
                    if page_num > max_page:
                        max_page = page_num
            max_pages = max_page
            print(f"Found {max_pages} total pages")
        
        # Look for event links
        event_links = soup.find_all('a', href=re.compile(r'EventID=', re.I))
        print(f"Page {page}: Found {len(event_links)} event links with EventID=")
        
        # Also check all links
        all_links = soup.find_all('a', href=True)
        event_related = [link for link in all_links if 'event' in link.get('href', '').lower()]
        print(f"Page {page}: Found {len(event_related)} links with 'event' in href")
        
        # Check page text for our target events
        page_text = soup.get_text()
        for event_name in event_names:
            if event_name.lower() in page_text.lower():
                print(f"  ✓ Found '{event_name}' in page text!")
                
                # Try to find the link
                for link in all_links:
                    link_text = link.get_text(strip=True)
                    href = link.get('href', '')
                    if event_name.lower() in link_text.lower():
                        print(f"    Link text: {link_text[:80]}")
                        print(f"    Link href: {href[:100]}")
                        
                        # Try to extract event ID
                        match = re.search(r'EventID=(\d+)', href, re.I)
                        if match:
                            print(f"    Event ID: {match.group(1)}")
                        else:
                            # Try other patterns
                            match = re.search(r'/events/(\d+)', href, re.I)
                            if match:
                                print(f"    Event ID (from path): {match.group(1)}")
            else:
                print(f"  ✗ '{event_name}' NOT found in page text")
        
        # Show sample event links
        print(f"\nSample event links from page {page}:")
        for link in event_links[:5]:
            href = link.get('href', '')
            link_text = link.get_text(strip=True)
            match = re.search(r'EventID=(\d+)', href, re.I)
            if match:
                print(f"  - Event ID: {match.group(1)}, Name: {link_text[:60]}")
        
        page += 1
        if page <= max_pages:
            print()

if __name__ == '__main__':
    import argparse
    from datetime import datetime
    
    parser = argparse.ArgumentParser(description='Debug event search')
    parser.add_argument('--date', type=str, required=True, help='Date to search (MM/DD/YYYY)')
    parser.add_argument('--events', nargs='+', required=True, help='Event names to look for')
    
    args = parser.parse_args()
    
    search_date = datetime.strptime(args.date, '%m/%d/%Y').date()
    debug_date_search(search_date, args.events)








