#!/usr/bin/env python3
"""
Enhanced game import script with all architectural improvements
"""
import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from src.utils.enhanced_validators import EnhancedDataValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

console = Console()
load_dotenv()


async def main():
    parser = argparse.ArgumentParser(description='Import games with enhanced pipeline')
    parser.add_argument('file', help='JSON file containing games data')
    parser.add_argument('provider', help='Provider ID (gotsport, tgs, usclub)')
    parser.add_argument('--dry-run', action='store_true', help='Run without committing')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for imports')
    parser.add_argument('--validate-only', action='store_true', help='Only validate, don\'t import')
    
    args = parser.parse_args()
    
    # Load games data
    console.print(f"[bold]Loading games from {args.file}[/bold]")
    file_path = Path(args.file)
    
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {args.file}[/red]")
        sys.exit(1)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix == '.json':
                games_data = json.load(f)
            else:
                # Try as newline-delimited JSON
                games_data = []
                for line in f:
                    if line.strip():
                        games_data.append(json.loads(line))
        
        # Handle different data structures
        if isinstance(games_data, dict):
            if 'games' in games_data:
                games = games_data['games']
            else:
                games = [games_data]
        else:
            games = games_data
        
        console.print(f"[green]Loaded {len(games)} games[/green]")
        
    except Exception as e:
        console.print(f"[red]Error loading file: {e}[/red]")
        sys.exit(1)
    
    # Validate only mode
    if args.validate_only:
        console.print("[bold yellow]Validation-only mode[/bold yellow]")
        validator = EnhancedDataValidator()
        result = validator.validate_import_batch(games, 'game')
        
        console.print("\n[bold]Validation Summary:[/bold]")
        console.print(f"  Total: {result['summary']['total']}")
        console.print(f"  [green]Valid: {result['summary']['valid_count']}[/green]")
        console.print(f"  [red]Invalid: {result['summary']['invalid_count']}[/red]")
        console.print(f"  Validation Rate: {result['summary']['validation_rate']:.1%}")
        
        if result['invalid']:
            console.print("\n[yellow]Invalid games (first 10):[/yellow]")
            for game in result['invalid'][:10]:
                errors = game.get('validation_errors', [])
                game_uid = game.get('game_uid', 'unknown')
                console.print(f"  [red]{game_uid}:[/red] {'; '.join(errors)}")
            
            if len(result['invalid']) > 10:
                console.print(f"  ... and {len(result['invalid']) - 10} more")
        
        return
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Run import
    pipeline = EnhancedETLPipeline(supabase, args.provider, dry_run=args.dry_run)
    pipeline.batch_size = args.batch_size
    
    try:
        mode_text = "DRY RUN" if args.dry_run else "IMPORT"
        console.print(f"\n[bold green]Starting {mode_text}[/bold green]")
        
        metrics = await pipeline.import_games(games)
        
        # Display results
        console.print("\n[bold green]Import completed successfully![/bold green]")
        console.print("\n[bold]Metrics:[/bold]")
        console.print(f"  Games processed: {metrics.games_processed}")
        
        # Deduplication metrics
        if metrics.duplicates_skipped > 0:
            dedup_rate = (metrics.duplicates_skipped / metrics.games_processed * 100) if metrics.games_processed > 0 else 0
            console.print(f"  [yellow]Duplicates skipped: {metrics.duplicates_skipped}[/yellow] ({dedup_rate:.1f}%)")
        
        console.print(f"  [green]Games accepted: {metrics.games_accepted}[/green]")
        console.print(f"  [red]Games quarantined: {metrics.games_quarantined}[/red]")
        console.print(f"  [yellow]Duplicates found (existing): {metrics.duplicates_found}[/yellow]")
        console.print(f"  Teams matched: {metrics.teams_matched}")
        console.print(f"  Teams created: {metrics.teams_created}")
        console.print(f"  [green]Auto-matched: {metrics.fuzzy_matches_auto}[/green]")
        console.print(f"  [yellow]Queued for review: {metrics.fuzzy_matches_manual}[/yellow]")
        console.print(f"  [red]Rejected: {metrics.fuzzy_matches_rejected}[/red]")
        console.print(f"  Processing time: {metrics.processing_time_seconds:.2f}s")
        
        # Summary
        if metrics.duplicates_skipped > 0:
            unique_games = metrics.games_processed - metrics.duplicates_skipped
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Unique games from source: {unique_games}")
            console.print(f"  Imported: {metrics.games_accepted}")
            console.print(f"  Already in database: {metrics.duplicates_found}")
        
        if metrics.errors:
            console.print(f"\n[yellow]Errors encountered: {len(metrics.errors)}[/yellow]")
            for error in metrics.errors[:5]:
                console.print(f"  - {error}")
            if len(metrics.errors) > 5:
                console.print(f"  ... and {len(metrics.errors) - 5} more")
        
        if args.dry_run:
            console.print("\n[yellow]Dry run completed - no changes were made[/yellow]")
        else:
            console.print("\n[green]Check build_logs table for detailed metrics[/green]")
            
    except Exception as e:
        console.print(f"\n[red]Import failed: {e}[/red]")
        logger.exception("Import error details")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

