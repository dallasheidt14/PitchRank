#!/usr/bin/env python3
"""
Process Missing Games Requests

This script processes user-initiated scrape requests from the scrape_requests table.
It queries for pending requests, scrapes the requested games, and imports them.

Usage:
    python scripts/process_missing_games.py [--limit 10] [--dry-run] [--continuous] [--interval 30]
"""

import os
import sys
import json
import tempfile
import argparse
import logging
import subprocess
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scrapers.gotsport import GotSportScraper

# Load environment variables
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MissingGamesProcessor:
    """Process missing game scrape requests"""
    
    def __init__(self, supabase_client: Client, dry_run: bool = False):
        self.supabase = supabase_client
        self.dry_run = dry_run
        
        # Initialize scrapers for different providers
        self.scrapers = {
            'gotsport': GotSportScraper(supabase_client, 'gotsport'),
            # Add other scrapers as needed
        }
        
        # Stats tracking
        self.stats = {
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'games_found': 0
        }
    
    def get_pending_requests(self, limit: int = 10) -> List[Dict]:
        """Fetch pending scrape requests from database"""
        try:
            result = self.supabase.table('scrape_requests')\
                .select('*')\
                .eq('status', 'pending')\
                .eq('request_type', 'missing_game')\
                .order('requested_at')\
                .limit(limit)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching pending requests: {e}")
            return []
    
    def update_request_status(self, request_id: str, status: str, **kwargs):
        """Update scrape request status in database"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would update request {request_id} to status: {status}")
            return
        
        try:
            update_data = {'status': status}
            
            # Add timestamps based on status
            if status == 'processing':
                update_data['processed_at'] = datetime.now().isoformat()
            elif status in ['completed', 'failed']:
                update_data['completed_at'] = datetime.now().isoformat()
            
            # Add any additional fields
            update_data.update(kwargs)
            
            self.supabase.table('scrape_requests')\
                .update(update_data)\
                .eq('id', request_id)\
                .execute()
                
            logger.info(f"Updated request {request_id} to status: {status}")
        except Exception as e:
            logger.error(f"Error updating request {request_id}: {e}")
    
    def get_provider_code(self, provider_id: str) -> Optional[str]:
        """Get provider code from provider ID"""
        try:
            result = self.supabase.table('providers')\
                .select('code')\
                .eq('id', provider_id)\
                .single()\
                .execute()
            
            return result.data['code'] if result.data else 'gotsport'
        except Exception as e:
            logger.warning(f"Error fetching provider code for {provider_id}: {e}")
            return 'gotsport'  # Default to gotsport
    
    def scrape_games_for_date(self, provider_code: str, team_id: str, game_date: str) -> List[Dict]:
        """Scrape games for a specific team within a 5-day window (±2 days from selected date)"""
        scraper = self.scrapers.get(provider_code)
        if not scraper:
            raise ValueError(f"No scraper available for provider: {provider_code}")
        
        # Parse the target date
        target_date = datetime.strptime(game_date, '%Y-%m-%d').date()
        
        # Define the 5-day window: 2 days before, target date, 2 days after
        date_window_start = target_date - timedelta(days=2)
        date_window_end = target_date + timedelta(days=2)
        
        # Scrape with a date range starting 2 days before (to catch timezone issues)
        # The scraper uses since_date, so we'll scrape from 2 days before and filter
        start_date = datetime.combine(date_window_start, datetime.min.time())
        
        logger.info(f"Scraping games for team {team_id} in 5-day window: {date_window_start} to {date_window_end} (selected date: {game_date})")
        
        try:
            # Use the scraper's method to get games (only takes since_date, not until_date)
            games = scraper.scrape_team_games(
                team_id,
                since_date=start_date
            )
            
            # Filter to games within the 5-day window
            filtered_games = []
            for game in games:
                # GameData.game_date is a string in 'YYYY-MM-DD' format
                # IMPORTANT: Preserve the exact date string from scraper to avoid timezone issues
                try:
                    # Parse date for comparison only (don't modify the original string)
                    game_dt = datetime.strptime(game.game_date, '%Y-%m-%d').date()
                    
                    # Include games within the 5-day window
                    if date_window_start <= game_dt <= date_window_end:
                        # Use the EXACT game_date string from the scraper (no manipulation)
                        # This ensures timezone issues don't cause date shifts
                        original_game_date = game.game_date
                        
                        # Verify the date string format
                        if not isinstance(original_game_date, str) or len(original_game_date) != 10:
                            logger.warning(f"Unexpected game_date format: {original_game_date}, type: {type(original_game_date)}")
                        
                        # Convert GameData to dict format for import
                        game_dict = {
                            'provider': provider_code,
                            'team_id': str(game.team_id),
                            'team_id_source': str(game.team_id),
                            'opponent_id': str(game.opponent_id) if game.opponent_id else '',
                            'opponent_id_source': str(game.opponent_id) if game.opponent_id else '',
                            'team_name': game.team_name or '',
                            'opponent_name': game.opponent_name or '',
                            'game_date': original_game_date,  # Use exact string from scraper
                            'home_away': game.home_away or '',
                            'goals_for': game.goals_for,
                            'goals_against': game.goals_against,
                            'result': game.result or 'U',
                            'competition': game.competition or '',
                            'venue': game.venue or '',
                            'source_url': game.meta.get('source_url', '') if game.meta else '',
                            'scraped_at': datetime.now().isoformat()
                        }
                        filtered_games.append(game_dict)
                        logger.info(f"Including game on {original_game_date} (within window, parsed as {game_dt})")
                    else:
                        logger.debug(f"Skipping game on {game.game_date} (outside window: {game_dt} not in {date_window_start} to {date_window_end})")
                except (ValueError, AttributeError) as e:
                    logger.warning(f"Error parsing game date for game: {e}, game_date value: {getattr(game, 'game_date', 'MISSING')}")
                    continue
            
            logger.info(f"Found {len(filtered_games)} games in 5-day window ({date_window_start} to {date_window_end})")
            if filtered_games:
                game_dates = sorted(set(g['game_date'] for g in filtered_games))
                logger.info(f"Game dates found: {', '.join(game_dates)}")
            
            return filtered_games
            
        except Exception as e:
            logger.error(f"Error scraping games: {e}")
            raise
    
    def save_games_to_temp_file(self, games: List[Dict]) -> Optional[str]:
        """Save games to temporary JSONL file for import"""
        if not games:
            return None
        
        # Log the exact dates being saved (for debugging date issues)
        game_dates_in_file = [g.get('game_date', 'MISSING') for g in games]
        logger.info(f"Saving {len(games)} games with dates: {', '.join(sorted(set(game_dates_in_file)))}")
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.jsonl',
            delete=False,
            encoding='utf-8'
        )
        
        try:
            # Write games as JSONL (one JSON object per line)
            for idx, game in enumerate(games):
                # Verify game_date before writing
                game_date = game.get('game_date', '')
                if not game_date or len(game_date) != 10:
                    logger.warning(f"Game {idx} has invalid game_date format: {game_date}")
                
                json.dump(game, temp_file, ensure_ascii=False)
                temp_file.write('\n')
            
            temp_file.flush()
            temp_file.close()
            
            logger.info(f"Saved {len(games)} games to {temp_file.name}")
            return temp_file.name
        except Exception as e:
            temp_file.close()
            # Clean up on error
            try:
                os.unlink(temp_file.name)
            except:
                pass
            raise
    
    def import_games(self, games: List[Dict], provider_code: str) -> int:
        """Import games using import_games_enhanced.py script"""
        if not games:
            return 0
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would import {len(games)} games")
            return len(games)
        
        # Save games to temporary file
        temp_file = None
        try:
            temp_file = self.save_games_to_temp_file(games)
            if not temp_file:
                return 0
            
            # Get the script path
            script_dir = Path(__file__).parent
            import_script = script_dir / 'import_games_enhanced.py'
            
            # Build command
            cmd = [
                sys.executable,
                str(import_script),
                temp_file,
                provider_code,
            ]
            
            if self.dry_run:
                cmd.append('--dry-run')
            
            logger.info(f"Running import script: {' '.join(cmd)}")
            
            # Run the import script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent  # Run from project root
            )
            
            if result.returncode != 0:
                logger.error(f"Import script failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"Import failed: {result.stderr or 'Unknown error'}")
            
            # Parse output to get number of games imported
            # The script outputs metrics, but we'll use the games count as a proxy
            # In a real scenario, you might want to parse the actual metrics from stdout
            logger.info(f"Import completed successfully")
            logger.debug(f"STDOUT: {result.stdout}")
            
            # Return the number of games we attempted to import
            # The actual imported count would require parsing the output
            return len(games)
            
        except Exception as e:
            logger.error(f"Error importing games: {e}")
            raise
        finally:
            # Clean up temporary file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete temporary file {temp_file}: {e}")
    
    def process_request(self, request: Dict) -> bool:
        """Process a single scrape request"""
        request_id = request.get('id')
        team_name = request.get('team_name', 'Unknown')
        game_date = request.get('game_date')
        provider_id = request.get('provider_id')
        provider_team_id = request.get('provider_team_id')
        
        # Validate required fields
        if not request_id:
            raise ValueError("Missing required field: id")
        if not game_date:
            raise ValueError("Missing required field: game_date")
        if not provider_id:
            raise ValueError("Missing required field: provider_id")
        if not provider_team_id:
            raise ValueError("Missing required field: provider_team_id")
        
        logger.info(f"Processing request {request_id} for {team_name} on {game_date}")
        logger.debug(f"Request data: provider_id={provider_id}, provider_team_id={provider_team_id}")
        
        try:
            # Update status to processing
            self.update_request_status(request_id, 'processing')
            
            # Get provider code
            provider_code = self.get_provider_code(provider_id)
            
            # Scrape games for the date (±2 days window to catch timezone issues)
            games = self.scrape_games_for_date(
                provider_code,
                provider_team_id,
                game_date
            )
            
            # Import games if found
            games_imported = 0
            if games:
                games_imported = self.import_games(games, provider_code)
                self.stats['games_found'] += games_imported
            
            # Update request as completed
            self.update_request_status(
                request_id,
                'completed',
                games_found=len(games)
            )
            
            logger.info(f"Successfully processed request {request_id}: "
                       f"{len(games)} games found in 5-day window, {games_imported} imported")
            
            self.stats['successful'] += 1
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process request {request_id}: {error_msg}")
            logger.debug(traceback.format_exc())
            
            # Update request as failed
            self.update_request_status(
                request_id,
                'failed',
                error_message=error_msg[:500]  # Truncate error message
            )
            
            self.stats['failed'] += 1
            return False
    
    def process_all(self, limit: int = 10) -> Dict:
        """Process all pending requests up to limit"""
        logger.info(f"Starting to process missing game requests (limit: {limit})")
        
        # Get pending requests
        requests = self.get_pending_requests(limit)
        
        if not requests:
            logger.info("No pending requests found")
            return self.stats
        
        logger.info(f"Found {len(requests)} pending requests")
        
        # Process each request
        for request in requests:
            self.stats['processed'] += 1
            
            try:
                self.process_request(request)
                
                # Add a small delay between requests to be nice to the API
                time.sleep(2)
                
            except KeyboardInterrupt:
                logger.info("Processing interrupted by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error processing request: {e}")
                continue
        
        # Log summary
        self.log_summary()
        return self.stats
    
    def log_summary(self):
        """Log processing summary"""
        logger.info("=" * 50)
        logger.info("Processing Summary:")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Successful: {self.stats['successful']}")
        logger.info(f"  Failed: {self.stats['failed']}")
        logger.info(f"  Total Games Found: {self.stats['games_found']}")
        logger.info("=" * 50)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Process missing game scrape requests')
    parser.add_argument('--limit', type=int, default=10,
                       help='Maximum number of requests to process')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run without making any changes')
    parser.add_argument('--continuous', action='store_true',
                       help='Run continuously, checking every 30 seconds')
    parser.add_argument('--interval', type=int, default=30,
                       help='Interval in seconds for continuous mode')
    
    args = parser.parse_args()
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY')
    
    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables")
        sys.exit(1)
    
    try:
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        sys.exit(1)
    
    # Create processor
    processor = MissingGamesProcessor(supabase, dry_run=args.dry_run)
    
    if args.continuous:
        logger.info(f"Running in continuous mode (interval: {args.interval}s)")
        
        while True:
            try:
                processor.process_all(limit=args.limit)
                logger.info(f"Sleeping for {args.interval} seconds...")
                time.sleep(args.interval)
                
                # Reset stats for next run
                processor.stats = {
                    'processed': 0,
                    'successful': 0,
                    'failed': 0,
                    'games_found': 0
                }
                
            except KeyboardInterrupt:
                logger.info("Stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in continuous mode: {e}")
                time.sleep(60)  # Wait longer on error
    else:
        # Single run
        stats = processor.process_all(limit=args.limit)
        
        # Exit with appropriate code
        if stats['failed'] > 0:
            sys.exit(1)
        sys.exit(0)


if __name__ == '__main__':
    main()
