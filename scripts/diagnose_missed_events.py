#!/usr/bin/env python3
"""
Diagnostic script to identify potentially missed events from GotSport event scraper

This script helps identify:
1. Events that were discovered but failed to scrape
2. Events that might have been missed due to date filtering
3. Events in the scraped_events.json that have no games
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
import json
import logging

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from scripts.scrape_new_gotsport_events import EventDiscovery, load_scraped_events

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_scraped_events_file(scraped_events_file: str = "data/raw/scraped_events.json"):
    """Check the scraped events file for issues"""
    scraped_events_path = Path(scraped_events_file)
    
    if not scraped_events_path.exists():
        console.print(f"[yellow]⚠️  Scraped events file not found: {scraped_events_file}[/yellow]")
        return
    
    scraped_event_ids = load_scraped_events(scraped_events_path)
    console.print(f"[cyan]Found {len(scraped_event_ids)} events in scraped_events.json[/cyan]")
    
    # Check for events that might have failed
    # We can't tell from the file alone, but we can list them
    table = Table(title="Scraped Event IDs", box=box.ROUNDED, show_header=True)
    table.add_column("Event ID", style="cyan")
    
    for event_id in sorted(scraped_event_ids)[:50]:  # Show first 50
        table.add_row(event_id)
    
    if len(scraped_event_ids) > 50:
        table.add_row(f"... and {len(scraped_event_ids) - 50} more")
    
    console.print(table)
    console.print()


def discover_events_in_range(start_date: date, end_date: date) -> list:
    """Discover all events in a date range"""
    console.print(f"[cyan]Discovering events from {start_date} to {end_date}...[/cyan]")
    
    discovery = EventDiscovery()
    all_events = discovery.discover_events_in_range(start_date, end_date)
    
    return all_events


def compare_discovered_vs_scraped(
    days_back: int = 14,
    scraped_events_file: str = "data/raw/scraped_events.json"
):
    """Compare discovered events vs scraped events to find missed ones"""
    console.print(Panel.fit(
        f"[bold cyan]Event Discovery Diagnostic[/bold cyan]\n"
        f"[dim]Checking last {days_back} days for missed events[/dim]",
        style="cyan"
    ))
    
    # Load scraped events
    scraped_events_path = Path(scraped_events_file)
    scraped_event_ids = load_scraped_events(scraped_events_path)
    
    # Discover events in the range
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    all_events = discover_events_in_range(start_date, end_date)
    
    # Find events that were discovered but not scraped
    missed_events = [e for e in all_events if e['event_id'] not in scraped_event_ids]
    
    # Also find events that were scraped but might have issues
    scraped_but_might_have_issues = [e for e in all_events if e['event_id'] in scraped_event_ids]
    
    # Display results
    console.print(f"\n[green]✅ Found {len(all_events)} total events in date range[/green]")
    console.print(f"[yellow]⚠️  {len(missed_events)} events discovered but NOT in scraped_events.json[/yellow]")
    console.print(f"[cyan]ℹ️  {len(scraped_but_might_have_issues)} events already in scraped_events.json[/cyan]\n")
    
    if missed_events:
        table = Table(title="Potentially Missed Events", box=box.ROUNDED, show_header=True)
        table.add_column("Event ID", style="cyan")
        table.add_column("Event Name", style="yellow")
        table.add_column("Date", style="green")
        table.add_column("End Date", style="blue")
        table.add_column("Status", style="red")
        
        for event in missed_events[:20]:  # Show first 20
            end_date_str = event.get('end_date', 'Unknown')
            if end_date_str:
                try:
                    end_date_obj = datetime.fromisoformat(end_date_str).date()
                    today = date.today()
                    if end_date_obj > today:
                        status = "Future event"
                    elif end_date_obj == today:
                        status = "Ends today"
                    else:
                        status = "Ended"
                except:
                    status = "Unknown"
            else:
                status = "No end date"
            
            table.add_row(
                event['event_id'],
                event['event_name'][:50] + "..." if len(event['event_name']) > 50 else event['event_name'],
                event.get('date', 'Unknown'),
                end_date_str or 'Unknown',
                status
            )
        
        if len(missed_events) > 20:
            table.add_row("...", f"... and {len(missed_events) - 20} more", "...", "...", "...")
        
        console.print(table)
        console.print()
        
        # Save missed events to file
        output_file = f"data/raw/missed_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump({
                'check_date': datetime.now().isoformat(),
                'days_back': days_back,
                'total_discovered': len(all_events),
                'missed_count': len(missed_events),
                'missed_events': missed_events
            }, f, indent=2)
        
        console.print(f"[dim]Missed events saved to {output_file}[/dim]\n")
    
    return missed_events


def check_recent_summaries(days_back: int = 7):
    """Check recent summary files for events that had issues"""
    console.print(f"[cyan]Checking recent summary files for issues...[/cyan]")
    
    data_dir = Path("data/raw")
    if not data_dir.exists():
        console.print("[yellow]⚠️  data/raw directory not found[/yellow]")
        return
    
    # Find all summary files from the last N days
    summary_files = sorted(data_dir.glob("new_events_*_summary.json"), reverse=True)
    
    if not summary_files:
        console.print("[yellow]⚠️  No summary files found[/yellow]")
        return
    
    # Check the most recent summary files
    recent_summaries = summary_files[:5]  # Last 5 runs
    
    table = Table(title="Recent Scrape Results", box=box.ROUNDED, show_header=True)
    table.add_column("Date", style="cyan")
    table.add_column("Total Events", style="green", justify="right")
    table.add_column("Success", style="green", justify="right")
    table.add_column("No Teams", style="yellow", justify="right")
    table.add_column("Errors", style="red", justify="right")
    table.add_column("Total Games", style="blue", justify="right")
    
    for summary_file in recent_summaries:
        try:
            with open(summary_file, 'r') as f:
                data = json.load(f)
            
            scrape_date = data.get('scrape_date', 'Unknown')
            try:
                date_obj = datetime.fromisoformat(scrape_date)
                date_str = date_obj.strftime('%Y-%m-%d %H:%M')
            except:
                date_str = scrape_date[:16] if len(scrape_date) > 16 else scrape_date
            
            events = data.get('events', [])
            success_count = sum(1 for e in events if e.get('status') == 'success')
            no_teams_count = sum(1 for e in events if e.get('status') == 'no_teams')
            error_count = sum(1 for e in events if e.get('status') == 'error')
            total_games = data.get('total_games', 0)
            
            table.add_row(
                date_str,
                str(len(events)),
                str(success_count),
                str(no_teams_count),
                str(error_count),
                str(total_games)
            )
        except Exception as e:
            logger.error(f"Error reading {summary_file}: {e}")
            continue
    
    console.print(table)
    console.print()
    
    # Show events with issues from most recent run
    if recent_summaries:
        try:
            with open(recent_summaries[0], 'r') as f:
                data = json.load(f)
            
            events = data.get('events', [])
            problematic_events = [e for e in events if e.get('status') in ['no_teams', 'error']]
            
            if problematic_events:
                console.print(f"[yellow]⚠️  {len(problematic_events)} events had issues in most recent run:[/yellow]\n")
                
                issue_table = Table(box=box.ROUNDED, show_header=True)
                issue_table.add_column("Event ID", style="cyan")
                issue_table.add_column("Event Name", style="yellow")
                issue_table.add_column("Status", style="red")
                issue_table.add_column("Issue", style="red")
                
                for event in problematic_events[:10]:
                    issue_table.add_row(
                        event.get('event_id', 'Unknown'),
                        event.get('event_name', 'Unknown')[:50],
                        event.get('status', 'Unknown'),
                        event.get('note', event.get('error', 'Unknown'))[:60]
                    )
                
                if len(problematic_events) > 10:
                    issue_table.add_row("...", f"... and {len(problematic_events) - 10} more", "...", "...")
                
                console.print(issue_table)
                console.print()
        except Exception as e:
            logger.error(f"Error analyzing recent summary: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose potentially missed events from GotSport scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--days-back', type=int, default=14,
                       help='How many days back to check for missed events (default: 14)')
    parser.add_argument('--scraped-events', type=str, default='data/raw/scraped_events.json',
                       help='Path to scraped_events.json file')
    parser.add_argument('--check-summaries', action='store_true',
                       help='Also check recent summary files for issues')
    
    args = parser.parse_args()
    
    # Check scraped events file
    check_scraped_events_file(args.scraped_events)
    
    # Compare discovered vs scraped
    missed_events = compare_discovered_vs_scraped(
        days_back=args.days_back,
        scraped_events_file=args.scraped_events
    )
    
    # Check recent summaries if requested
    if args.check_summaries:
        check_recent_summaries(days_back=args.days_back)
    
    if missed_events:
        console.print(f"\n[bold yellow]Recommendation:[/bold yellow]")
        console.print(f"Run the scraper with --days-back {args.days_back} to catch these missed events:")
        console.print(f"  python scripts/scrape_new_gotsport_events.py --days-back {args.days_back} --no-auto-import")
    else:
        console.print("\n[bold green]✅ No missed events found![/bold green]")


if __name__ == '__main__':
    main()












