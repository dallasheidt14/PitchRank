#!/usr/bin/env python3
"""
Scrape games from AthleteOne/TGS events by extracting teams and scraping their games

Usage:
    python scripts/scrape_athleteone_event.py \
      --org-id 16 \
      --org-season-id 72 \
      --event-id 3955 \
      --flight-id 0 \
      --max-teams 20 \
      --output data/raw/athleteone_event_output.csv
"""
import sys
import argparse
import csv
from pathlib import Path
from datetime import datetime
import logging

sys.path.append(str(Path(__file__).parent.parent))

from rich.console import Console
from src.scrapers.athleteone_event import AthleteOneEventScraper
from src.base import GameData

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def game_data_to_csv_dict(game: GameData) -> dict:
    """Convert GameData to CSV row format"""
    return {
        'provider': game.provider_id,
        'team_id': game.team_id,
        'team_id_source': game.team_id,
        'opponent_id': game.opponent_id or '',
        'opponent_id_source': game.opponent_id or '',
        'team_name': game.team_name or '',
        'opponent_name': game.opponent_name or '',
        'game_date': game.game_date or '',
        'home_away': game.home_away,
        'goals_for': game.goals_for if game.goals_for is not None else '',
        'goals_against': game.goals_against if game.goals_against is not None else '',
        'result': game.result or 'U',
        'competition': game.competition or '',
        'venue': game.venue or '',
        'source_url': game.meta.get('fetch_url', '') if game.meta else '',
        'scraped_at': datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Scrape games from AthleteOne/TGS events by extracting teams',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--org-id', type=str, required=True, help='Organization ID')
    parser.add_argument('--org-season-id', type=str, required=True, help='Organization season ID')
    parser.add_argument('--event-id', type=str, required=True, help='Event ID')
    parser.add_argument('--flight-id', type=str, required=True, help='Flight ID')
    parser.add_argument('--since-date', type=str, default=None, help='Only include games after this date (YYYY-MM-DD)')
    parser.add_argument('--max-teams', type=int, default=None, help='Limit number of teams to process (default: all)')
    parser.add_argument('--output', type=str, default=None, help='Output CSV file path')
    parser.add_argument('--load-from-file', type=str, default=None, help='Load HTML from file instead of API')
    
    args = parser.parse_args()
    
    # Parse since_date if provided
    since_date_obj = None
    if args.since_date:
        try:
            since_date_obj = datetime.strptime(args.since_date, '%Y-%m-%d')
        except ValueError:
            console.print(f"[red]Error: Invalid date format '{args.since_date}'. Use YYYY-MM-DD.[/red]")
            sys.exit(1)
    
    # Initialize scraper
    try:
        scraper = AthleteOneEventScraper()
    except Exception as e:
        console.print(f"[red]Error initializing scraper: {e}[/red]")
        logger.exception("Error initializing scraper")
        sys.exit(1)
    
    # Extract teams and scrape games
    console.print(f"[cyan]Extracting teams from event...[/cyan]")
    console.print(f"  Org ID: {args.org_id}")
    console.print(f"  Org Season ID: {args.org_season_id}")
    console.print(f"  Event ID: {args.event_id}")
    console.print(f"  Flight ID: {args.flight_id}")
    if args.max_teams:
        console.print(f"  Max Teams: {args.max_teams}")
    console.print()
    
    try:
        games = scraper.scrape_event_by_teams(
            org_id=args.org_id,
            org_season_id=args.org_season_id,
            event_id=args.event_id,
            flight_id=args.flight_id,
            since_date=since_date_obj,
            max_teams=args.max_teams,
            load_from_file=args.load_from_file,
        )
    except Exception as e:
        console.print(f"[red]Error scraping games: {e}[/red]")
        logger.exception("Error scraping games")
        sys.exit(1)
    
    if not games:
        console.print("[yellow]No games found[/yellow]")
        sys.exit(0)
    
    console.print(f"[green]Found {len(games)} game entries[/green]")
    
    # Determine output destination
    output_file = args.output
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"data/raw/athleteone_event_{args.org_id}_{args.event_id}_{timestamp}.csv"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write CSV
    console.print(f"[dim]Writing to {output_file}...[/dim]")
    
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'provider', 'team_id', 'team_id_source', 'opponent_id', 'opponent_id_source',
                'team_name', 'opponent_name', 'game_date', 'home_away',
                'goals_for', 'goals_against', 'result', 'competition', 'venue',
                'source_url', 'scraped_at'
            ]
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for game in games:
                row = game_data_to_csv_dict(game)
                writer.writerow(row)
        
        console.print(f"[bold green]✅ Successfully wrote {len(games)} game entries to {output_file}[/bold green]")
        
        # Print summary
        if games:
            unique_teams = set(g.team_id for g in games)
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Total game entries: {len(games)}")
            console.print(f"  Unique teams: {len(unique_teams)}")
            
            # Show sample
            sample = games[0]
            console.print(f"\n[bold]Sample GameData entry:[/bold]")
            console.print(f"  Team: {sample.team_name} ({sample.team_id})")
            console.print(f"  Opponent: {sample.opponent_name} ({sample.opponent_id})")
            console.print(f"  Date: {sample.game_date}")
            console.print(f"  Score: {sample.goals_for} - {sample.goals_against}")
            console.print(f"  Result: {sample.result}")
        
    except Exception as e:
        console.print(f"[red]Error writing CSV: {e}[/red]")
        logger.exception("Error writing CSV")
        sys.exit(1)


if __name__ == '__main__':
    main()

