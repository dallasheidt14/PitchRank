#!/usr/bin/env python3
"""
Reprocess quarantined games that failed due to date format issues

This script:
1. Reads quarantined games from quarantine_games table
2. Filters for date-related validation errors
3. Fixes date formats using parse_game_date()
4. Re-processes through EnhancedETLPipeline
5. Deletes successfully recovered games from quarantine

Usage:
    # Dry-run test with 500 games
    python scripts/reprocess_quarantined_games.py --provider gotsport --dry-run --limit 500
    
    # Process all quarantined games
    python scripts/reprocess_quarantined_games.py --provider gotsport --batch-size 1000
    
    # Process specific reason code
    python scripts/reprocess_quarantined_games.py --provider gotsport --reason-code validation_failed

Environment Variables Required:
    SUPABASE_URL - Your Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY - Service role key for database access
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from collections import Counter

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from src.utils.enhanced_validators import parse_game_date

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

console = Console()
# Load environment variables - check for local Supabase first
use_local = os.getenv('USE_LOCAL_SUPABASE', 'false').lower() == 'true'
if use_local:
    # Load .env.local if using local Supabase
    env_local = Path('.env.local')
    if env_local.exists():
        load_dotenv(env_local, override=True)
        logger.info("Loaded .env.local for local Supabase")
    else:
        logger.warning(".env.local not found, falling back to .env")
        load_dotenv()
else:
    load_dotenv()
    # Also try .env.local if .env doesn't have the required vars
    if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        env_local = Path('.env.local')
        if env_local.exists():
            load_dotenv(env_local, override=True)
            logger.info("Loaded .env.local as fallback")


def is_date_related_error(error_details: str) -> bool:
    """Check if error is related to date format"""
    if not error_details:
        return False
    
    error_lower = error_details.lower()
    date_keywords = [
        'date format',
        'invalid date',
        'unrecognized date',
        'date',
        'strptime'
    ]
    
    return any(keyword in error_lower for keyword in date_keywords)


def fix_game_date(game_data: Dict) -> Optional[Dict]:
    """Fix date format in game data"""
    try:
        if 'game_date' in game_data and game_data['game_date']:
            # Parse and normalize date
            date_obj = parse_game_date(str(game_data['game_date']))
            # Convert back to string in ISO format for consistency
            game_data['game_date'] = date_obj.strftime('%Y-%m-%d')
        return game_data
    except ValueError as e:
        logger.warning(f"Failed to fix date '{game_data.get('game_date')}': {e}")
        return None


async def reprocess_quarantined_games(
    supabase,
    provider_code: str,
    reason_code: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    batch_size: int = 1000
) -> Dict:
    """
    Reprocess quarantined games with fixed date formats
    
    Args:
        supabase: Supabase client
        provider_code: Provider code for games
        reason_code: Filter by specific reason code (default: 'validation_failed')
        limit: Maximum number of games to process (None for all)
        dry_run: If True, don't actually insert or delete
        batch_size: Batch size for processing
        
    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'total_quarantined': 0,
        'date_related': 0,
        'processed': 0,
        'recovered': 0,
        'failed': 0,
        'duplicates': 0,
        'still_invalid': 0,
        'deleted_from_quarantine': 0
    }
    
    # Query quarantined games
    query = supabase.table('quarantine_games').select('*')
    
    if reason_code:
        query = query.eq('reason_code', reason_code)
    else:
        # Default to validation_failed
        query = query.eq('reason_code', 'validation_failed')
    
    # Get total count
    count_query = supabase.table('quarantine_games').select('id', count='exact')
    if reason_code:
        count_query = count_query.eq('reason_code', reason_code)
    else:
        count_query = count_query.eq('reason_code', 'validation_failed')
    
    count_result = count_query.limit(1).execute()
    stats['total_quarantined'] = count_result.count if hasattr(count_result, 'count') else 0
    
    if stats['total_quarantined'] == 0:
        console.print("[yellow]No quarantined games found matching criteria[/yellow]")
        return stats
    
    console.print(f"[cyan]Found {stats['total_quarantined']:,} quarantined games[/cyan]")
    
    # Fetch games in batches
    offset = 0
    processed_count = 0
    recovered_games = []
    failed_ids = []
    
    # Initialize pipeline
    pipeline = EnhancedETLPipeline(
        supabase=supabase,
        provider_code=provider_code,
        dry_run=dry_run,
        skip_validation=False  # Re-validate with fixed dates
    )
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Processing quarantined games...", total=limit or stats['total_quarantined'])
        
        while True:
            # Fetch batch with retry logic for timeouts
            max_retries = 3
            result = None
            
            for attempt in range(max_retries):
                try:
                    batch_query = supabase.table('quarantine_games').select('*')
                    if reason_code:
                        batch_query = batch_query.eq('reason_code', reason_code)
                    else:
                        batch_query = batch_query.eq('reason_code', 'validation_failed')
                    
                    batch_query = batch_query.order('created_at', desc=False)
                    batch_query = batch_query.range(offset, offset + batch_size - 1)
                    
                    result = batch_query.execute()
                    break  # Success, exit retry loop
                except Exception as e:
                    if 'timeout' in str(e).lower() or '57014' in str(e) or attempt == max_retries - 1:
                        if attempt < max_retries - 1:
                            logger.warning(f"Query timeout at offset {offset}, retrying (attempt {attempt + 1}/{max_retries})...")
                            import time
                            time.sleep(2)  # Wait before retry
                            continue
                        else:
                            logger.error(f"Query failed after {max_retries} attempts at offset {offset}: {e}")
                            # Skip this batch and continue
                            offset += batch_size
                            if limit and processed_count >= limit:
                                return stats
                            continue
                    else:
                        raise  # Re-raise if not a timeout error
            
            if not result or not result.data or len(result.data) == 0:
                break
            
            # Filter for date-related errors
            date_related_games = []
            for game in result.data:
                error_details = game.get('error_details', '')
                if is_date_related_error(error_details):
                    stats['date_related'] += 1
                    date_related_games.append(game)
            
            if not date_related_games:
                offset += batch_size
                if limit and processed_count >= limit:
                    break
                continue
            
            # Fix dates and prepare for reprocessing
            fixed_games = []
            game_id_map = {}  # Map fixed game to quarantine ID
            
            for quarantined_game in date_related_games:
                raw_data = quarantined_game.get('raw_data', {})
                if not raw_data:
                    continue
                
                # Fix date format
                fixed_game = fix_game_date(raw_data.copy())
                if fixed_game:
                    fixed_games.append(fixed_game)
                    game_id_map[len(fixed_games) - 1] = quarantined_game['id']
                else:
                    stats['still_invalid'] += 1
                    failed_ids.append(quarantined_game['id'])
            
            # Reprocess fixed games
            if fixed_games:
                try:
                    metrics = await pipeline.import_games(fixed_games, provider_code=provider_code)
                    
                    stats['processed'] += len(fixed_games)
                    stats['recovered'] += metrics.games_accepted
                    stats['duplicates'] += metrics.duplicates_found
                    stats['failed'] += metrics.games_quarantined
                    
                    # Track which games were successfully recovered
                    # Games that were accepted or were duplicates (already in DB) are considered recovered
                    recovered_count = metrics.games_accepted + metrics.duplicates_found
                    
                    if not dry_run:
                        # Delete successfully recovered games from quarantine
                        # Strategy: Delete games that were processed and not re-quarantined
                        # Since duplicates are already in DB, they're also considered recovered
                        success_rate = recovered_count / len(fixed_games) if len(fixed_games) > 0 else 0
                        
                        if success_rate > 0:
                            # Delete games from quarantine that were successfully processed
                            # We delete all games in the batch if success rate is high enough
                            # This is safe because:
                            # - Accepted games are now in DB
                            # - Duplicate games are already in DB
                            # - Failed games will be re-quarantined by the pipeline
                            
                            if success_rate >= 0.5:  # 50% success rate threshold
                                # Delete all games in this batch from quarantine
                                quarantine_ids = [game_id_map[i] for i in range(len(fixed_games))]
                                try:
                                    # Batch delete for efficiency
                                    for q_id in quarantine_ids:
                                        try:
                                            supabase.table('quarantine_games').delete().eq('id', q_id).execute()
                                            stats['deleted_from_quarantine'] += 1
                                        except Exception as e:
                                            logger.warning(f"Failed to delete quarantine ID {q_id}: {e}")
                                except Exception as e:
                                    logger.warning(f"Failed to delete batch from quarantine: {e}")
                    
                    recovered_games.extend(fixed_games[:recovered_count])
                    
                except Exception as e:
                    logger.error(f"Error reprocessing batch: {e}")
                    stats['failed'] += len(fixed_games)
            
            offset += batch_size
            processed_count += len(date_related_games)
            progress.update(task, advance=len(date_related_games))
            
            if limit and processed_count >= limit:
                break
    
    return stats


def display_summary(stats: Dict):
    """Display processing summary"""
    table = Table(title="Reprocessing Summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta", justify="right")
    table.add_column("Percentage", style="yellow", justify="right")
    
    total = stats['total_quarantined']
    if total > 0:
        table.add_row("Total Quarantined", f"{total:,}", "100.0%")
        table.add_row("Date-Related Errors", f"{stats['date_related']:,}", f"{stats['date_related']/total*100:.1f}%")
        table.add_row("Processed", f"{stats['processed']:,}", f"{stats['processed']/total*100:.1f}%")
        table.add_row("Recovered", f"{stats['recovered']:,}", f"{stats['recovered']/stats['processed']*100:.1f}%" if stats['processed'] > 0 else "0.0%")
        table.add_row("Duplicates (already in DB)", f"{stats['duplicates']:,}", f"{stats['duplicates']/stats['processed']*100:.1f}%" if stats['processed'] > 0 else "0.0%")
        table.add_row("Failed", f"{stats['failed']:,}", f"{stats['failed']/stats['processed']*100:.1f}%" if stats['processed'] > 0 else "0.0%")
        table.add_row("Still Invalid", f"{stats['still_invalid']:,}", f"{stats['still_invalid']/total*100:.1f}%")
        table.add_row("Deleted from Quarantine", f"{stats['deleted_from_quarantine']:,}", f"{stats['deleted_from_quarantine']/stats['processed']*100:.1f}%" if stats['processed'] > 0 else "0.0%")
    else:
        table.add_row("Total Quarantined", "0", "N/A")
    
    console.print(table)


async def main():
    parser = argparse.ArgumentParser(
        description='Reprocess quarantined games with fixed date formats'
    )
    parser.add_argument(
        '--provider',
        type=str,
        required=True,
        help='Provider code (e.g., "gotsport")'
    )
    parser.add_argument(
        '--reason-code',
        type=str,
        default='validation_failed',
        help='Filter by reason code (default: validation_failed)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of games to process (default: all)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing (default: 1000)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - do not insert or delete'
    )
    
    args = parser.parse_args()
    
    # Ensure environment variables are loaded (reload in case they weren't set initially)
    if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        env_local = Path('.env.local')
        if env_local.exists():
            load_dotenv(env_local, override=True)
        else:
            load_dotenv()
    
    # Connect to Supabase
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        console.print("[yellow]Please check your .env or .env.local file[/yellow]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    console.print(Panel.fit(
        f"[bold cyan]Reprocess Quarantined Games[/bold cyan]\n\n"
        f"Provider: {args.provider}\n"
        f"Reason Code: {args.reason_code}\n"
        f"Limit: {args.limit or 'All'}\n"
        f"Batch Size: {args.batch_size}\n"
        f"Dry Run: {'Yes' if args.dry_run else 'No'}",
        title="Configuration"
    ))
    
    if args.dry_run:
        console.print("[yellow]⚠️  DRY RUN MODE - No changes will be made[/yellow]\n")
    
    # Reprocess games
    stats = await reprocess_quarantined_games(
        supabase=supabase,
        provider_code=args.provider,
        reason_code=args.reason_code,
        limit=args.limit,
        dry_run=args.dry_run,
        batch_size=args.batch_size
    )
    
    # Display summary
    console.print("\n")
    display_summary(stats)
    
    if not args.dry_run:
        console.print(f"\n[green]✅ Reprocessing complete![/green]")
        console.print(f"[green]Recovered {stats['recovered']:,} games from quarantine[/green]")
    else:
        console.print(f"\n[yellow]Dry run complete - no changes made[/yellow]")


if __name__ == '__main__':
    asyncio.run(main())

