#!/usr/bin/env python3
"""
Manual ECNL conference discovery using browser automation or manual mapping

Since the API response format may vary, this script helps discover conferences
by testing known patterns or using the browser to extract conference options.
"""
import sys
import json
import requests
from pathlib import Path
from bs4 import BeautifulSoup

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Constants
API_BASE = "https://api.athleteone.com"
ORG_ID = "9"
ORG_SEASON_ID = "69"

output_dir = Path("data/raw")
output_dir.mkdir(parents=True, exist_ok=True)

# Known conferences from browser inspection
# These are the conferences we saw in the dropdown
KNOWN_CONFERENCES = [
    "ECNL Girls Mid-Atlantic 2025-26",
    "ECNL Girls Midwest 2025-26",
    "ECNL Girls New England 2025-26",
    "ECNL Girls North Atlantic 2025-26",
    "ECNL Girls Northern Cal 2025-26",
    "ECNL Girls Northwest 2025-26",
    "ECNL Girls Ohio Valley 2025-26",
    "ECNL Girls Southeast 2025-26",
    "ECNL Girls Southwest 2025-26",
    "ECNL Girls Texas 2025-26"
]

# Known age groups from browser inspection
KNOWN_AGE_GROUPS = [
    "G2013",
    "G2012",
    "G2011",
    "G2010",
    "G2009",
    "G2008/2007"
]

print("=" * 60)
print("ECNL Conference Discovery (Manual/API Testing)")
print("=" * 60)

# Step 1: Try to get event list
print(f"\nStep 1: Fetching event list from API...")
event_list_url = f"{API_BASE}/api/Script/get-event-list-by-season-id/{ORG_SEASON_ID}/0"

try:
    response = requests.get(
        event_list_url,
        timeout=30,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://theecnl.com/'
        }
    )
    response.raise_for_status()
    event_list_html = response.text
    
    # Save for inspection
    html_file = output_dir / "ecnl_event_list_api.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(event_list_html)
    print(f"✓ Fetched {len(event_list_html)} characters")
    print(f"✓ Saved to {html_file}")
    
    # Try to parse
    soup = BeautifulSoup(event_list_html, 'html.parser')
    events = []
    
    # Look for various patterns
    options = soup.find_all('option')
    print(f"\nFound {len(options)} <option> elements")
    
    for option in options:
        value = option.get('value', '')
        text = option.get_text(strip=True)
        if value and value != "0" and value != "" and text:
            events.append({
                'id': value,
                'name': text
            })
            print(f"  Event: {text} (ID: {value})")
    
    if not events:
        print("\n⚠ No events found in HTML. Response format may be different.")
        print(f"First 500 chars: {event_list_html[:500]}")
        print("\nTrying alternative parsing...")
        
        # Try looking for other patterns
        # Sometimes the data is in script tags or other formats
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'event' in script.string.lower():
                print(f"Found script tag with potential event data")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Step 2: If we found events, get divisions for each
all_conferences = []

if events:
    print(f"\nStep 2: Getting divisions for {len(events)} events...")
    
    for event in events[:20]:  # Limit for testing
        event_id = event['id']
        event_name = event['name']
        
        print(f"\n  Processing: {event_name} (ID: {event_id})")
        
        try:
            division_url = f"{API_BASE}/api/Script/get-division-list-by-event-id/{ORG_ID}/{event_id}/0/0"
            response = requests.get(division_url, timeout=30)
            response.raise_for_status()
            division_html = response.text
            
            soup = BeautifulSoup(division_html, 'html.parser')
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
            
            print(f"    Found {len(divisions)} divisions")
            
            for div in divisions:
                all_conferences.append({
                    'conference': event_name,
                    'age_group': div['name'],
                    'org_id': ORG_ID,
                    'org_season_id': ORG_SEASON_ID,
                    'event_id': event_id,
                    'flight_id': div['id']
                })
                print(f"    - {div['name']} (flight_id: {div['id']})")
                
        except Exception as e:
            print(f"    ✗ Error: {e}")

# Step 3: Save results
print(f"\nStep 3: Saving results...")
print(f"Total conferences found: {len(all_conferences)}")

if all_conferences:
    simplified_file = output_dir / "ecnl_conferences_simplified.json"
    with open(simplified_file, 'w') as f:
        json.dump(all_conferences, f, indent=2)
    print(f"✓ Saved to {simplified_file}")
    
    # Show summary
    by_conference = {}
    for conf in all_conferences:
        conf_name = conf['conference']
        if conf_name not in by_conference:
            by_conference[conf_name] = []
        by_conference[conf_name].append(conf['age_group'])
    
    print(f"\nSummary:")
    print(f"  Total conference/age group combinations: {len(all_conferences)}")
    print(f"  Unique conferences: {len(by_conference)}")
    for conf_name, age_groups in sorted(by_conference.items()):
        print(f"    - {conf_name}: {len(age_groups)} age groups")
else:
    print("\n⚠ No conferences discovered via API.")
    print("\nNote: You may need to:")
    print("  1. Use browser automation to extract conferences from the page")
    print("  2. Manually map conferences by inspecting the ECNL website")
    print("  3. Test different event_id values to find all conferences")

print("\n" + "=" * 60)
print("Discovery complete!")
print("=" * 60)












