#!/usr/bin/env python3
"""
Scrape games from GotSport and save to file for import
"""
import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime
import json
import csv
import logging

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track
from rich.table import Table
from rich import box

from src.scrapers.gotsport import GotSportScraper

console = Console()
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def scrape_games(provider: str = 'gotsport', output_file: str = None, limit_teams: int = None):
    """
    Scrape games from GotSport for all teams or specified teams
    """
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Initialize scraper
    scraper = GotSportScraper(supabase, provider)
    
    # Get teams to scrape
    teams = scraper._get_teams_to_scrape()
    
    if limit_teams:
        teams = teams[:limit_teams]
    
    console.print(f"[bold cyan]Scraping games for {len(teams)} teams[/bold cyan]\n")
    
    all_games = []
    errors = []
    
    # Scrape games for each team
    for team in track(teams, description="Scraping teams..."):
        team_id = team.get('provider_team_id')
        team_name = team.get('team_name', 'Unknown')
        
        try:
            games = scraper.scrape_team_games_as_dict(team_id)
            all_games.extend(games)
            console.print(f"[green]✓[/green] {team_name}: {len(games)} games")
        except Exception as e:
            error_msg = f"Team {team_id} ({team_name}): {str(e)}"
            errors.append(error_msg)
            console.print(f"[red]✗[/red] {error_msg}")
            logger.error(error_msg, exc_info=True)
    
    # Save to file
    if not output_file:
        output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save as JSONL
    with open(output_path, 'w', encoding='utf-8') as f:
        for game in all_games:
            f.write(json.dumps(game) + '\n')
    
    console.print(f"\n[bold green]✅ Scraping complete![/bold green]")
    console.print(f"  Games scraped: {len(all_games):,}")
    console.print(f"  Errors: {len(errors)}")
    console.print(f"  Output file: {output_path}")
    
    if errors:
        console.print(f"\n[yellow]Errors encountered:[/yellow]")
        for error in errors[:10]:
            console.print(f"  - {error}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more")
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='Scrape games from GotSport')
    parser.add_argument('--provider', type=str, default='gotsport', help='Provider code')
    parser.add_argument('--output', type=str, default=None, help='Output file path (default: auto-generated)')
    parser.add_argument('--limit-teams', type=int, default=None, help='Limit number of teams to scrape (for testing)')
    
    args = parser.parse_args()
    
    try:
        output_file = asyncio.run(scrape_games(
            provider=args.provider,
            output_file=args.output,
            limit_teams=args.limit_teams
        ))
        console.print(f"\n[green]Next step: Import games[/green]")
        console.print(f"  python scripts/import_games_enhanced.py {output_file} {args.provider} --stream")
    except KeyboardInterrupt:
        console.print("\n[yellow]Scraping cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error in scraper")
        sys.exit(1)


if __name__ == '__main__':
    main()

