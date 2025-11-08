#!/usr/bin/env python3
"""
Weekly automation script for PitchRank updates
1. Scrape new games (or import from file)
2. Import games to database
3. Recalculate rankings

Can be run manually or scheduled via Windows Task Scheduler
"""
import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime
import logging

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

# Import functions will be called via subprocess to avoid import issues
import subprocess

console = Console()
load_dotenv()

# Configure logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"weekly_update_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def scrape_games(provider: str, games_file: str = None, output_file: str = None):
    """
    Step 1: Scrape new games from GotSport
    
    If games_file is provided, use that instead of scraping.
    Otherwise, scrape from GotSport and save to file.
    """
    console.print(Panel.fit("[bold cyan]Step 1: Scraping New Games[/bold cyan]", style="cyan"))
    
    if games_file:
        console.print(f"[yellow]Using provided games file: {games_file}[/yellow]")
        return games_file
    
    # Scrape from GotSport
    try:
        console.print(f"[green]Scraping games from {provider}...[/green]")
        
        # Call scrape script via subprocess
        script_path = Path(__file__).parent.parent / "scrape_games.py"
        if not output_file:
            output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        
        cmd = [
            sys.executable,
            str(script_path),
            '--provider', provider,
            '--output', output_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            console.print(f"[green]✅ Games scraped successfully to {output_file}[/green]")
            return output_file
        else:
            console.print(f"[red]❌ Scraping failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Scrape stderr: {result.stderr}")
            return None
        
    except Exception as e:
        console.print(f"[red]❌ Error scraping games: {e}[/red]")
        logger.error(f"Scrape error: {e}", exc_info=True)
        return None


async def import_games(games_file: str, provider: str):
    """
    Step 2: Import games to database
    """
    console.print(Panel.fit("[bold cyan]Step 2: Importing Games[/bold cyan]", style="cyan"))
    
    if not games_file or not Path(games_file).exists():
        console.print("[yellow]No games file to import. Skipping import step.[/yellow]")
        return False
    
    try:
        console.print(f"[green]Importing games from {games_file}...[/green]")
        
        # Call import script via subprocess
        script_path = Path(__file__).parent.parent / "import_games_enhanced.py"
        cmd = [
            sys.executable,
            str(script_path),
            games_file,
            provider,
            '--stream',
            '--batch-size', '2000',
            '--concurrency', '4',
            '--checkpoint'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            console.print("[green]✅ Games imported successfully[/green]")
            return True
        else:
            console.print(f"[red]❌ Import failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Import stderr: {result.stderr}")
            return False
        
    except Exception as e:
        console.print(f"[red]❌ Error importing games: {e}[/red]")
        logger.error(f"Import error: {e}", exc_info=True)
        return False


async def recalculate_rankings(use_ml: bool = True):
    """
    Step 3: Recalculate rankings
    """
    console.print(Panel.fit("[bold cyan]Step 3: Recalculating Rankings[/bold cyan]", style="cyan"))
    
    try:
        mode = "ML-Enhanced" if use_ml else "v53e Only"
        console.print(f"[green]Calculating {mode} rankings...[/green]")
        
        # Call rankings script via subprocess
        script_path = Path(__file__).parent.parent / "calculate_rankings.py"
        cmd = [sys.executable, str(script_path), '--lookback-days', '365']
        if use_ml:
            cmd.append('--ml')
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            console.print("[green]✅ Rankings calculated successfully[/green]")
            return True
        else:
            console.print(f"[red]❌ Rankings calculation failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Rankings stderr: {result.stderr}")
            return False
        
    except Exception as e:
        console.print(f"[red]❌ Error calculating rankings: {e}[/red]")
        logger.error(f"Rankings error: {e}", exc_info=True)
        return False


async def weekly_update(
    provider: str = 'gotsport',
    games_file: str = None,
    use_ml: bool = True,
    skip_scrape: bool = False,
    skip_import: bool = False,
    skip_rankings: bool = False
):
    """
    Run complete weekly update workflow
    """
    start_time = datetime.now()
    
    console.print(Panel.fit(
        "[bold green]🔄 PitchRank Weekly Update[/bold green]",
        style="green"
    ))
    console.print(f"[dim]Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n")
    
    results = {
        'scrape': None,
        'import': None,
        'rankings': None
    }
    
    # Step 1: Scrape
    if not skip_scrape:
        scraped_file = await scrape_games(provider, games_file)
        if scraped_file:
            games_file = scraped_file  # Use scraped file for import
        results['scrape'] = scraped_file is not None
    else:
        console.print("[yellow]⏭️  Skipping scrape step[/yellow]")
    
    # Step 2: Import
    if not skip_import and games_file:
        results['import'] = await import_games(games_file, provider)
    elif skip_import:
        console.print("[yellow]⏭️  Skipping import step[/yellow]")
    else:
        console.print("[yellow]⏭️  No games file to import[/yellow]")
    
    # Step 3: Recalculate Rankings
    if not skip_rankings:
        results['rankings'] = await recalculate_rankings(use_ml)
    else:
        console.print("[yellow]⏭️  Skipping rankings calculation[/yellow]")
    
    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    console.print("\n")
    console.print(Panel.fit("[bold]📊 Update Summary[/bold]", style="cyan"))
    
    summary_table = Table(box=box.ROUNDED)
    summary_table.add_column("Step", style="cyan")
    summary_table.add_column("Status", style="green")
    
    if results['scrape'] is not None:
        status = "✅ Success" if results['scrape'] else "❌ Failed"
        summary_table.add_row("Scrape", status)
    
    if results['import'] is not None:
        status = "✅ Success" if results['import'] else "❌ Failed"
        summary_table.add_row("Import", status)
    
    if results['rankings'] is not None:
        status = "✅ Success" if results['rankings'] else "❌ Failed"
        summary_table.add_row("Rankings", status)
    
    console.print(summary_table)
    console.print(f"\n[dim]Total duration: {duration:.1f} seconds[/dim]")
    console.print(f"[dim]Log file: {log_file}[/dim]")
    
    # Return success if all completed steps succeeded
    all_succeeded = all(
        v for v in results.values() 
        if v is not None
    ) if any(v is not None for v in results.values()) else False
    
    return all_succeeded


def main():
    parser = argparse.ArgumentParser(
        description='Weekly automation for PitchRank updates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full update with games file
  python scripts/weekly/update.py --games-file data/master/all_games_master.csv
  
  # Import only (skip scrape)
  python scripts/weekly/update.py --skip-scrape --games-file data/new_games.csv
  
  # Rankings only
  python scripts/weekly/update.py --skip-scrape --skip-import
  
  # v53e only (no ML)
  python scripts/weekly/update.py --no-ml
        """
    )
    
    parser.add_argument('--provider', type=str, default='gotsport',
                       help='Provider code (default: gotsport)')
    parser.add_argument('--games-file', type=str, default=None,
                       help='Path to games CSV file (for import step)')
    parser.add_argument('--ml', action='store_true', default=True,
                       help='Use ML-enhanced rankings (default: True)')
    parser.add_argument('--no-ml', action='store_true',
                       help='Use v53e-only rankings (no ML)')
    parser.add_argument('--skip-scrape', action='store_true',
                       help='Skip scraping step')
    parser.add_argument('--skip-import', action='store_true',
                       help='Skip import step')
    parser.add_argument('--skip-rankings', action='store_true',
                       help='Skip rankings calculation')
    
    args = parser.parse_args()
    
    use_ml = args.ml and not args.no_ml
    
    try:
        success = asyncio.run(weekly_update(
            provider=args.provider,
            games_file=args.games_file,
            use_ml=use_ml,
            skip_scrape=args.skip_scrape,
            skip_import=args.skip_import,
            skip_rankings=args.skip_rankings
        ))
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Update cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error in weekly update")
        sys.exit(1)


if __name__ == '__main__':
    main()

