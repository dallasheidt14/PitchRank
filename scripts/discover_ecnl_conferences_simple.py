#!/usr/bin/env python3
"""
Simple ECNL conference discovery - writes results to files
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

log_file = output_dir / "ecnl_discovery_log.txt"
log = open(log_file, 'w')

def log_msg(msg):
    print(msg)
    log.write(msg + '\n')
    log.flush()

log_msg("=" * 60)
log_msg("ECNL Conference Discovery")
log_msg("=" * 60)

# Step 1: Get event list
log_msg(f"\nStep 1: Fetching event list (org_season_id={ORG_SEASON_ID})")
event_list_url = f"{API_BASE}/api/Script/get-event-list-by-season-id/{ORG_SEASON_ID}/0"

try:
    response = requests.get(event_list_url, timeout=30)
    response.raise_for_status()
    event_list_html = response.text
    log_msg(f"✓ Fetched {len(event_list_html)} characters")
    
    # Save raw HTML
    html_file = output_dir / "ecnl_event_list.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(event_list_html)
    log_msg(f"✓ Saved to {html_file}")
    
    # Parse HTML
    soup = BeautifulSoup(event_list_html, 'html.parser')
    events = []
    
    # Look for option elements
    options = soup.find_all('option')
    log_msg(f"\nFound {len(options)} option elements")
    
    for option in options:
        value = option.get('value', '')
        text = option.get_text(strip=True)
        if value and value != "0" and value != "":
            events.append({
                'id': value,
                'name': text
            })
            log_msg(f"  Event: {text} (ID: {value})")
    
    log_msg(f"\n✓ Found {len(events)} events")
    
    if not events:
        log_msg("\n⚠ No events found. Response might be in different format.")
        log_msg(f"First 1000 chars of response:\n{event_list_html[:1000]}")
    
except Exception as e:
    log_msg(f"\n✗ Error fetching event list: {e}")
    import traceback
    traceback.print_exc(file=log)
    log.close()
    sys.exit(1)

# Step 2: For each event, get divisions
log_msg(f"\nStep 2: Getting divisions for each event")
all_conferences = []

for event in events[:20]:  # Limit to first 20 for testing
    event_id = event['id']
    event_name = event['name']
    
    log_msg(f"\n  Processing: {event_name} (ID: {event_id})")
    
    try:
        division_url = f"{API_BASE}/api/Script/get-division-list-by-event-id/{ORG_ID}/{event_id}/0/0"
        response = requests.get(division_url, timeout=30)
        response.raise_for_status()
        division_html = response.text
        
        # Parse divisions
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
        
        log_msg(f"    Found {len(divisions)} divisions")
        
        # Create conference entries
        for div in divisions:
            all_conferences.append({
                'conference': event_name,
                'age_group': div['name'],
                'org_id': ORG_ID,
                'org_season_id': ORG_SEASON_ID,
                'event_id': event_id,
                'flight_id': div['id']
            })
            log_msg(f"    - {div['name']} (flight_id: {div['id']})")
            
    except Exception as e:
        log_msg(f"    ✗ Error: {e}")

# Step 3: Save results
log_msg(f"\nStep 3: Saving results")
log_msg(f"Total conferences found: {len(all_conferences)}")

if all_conferences:
    # Save full format
    full_file = output_dir / "ecnl_conferences.json"
    with open(full_file, 'w') as f:
        json.dump(all_conferences, f, indent=2)
    log_msg(f"✓ Saved full format to {full_file}")
    
    # Save simplified format (already in simplified format)
    simplified_file = output_dir / "ecnl_conferences_simplified.json"
    with open(simplified_file, 'w') as f:
        json.dump(all_conferences, f, indent=2)
    log_msg(f"✓ Saved simplified format to {simplified_file}")
    
    # Show summary
    log_msg(f"\nSummary:")
    log_msg(f"  Total conference/age group combinations: {len(all_conferences)}")
    
    # Group by conference
    by_conference = {}
    for conf in all_conferences:
        conf_name = conf['conference']
        if conf_name not in by_conference:
            by_conference[conf_name] = []
        by_conference[conf_name].append(conf['age_group'])
    
    log_msg(f"  Unique conferences: {len(by_conference)}")
    for conf_name, age_groups in by_conference.items():
        log_msg(f"    - {conf_name}: {len(age_groups)} age groups")
else:
    log_msg("\n⚠ No conferences found!")

log_msg("\n" + "=" * 60)
log_msg("Discovery complete!")
log_msg("=" * 60)

log.close()












