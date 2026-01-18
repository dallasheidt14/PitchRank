#!/usr/bin/env python3
"""Test that the fixed scraper finds RSL-AZ and Baltimore events"""
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))

from scripts.scrape_new_gotsport_events import EventDiscovery

discovery = EventDiscovery()
events = discovery.discover_events_by_date(date(2025, 12, 8))

print(f"\nFound {len(events)} total events for 12/8/2025\n")

# Check for our target events
rsl_found = False
baltimore_found = False

for e in events:
    event_name = e['event_name']
    event_id = e['event_id']
    
    if 'RSL' in event_name or 'Holiday Classic' in event_name:
        print(f"✓ Found RSL-AZ Holiday Classic: {event_name} (ID: {event_id})")
        rsl_found = True
    
    if 'Baltimore' in event_name:
        print(f"✓ Found Baltimore College Showcase: {event_name} (ID: {event_id})")
        baltimore_found = True

if not rsl_found:
    print("✗ RSL-AZ Holiday Classic NOT found")
if not baltimore_found:
    print("✗ 2025 Baltimore College Showcase NOT found")

print(f"\nAll events found:")
for e in events:
    print(f"  - {e['event_name']} ({e['event_id']})")








