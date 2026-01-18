#!/usr/bin/env python3
"""
List all teams in a GotSport event, organized by bracket/group
"""
import sys
import argparse
from pathlib import Path
import re

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

from src.scrapers.gotsport_event import GotSportEventScraper

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)


def list_teams(event_id: str = None, event_url: str = None):
    """
    List all teams in an event, organized by bracket/group
    
    Args:
        event_id: GotSport event ID (e.g., "40550")
        event_url: Full URL to event page (alternative to event_id)
    """
    if not event_id and not event_url:
        console.print("[bold red]Error: Must provide either event_id or event_url[/bold red]")
        return
    
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Initialize scraper
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Extract event ID from URL if provided
    if event_url:
        match = re.search(r'/events/(\d+)', event_url)
        if not match:
            console.print(f"[bold red]Error: Could not extract event ID from URL: {event_url}[/bold red]")
            return
        event_id = match.group(1)
    
    console.print(f"[bold cyan]Fetching teams from event {event_id}...[/bold cyan]\n")
    
    # Get teams organized by bracket
    brackets = scraper.list_event_teams(event_id=event_id)
    
    if not brackets:
        console.print("[bold yellow]No teams found in this event[/bold yellow]")
        return
    
    # Display teams organized by bracket
    total_teams = sum(len(teams) for teams in brackets.values())
    console.print(f"[bold green]Found {total_teams} teams in {len(brackets)} brackets[/bold green]\n")
    
    # Export to JSON option
    import json
    from pathlib import Path
    output_file = f"data/raw/event_{event_id}_teams.json"
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to JSON-serializable format
    json_output = {}
    for bracket_name, teams in brackets.items():
        json_output[bracket_name] = [
            {
                'team_id': t.team_id,
                'team_name': t.team_name,
                'bracket_name': t.bracket_name,
                'actual_age_group': t.age_group,  # Team's actual age group
                'gender': t.gender,
                'division': t.division,
                'playing_up': t.playing_up  # True if playing in bracket above their age
            }
            for t in teams
        ]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2)
    
    console.print(f"[dim]Exported to JSON: {output_file}[/dim]\n")
    
    # Sort brackets alphabetically for consistent display
    sorted_brackets = sorted(brackets.items(), key=lambda x: x[0])
    
    for bracket_name, teams in sorted_brackets:
        # Create a table for this bracket
        table = Table(
            title=f"[bold]{bracket_name}[/bold] ({len(teams)} teams)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("Team ID", style="dim", width=10)
        table.add_column("Team Name", style="cyan", width=50)
        table.add_column("Actual Age", style="yellow", width=10)
        table.add_column("Gender", style="green", width=8)
        table.add_column("Playing Up", style="red", width=10)
        
        # Sort teams by team name for readability
        sorted_teams = sorted(teams, key=lambda t: t.team_name)
        
        for team in sorted_teams:
            age_display = team.age_group or "—"
            gender_display = team.gender or "—"
            playing_up_display = "⚠️ YES" if team.playing_up else "—"
            table.add_row(
                team.team_id,
                team.team_name,
                age_display,
                gender_display,
                playing_up_display
            )
        
        console.print(table)
        console.print()  # Blank line between brackets
    
    # Summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Total brackets: {len(brackets)}")
    console.print(f"  Total teams: {total_teams}")
    console.print(f"  JSON export: {output_file}")
    
    # Usage instructions
    console.print(f"\n[bold]Next Steps:[/bold]")
    console.print(f"  [dim]1. Review teams by bracket in the JSON file[/dim]")
    console.print(f"  [dim]2. Use PitchRank compare feature to audit bracket placements[/dim]")
    console.print(f"  [dim]3. Scrape games: python scripts/scrape_event.py --event-id {event_id}[/dim]")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='List all teams in a GotSport event, organized by bracket/group',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List teams by event ID
  python scripts/list_event_teams.py --event-id 40550
  
  # List teams by URL
  python scripts/list_event_teams.py --event-url "https://system.gotsport.com/org_event/events/40550"
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--event-id', type=str, help='GotSport event ID (e.g., 40550)')
    group.add_argument('--event-url', type=str, help='Full URL to event page')
    
    args = parser.parse_args()
    
    list_teams(event_id=args.event_id, event_url=args.event_url)

