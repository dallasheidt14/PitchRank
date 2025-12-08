#!/usr/bin/env python3
"""
Enhanced game import script with all architectural improvements
"""
import asyncio
import argparse
import csv
import json
import logging
import random
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Generator, Optional

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

from src.etl.enhanced_pipeline import EnhancedETLPipeline, ImportMetrics
from src.utils.enhanced_validators import EnhancedDataValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

console = Console()
# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
    logger.info("Loaded .env.local")
else:
    load_dotenv()
    logger.info("Loaded .env")

# Also check USE_LOCAL_SUPABASE flag for local development
use_local = os.getenv('USE_LOCAL_SUPABASE', 'false').lower() == 'true'
if use_local:
    env_local = Path('.env.local')
    if env_local.exists():
        load_dotenv(env_local, override=True)
        logger.info("Loaded .env.local for local Supabase")


def stream_games_jsonl(file_path: Path, batch_size: int = 1000) -> Generator[List[Dict], None, None]:
    """Stream games from JSONL file in batches"""
    batch = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    batch.append(json.loads(line))
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON on line {line_num}: {e}")
                    continue
        if batch:
            yield batch


def stream_games_csv(file_path: Path, batch_size: int = 1000, limit: Optional[int] = None) -> Generator[List[Dict], None, None]:
    """Stream games from CSV file in batches"""
    batch = []
    processed = 0
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 1):
            if limit and processed >= limit:
                break
            try:
                # Map CSV columns to game data format
                game = {
                    'provider': row.get('provider', '').strip(),
                    'team_id': row.get('team_id') or row.get('team_id_source', ''),
                    'team_id_source': row.get('team_id_source', ''),
                    'team_name': row.get('team_name', '').strip(),
                    'club_name': row.get('club_name') or row.get('team_club_name', '').strip(),
                    'opponent_id': row.get('opponent_id') or row.get('opponent_id_source', ''),
                    'opponent_id_source': row.get('opponent_id_source', ''),
                    'opponent_name': row.get('opponent_name', '').strip(),
                    'opponent_club_name': row.get('opponent_club_name', '').strip(),
                    'age_group': row.get('age_group', '').strip(),
                    'gender': row.get('gender', '').strip(),
                    'state': row.get('state', '').strip(),
                    'competition': row.get('competition', '').strip(),
                    'division_name': row.get('division_name', '').strip(),
                    'event_name': row.get('event_name', '').strip(),
                    'venue': row.get('venue', '').strip(),
                    'game_date': row.get('game_date', '').strip(),
                    'home_away': row.get('home_away', '').strip(),
                    'goals_for': row.get('goals_for', ''),
                    'goals_against': row.get('goals_against', ''),
                    'result': row.get('result', '').strip(),
                    'source_url': row.get('source_url', '').strip(),
                    'scraped_at': row.get('scraped_at', '').strip(),
                    'mls_division': row.get('mls_division', '').strip()  # Modular11 division (HD/AD)
                }
                
                # Convert numeric fields
                try:
                    # Convert team IDs to strings (remove .0 if present from float conversion)
                    if game['team_id']:
                        game['team_id'] = str(int(float(game['team_id']))) if game['team_id'] else ''
                    if game['opponent_id']:
                        game['opponent_id'] = str(int(float(game['opponent_id']))) if game['opponent_id'] else ''
                    
                    # Convert scores to integers
                    if game['goals_for']:
                        game['goals_for'] = int(float(game['goals_for'])) if game['goals_for'] else None
                    if game['goals_against']:
                        game['goals_against'] = int(float(game['goals_against'])) if game['goals_against'] else None
                except (ValueError, TypeError):
                    pass  # Keep as string if conversion fails
                
                batch.append(game)
                processed += 1
                
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
                    if limit and processed >= limit:
                        break
            except Exception as e:
                logger.warning(f"Error processing CSV row {row_num}: {e}")
                continue
        if batch:
            yield batch


def load_games_csv(file_path: Path, limit: Optional[int] = None) -> List[Dict]:
    """Load all games from CSV file into memory"""
    games = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 1):
            if limit and len(games) >= limit:
                break
            try:
                # Map CSV columns to game data format
                game = {
                    'provider': row.get('provider', '').strip(),
                    'team_id': row.get('team_id') or row.get('team_id_source', ''),
                    'team_id_source': row.get('team_id_source', ''),
                    'team_name': row.get('team_name', '').strip(),
                    'club_name': row.get('club_name') or row.get('team_club_name', '').strip(),
                    'opponent_id': row.get('opponent_id') or row.get('opponent_id_source', ''),
                    'opponent_id_source': row.get('opponent_id_source', ''),
                    'opponent_name': row.get('opponent_name', '').strip(),
                    'opponent_club_name': row.get('opponent_club_name', '').strip(),
                    'age_group': row.get('age_group', '').strip(),
                    'gender': row.get('gender', '').strip(),
                    'state': row.get('state', '').strip(),
                    'competition': row.get('competition', '').strip(),
                    'division_name': row.get('division_name', '').strip(),
                    'event_name': row.get('event_name', '').strip(),
                    'venue': row.get('venue', '').strip(),
                    'game_date': row.get('game_date', '').strip(),
                    'home_away': row.get('home_away', '').strip(),
                    'goals_for': row.get('goals_for', ''),
                    'goals_against': row.get('goals_against', ''),
                    'result': row.get('result', '').strip(),
                    'source_url': row.get('source_url', '').strip(),
                    'scraped_at': row.get('scraped_at', '').strip(),
                    'mls_division': row.get('mls_division', '').strip()  # Modular11 division (HD/AD)
                }
                
                # Convert numeric fields
                try:
                    # Convert team IDs to strings (remove .0 if present from float conversion)
                    if game['team_id']:
                        game['team_id'] = str(int(float(game['team_id']))) if game['team_id'] else ''
                    if game['opponent_id']:
                        game['opponent_id'] = str(int(float(game['opponent_id']))) if game['opponent_id'] else ''
                    
                    # Convert scores to integers
                    if game['goals_for']:
                        game['goals_for'] = int(float(game['goals_for'])) if game['goals_for'] else None
                    if game['goals_against']:
                        game['goals_against'] = int(float(game['goals_against'])) if game['goals_against'] else None
                except (ValueError, TypeError):
                    pass  # Keep as string if conversion fails
                
                games.append(game)
            except Exception as e:
                logger.warning(f"Error processing CSV row {row_num}: {e}")
                continue
    return games


def log_checkpoint(batch_num: int, games_processed: int, elapsed_time: float, provider: str):
    """Log checkpoint to file"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "import_progress.log", "a") as f:
        f.write(f"{datetime.now()} - Provider: {provider} - Batch {batch_num} - "
                f"Games: {games_processed:,} - Elapsed: {elapsed_time:.1f}s\n")


async def import_batch_with_retry(
    pipeline: EnhancedETLPipeline,
    batch: List[Dict],
    semaphore: asyncio.Semaphore,
    max_retries: int = 2
) -> Optional[ImportMetrics]:
    """Import batch with retry logic and concurrency control"""
    async with semaphore:
        for attempt in range(max_retries + 1):
            try:
                return await pipeline.import_games(batch)
            except Exception as e:
                if attempt < max_retries:
                    wait_time = (1.5 ** attempt)  # 1.0s, 2.5s
                    jitter = random.uniform(0, 0.5)  # Add jitter to avoid retry collisions
                    await asyncio.sleep(wait_time + jitter)
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time + jitter:.1f}s")
                else:
                    logger.error(f"Batch failed after {max_retries} retries: {e}")
                    raise


async def main():
    parser = argparse.ArgumentParser(description='Import games with enhanced pipeline')
    parser.add_argument('file', help='JSON/JSONL/CSV file containing games data')
    parser.add_argument('provider', help='Provider ID (gotsport, tgs, usclub)')
    parser.add_argument('--dry-run', action='store_true', help='Run without committing')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for streaming and inserts (default: 1000, recommended: 500 for Supabase)')
    parser.add_argument('--validate-only', action='store_true', help='Only validate, don\'t import')
    parser.add_argument('--stream', action='store_true', help='Force streaming mode (auto-enabled for large files)')
    parser.add_argument('--concurrency', type=int, default=4, help='Number of concurrent batches (default: 4)')
    parser.add_argument('--checkpoint', action='store_true', help='Enable progress checkpointing')
    parser.add_argument('--skip-validation', action='store_true', help='Skip validation during import')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of games to process (for testing)')
    parser.add_argument('--summary-only', action='store_true', help='Suppress per-team logs and show only summary (Modular11)')
    
    args = parser.parse_args()
    
    # Check file and determine loading mode
    file_path = Path(args.file)
    if not file_path.exists():
        console.print(f"[red]Error: File not found: {args.file}[/red]")
        sys.exit(1)
    
    # Check file size once at startup
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    
    # Determine if streaming should be used
    use_streaming = args.stream or file_size_mb > 50 or file_path.suffix in ['.jsonl', '.ndjson']
    
    if use_streaming and not args.stream:
        logger.info(f"Auto-enabled streaming for {file_path.name} ({file_size_mb:.1f} MB)")
        console.print(f"[cyan]Auto-enabled streaming for {file_path.name} ({file_size_mb:.1f} MB)[/cyan]")
    
    # Load games data (streaming or in-memory)
    try:
        if file_path.suffix == '.csv':
            # CSV file handling
            console.print(f"[bold]Loading games from CSV: {args.file}[/bold]")
            if use_streaming and file_size_mb > 50:
                # Streaming mode for large CSV files
                console.print(f"[cyan]Streaming CSV file ({file_size_mb:.1f} MB)...[/cyan]")
                if args.limit:
                    console.print(f"[yellow]Limiting to first {args.limit:,} games for testing[/yellow]")
                games_batches = list(stream_games_csv(file_path, args.batch_size, args.limit))
                total_games = sum(len(batch) for batch in games_batches)
                console.print(f"[green]Streaming ready: {len(games_batches)} batches, {total_games:,} games[/green]")
                games = None  # Will process batches directly
            else:
                # In-memory mode for small CSV files
                if args.limit:
                    console.print(f"[yellow]Limiting to first {args.limit:,} games for testing[/yellow]")
                games = load_games_csv(file_path, args.limit)
                console.print(f"[green]Loaded {len(games):,} games from CSV[/green]")
                games_batches = None
        elif use_streaming and file_path.suffix in ['.jsonl', '.ndjson']:
            # Streaming mode for JSONL files - count lines first for progress tracking
            console.print(f"[bold]Streaming games from {args.file}[/bold]")
            if args.limit:
                console.print(f"[yellow]Limiting to first {args.limit:,} games for testing[/yellow]")

            # Count total lines for progress estimation (fast pass)
            total_lines = 0
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        total_lines += 1
                        if args.limit and total_lines >= args.limit:
                            break

            # Create generator (don't load into memory)
            def limited_stream():
                """Stream with optional limit"""
                total = 0
                for batch in stream_games_jsonl(file_path, args.batch_size):
                    if args.limit:
                        remaining = args.limit - total
                        if remaining <= 0:
                            break
                        if len(batch) > remaining:
                            batch = batch[:remaining]
                    yield batch
                    total += len(batch)

            games_batches = limited_stream()  # Generator, not list
            total_games = min(total_lines, args.limit) if args.limit else total_lines
            num_batches = (total_games + args.batch_size - 1) // args.batch_size
            console.print(f"[green]Streaming ready: ~{num_batches} batches, {total_games:,} games[/green]")
            games = None  # Will process batches directly
        else:
            # In-memory mode for small files or JSON arrays
            console.print(f"[bold]Loading games from {args.file}[/bold]")
            if file_size_mb > 500:
                console.print("[yellow]Very large JSON file detected - loading may take time[/yellow]")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix == '.json':
                    games_data = json.load(f)
                    # Handle different data structures
                    if isinstance(games_data, dict):
                        games = games_data.get('games', [games_data])
                    else:
                        games = games_data
                else:
                    # Unknown format - try as newline-delimited JSON
                    console.print("[yellow]Unknown file extension - attempting JSONL format[/yellow]")
                    games = []
                    for line_num, line in enumerate(f, 1):
                        if line.strip():
                            try:
                                games.append(json.loads(line))
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON on line {line_num}: {e}")
                                continue
            
            console.print(f"[green]Loaded {len(games):,} games[/green]")
            games_batches = None
        
    except Exception as e:
        console.print(f"[red]Error loading file: {e}[/red]")
        logger.exception("File loading error")
        sys.exit(1)
    
    # Validate only mode
    if args.validate_only:
        console.print(f"[bold yellow]Validation-only mode for provider: {args.provider}[/bold yellow]")
        validator = EnhancedDataValidator()
        
        if games is not None:
            # Validate all games at once
            result = validator.validate_import_batch(games, 'game')
        else:
            # Validate in batches for streaming
            all_valid = []
            all_invalid = []
            for batch in games_batches:
                batch_result = validator.validate_import_batch(batch, 'game')
                all_valid.extend(batch_result['valid'])
                all_invalid.extend(batch_result['invalid'])
            result = {
                'summary': {
                    'total': len(all_valid) + len(all_invalid),
                    'valid_count': len(all_valid),
                    'invalid_count': len(all_invalid),
                    'validation_rate': len(all_valid) / (len(all_valid) + len(all_invalid)) if (all_valid or all_invalid) else 0.0
                },
                'invalid': all_invalid
            }
        
        console.print("\n[bold]Validation Summary:[/bold]")
        console.print(f"  Provider: {args.provider}")
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
    
    # Initialize pipeline
    pipeline = EnhancedETLPipeline(supabase, args.provider, dry_run=args.dry_run, skip_validation=args.skip_validation, summary_only=args.summary_only)
    pipeline.batch_size = args.batch_size
    
    # Run import
    mode_text = "DRY RUN" if args.dry_run else "IMPORT"
    console.print(f"\n[bold green]Starting {mode_text} for provider: {args.provider}[/bold green]")
    
    start_time = datetime.now()
    failed_batches = []
    failed_rows = 0
    aggregated_metrics = ImportMetrics()
    
    try:
        if use_streaming and games_batches is not None:
            # Streaming mode with concurrency - process generator without loading all into memory
            logger.info(f"Starting streaming {mode_text.lower()} for provider: {args.provider}, "
                       f"file: {args.file}, concurrency: {args.concurrency}")

            semaphore = asyncio.Semaphore(args.concurrency)

            # Process batches as they come from generator
            async def process_batch(batch_num: int, batch: List[Dict]) -> Optional[ImportMetrics]:
                """Process a single batch with error handling"""
                try:
                    return await import_batch_with_retry(pipeline, batch, semaphore)
                except Exception as e:
                    # Track failed batches
                    failed_batches.append({
                        'batch_num': batch_num,
                        'size': len(batch),
                        'error': str(e)
                    })
                    nonlocal failed_rows
                    failed_rows += len(batch)
                    logger.error(f"Batch {batch_num} failed: {e}")
                    return None

            # Execute batches concurrently with sliding window
            batch_start = datetime.now()
            completed_batches = 0
            pending_tasks = []
            batch_num = 0

            # Consume generator and create tasks
            for batch in games_batches:
                batch_num += 1
                task = asyncio.create_task(process_batch(batch_num, batch))
                pending_tasks.append(task)

                # When we have enough tasks, wait for some to complete
                if len(pending_tasks) >= args.concurrency * 2:
                    # Wait for at least half to complete
                    done, pending_tasks_set = await asyncio.wait(
                        pending_tasks,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    pending_tasks = list(pending_tasks_set)

                    # Process completed results
                    for task in done:
                        result = task.result()
                        if result:
                            aggregated_metrics.games_processed += result.games_processed
                            aggregated_metrics.games_accepted += result.games_accepted
                            aggregated_metrics.games_quarantined += result.games_quarantined
                            aggregated_metrics.duplicates_found += result.duplicates_found
                            aggregated_metrics.duplicates_skipped += result.duplicates_skipped
                            aggregated_metrics.teams_matched += result.teams_matched
                            aggregated_metrics.teams_created += result.teams_created
                            aggregated_metrics.fuzzy_matches_auto += result.fuzzy_matches_auto
                            aggregated_metrics.fuzzy_matches_manual += result.fuzzy_matches_manual
                            aggregated_metrics.fuzzy_matches_rejected += result.fuzzy_matches_rejected
                            aggregated_metrics.errors.extend(result.errors)
                            completed_batches += 1

                            # Checkpoint logging
                            if args.checkpoint and completed_batches % 10 == 0:
                                elapsed = (datetime.now() - batch_start).total_seconds()
                                log_checkpoint(completed_batches, aggregated_metrics.games_processed, elapsed, args.provider)
                                logger.info(f"Checkpoint: {completed_batches} batches completed, "
                                           f"Games: {aggregated_metrics.games_processed:,}, Elapsed: {elapsed:.1f}s")

            # Wait for remaining tasks
            if pending_tasks:
                results = await asyncio.gather(*pending_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        continue
                    if result:
                        aggregated_metrics.games_processed += result.games_processed
                        aggregated_metrics.games_accepted += result.games_accepted
                        aggregated_metrics.games_quarantined += result.games_quarantined
                        aggregated_metrics.duplicates_found += result.duplicates_found
                        aggregated_metrics.duplicates_skipped += result.duplicates_skipped
                        aggregated_metrics.teams_matched += result.teams_matched
                        aggregated_metrics.teams_created += result.teams_created
                        aggregated_metrics.fuzzy_matches_auto += result.fuzzy_matches_auto
                        aggregated_metrics.fuzzy_matches_manual += result.fuzzy_matches_manual
                        aggregated_metrics.fuzzy_matches_rejected += result.fuzzy_matches_rejected
                        aggregated_metrics.errors.extend(result.errors)
                        completed_batches += 1

            aggregated_metrics.processing_time_seconds = (datetime.now() - start_time).total_seconds()
            total_batches = batch_num  # Store for exit code check
            
        else:
            # In-memory mode (single batch or small file)
            logger.info(f"Starting {mode_text.lower()} for provider: {args.provider}, "
                       f"file: {args.file}, games: {len(games) if games else 0}")
            
            metrics = await pipeline.import_games(games)
            aggregated_metrics = metrics
        
        # Display results (after all batches complete)
        console.print("\n[bold green]Import completed![/bold green]")
        console.print(f"\n[bold]Provider: {args.provider}[/bold]")
        console.print("\n[bold]Metrics:[/bold]")
        console.print(f"  Games processed: {aggregated_metrics.games_processed:,}")
        logger.info(f"Import completed for provider: {args.provider}, "
                   f"games processed: {aggregated_metrics.games_processed}, "
                   f"accepted: {aggregated_metrics.games_accepted}")
        
        # Deduplication metrics
        if aggregated_metrics.duplicates_skipped > 0:
            dedup_rate = (aggregated_metrics.duplicates_skipped / aggregated_metrics.games_processed * 100) if aggregated_metrics.games_processed > 0 else 0
            console.print(f"  [yellow]Duplicates skipped: {aggregated_metrics.duplicates_skipped:,}[/yellow] ({dedup_rate:.1f}%)")
        
        console.print(f"  [green]Games accepted: {aggregated_metrics.games_accepted:,}[/green]")
        console.print(f"  [red]Games quarantined: {aggregated_metrics.games_quarantined:,}[/red]")
        console.print(f"  [yellow]Duplicates found (existing): {aggregated_metrics.duplicates_found:,}[/yellow]")
        console.print(f"  Teams matched: {aggregated_metrics.teams_matched:,}")
        console.print(f"  Teams created: {aggregated_metrics.teams_created:,}")
        console.print(f"  [green]Auto-matched: {aggregated_metrics.fuzzy_matches_auto:,}[/green]")
        console.print(f"  [yellow]Queued for review: {aggregated_metrics.fuzzy_matches_manual:,}[/yellow]")
        console.print(f"  [red]Rejected: {aggregated_metrics.fuzzy_matches_rejected:,}[/red]")
        console.print(f"  Processing time: {aggregated_metrics.processing_time_seconds:.2f}s")
        
        # Partial failure reporting
        if failed_batches:
            console.print(f"\n[red]Failed batches: {len(failed_batches)} ({failed_rows:,} rows)[/red]")
            for failed in failed_batches[:5]:
                console.print(f"  Batch {failed['batch_num']} ({failed['size']} rows): {failed['error'][:100]}")
            if len(failed_batches) > 5:
                console.print(f"  ... and {len(failed_batches) - 5} more")
        
        # Summary
        if aggregated_metrics.duplicates_skipped > 0:
            unique_games = aggregated_metrics.games_processed - aggregated_metrics.duplicates_skipped
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Unique games from source: {unique_games:,}")
            console.print(f"  Imported: {aggregated_metrics.games_accepted:,}")
            console.print(f"  Already in database: {aggregated_metrics.duplicates_found:,}")
        
        if aggregated_metrics.errors:
            console.print(f"\n[yellow]Errors encountered: {len(aggregated_metrics.errors)}[/yellow]")
            for error in aggregated_metrics.errors[:5]:
                console.print(f"  - {error[:100]}")
            if len(aggregated_metrics.errors) > 5:
                console.print(f"  ... and {len(aggregated_metrics.errors) - 5} more")
        
        if args.dry_run:
            console.print("\n[yellow]Dry run completed - no changes were made[/yellow]")
        
        # Print Modular11 summary (for both dry-run and real imports)
        pipeline.print_modular11_summary(aggregated_metrics)
        
        if not args.dry_run:
            console.print("\n[green]Check build_logs table for detailed metrics[/green]")
        
        # Exit code based on success/failure
        if use_streaming and 'total_batches' in dir():
            if failed_batches and len(failed_batches) == total_batches:
                sys.exit(1)  # All batches failed
            
    except Exception as e:
        console.print(f"\n[red]Import failed: {e}[/red]")
        logger.exception("Import error details")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

