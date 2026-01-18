#!/usr/bin/env python3
"""
Search for U12 teams on SincSports using the search form
"""
import sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import re
import time

sys.path.append(str(Path(__file__).parent.parent))

BASE_URL = "https://soccer.sincsports.com"

def search_teams(gender="Boys", state="All States", age="U12", team_type="Team"):
    """Search for teams using the SincSports search form"""
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    
    # First, get the search page to extract ViewState
    search_url = f"{BASE_URL}/sicClubs.aspx?sinc=Y"
    print(f"Loading search page: {search_url}")
    
    response = session.get(search_url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Extract ViewState and EventValidation
    viewstate = soup.find('input', {'name': '__VIEWSTATE'})
    eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
    
    if not viewstate:
        print("Could not find ViewState - page structure may have changed")
        return []
    
    viewstate_value = viewstate.get('value', '')
    eventvalidation_value = eventvalidation.get('value', '') if eventvalidation else ''
    
    print(f"Found ViewState (length: {len(viewstate_value)})")
    
    # Prepare POST data
    # Note: We need to figure out the exact form field names
    # Let's inspect the form structure
    form = soup.find('form')
    if form:
        print(f"Form action: {form.get('action', 'N/A')}")
        print(f"Form method: {form.get('method', 'N/A')}")
    
    # Try to find the search button/input
    search_inputs = soup.find_all('input', {'type': 'submit'})
    print(f"Found {len(search_inputs)} submit inputs")
    for inp in search_inputs:
        print(f"  - {inp.get('name', 'unnamed')}: {inp.get('value', '')}")
    
    # For now, let's try a simple approach - look for team links in the page
    # The search might use AJAX, so we may need to inspect network requests
    
    # Extract team IDs from any links on the page
    team_ids = set()
    team_links = soup.find_all('a', href=re.compile(r'teamid=|team/default\.aspx\?teamid='))
    
    for link in team_links:
        href = link.get('href', '')
        match = re.search(r'teamid=([A-Z0-9]+)', href)
        if match:
            team_ids.add(match.group(1))
    
    print(f"\nFound {len(team_ids)} team IDs on search page")
    
    return list(team_ids)


def search_u12_teams_by_state(state="North Carolina"):
    """Search for U12 teams in a specific state"""
    print(f"\n{'='*60}")
    print(f"Searching for U12 teams in {state}")
    print(f"{'='*60}\n")
    
    team_ids = search_teams(gender="Boys", state=state, age="U12")
    
    if team_ids:
        print(f"\nFound {len(team_ids)} U12 team IDs:")
        for team_id in sorted(team_ids)[:20]:  # Show first 20
            print(f"  {team_id}")
        if len(team_ids) > 20:
            print(f"  ... and {len(team_ids) - 20} more")
    
    return team_ids


if __name__ == '__main__':
    # Try searching for U12 teams
    all_team_ids = set()
    
    # Search in multiple states
    states = ["North Carolina", "South Carolina", "Georgia", "All States"]
    
    for state in states:
        try:
            team_ids = search_u12_teams_by_state(state)
            all_team_ids.update(team_ids)
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"Error searching {state}: {e}")
    
    print(f"\n{'='*60}")
    print(f"Total unique U12 team IDs found: {len(all_team_ids)}")
    print(f"{'='*60}\n")
    
    if all_team_ids:
        print("Team IDs for import:")
        team_list = sorted(all_team_ids)
        for i, team_id in enumerate(team_list, 1):
            print(f'  "{team_id}",', end='')
            if i % 10 == 0:
                print()
        if len(team_list) % 10 != 0:
            print()

















