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
import re
import json

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


def count_games_in_jsonl(file_path: str) -> int:
    """Count the number of games in a JSONL file"""
    try:
        count = 0
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        json.loads(line)  # Validate JSON
                        count += 1
                    except json.JSONDecodeError:
                        continue
        return count
    except Exception as e:
        logger.warning(f"Error counting games in {file_path}: {e}")
        return 0


def get_sample_games_from_jsonl(file_path: str, sample_size: int = 2) -> list:
    """Get a sample of games from a JSONL file for display"""
    try:
        samples = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and len(samples) < sample_size:
                    try:
                        game = json.loads(line)
                        # Extract key fields for display
                        # Note: Scraped games use goals_for/goals_against, not home_score/away_score
                        sample = {
                            'team_name': game.get('team_name', 'N/A') or game.get('club_name', 'N/A'),
                            'opponent_name': game.get('opponent_name', 'N/A') or game.get('opponent_club_name', 'N/A'),
                            'game_date': game.get('game_date', 'N/A'),
                            'goals_for': game.get('goals_for'),
                            'goals_against': game.get('goals_against'),
                            'result': game.get('result', 'N/A'),
                        }
                        samples.append(sample)
                    except json.JSONDecodeError:
                        continue
        return samples
    except Exception as e:
        logger.warning(f"Error getting sample games from {file_path}: {e}")
        return []


def parse_import_metrics(output: str) -> dict:
    """Parse import metrics from the import script output"""
    metrics = {
        'games_processed': 0,
        'games_accepted': 0,
        'games_quarantined': 0,
        'duplicates_skipped': 0,
        'duplicates_found': 0,
        'teams_matched': 0,
        'teams_created': 0
    }
    
    # Parse "Games processed: X" pattern
    match = re.search(r'Games processed:\s*([\d,]+)', output)
    if match:
        metrics['games_processed'] = int(match.group(1).replace(',', ''))
    
    # Parse "Games accepted: X" pattern
    match = re.search(r'Games accepted:\s*([\d,]+)', output)
    if match:
        metrics['games_accepted'] = int(match.group(1).replace(',', ''))
    
    # Parse "Games quarantined: X" pattern
    match = re.search(r'Games quarantined:\s*([\d,]+)', output)
    if match:
        metrics['games_quarantined'] = int(match.group(1).replace(',', ''))
    
    # Parse "Duplicates skipped: X" pattern
    match = re.search(r'Duplicates skipped:\s*([\d,]+)', output)
    if match:
        metrics['duplicates_skipped'] = int(match.group(1).replace(',', ''))
    
    # Parse "Duplicates found: X" pattern
    match = re.search(r'Duplicates found.*?:\s*([\d,]+)', output)
    if match:
        metrics['duplicates_found'] = int(match.group(1).replace(',', ''))
    
    # Parse "Teams matched: X" pattern
    match = re.search(r'Teams matched:\s*([\d,]+)', output)
    if match:
        metrics['teams_matched'] = int(match.group(1).replace(',', ''))
    
    # Parse "Teams created: X" pattern
    match = re.search(r'Teams created:\s*([\d,]+)', output)
    if match:
        metrics['teams_created'] = int(match.group(1).replace(',', ''))
    
    return metrics


async def scrape_games(provider: str, games_file: str = None, output_file: str = None):
    """
    Step 1: Scrape new games from GotSport
    
    If games_file is provided, use that instead of scraping.
    Otherwise, scrape from GotSport and save to file.
    """
    console.print(Panel.fit("[bold cyan]Step 1: Scraping New Games[/bold cyan]", style="cyan"))
    
    if games_file:
        console.print(f"[yellow]Using provided games file: {games_file}[/yellow]")
        games_count = 0
        if Path(games_file).exists():
            if games_file.endswith('.jsonl'):
                games_count = count_games_in_jsonl(games_file)
            else:
                # For CSV files, we'd need to count differently, but for now just show file exists
                games_count = 0
        return games_file, games_count
    
    # Scrape from GotSport
    try:
        console.print(f"[green]Scraping games from {provider}...[/green]")
        
        # Call scrape script via subprocess
        script_path = Path(__file__).parent.parent / "scrape_games.py"
        if not output_file:
            # Create absolute path relative to project root
            # Script is at scripts/weekly/update.py, so parent.parent.parent is project root
            project_root = Path(__file__).parent.parent.parent
            output_dir = project_root / "data" / "raw"
            output_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            output_file = str(output_dir / f"scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
        else:
            # Convert to absolute path if relative
            if not Path(output_file).is_absolute():
                project_root = Path(__file__).parent.parent.parent
                output_file = str(project_root / output_file)
            # Ensure directory exists
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            sys.executable,
            str(script_path),
            '--provider', provider,
            '--output', output_file
            # Note: We handle import separately to capture metrics
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Log output for debugging
        if result.stdout:
            logger.info(f"Scrape stdout: {result.stdout}")
        if result.stderr:
            logger.info(f"Scrape stderr: {result.stderr}")
        
        if result.returncode == 0:
            # Count games in the scraped file
            games_count = 0
            output_path = Path(output_file)
            if output_path.exists():
                games_count = count_games_in_jsonl(output_file)
                console.print(f"[green]✅ Games scraped successfully[/green]")
                console.print(f"[bold]  File location: {output_path.absolute()}[/bold]")
                console.print(f"[dim]  Games scraped: {games_count:,}[/dim]")
            else:
                # Try to parse from output as fallback
                output_text = result.stdout + result.stderr
                match = re.search(r'Games scraped:\s*([\d,]+)', output_text)
                if match:
                    games_count = int(match.group(1).replace(',', ''))
                    console.print(f"[green]✅ Games scraped successfully[/green]")
                    console.print(f"[bold]  File location: {output_path.absolute()}[/bold]")
                    console.print(f"[dim]  Games scraped: {games_count:,}[/dim]")
                else:
                    console.print(f"[green]✅ Games scraped successfully[/green]")
                    console.print(f"[bold]  File location: {output_path.absolute()}[/bold]")
                    console.print(f"[yellow]  Warning: Output file not found, cannot count games[/yellow]")
            
            return str(output_path.absolute()), games_count
        else:
            console.print(f"[red]❌ Scraping failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Scrape stderr: {result.stderr}")
            return None, 0
        
    except Exception as e:
        console.print(f"[red]❌ Error scraping games: {e}[/red]")
        logger.error(f"Scrape error: {e}", exc_info=True)
        return None, 0


async def import_games(games_file: str, provider: str):
    """
    Step 2: Import games to database
    Returns (success: bool, metrics: dict)
    """
    console.print(Panel.fit("[bold cyan]Step 2: Importing Games[/bold cyan]", style="cyan"))
    
    if not games_file or not Path(games_file).exists():
        console.print("[yellow]No games file to import. Skipping import step.[/yellow]")
        return False, {}
    
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
        
        # Log output for debugging
        if result.stdout:
            logger.info(f"Import stdout: {result.stdout}")
        if result.stderr:
            logger.info(f"Import stderr: {result.stderr}")
        
        if result.returncode == 0:
            # Parse metrics from output
            metrics = parse_import_metrics(result.stdout + result.stderr)
            console.print("[green]✅ Games imported successfully[/green]")
            if metrics['games_processed'] > 0:
                console.print(f"[dim]  Games processed: {metrics['games_processed']:,}[/dim]")
                console.print(f"[dim]  Games accepted: {metrics['games_accepted']:,}[/dim]")
                if metrics['games_quarantined'] > 0:
                    console.print(f"[dim]  Games quarantined: {metrics['games_quarantined']:,}[/dim]")
                if metrics['duplicates_skipped'] > 0:
                    console.print(f"[dim]  Duplicates skipped: {metrics['duplicates_skipped']:,}[/dim]")
            return True, metrics
        else:
            console.print(f"[red]❌ Import failed with return code {result.returncode}[/red]")
            if result.stderr:
                logger.error(f"Import stderr: {result.stderr}")
            return False, {}
        
    except Exception as e:
        console.print(f"[red]❌ Error importing games: {e}[/red]")
        logger.error(f"Import error: {e}", exc_info=True)
        return False, {}


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
    
    # Store metrics for summary
    scrape_metrics = {
        'games_count': 0,
        'file_path': None
    }
    import_metrics = {}
    
    # Step 1: Scrape
    if not skip_scrape:
        scraped_result = await scrape_games(provider, games_file)
        if scraped_result and scraped_result[0]:
            games_file = scraped_result[0]  # Use scraped file for import
            scrape_metrics['games_count'] = scraped_result[1]
            scrape_metrics['file_path'] = scraped_result[0]
        results['scrape'] = scraped_result is not None and scraped_result[0] is not None
    else:
        console.print("[yellow]⏭️  Skipping scrape step[/yellow]")
    
    # Step 2: Import
    if not skip_import and games_file:
        import_result = await import_games(games_file, provider)
        results['import'] = import_result[0]
        import_metrics = import_result[1]
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
    summary_table.add_column("Details", style="dim")
    
    if results['scrape'] is not None:
        status = "✅ Success" if results['scrape'] else "❌ Failed"
        details = ""
        if results['scrape'] and scrape_metrics['games_count'] > 0:
            details = f"{scrape_metrics['games_count']:,} games scraped"
            if scrape_metrics['file_path']:
                file_name = Path(scrape_metrics['file_path']).name
                details += f" → {file_name}"
        summary_table.add_row("Scrape", status, details)
    
    if results['import'] is not None:
        status = "✅ Success" if results['import'] else "❌ Failed"
        details = ""
        if results['import'] and import_metrics:
            if import_metrics.get('games_accepted', 0) > 0:
                details = f"{import_metrics['games_accepted']:,} games imported"
                if import_metrics.get('games_processed', 0) > import_metrics.get('games_accepted', 0):
                    details += f" ({import_metrics['games_processed']:,} processed)"
            elif import_metrics.get('games_processed', 0) > 0:
                details = f"{import_metrics['games_processed']:,} games processed"
        summary_table.add_row("Import", status, details)
    
    if results['rankings'] is not None:
        status = "✅ Success" if results['rankings'] else "❌ Failed"
        summary_table.add_row("Rankings", status, "")
    
    console.print(summary_table)
    
    # Additional details section
    if scrape_metrics['file_path']:
        file_path = Path(scrape_metrics['file_path'])
        if file_path.exists():
            file_size = file_path.stat().st_size / (1024 * 1024)  # MB
            console.print(f"\n[bold]📁 Scraped Games File:[/bold]")
            console.print(f"  [cyan]Path: {file_path.absolute()}[/cyan]")
            console.print(f"  [dim]Size: {file_size:.1f} MB[/dim]")
            console.print(f"  [dim]Games: {scrape_metrics['games_count']:,}[/dim]")
        else:
            console.print(f"\n[bold]📁 Scraped Games File:[/bold]")
            console.print(f"  [cyan]Path: {file_path.absolute()}[/cyan]")
            console.print(f"  [yellow]⚠️  File not found at expected location[/yellow]")
        
        # Show sample of scraped games
        if scrape_metrics['games_count'] > 0:
            samples = get_sample_games_from_jsonl(scrape_metrics['file_path'], sample_size=2)
            if samples:
                console.print(f"\n[dim]Sample of scraped games (first {len(samples)} of {scrape_metrics['games_count']:,}):[/dim]")
                for i, game in enumerate(samples, 1):
                    score_str = ""
                    if game.get('goals_for') is not None and game.get('goals_against') is not None:
                        score_str = f" ({game['goals_for']}-{game['goals_against']})"
                    result_str = f" [{game.get('result', '')}]" if game.get('result') else ""
                    console.print(f"  [dim]{i}. {game['team_name']} vs {game['opponent_name']} on {game['game_date']}{score_str}{result_str}[/dim]")
    
    if import_metrics and import_metrics.get('games_accepted', 0) > 0:
        console.print(f"\n[dim]Import details:[/dim]")
        console.print(f"  [dim]Games accepted: {import_metrics.get('games_accepted', 0):,}[/dim]")
        if import_metrics.get('duplicates_skipped', 0) > 0:
            console.print(f"  [dim]Duplicates skipped: {import_metrics.get('duplicates_skipped', 0):,}[/dim]")
        if import_metrics.get('games_quarantined', 0) > 0:
            console.print(f"  [dim]Games quarantined: {import_metrics.get('games_quarantined', 0):,}[/dim]")
        if import_metrics.get('teams_created', 0) > 0:
            console.print(f"  [dim]New teams created: {import_metrics.get('teams_created', 0):,}[/dim]")
    
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

