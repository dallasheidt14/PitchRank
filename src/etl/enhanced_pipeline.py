"""Enhanced ETL Pipeline with metrics tracking and bulk operations"""
import asyncio
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
import logging
from dataclasses import dataclass, field
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from supabase import Client
from config.settings import MATCHING_CONFIG, BUILD_ID
from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import EnhancedDataValidator

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
            'errors': self.errors
        }


class EnhancedETLPipeline:
    """Enhanced ETL pipeline with bulk operations, validation, and metrics tracking"""
    
    def __init__(self, supabase: Client, provider_code: str, dry_run: bool = False):
        self.supabase = supabase
        self.provider_code = provider_code
        self.dry_run = dry_run
        self.metrics = ImportMetrics()
        self.batch_size = 1000
        self.validator = EnhancedDataValidator()
        self.matcher = GameHistoryMatcher(supabase)
        self.build_id = BUILD_ID
        
        # Get provider UUID
        try:
            result = self.supabase.table('providers').select('id').eq(
                'code', provider_code
            ).single().execute()
            self.provider_id = result.data['id']
        except Exception as e:
            logger.error(f"Provider not found: {provider_code}")
            raise ValueError(f"Provider not found: {provider_code}") from e
        
    async def import_games(self, games: List[Dict], provider_code: Optional[str] = None) -> ImportMetrics:
        """
        Import games with bulk operations, validation, and metrics tracking
        
        Args:
            games: List of game dictionaries
            provider_code: Optional provider code override
            
        Returns:
            ImportMetrics object with detailed statistics
        """
        start_time = datetime.now()
        
        try:
            # Step 1: Validate all games
            valid_games, invalid_games = await self._validate_games(games)
            self.metrics.games_processed = len(games)
            self.metrics.games_quarantined = len(invalid_games)
            
            # Log invalid games for review
            if invalid_games:
                await self._log_invalid_games(invalid_games)
            
            # Step 2: Check for duplicates
            existing_uids = await self._check_duplicates(valid_games)
            self.metrics.duplicates_found = len(existing_uids)
            
            # Filter out duplicates (enforce immutability)
            new_games = [g for g in valid_games if g.get('game_uid') not in existing_uids]
            
            # Step 3: Match teams and prepare game records
            game_records = []
            for game in new_games:
                try:
                    # Match game history to get structured game record
                    matched_game = self.matcher.match_game_history(game)
                    if matched_game.get('match_status') == 'matched':
                        game_records.append(matched_game)
                        self.metrics.teams_matched += 2  # Home and away
                    elif matched_game.get('match_status') == 'partial':
                        game_records.append(matched_game)
                        self.metrics.teams_matched += 1
                except Exception as e:
                    logger.warning(f"Error matching game: {e}")
                    self.metrics.errors.append(f"Match error: {str(e)}")
            
            # Step 4: Bulk insert games
            if game_records and not self.dry_run:
                inserted_count = await self._bulk_insert_games(game_records)
                self.metrics.games_accepted = inserted_count
            elif self.dry_run:
                self.metrics.games_accepted = len(game_records)
                logger.info("Dry run mode - games not inserted")
            
            # Step 5: Process team matching statistics
            await self._process_team_matching_stats()
            
            # Step 6: Calculate processing time
            self.metrics.processing_time_seconds = (
                datetime.now() - start_time
            ).total_seconds()
            
            # Step 7: Log build metrics
            await self._log_build_metrics()
            
            if self.dry_run:
                logger.info("Dry run completed - no changes committed")
            else:
                logger.info(f"Import completed: {self.metrics.games_accepted} games imported")
            
            return self.metrics
            
        except Exception as e:
            self.metrics.errors.append(str(e))
            logger.error(f"Import failed: {e}")
            await self._log_build_metrics()  # Log partial metrics
            raise
            
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
        
        for game in games:
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
            game_date = game.get('game_date', '')
            team1_id = str(game.get('team_id', ''))
            team2_id = str(game.get('opponent_id', ''))
            
            # Sort team IDs for consistent key (order doesn't matter)
            sorted_teams = sorted([team1_id, team2_id])
            game_key = f"{provider_code}:{game_date}:{sorted_teams[0]}:{sorted_teams[1]}"
            
            # Check if we've seen this game before
            if game_key in seen_games:
                # Duplicate found - validate dates match
                existing_game = seen_games[game_key]
                existing_date = existing_game.get('game_date', '')
                current_date = game_date
                
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
            
            # Generate game_uid for the transformed game
            from src.models.game_matcher import GameHistoryMatcher
            game_uid = GameHistoryMatcher.generate_game_uid(
                provider=provider_code,
                game_date=game_date,
                team1_id=sorted_teams[0],
                team2_id=sorted_teams[1]
            )
            transformed_game['game_uid'] = game_uid
            
            # First occurrence - store it
            seen_games[game_key] = transformed_game
            valid.append(transformed_game)
        
        # Update metrics
        self.metrics.duplicates_skipped = duplicates_skipped
        if date_mismatches > 0:
            logger.warning(f"Found {date_mismatches} games with date mismatches between perspectives")
            self.metrics.errors.append(f"{date_mismatches} games had date mismatches")
        
        logger.info(
            f"Validation complete: {len(valid)} unique games, "
            f"{duplicates_skipped} duplicates skipped, "
            f"{len(invalid)} invalid"
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
        
        # Create transformed game record
        transformed = game.copy()
        transformed['home_team_id'] = home_team_id
        transformed['away_team_id'] = away_team_id
        transformed['home_provider_id'] = home_team_id  # For provider ID lookup
        transformed['away_provider_id'] = away_team_id
        transformed['home_score'] = home_score
        transformed['away_score'] = away_score
        
        # Keep original fields for reference
        transformed['_source_team_id'] = team_id
        transformed['_source_opponent_id'] = opponent_id
        transformed['_source_home_away'] = home_away
        
        return transformed
    
    async def _check_duplicates(self, games: List[Dict]) -> set:
        """Check for existing game UIDs"""
        if not games:
            return set()
        
        # Extract game UIDs
        game_uids = [g.get('game_uid') for g in games if g.get('game_uid')]
        
        if not game_uids:
            return set()
        
        # Check in batches to avoid query size limits
        existing = set()
        for chunk in self._chunks(game_uids, 1000):
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
            return 0
        
        inserted = 0
        
        # Prepare game records for insertion
        insert_records = []
        for game in game_records:
            # Ensure all required fields are present
            record = {
                'game_uid': game.get('game_uid'),
                'home_team_master_id': game.get('home_team_master_id'),
                'away_team_master_id': game.get('away_team_master_id'),
                'home_provider_id': game.get('home_provider_id', ''),
                'away_provider_id': game.get('away_provider_id', ''),
                'home_score': game.get('home_score'),
                'away_score': game.get('away_score'),
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
            insert_records.append(record)
        
        # Insert in batches
        for chunk in self._chunks(insert_records, self.batch_size):
            try:
                # Use Supabase insert with batch
                result = self.supabase.table('games').insert(chunk).execute()
                if result.data:
                    inserted += len(result.data)
            except Exception as e:
                error_str = str(e).lower()
                if 'duplicate' in error_str or 'unique' in error_str:
                    # Handle duplicates individually
                    for record in chunk:
                        try:
                            self.supabase.table('games').insert(record).execute()
                            inserted += 1
                        except:
                            pass  # Skip if still duplicate
                else:
                    logger.error(f"Error inserting batch: {e}")
                    self.metrics.errors.append(f"Batch insert error: {str(e)}")
        
        return inserted
    
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
    
    @staticmethod
    def _chunks(lst: List, size: int):
        """Yield successive chunks from list"""
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

