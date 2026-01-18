#!/usr/bin/env python3
"""Check event dates for RSL-AZ and Baltimore events"""
import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).parent.parent))

from scripts.scrape_new_gotsport_events import EventDiscovery

discovery = EventDiscovery()
events = discovery.discover_events_by_date(date(2025, 12, 8))

print("\n" + "="*60)
print("Events found when searching 12/8/2025:")
print("="*60 + "\n")

for e in events:
    if 'RSL' in e['event_name'] or 'Baltimore' in e['event_name']:
        print(f"Event: {e['event_name']}")
        print(f"  Event ID: {e['event_id']}")
        print(f"  Date field: {e['date']}")
        print(f"  Start Date: {e.get('start_date', 'N/A')}")
        print(f"  End Date: {e.get('end_date', 'N/A')}")
        print()








