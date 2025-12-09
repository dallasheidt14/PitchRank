"""Enhanced ETL Pipeline with metrics tracking and bulk operations"""
import asyncio
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
import logging
from dataclasses import dataclass, field
import copy
import json
import sys
import time
import random
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from supabase import Client
from config.settings import MATCHING_CONFIG, BUILD_ID
from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import EnhancedDataValidator, parse_game_date

logger = logging.getLogger(__name__)


@dataclass
class ImportMetrics:
    """Track detailed metrics for build logs"""
    games_processed: int = 0
    games_accepted: int = 0
    games_quarantined: int = 0
    duplicates_found: int = 0
    duplicates_skipped: int = 0  # Perspective-based duplicates (should be ~50% of total)
    teams_matched: int = 0
    teams_created: int = 0
    fuzzy_matches_auto: int = 0
    fuzzy_matches_manual: int = 0
    fuzzy_matches_rejected: int = 0
    processing_time_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    errors: List[str] = field(default_factory=list)
    # Debugging fields
    matched_games_count: int = 0
    partial_games_count: int = 0
    failed_games_count: int = 0
    skipped_empty_provider_ids: int = 0  # Games skipped due to empty provider IDs
    skipped_empty_game_date: int = 0  # Games skipped due to empty game_date
    skipped_empty_scores: int = 0  # Games skipped due to missing both scores
    duplicate_key_violations: int = 0  # Games rejected due to unique constraint (already in DB)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for JSONB storage"""
        return {
            'games_processed': self.games_processed,
            'games_accepted': self.games_accepted,
            'games_quarantined': self.games_quarantined,
            'duplicates_found': self.duplicates_found,
            'duplicates_skipped': self.duplicates_skipped,
            'teams_matched': self.teams_matched,
            'teams_created': self.teams_created,
            'fuzzy_matches_auto': self.fuzzy_matches_auto,
            'fuzzy_matches_manual': self.fuzzy_matches_manual,
            'fuzzy_matches_rejected': self.fuzzy_matches_rejected,
            'processing_time_seconds': round(self.processing_time_seconds, 2),
            'memory_usage_mb': round(self.memory_usage_mb, 2),
            'errors': self.errors,
            'matched_games_count': self.matched_games_count,
            'partial_games_count': self.partial_games_count,
            'failed_games_count': self.failed_games_count,
            'skipped_empty_provider_ids': self.skipped_empty_provider_ids,
            'skipped_empty_game_date': self.skipped_empty_game_date,
            'skipped_empty_scores': self.skipped_empty_scores,
            'duplicate_key_violations': self.duplicate_key_violations
        }


class EnhancedETLPipeline:
    """Enhanced ETL pipeline with bulk operations, validation, and metrics tracking"""
    
    def __init__(self, supabase: Client, provider_code: str, dry_run: bool = False, skip_validation: bool = False, summary_only: bool = False):
        self.supabase = supabase
        self.provider_code = provider_code
        self.dry_run = dry_run
        self.skip_validation = skip_validation
        self.summary_only = summary_only
        self.metrics = ImportMetrics()
        # Dynamic batch size based on total games for optimal performance
        # Larger batches = fewer DB round trips, but watch for 429/timeout errors
        # Reduced default batch size to avoid Supabase API rate limits
        self.batch_size = 1000  # Default, reduced from 2000 to avoid rate limits
        self._batch_count = 0  # Track batches for logging frequency
        self._log_every_n_batches = 50  # Log metrics to DB every N batches
        self._log_every_n_games = 10000  # Log progress updates every N games
        self._last_logged_games = 0  # Track last logged game count
        self.validator = EnhancedDataValidator()
        self.build_id = BUILD_ID
        
        # Get provider UUID with retry logic
        max_retries = 5
        retry_delay = 0.5
        self.provider_id = None
        
        for attempt in range(max_retries):
            try:
                result = self.supabase.table('providers').select('id').eq(
                    'code', provider_code
                ).single().execute()
                self.provider_id = result.data['id']
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"Provider lookup failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Provider not found after {max_retries} attempts: {provider_code}")
                    raise ValueError(f"Provider not found: {provider_code}") from e
        
        # Initialize matcher with provider_id to avoid repeated lookups
        # Preload alias map cache for fast lookups
        self.alias_cache = {}
        try:
            alias_result = self.supabase.table('team_alias_map').select(
                'provider_team_id, team_id_master, match_method, review_status'
            ).eq('provider_id', self.provider_id).eq(
                'review_status', 'approved'
            ).execute()
            
            for alias in alias_result.data:
                team_id = str(alias['provider_team_id'])
                if team_id not in self.alias_cache:
                    self.alias_cache[team_id] = {
                        'team_id_master': alias['team_id_master'],
                        'match_method': alias.get('match_method'),
                        'review_status': alias.get('review_status')
                    }
            
            logger.info(f"Loaded {len(self.alias_cache)} alias mappings into cache")
        except Exception as e:
            logger.warning(f"Could not preload alias cache: {e}")
            self.alias_cache = {}
        
        # Use Modular11-specific matcher for Modular11 provider (with age_group validation)
        # Use standard matcher for all other providers (GotSport, etc.)
        if provider_code.lower() == 'modular11':
            # Lazy import to avoid breaking other providers if module doesn't exist yet
            from src.models.modular11_matcher import Modular11GameMatcher
            logger.info("Using Modular11GameMatcher (with age_group validation)")
            # Enable debug mode for dry runs OR summary_only mode (to track summary data)
            # But suppress per-team logs if summary_only is True
            debug_mode = dry_run or summary_only
            self.matcher = Modular11GameMatcher(supabase, provider_id=self.provider_id, alias_cache=self.alias_cache, debug=debug_mode, summary_only=summary_only)
        else:
            logger.info(f"Using standard GameHistoryMatcher for provider: {provider_code}")
            self.matcher = GameHistoryMatcher(supabase, provider_id=self.provider_id, alias_cache=self.alias_cache)
    
    def _has_valid_scores(self, game: Dict) -> bool:
        """
        Return True only if both goals_for and goals_against are valid numeric values.
        
        Handles: None, 'None' (case-insensitive), 'null' (case-insensitive), empty strings, 
        and non-numeric values. Returns False for any missing, invalid, or partial scores.
        
        Supports both source format (goals_for/goals_against) and transformed format 
        (home_score/away_score).
        
        Args:
            game: Game dictionary with either:
                - 'goals_for' and 'goals_against' keys (source format), or
                - 'home_score' and 'away_score' keys (transformed format)
            
        Returns:
            True if both scores are valid numeric values, False otherwise
        """
        try:
            # Check for transformed format first (home_score/away_score)
            if 'home_score' in game or 'away_score' in game:
                goals_for = game.get('home_score')
                goals_against = game.get('away_score')
            else:
                # Source format (goals_for/goals_against)
                goals_for = game.get('goals_for')
                goals_against = game.get('goals_against')
            
            # Normalize to string and check for empty/missing values
            def normalize_score(score):
                if score is None:
                    return ''
                return str(score).strip().lower()
            
            gf = normalize_score(goals_for)
            ga = normalize_score(goals_against)
            
            # Check if either score is missing or invalid
            if gf in ('', 'none', 'null') or ga in ('', 'none', 'null'):
                return False
            
            # Validate that both can be converted to float (numeric)
            float(gf)
            float(ga)
            
            return True
        except (ValueError, TypeError):
            # Non-numeric values or conversion errors
            return False
    
    def _make_composite_key(self, game: Dict) -> str:
        """
        Construct composite key matching the database unique constraint.
        
        Mirrors the DB constraint: (provider_id, home_provider_id, away_provider_id, 
        game_date, COALESCE(home_score, -1), COALESCE(away_score, -1))
        
        Args:
            game: Game record dictionary with provider_id, home_provider_id, 
                  away_provider_id, game_date, home_score, away_score
            
        Returns:
            Composite key string: "provider_id|home_provider_id|away_provider_id|game_date|home_score|-1|away_score|-1"
        """
        provider_id = str(game.get('provider_id', ''))
        home_provider_id = str(game.get('home_provider_id', ''))
        away_provider_id = str(game.get('away_provider_id', ''))
        game_date = str(game.get('game_date', ''))
        # Handle None scores by converting to -1 (matching COALESCE behavior)
        home_score = game.get('home_score')
        away_score = game.get('away_score')
        home_score_str = str(home_score) if home_score is not None else '-1'
        away_score_str = str(away_score) if away_score is not None else '-1'
        
        return f"{provider_id}|{home_provider_id}|{away_provider_id}|{game_date}|{home_score_str}|{away_score_str}"
        
    async def import_games(self, games: List[Dict], provider_code: Optional[str] = None) -> ImportMetrics:
        """
        Import games with bulk operations, validation, and metrics tracking
        
        Args:
            games: List of game dictionaries
            provider_code: Optional provider code override
            
        Returns:
            ImportMetrics object with detailed statistics for THIS BATCH ONLY
            (to avoid double-counting when batches run concurrently)
        """
        start_time = datetime.now()
        
        # Initialize import start time on first batch
        if not hasattr(self, '_import_start_time'):
            self._import_start_time = start_time
        
        # Create batch-specific metrics to avoid double-counting in concurrent batches
        # We'll still update self.metrics for overall tracking, but return batch_metrics
        batch_metrics = ImportMetrics()
        
        try:
            # Step 1: Validate all games (or skip if flag is set)
            # Store current duplicates_skipped before validation to calculate batch-specific value
            prev_duplicates_skipped = self.metrics.duplicates_skipped
            
            if self.skip_validation:
                # Skip validation but still do schema coercion/transformation
                valid_games, invalid_games = await self._validate_games_skip_validation(games)
            else:
                valid_games, invalid_games = await self._validate_games(games)
            
            # Track batch-specific metrics
            batch_metrics.games_processed = len(games)
            batch_metrics.games_quarantined = len(invalid_games)
            # Calculate batch-specific duplicates_skipped (validation method sets it, so get the delta)
            batch_metrics.duplicates_skipped = self.metrics.duplicates_skipped - prev_duplicates_skipped
            
            # Also update shared metrics for logging (but aggregation will use batch_metrics)
            self.metrics.games_processed += len(games)  # ACCUMULATE
            self.metrics.games_quarantined += len(invalid_games)  # ACCUMULATE
            
            # Log invalid games for review
            if invalid_games:
                await self._log_invalid_games(invalid_games)
            
            # Step 2: Check for duplicates
            existing_uids = await self._check_duplicates(valid_games)
            batch_metrics.duplicates_found = len(existing_uids)
            self.metrics.duplicates_found += len(existing_uids)  # ACCUMULATE for logging
            
            # Filter out duplicates (enforce immutability)
            new_games = [g for g in valid_games if g.get('game_uid') not in existing_uids]
            
            # Step 3: Match teams and prepare game records
            game_records = []
            matched_count = 0
            partial_count = 0
            failed_count = 0
            
            for game in new_games:
                try:
                    # Match game history to get structured game record
                    # Pass dry_run flag to game_data for diagnostic mode
                    if self.dry_run:
                        game['dry_run'] = True
                    matched_game = self.matcher.match_game_history(game)
                    match_status = matched_game.get('match_status')
                    
                    if match_status == 'matched':
                        game_records.append(matched_game)
                        matched_count += 1
                        batch_metrics.teams_matched += 2  # Home and away
                        self.metrics.teams_matched += 2  # Also update shared for logging
                    elif match_status == 'partial':
                        game_records.append(matched_game)
                        partial_count += 1
                        batch_metrics.teams_matched += 1
                        self.metrics.teams_matched += 1  # Also update shared for logging
                    else:
                        failed_count += 1
                        # Don't increment teams_matched for failed matches
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"Error matching game: {e}")
                    batch_metrics.errors.append(f"Match error: {str(e)}")
                    self.metrics.errors.append(f"Match error: {str(e)}")
            
            # Store counts in batch metrics for debugging
            batch_metrics.matched_games_count = matched_count
            batch_metrics.partial_games_count = partial_count
            batch_metrics.failed_games_count = failed_count
            # Also update shared metrics
            self.metrics.matched_games_count = matched_count
            self.metrics.partial_games_count = partial_count
            self.metrics.failed_games_count = failed_count
            
            logger.info(f"Matched {len(game_records)} games (matched: {matched_count}, partial: {partial_count}, failed: {failed_count})")
            
            # Step 4: Filter games with invalid scores before bulk insert
            valid_game_records = [g for g in game_records if self._has_valid_scores(g)]
            skipped_count = len(game_records) - len(valid_game_records)
            
            if skipped_count > 0:
                batch_metrics.skipped_empty_scores = skipped_count
                self.metrics.skipped_empty_scores += skipped_count
                logger.warning(f"Skipped {skipped_count} games with invalid or missing scores")
            
            # Step 5: Bulk insert games
            if valid_game_records and not self.dry_run:
                logger.info(f"Attempting to insert {len(valid_game_records)} matched games...")
                inserted_count = await self._bulk_insert_games(valid_game_records)
                batch_metrics.games_accepted = inserted_count  # Batch-specific count
                self.metrics.games_accepted += inserted_count  # Also update shared for logging
                logger.info(f"Inserted {inserted_count} games successfully (batch accepted: {inserted_count})")
                
                # Step 5b: Update last_scraped_at for teams based on imported games
                await self._update_team_scrape_dates(valid_game_records)
            elif self.dry_run:
                batch_metrics.games_accepted = len(valid_game_records)
                self.metrics.games_accepted += len(valid_game_records)  # Also update shared for logging
                logger.info("Dry run mode - games not inserted")
            elif not valid_game_records:
                logger.warning(f"No game records to insert after matching and score validation (matched: {matched_count}, partial: {partial_count}, failed: {failed_count}, skipped scores: {skipped_count})")
            
            # Step 6: Process team matching statistics
            await self._process_team_matching_stats()
            
            # Step 7: Calculate processing time
            batch_metrics.processing_time_seconds = (datetime.now() - start_time).total_seconds()
            self.metrics.processing_time_seconds += batch_metrics.processing_time_seconds  # Accumulate for logging
            
            # Step 8: Log build metrics and progress updates
            self._batch_count += 1
            
            # Check if we should log progress update (every 10k games)
            games_since_last_log = self.metrics.games_processed - self._last_logged_games
            should_log_progress = games_since_last_log >= self._log_every_n_games
            
            # Log to database (less frequent, every N batches)
            if self._batch_count % self._log_every_n_batches == 0 or self._batch_count == 1:
                await self._log_build_metrics()
                logger.info(f"📊 [DB LOG] Batch {self._batch_count} | Processed: {self.metrics.games_processed:,} | Accepted: {self.metrics.games_accepted:,} | Quarantined: {self.metrics.games_quarantined:,} | Duplicates: {self.metrics.duplicates_found:,}")
            
            # Log progress update to console (every 10k games)
            if should_log_progress:
                elapsed_time = (datetime.now() - getattr(self, "_import_start_time", datetime.now())).total_seconds()
                games_per_sec = self.metrics.games_processed / elapsed_time if elapsed_time > 0 else 0
                remaining_games = 996136 - self.metrics.games_processed  # Approximate total from CSV
                eta_seconds = remaining_games / games_per_sec if games_per_sec > 0 else 0
                eta_minutes = eta_seconds / 60
                
                logger.info(
                    f"\n{'='*80}\n"
                    f"📈 PROGRESS UPDATE ({self.metrics.games_processed:,} games processed)\n"
                    f"{'='*80}\n"
                    f"  ✅ Accepted:        {self.metrics.games_accepted:,} games\n"
                    f"  ⚠️  Quarantined:     {self.metrics.games_quarantined:,} games\n"
                    f"  🔄 Duplicates:       {self.metrics.duplicates_found:,} games (already in DB)\n"
                    f"  📊 Perspective dup: {self.metrics.duplicates_skipped:,} skipped\n"
                    f"  ⚡ Processing rate: {games_per_sec:.1f} games/sec\n"
                    f"  ⏱️  Elapsed time:    {elapsed_time/60:.1f} minutes\n"
                    f"  🎯 ETA:             {eta_minutes:.1f} minutes remaining\n"
                    f"{'='*80}\n"
                )
                self._last_logged_games = self.metrics.games_processed
            
            if self.dry_run:
                logger.info("Dry run completed - no changes committed")
            else:
                logger.info(f"Batch completed: {batch_metrics.games_accepted} games imported")
            
            # Return batch-specific metrics (not shared self.metrics) to avoid double-counting
            return batch_metrics
            
        except Exception as e:
            batch_metrics.errors.append(str(e))
            self.metrics.errors.append(str(e))
            logger.error(f"Import failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self._log_build_metrics()  # Log partial metrics
            # Return batch metrics even on error so aggregation can track failures
            return batch_metrics
            
    async def _validate_games(self, games: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Validate games data, deduplicate perspective-based duplicates, and transform to neutral format.
        
        Source data has each game twice (once from each team's perspective):
        - Format: team_id, opponent_id, home_away, goals_for, goals_against
        - Need to deduplicate and convert to: home_team_id, away_team_id, home_score, away_score
        """
        valid = []
        invalid = []
        seen_games = {}  # game_key -> first occurrence
        duplicates_skipped = 0
        date_mismatches = 0
        skipped_empty_scores = 0
        
        for game in games:
            # Skip games with no scores at all (both goals_for and goals_against are None/null/empty)
            goals_for = game.get('goals_for')
            goals_against = game.get('goals_against')
            
            # Check if both scores are missing
            def is_empty_score(score):
                return score is None or score == '' or str(score).strip().lower() == 'none'
            
            if is_empty_score(goals_for) and is_empty_score(goals_against):
                skipped_empty_scores += 1
                if skipped_empty_scores <= 5:  # Log first 5 examples
                    logger.debug(f"Skipping game with no scores: {game.get('team_id')} vs {game.get('opponent_id')} on {game.get('game_date')}")
                continue
            
            # First validate the game
            is_valid, errors = self.validator.validate_game(game)
            if not is_valid:
                game_copy = game.copy()
                game_copy['validation_errors'] = errors
                invalid.append(game_copy)
                continue
            
            # Create game key for deduplication BEFORE transformation
            # This ensures we catch duplicates regardless of perspective
            provider_code = game.get('provider', self.provider_code)
            game_date_raw = game.get('game_date', '')
            
            # Normalize date to YYYY-MM-DD format for consistent game_uid generation
            # This ensures game_uid matches what's stored in the database
            try:
                date_obj = parse_game_date(game_date_raw)
                game_date_normalized = date_obj.strftime('%Y-%m-%d')
            except ValueError:
                # If date parsing fails, use raw date (will be caught by validation later)
                game_date_normalized = game_date_raw
            
            team1_id = str(game.get('team_id', ''))
            team2_id = str(game.get('opponent_id', ''))
            
            # Sort team IDs for consistent key (order doesn't matter)
            sorted_teams = sorted([team1_id, team2_id])
            game_key = f"{provider_code}:{game_date_normalized}:{sorted_teams[0]}:{sorted_teams[1]}"
            
            # Check if we've seen this game before
            if game_key in seen_games:
                # Duplicate found - validate dates match
                existing_game = seen_games[game_key]
                existing_date = existing_game.get('game_date', '')
                current_date = game_date_normalized
                
                if existing_date != current_date:
                    logger.warning(
                        f"Date mismatch for game {game_key}: "
                        f"existing={existing_date}, current={current_date}"
                    )
                    date_mismatches += 1
                    # Use first occurrence's date
                
                duplicates_skipped += 1
                logger.debug(f"Skipping duplicate game: {game_key}")
                continue
            
            # Transform from perspective-based to neutral format
            transformed_game = self._transform_game_perspective(game)
            
            # Generate game_uid using normalized date format
            from src.models.game_matcher import GameHistoryMatcher
            game_uid = GameHistoryMatcher.generate_game_uid(
                provider=provider_code,
                game_date=game_date_normalized,  # Use normalized date
                team1_id=sorted_teams[0],
                team2_id=sorted_teams[1]
            )
            transformed_game['game_uid'] = game_uid
            # Store normalized date in transformed game for consistency
            transformed_game['game_date'] = game_date_normalized
            
            # First occurrence - store it
            seen_games[game_key] = transformed_game
            valid.append(transformed_game)
        
        # Update metrics
        self.metrics.duplicates_skipped = duplicates_skipped
        self.metrics.skipped_empty_scores = skipped_empty_scores
        if date_mismatches > 0:
            logger.warning(f"Found {date_mismatches} games with date mismatches between perspectives")
            self.metrics.errors.append(f"{date_mismatches} games had date mismatches")
        if skipped_empty_scores > 0:
            logger.info(f"Skipped {skipped_empty_scores} games with no scores")
        
        logger.info(
            f"Validation complete: {len(valid)} unique games, "
            f"{duplicates_skipped} duplicates skipped, "
            f"{skipped_empty_scores} games with no scores skipped, "
            f"{len(invalid)} invalid"
        )
        
        return valid, invalid
    
    async def _validate_games_skip_validation(self, games: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Skip validation but still do schema coercion/transformation and deduplication.
        
        This is used when --skip-validation flag is set (after pre-validating with --validate-only).
        """
        valid = []
        invalid = []  # Empty since we skip validation
        seen_games = {}  # game_key -> first occurrence
        duplicates_skipped = 0
        date_mismatches = 0
        skipped_empty_scores = 0
        
        for game in games:
            # Skip games with no scores at all (both goals_for and goals_against are None/null/empty)
            goals_for = game.get('goals_for')
            goals_against = game.get('goals_against')
            
            # Check if both scores are missing
            def is_empty_score(score):
                return score is None or score == '' or str(score).strip().lower() == 'none'
            
            if is_empty_score(goals_for) and is_empty_score(goals_against):
                skipped_empty_scores += 1
                if skipped_empty_scores <= 5:  # Log first 5 examples
                    logger.debug(f"Skipping game with no scores: {game.get('team_id')} vs {game.get('opponent_id')} on {game.get('game_date')}")
                continue
            
            # Skip validation check, but still do deduplication and transformation
            
            # Create game key for deduplication BEFORE transformation
            provider_code = game.get('provider', self.provider_code)
            game_date_raw = game.get('game_date', '')
            
            # Normalize date to YYYY-MM-DD format for consistent game_uid generation
            try:
                date_obj = parse_game_date(game_date_raw)
                game_date_normalized = date_obj.strftime('%Y-%m-%d')
            except ValueError:
                game_date_normalized = game_date_raw
            
            team1_id = str(game.get('team_id', ''))
            team2_id = str(game.get('opponent_id', ''))
            
            # Sort team IDs for consistent key (order doesn't matter)
            sorted_teams = sorted([team1_id, team2_id])
            game_key = f"{provider_code}:{game_date_normalized}:{sorted_teams[0]}:{sorted_teams[1]}"
            
            # Check if we've seen this game before
            if game_key in seen_games:
                # Duplicate found - validate dates match
                existing_game = seen_games[game_key]
                existing_date = existing_game.get('game_date', '')
                current_date = game_date_normalized
                
                if existing_date != current_date:
                    logger.warning(
                        f"Date mismatch for game {game_key}: "
                        f"existing={existing_date}, current={current_date}"
                    )
                    date_mismatches += 1
                
                duplicates_skipped += 1
                logger.debug(f"Skipping duplicate game: {game_key}")
                continue
            
            # Transform from perspective-based to neutral format
            transformed_game = self._transform_game_perspective(game)
            
            # Generate game_uid using normalized date format
            from src.models.game_matcher import GameHistoryMatcher
            game_uid = GameHistoryMatcher.generate_game_uid(
                provider=provider_code,
                game_date=game_date_normalized,  # Use normalized date
                team1_id=sorted_teams[0],
                team2_id=sorted_teams[1]
            )
            transformed_game['game_uid'] = game_uid
            # Store normalized date in transformed game for consistency
            transformed_game['game_date'] = game_date_normalized
            
            # First occurrence - store it
            seen_games[game_key] = transformed_game
            valid.append(transformed_game)
        
        # Update metrics
        self.metrics.duplicates_skipped = duplicates_skipped
        if date_mismatches > 0:
            logger.warning(f"Found {date_mismatches} games with date mismatches between perspectives")
            self.metrics.errors.append(f"{date_mismatches} games had date mismatches")
        
        # Update metrics
        self.metrics.duplicates_skipped = duplicates_skipped
        self.metrics.skipped_empty_scores = skipped_empty_scores
        if skipped_empty_scores > 0:
            logger.info(f"Skipped {skipped_empty_scores} games with no scores")
        
        logger.info(
            f"Processing complete (validation skipped): {len(valid)} unique games, "
            f"{duplicates_skipped} duplicates skipped, "
            f"{skipped_empty_scores} games with no scores skipped"
        )
        
        return valid, invalid
    
    def _transform_game_perspective(self, game: Dict) -> Dict:
        """
        Transform game from perspective-based format to neutral home/away format.
        
        Source format:
        - team_id, opponent_id, home_away ("H" or "A"), goals_for, goals_against
        
        Target format:
        - home_team_id, away_team_id, home_score, away_score
        """
        team_id = game.get('team_id')
        opponent_id = game.get('opponent_id')
        home_away = game.get('home_away', 'H').upper()
        goals_for = game.get('goals_for')
        goals_against = game.get('goals_against')
        
        # Determine home/away based on home_away flag
        if home_away == 'H':
            # team_id is home, opponent_id is away
            home_team_id = team_id
            away_team_id = opponent_id
            home_score = goals_for
            away_score = goals_against
        else:
            # team_id is away, opponent_id is home
            home_team_id = opponent_id
            away_team_id = team_id
            home_score = goals_against
            away_score = goals_for
        
        # Ensure scores are integers (not floats) - database expects INTEGER type
        # Handle None, empty string, and string 'None' cases
        if home_score is None or home_score == '' or str(home_score).strip().lower() == 'none':
            home_score_int = None
        else:
            try:
                home_score_int = int(float(home_score))
            except (ValueError, TypeError):
                home_score_int = None
        
        if away_score is None or away_score == '' or str(away_score).strip().lower() == 'none':
            away_score_int = None
        else:
            try:
                away_score_int = int(float(away_score))
            except (ValueError, TypeError):
                away_score_int = None
        
        # Create transformed game record
        transformed = game.copy()
        transformed['home_team_id'] = home_team_id
        transformed['away_team_id'] = away_team_id
        transformed['home_provider_id'] = home_team_id  # For provider ID lookup
        transformed['away_provider_id'] = away_team_id
        transformed['home_score'] = home_score_int
        transformed['away_score'] = away_score_int
        
        # Transform team names based on home/away
        team_name = game.get('team_name', '')
        opponent_name = game.get('opponent_name', '')
        club_name = game.get('club_name', '')
        opponent_club_name = game.get('opponent_club_name', '')
        
        if home_away == 'H':
            transformed['home_team_name'] = team_name
            transformed['away_team_name'] = opponent_name
            transformed['home_club_name'] = club_name
            transformed['away_club_name'] = opponent_club_name
        else:
            transformed['home_team_name'] = opponent_name
            transformed['away_team_name'] = team_name
            transformed['home_club_name'] = opponent_club_name
            transformed['away_club_name'] = club_name
        
        # Keep original fields for reference
        transformed['_source_team_id'] = team_id
        transformed['_source_opponent_id'] = opponent_id
        transformed['_source_home_away'] = home_away
        
        # Preserve mls_division for Modular11 (needed for division-aware matching)
        if 'mls_division' in game:
            transformed['mls_division'] = game['mls_division']
        
        return transformed
    
    async def _check_duplicates(self, games: List[Dict]) -> set:
        """Check for existing game UIDs - OPTIMIZED with larger batches"""
        if not games:
            return set()
        
        # Extract game UIDs
        game_uids = [g.get('game_uid') for g in games if g.get('game_uid')]
        
        if not game_uids:
            return set()
        
        # OPTIMIZED: Use larger batches (2000 instead of 1000) for fewer queries
        existing = set()
        for chunk in self._chunks(game_uids, 2000):  # Increased from 1000
            try:
                # Query Supabase for existing game_uid values
                result = self.supabase.table('games').select('game_uid').in_(
                    'game_uid', chunk
                ).execute()
                
                if result.data:
                    existing.update(row['game_uid'] for row in result.data if row.get('game_uid'))
            except Exception as e:
                logger.warning(f"Error checking duplicates: {e}")
                # Continue processing even if duplicate check fails
        
        return existing
    
    async def _bulk_insert_games(self, game_records: List[Dict]) -> int:
        """Bulk insert games using Supabase batch operations"""
        if not game_records:
            logger.warning("_bulk_insert_games called with empty game_records list")
            return 0
        
        logger.info(f"Preparing {len(game_records)} game records for insertion...")
        inserted = 0
        duplicate_violations = 0  # Track duplicates caught during insert
        
        # Prepare game records for insertion
        insert_records = []
        skipped_empty_provider_ids = 0
        skipped_empty_game_date = 0
        
        for game in game_records:
            # Ensure all required fields are present
            # Convert scores to integers (database expects INTEGER, not FLOAT)
            home_score = game.get('home_score')
            away_score = game.get('away_score')
            # Handle string scores like "0.0" or float scores
            # Also handle string 'None' which can occur from JSON serialization issues
            if home_score is None or home_score == '' or str(home_score).strip().lower() == 'none':
                home_score_int = None
            else:
                try:
                    home_score_int = int(float(home_score))
                except (ValueError, TypeError):
                    home_score_int = None
            
            if away_score is None or away_score == '' or str(away_score).strip().lower() == 'none':
                away_score_int = None
            else:
                try:
                    away_score_int = int(float(away_score))
                except (ValueError, TypeError):
                    away_score_int = None
            
            record = {
                'game_uid': game.get('game_uid'),
                'home_team_master_id': game.get('home_team_master_id'),
                'away_team_master_id': game.get('away_team_master_id'),
                # Use home_provider_id/away_provider_id from matcher, with fallback to team_id/opponent_id
                # The matcher sets these based on home_away flag, so fallback should work correctly
                'home_provider_id': game.get('home_provider_id') or game.get('team_id', ''),
                'away_provider_id': game.get('away_provider_id') or game.get('opponent_id', ''),
                'home_score': home_score_int,
                'away_score': away_score_int,
                'result': game.get('result'),
                'game_date': game.get('game_date'),
                'competition': game.get('competition'),
                'division_name': game.get('division_name'),
                'event_name': game.get('event_name'),
                'venue': game.get('venue'),
                'provider_id': self.provider_id,
                'source_url': game.get('source_url'),
                'scraped_at': game.get('scraped_at'),
                'is_immutable': True,
                'original_import_id': None  # Can be set to build_id if needed
            }
            
            # Validate required fields before adding to insert batch
            if not record['home_provider_id'] or not record['away_provider_id']:
                skipped_empty_provider_ids += 1
                if skipped_empty_provider_ids <= 5:  # Log first 5 examples
                    logger.warning(f"Skipping game with empty provider IDs: home={record['home_provider_id']}, away={record['away_provider_id']}, game_uid={record['game_uid']}")
                # Don't increment metrics - this is a data quality issue
                continue
            if not record['game_date']:
                skipped_empty_game_date += 1
                if skipped_empty_game_date <= 5:  # Log first 5 examples
                    logger.warning(f"Skipping game with empty game_date: game_uid={record['game_uid']}")
                continue
            
            # Normalize date to YYYY-MM-DD format for database consistency
            try:
                date_obj = parse_game_date(record['game_date'])
                record['game_date'] = date_obj.strftime('%Y-%m-%d')
            except ValueError as e:
                logger.warning(f"Failed to normalize date '{record['game_date']}': {e}")
                # Skip this record if date normalization fails
                skipped_empty_game_date += 1
                continue
                
            insert_records.append(record)
        
        if skipped_empty_provider_ids > 0:
            logger.warning(f"⚠️  Skipped {skipped_empty_provider_ids} games due to empty provider IDs")
            self.metrics.skipped_empty_provider_ids = skipped_empty_provider_ids
        if skipped_empty_game_date > 0:
            logger.warning(f"⚠️  Skipped {skipped_empty_game_date} games due to empty game_date")
            self.metrics.skipped_empty_game_date = skipped_empty_game_date
        
        logger.info(f"Prepared {len(insert_records)} records for insertion (skipped {skipped_empty_provider_ids + skipped_empty_game_date} due to validation)")
        
        # Deduplicate using composite key constraint (matches DB unique constraint)
        # This prevents duplicate constraint violations during insert
        seen_composite_keys = set()
        deduped_records = []
        composite_duplicates_count = 0
        
        for record in insert_records:
            composite_key = self._make_composite_key(record)
            if composite_key not in seen_composite_keys:
                seen_composite_keys.add(composite_key)
                deduped_records.append(record)
            else:
                composite_duplicates_count += 1
                # These are cross-run duplicates (already exist in DB by composite constraint)
                self.metrics.duplicates_found += 1
        
        if composite_duplicates_count > 0:
            logger.info(f"🔁 Deduped {composite_duplicates_count} games pre-insert using composite constraint (already exist in DB)")
        
        insert_records = deduped_records
        
        # Insert in batches
        # Track SSL error frequency for adaptive batch sizing
        ssl_error_count = 0
        current_batch_size = self.batch_size
        
        for chunk in self._chunks(insert_records, current_batch_size):
            # Enhanced retry logic: more retries for SSL errors, fewer for other errors
            max_retries = 5  # Increased from 3 for SSL errors
            retry_delay = 1.0
            inserted_chunk = False
            is_ssl_error = False
            
            for attempt in range(max_retries):
                try:
                    # Use Supabase insert with batch (returning='minimal' for performance)
                    result = self.supabase.table('games').insert(chunk, returning='minimal').execute()
                    
                    # Supabase Python client: if no exception is raised, insert succeeded
                    # With returning='minimal', result.data is typically [] or None
                    # No status_code attribute exists - success = no exception
                    inserted += len(chunk)
                    inserted_chunk = True
                    logger.info(f"✅ Successfully inserted batch of {len(chunk)} games")
                    
                    # Reset SSL error count on success
                    if is_ssl_error:
                        ssl_error_count = 0
                        # Gradually restore batch size after successful inserts
                        if current_batch_size < self.batch_size:
                            current_batch_size = min(current_batch_size + 500, self.batch_size)
                            logger.info(f"Restoring batch size to {current_batch_size} after successful insert")
                    break
                    
                except Exception as e:
                    import traceback
                    error_str = str(e).lower()
                    error_type = type(e).__name__
                    
                    logger.error(f"Exception during batch insert (attempt {attempt + 1}/{max_retries}): {error_type}: {str(e)}")
                    
                    # Check for duplicate/unique constraint violations
                    if 'duplicate' in error_str or 'unique' in error_str or '23505' in error_str:
                        # Duplicate key violation - fall back to individual inserts to save valid records
                        logger.warning(f"⚠️  Duplicate key violation in batch of {len(chunk)} games - falling back to individual inserts")

                        # Try inserting each record individually to save valid ones
                        individual_inserted = 0
                        individual_duplicates = 0

                        for record in chunk:
                            try:
                                self.supabase.table('games').insert(record, returning='minimal').execute()
                                individual_inserted += 1
                            except Exception as individual_e:
                                individual_error_str = str(individual_e).lower()
                                if 'duplicate' in individual_error_str or 'unique' in individual_error_str or '23505' in individual_error_str:
                                    individual_duplicates += 1
                                else:
                                    logger.debug(f"Individual insert failed: {individual_e}")

                        inserted += individual_inserted
                        duplicate_violations += individual_duplicates
                        self.metrics.duplicates_found += individual_duplicates

                        logger.info(f"✅ Fallback complete: {individual_inserted} inserted, {individual_duplicates} duplicates skipped")
                        inserted_chunk = True
                        break
                    elif '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                        # Rate limit error - wait longer and reduce batch size
                        logger.warning(f"⚠️  Rate limit hit (429) - reducing batch size and waiting longer")
                        if current_batch_size > 500:
                            new_batch_size = max(500, int(current_batch_size * 0.5))
                            logger.warning(f"Reducing batch size from {current_batch_size} to {new_batch_size} due to rate limit")
                            current_batch_size = new_batch_size
                        
                        # Longer wait for rate limits (60-120 seconds)
                        if attempt < max_retries - 1:
                            wait_time = 60 + (attempt * 20) + random.uniform(0, 10)  # 60s, 80s, 100s...
                            logger.warning(f"Rate limit error (attempt {attempt + 1}/{max_retries}), waiting {wait_time:.1f}s before retry...")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Rate limit error after {max_retries} attempts - consider reducing batch size further")
                            self.metrics.errors.append(f"Rate limit error (429) after {max_retries} attempts")
                            break
                    elif 'ssl' in error_str or 'sslv3' in error_str or 'bad record mac' in error_str or 'connection' in error_str or 'timeout' in error_str or 'forcibly closed' in error_str:
                        # Enhanced SSL/network error handling
                        is_ssl_error = True
                        ssl_error_count += 1
                        
                        # Reduce batch size if multiple SSL errors occur
                        if ssl_error_count >= 3 and current_batch_size > 500:
                            new_batch_size = max(500, int(current_batch_size * 0.7))
                            logger.warning(f"Reducing batch size from {current_batch_size} to {new_batch_size} due to SSL errors")
                            current_batch_size = new_batch_size
                        
                        # Retry with exponential backoff + jitter
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 0.5)  # Add jitter
                            logger.warning(f"SSL/Network error inserting batch (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.1f}s: {e}")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"SSL/Network error inserting batch after {max_retries} attempts: {e}")
                            self.metrics.errors.append(f"Batch insert SSL/network error (attempts: {max_retries}): {str(e)[:200]}")
                            # Try splitting batch in half if SSL error persists
                            if len(chunk) > 100:
                                logger.info(f"Attempting to split failed batch of {len(chunk)} games into smaller chunks")
                                mid = len(chunk) // 2
                                # Recursively try smaller batches (will be handled in next iteration)
                                # For now, just log and continue
                            break
                    elif 'null' in error_str and ('violates' in error_str or 'constraint' in error_str):
                        # NOT NULL constraint violation - log and skip batch
                        logger.error(f"❌ NOT NULL constraint violation: {str(e)}")
                        logger.error(f"Sample record: {chunk[0] if chunk else 'N/A'}")
                        self.metrics.errors.append(f"NOT NULL constraint violation: {str(e)[:200]}")
                        inserted_chunk = True  # Don't retry - fix the data first
                        break
                    else:
                        # Other errors - log and retry
                        logger.error(f"Error inserting batch (attempt {attempt + 1}/{max_retries}): {e}")
                        logger.error(f"Sample record from failed batch: {chunk[0] if chunk else 'No records'}")
                        logger.debug(f"Full traceback: {traceback.format_exc()}")
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            logger.warning(f"Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.metrics.errors.append(f"Batch insert error: {str(e)[:200]}")
                            break
            
            if not inserted_chunk:
                logger.warning(f"Failed to insert batch of {len(chunk)} games after retries")
            
            # Add delay between batches to avoid rate limits (especially for large imports)
            # Small delay helps prevent hitting Supabase API rate limits
            if inserted_chunk and len(insert_records) > 10000:  # Only for large imports
                time.sleep(0.1)  # 100ms delay between batches
        
        # Update metrics with duplicate violations
        if duplicate_violations > 0:
            self.metrics.duplicate_key_violations = duplicate_violations
            logger.info(f"📊 Summary: Inserted {inserted} new games, {duplicate_violations} were duplicates (already in DB)")
        
        return inserted
    
    async def _update_team_scrape_dates(self, game_records: List[Dict]):
        """
        Update last_scraped_at for teams based on scraped_at timestamps from imported games.
        
        This ensures that teams show as recently scraped even when importing from files,
        which helps the dashboard track which teams have recent data.
        
        Args:
            game_records: List of game records that were successfully inserted
        """
        if not game_records or self.dry_run:
            return
        
        try:
            # Extract unique team IDs and their most recent scraped_at timestamps
            team_scrape_dates: Dict[str, datetime] = {}
            
            for game in game_records:
                scraped_at_str = game.get('scraped_at')
                if not scraped_at_str:
                    continue
                
                # Parse scraped_at timestamp
                try:
                    # Handle ISO format with or without timezone
                    scraped_at = datetime.fromisoformat(scraped_at_str.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    try:
                        # Fallback: try parsing as standard format
                        scraped_at = datetime.strptime(scraped_at_str, '%Y-%m-%dT%H:%M:%S.%f')
                    except (ValueError, TypeError):
                        logger.debug(f"Could not parse scraped_at: {scraped_at_str}")
                        continue
                
                # Track most recent scraped_at for each team
                home_team_id = game.get('home_team_master_id')
                away_team_id = game.get('away_team_master_id')
                
                if home_team_id:
                    if home_team_id not in team_scrape_dates or scraped_at > team_scrape_dates[home_team_id]:
                        team_scrape_dates[home_team_id] = scraped_at
                
                if away_team_id:
                    if away_team_id not in team_scrape_dates or scraped_at > team_scrape_dates[away_team_id]:
                        team_scrape_dates[away_team_id] = scraped_at
            
            if not team_scrape_dates:
                logger.debug("No valid scraped_at timestamps found in imported games")
                return
            
            # Update teams.last_scraped_at in batches
            batch_size = 100
            updated_count = 0
            
            team_ids = list(team_scrape_dates.keys())
            for i in range(0, len(team_ids), batch_size):
                batch_ids = team_ids[i:i + batch_size]
                
                for team_id in batch_ids:
                    scraped_at = team_scrape_dates[team_id]
                    scraped_at_iso = scraped_at.isoformat()
                    
                    try:
                        # Update last_scraped_at for this team
                        self.supabase.table('teams').update({
                            'last_scraped_at': scraped_at_iso
                        }).eq('team_id_master', team_id).eq('provider_id', self.provider_id).execute()
                        updated_count += 1
                    except Exception as e:
                        logger.warning(f"Error updating last_scraped_at for team {team_id}: {e}")
            
            if updated_count > 0:
                logger.info(f"Updated last_scraped_at for {updated_count} teams based on imported games")
        
        except Exception as e:
            logger.warning(f"Error updating team scrape dates: {e}")
            # Don't fail the import if this step fails
    
    async def _process_team_matching_stats(self):
        """Process team matching statistics from alias map"""
        try:
            # Count direct ID matches
            direct_result = self.supabase.table('team_alias_map').select(
                'id', count='exact'
            ).eq('provider_id', self.provider_id).eq(
                'match_method', 'direct_id'
            ).eq('review_status', 'approved').execute()
            
            if hasattr(direct_result, 'count'):
                # Direct ID matches are tracked in teams_matched
                pass  # Already counted during import
            
            # Count fuzzy matches by confidence level
            # Auto-approved (>= 0.9)
            auto_result = self.supabase.table('team_alias_map').select(
                'id', count='exact'
            ).eq('provider_id', self.provider_id).eq(
                'match_method', 'fuzzy_auto'
            ).eq('review_status', 'approved').execute()
            
            if hasattr(auto_result, 'count'):
                self.metrics.fuzzy_matches_auto = auto_result.count or 0
            
            # Manual review (0.75-0.9)
            review_result = self.supabase.table('team_alias_map').select(
                'id', count='exact'
            ).eq('provider_id', self.provider_id).eq(
                'match_method', 'fuzzy_review'
            ).eq('review_status', 'pending').execute()
            
            if hasattr(review_result, 'count'):
                self.metrics.fuzzy_matches_manual = review_result.count or 0
            
            # Rejected matches would need to be tracked separately
            # For now, we'll estimate based on processing
            
        except Exception as e:
            logger.warning(f"Error processing team matching stats: {e}")
    
    async def _log_invalid_games(self, invalid_games: List[Dict]):
        """Log invalid games to quarantine table"""
        if not invalid_games or self.dry_run:
            return
        
        for game in invalid_games:
            try:
                self.supabase.table('quarantine_games').insert({
                    'raw_data': game,
                    'reason_code': 'validation_failed',
                    'error_details': '; '.join(game.get('validation_errors', []))
                }).execute()
            except Exception as e:
                logger.warning(f"Could not quarantine game: {e}")
    
    async def _log_build_metrics(self):
        """Log detailed metrics to build_logs table"""
        try:
            # Get or create build log entry
            build_log_data = {
                'build_id': self.build_id,
                'stage': 'game_import',
                'provider_id': self.provider_id,
                'parameters': {
                    'provider_code': self.provider_code,
                    'batch_size': self.batch_size,
                    'dry_run': self.dry_run
                },
                'started_at': datetime.now().isoformat(),
                'completed_at': datetime.now().isoformat(),
                'records_processed': self.metrics.games_processed,
                'records_succeeded': self.metrics.games_accepted,
                'records_failed': self.metrics.games_quarantined + self.metrics.duplicates_found,
                'errors': self.metrics.errors[:100],  # Limit stored errors
                'metrics': self.metrics.to_dict()
            }
            
            # Check if build log exists
            existing = self.supabase.table('build_logs').select('id').eq(
                'build_id', self.build_id
            ).eq('stage', 'game_import').execute()
            
            if existing.data:
                # Update existing
                self.supabase.table('build_logs').update(build_log_data).eq(
                    'build_id', self.build_id
                ).eq('stage', 'game_import').execute()
            else:
                # Create new
                self.supabase.table('build_logs').insert(build_log_data).execute()
                
        except Exception as e:
            logger.error(f"Error logging build metrics: {e}")
    
    def print_modular11_summary(self, metrics: ImportMetrics) -> None:
        """
        Print a clean structured summary for Modular11 imports.
        
        Includes:
        - Total games processed
        - Unique games, imported, duplicates
        - Teams matched, fuzzy matches, new teams
        - Age breakdown
        - Rejected fuzzy matches (top candidate only)
        - New teams created
        """
        if not hasattr(self.matcher, 'summary') or self.provider_code.lower() != 'modular11':
            return
        
        summary = self.matcher.summary
        
        print("\n" + "=" * 70)
        print("MODULAR11 IMPORT SUMMARY")
        print("=" * 70)
        
        # Game Statistics
        print("\nGAME STATISTICS:")
        print(f"  Total Games Processed: {metrics.games_processed:,}")
        unique_games = metrics.games_processed - metrics.duplicates_skipped
        print(f"  Unique Games: {unique_games:,}")
        print(f"  Imported: {metrics.games_accepted:,}")
        print(f"  Already in Database: {metrics.duplicates_found:,}")
        print(f"  Duplicates Skipped: {metrics.duplicates_skipped:,}")
        print(f"  Quarantined: {metrics.games_quarantined:,}")
        
        # Team Matching Statistics
        print("\nTEAM MATCHING:")
        print(f"  Total Teams Seen: {summary['processed']:,}")
        print(f"  Alias Matches: {summary['alias_matches']:,}")
        print(f"  Fuzzy Matches: {summary['fuzzy_matches']:,}")
        print(f"  New Teams Created: {summary['new_teams']:,}")
        print(f"  Review Queue Entries (Optional): {summary['review_queue']:,}")
        
        # Age Breakdown
        if summary['by_age']:
            print("\nBy Age:")
            for age in sorted(summary['by_age'].keys()):
                stats = summary['by_age'][age]
                matched = stats.get('matched', 0)
                new = stats.get('new', 0)
                print(f"  {age.upper()}: {new} created, {matched} matched")
        
        # Rejected Fuzzy Matches (top candidate only)
        if summary['fuzzy_reject_details']:
            print("\nFUZZY MATCHES REJECTED (Top Candidate Only):")
            for i, detail in enumerate(summary['fuzzy_reject_details'], 1):
                print(f"\n  {i}. {detail['incoming']}")
                print(f"     Age: {detail['age']}, Division: {detail.get('division', 'N/A')}")
                if detail.get('top_candidates') and len(detail['top_candidates']) > 0:
                    top = detail['top_candidates'][0]
                    div_info = f" (div: {top.get('division', 'N/A')})" if top.get('division') else ""
                    print(f"     Best Candidate: {top['team_name']}{div_info}")
                    print(f"       Score: {top['score']:.4f} (need >= 0.93)")
                    print(f"       Division Match: {'Yes' if top.get('division_match') else 'No'}")
                    print(f"       Token Overlap: {'Yes' if top.get('token_overlap') else 'No'}")
                    if detail.get('second_team'):
                        print(f"       Gap to 2nd: {detail.get('score_gap', 0):.4f} (need >= 0.07)")
                print(f"     Reason: {detail['reason']}")
        
        # New Teams Created
        if summary['new_team_details']:
            print("\nNEW TEAMS CREATED:")
            for i, detail in enumerate(summary['new_team_details'], 1):
                print(f"  {i}. {detail['clean_name']}")
                print(f"     ID: {detail['team_id']}")
                print(f"     Age: {detail['age']}, Division: {detail.get('division', 'N/A')}")
        
        # Accepted Fuzzy Matches
        if summary['fuzzy_details']:
            print("\nFUZZY MATCHES ACCEPTED:")
            for i, detail in enumerate(summary['fuzzy_details'], 1):
                print(f"  {i}. {detail['incoming']} → {detail['matched_team']}")
                print(f"     Score: {detail['score']:.4f}, Gap: {detail['gap']:.4f}")
                print(f"     Age: {detail['age']}, Division: {detail.get('division', 'N/A')}")
        
        print("\n" + "=" * 70 + "\n")
    
    @staticmethod
    def _chunks(lst: List, size: int):
        """Yield successive chunks from list"""
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

