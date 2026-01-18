#!/usr/bin/env python3
"""
Manage the scraped events tracking file
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

def load_scraped_events(file_path: Path):
    """Load scraped events from file"""
    if not file_path.exists():
        return set(), None
    
    with open(file_path, 'r') as f:
        data = json.load(f)
        return set(data.get('scraped_event_ids', [])), data.get('last_updated')

def save_scraped_events(file_path: Path, event_ids: set, last_updated: str = None):
    """Save scraped events to file"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump({
            'scraped_event_ids': sorted(list(event_ids)),
            'last_updated': last_updated or datetime.now().isoformat()
        }, f, indent=2)

def list_events(file_path: Path):
    """List all scraped events"""
    event_ids, last_updated = load_scraped_events(file_path)
    
    print(f"\n{'='*60}")
    print(f"Scraped Events Tracking")
    print(f"{'='*60}")
    print(f"File: {file_path}")
    print(f"Total events tracked: {len(event_ids)}")
    if last_updated:
        print(f"Last updated: {last_updated}")
    print(f"\nEvent IDs:")
    
    for event_id in sorted(event_ids):
        print(f"  - {event_id}")
    
    print()

def remove_event(file_path: Path, event_id: str):
    """Remove an event from the tracking file"""
    event_ids, last_updated = load_scraped_events(file_path)
    
    if event_id in event_ids:
        event_ids.remove(event_id)
        save_scraped_events(file_path, event_ids, last_updated)
        print(f"✅ Removed event {event_id} from tracking")
        print(f"   {len(event_ids)} events remaining")
    else:
        print(f"⚠️  Event {event_id} not found in tracking file")

def add_event(file_path: Path, event_id: str):
    """Add an event to the tracking file"""
    event_ids, _ = load_scraped_events(file_path)
    
    if event_id in event_ids:
        print(f"⚠️  Event {event_id} already in tracking file")
    else:
        event_ids.add(event_id)
        save_scraped_events(file_path, event_ids)
        print(f"✅ Added event {event_id} to tracking")
        print(f"   {len(event_ids)} events total")

def clear_all(file_path: Path, confirm: bool = False):
    """Clear all scraped events"""
    if not confirm:
        print("⚠️  This will clear ALL tracked events!")
        print("   Use --confirm to proceed")
        return
    
    save_scraped_events(file_path, set())
    print("✅ Cleared all tracked events")

def check_event(file_path: Path, event_id: str):
    """Check if an event has been scraped"""
    event_ids, last_updated = load_scraped_events(file_path)
    
    if event_id in event_ids:
        print(f"✅ Event {event_id} HAS been scraped")
        print(f"   Last updated: {last_updated}")
    else:
        print(f"❌ Event {event_id} has NOT been scraped yet")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manage scraped events tracking file')
    parser.add_argument('--file', type=str, default='data/raw/scraped_events.json',
                       help='Path to scraped events file (default: data/raw/scraped_events.json)')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # List command
    subparsers.add_parser('list', help='List all scraped events')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check if an event has been scraped')
    check_parser.add_argument('event_id', help='Event ID to check')
    
    # Remove command
    remove_parser = subparsers.add_parser('remove', help='Remove an event from tracking')
    remove_parser.add_argument('event_id', help='Event ID to remove')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add an event to tracking')
    add_parser.add_argument('event_id', help='Event ID to add')
    
    # Clear command
    clear_parser = subparsers.add_parser('clear', help='Clear all tracked events')
    clear_parser.add_argument('--confirm', action='store_true', help='Confirm clearing all events')
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    
    if args.command == 'list':
        list_events(file_path)
    elif args.command == 'check':
        check_event(file_path, args.event_id)
    elif args.command == 'remove':
        remove_event(file_path, args.event_id)
    elif args.command == 'add':
        add_event(file_path, args.event_id)
    elif args.command == 'clear':
        clear_all(file_path, args.confirm)
    else:
        parser.print_help()








