"""Test suite for enhanced ETL pipeline"""
import pytest
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict

# Import the modules we're testing
from src.etl.enhanced_pipeline import EnhancedETLPipeline, ImportMetrics
from src.utils.enhanced_validators import EnhancedDataValidator


class TestEnhancedPipeline:
    """Test suite for enhanced ETL pipeline"""
    
    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase client"""
        supabase = Mock()
        
        # Mock provider lookup
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        
        # Mock table operations
        supabase.table.return_value.insert.return_value.execute.return_value.data = []
        supabase.table.return_value.select.return_value.execute.return_value.data = []
        supabase.table.return_value.select.return_value.count = 0
        supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
        
        return supabase
    
    @pytest.fixture
    def sample_games(self):
        """Sample game data for testing"""
        return [
            {
                'game_uid': 'test-001',
                'home_team_id': 'team-a',
                'away_team_id': 'team-b',
                'home_provider_id': 'team-a',
                'away_provider_id': 'team-b',
                'game_date': '2024-01-15',
                'home_score': 2,
                'away_score': 1,
                'age_group': 'u14',
                'gender': 'Male',
                'provider': 'gotsport'
            },
            {
                'game_uid': 'test-002',
                'home_team_id': 'team-c',
                'away_team_id': 'team-d',
                'home_provider_id': 'team-c',
                'away_provider_id': 'team-d',
                'game_date': '2024-01-16',
                'home_score': 3,
                'away_score': 3,
                'age_group': 'u14',
                'gender': 'Female',
                'provider': 'gotsport'
            }
        ]
    
    @pytest.mark.asyncio
    async def test_game_validation(self, mock_supabase, sample_games):
        """Test game validation logic"""
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        
        # Add invalid game
        invalid_game = {
            'game_uid': 'invalid-001',
            'home_team_id': 'team-a',
            # Missing away_team_id
            'game_date': '2024-01-15',
            'home_score': -1,  # Invalid negative score
            'away_score': 1
        }
        
        games = sample_games + [invalid_game]
        valid, invalid, stats = await pipeline._validate_games(games)

        assert len(valid) == 2
        assert len(invalid) == 1
        assert 'validation_errors' in invalid[0]
        assert 'duplicates_skipped' in stats
    
    @pytest.mark.asyncio
    async def test_duplicate_detection(self, mock_supabase, sample_games):
        """Test duplicate game detection"""
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        
        # Mock existing games
        mock_result = Mock()
        mock_result.data = [{'game_uid': 'test-001'}]
        mock_supabase.table.return_value.select.return_value.in_.return_value.execute.return_value = mock_result
        
        duplicates = await pipeline._check_duplicates(sample_games)
        
        assert len(duplicates) == 1
        assert 'test-001' in duplicates
    
    @pytest.mark.asyncio
    async def test_bulk_insert_performance(self, mock_supabase):
        """Test bulk insert handles large batches"""
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=False)
        pipeline.batch_size = 100
        
        # Create 1000 games
        large_game_set = []
        for i in range(1000):
            large_game_set.append({
                'game_uid': f'perf-{i:04d}',
                'home_team_master_id': f'team-{i % 50}',
                'away_team_master_id': f'team-{(i + 1) % 50}',
                'home_provider_id': f'team-{i % 50}',
                'away_provider_id': f'team-{(i + 1) % 50}',
                'game_date': '2024-01-15',
                'home_score': i % 5,
                'away_score': (i + 1) % 5,
                'provider_id': 'test-provider-uuid'
            })
        
        # Mock insert result
        mock_result = Mock()
        mock_result.data = [{'id': f'game-{i}'} for i in range(100)]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_result
        
        count = await pipeline._bulk_insert_games(large_game_set)
        
        # Verify batching worked (should be called multiple times)
        assert mock_supabase.table.return_value.insert.called
    
    def test_metrics_to_dict(self):
        """Test metrics conversion to dictionary"""
        metrics = ImportMetrics()
        metrics.games_processed = 100
        metrics.games_accepted = 95
        metrics.games_quarantined = 5
        metrics.processing_time_seconds = 45.2
        
        result = metrics.to_dict()
        
        assert result['games_processed'] == 100
        assert result['games_accepted'] == 95
        assert result['games_quarantined'] == 5
        assert result['processing_time_seconds'] == 45.2

    def test_should_log_modular11_game_details_is_disabled_for_summary_only(self, mock_supabase):
        """Per-game Modular11 logging should be suppressed in summary-only mode."""
        pipeline = EnhancedETLPipeline(mock_supabase, 'modular11', dry_run=True, summary_only=True)

        assert pipeline._should_log_modular11_game_details() is False

    def test_should_log_modular11_game_details_is_enabled_for_default_modular11_runs(self, mock_supabase):
        """Default Modular11 runs should still emit per-game details."""
        pipeline = EnhancedETLPipeline(mock_supabase, 'modular11', dry_run=True, summary_only=False)

        assert pipeline._should_log_modular11_game_details() is True


class TestEnhancedValidator:
    """Test suite for enhanced validators"""
    
    def test_validate_game_edge_cases(self):
        """Test various edge cases"""
        validator = EnhancedDataValidator()
        
        # Test same team playing itself
        is_valid, errors = validator.validate_game({
            'game_uid': 'edge-001',
            'home_team_id': 'team-a',
            'away_team_id': 'team-a',  # Same as home
            'home_provider_id': 'team-a',
            'away_provider_id': 'team-a',
            'game_date': '2024-01-15',
            'home_score': 2,
            'away_score': 1
        })
        
        assert not is_valid
        assert any('cannot be the same' in err.lower() for err in errors)
        
        # Test future date beyond the 365-day scheduling window (typo guard).
        future_date = (datetime.now() + timedelta(days=400)).strftime('%Y-%m-%d')
        is_valid, errors = validator.validate_game({
            'game_uid': 'edge-002',
            'home_team_id': 'team-a',
            'away_team_id': 'team-b',
            'home_provider_id': 'team-a',
            'away_provider_id': 'team-b',
            'game_date': future_date,
            'home_score': 0,
            'away_score': 0
        })
        
        assert not is_valid
        assert any('future' in err.lower() for err in errors)
        
        # Test unusually high score
        is_valid, errors = validator.validate_game({
            'game_uid': 'edge-003',
            'home_team_id': 'team-a',
            'away_team_id': 'team-b',
            'home_provider_id': 'team-a',
            'away_provider_id': 'team-b',
            'game_date': '2024-01-15',
            'home_score': 75,
            'away_score': 0
        })
        
        assert not is_valid
        assert any('high score' in err.lower() for err in errors)
    
    def test_validate_team_comprehensive(self):
        """Test comprehensive team validation"""
        validator = EnhancedDataValidator()
        
        # Valid team
        is_valid, errors = validator.validate_team({
            'team_name': 'FC United',
            'provider_team_id': '12345',
            'age_group': 'u14',
            'gender': 'Male',
            'state_code': 'CA'
        })
        assert is_valid
        assert len(errors) == 0
        
        # Invalid team name (too short)
        is_valid, errors = validator.validate_team({
            'team_name': 'FC',
            'provider_team_id': '12345'
        })
        assert not is_valid
        assert any('too short' in err.lower() for err in errors)
        
        # Invalid age group
        is_valid, errors = validator.validate_team({
            'team_name': 'FC United',
            'provider_team_id': '12345',
            'age_group': 'invalid'
        })
        assert not is_valid
        assert any('age group' in err.lower() for err in errors)
    
    def test_validate_batch(self):
        """Test batch validation"""
        validator = EnhancedDataValidator()
        
        games = [
            {
                'game_uid': 'valid-001',
                'home_team_id': 'team-a',
                'away_team_id': 'team-b',
                'home_provider_id': 'team-a',
                'away_provider_id': 'team-b',
                'game_date': '2024-01-15',
                'home_score': 2,
                'away_score': 1
            },
            {
                'game_uid': 'invalid-001',
                'home_team_id': 'team-a',
                # Missing away_team_id
                'game_date': '2024-01-15',
                'home_score': 2,
                'away_score': 1
            }
        ]
        
        result = validator.validate_import_batch(games, 'game')
        
        assert result['summary']['total'] == 2
        assert result['summary']['valid_count'] == 1
        assert result['summary']['invalid_count'] == 1
        assert result['summary']['validation_rate'] == 0.5


class TestBackfillDuplicateTeamLinks:
    """Tests for _backfill_duplicate_team_links healing NULL master IDs."""

    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase client sufficient for pipeline construction."""
        supabase = Mock()

        # Provider lookup
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result

        # General table mocks
        supabase.table.return_value.insert.return_value.execute.return_value.data = []
        supabase.table.return_value.select.return_value.execute.return_value.data = []
        supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
        # Health check
        supabase.table.return_value.select.return_value.limit.return_value.execute.return_value.data = []
        # Range for alias cache pagination
        supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.range.return_value.execute.return_value.data = []

        return supabase

    def _build_pipeline(self, supabase, dry_run=False):
        return EnhancedETLPipeline(supabase, 'gotsport', dry_run=dry_run)

    @pytest.mark.asyncio
    async def test_backfill_heals_null_home_master_id(self, mock_supabase):
        """Existing row has NULL home_team_master_id; candidate has it resolved."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=False)

        existing_row = {
            'id': 'row-1',
            'game_uid': 'gs:2026-02-20:499398:123',
            'home_team_master_id': None,
            'away_team_master_id': 'away-master-1',
        }

        # Mock: lookup by game_uid returns the existing row
        select_mock = Mock()
        select_mock.data = [existing_row]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = select_mock

        update_mock = Mock()
        update_mock.data = [{'id': 'row-1'}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = update_mock

        candidates = [{
            'game_uid': 'gs:2026-02-20:499398:123',
            'home_team_master_id': '9017bed1-af58-4303-abe9-f10d2551693f',
            'away_team_master_id': 'away-master-1',
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 1
        # Verify update was called with only the missing field
        mock_supabase.table.return_value.update.assert_called_once_with(
            {'home_team_master_id': '9017bed1-af58-4303-abe9-f10d2551693f'}
        )

    @pytest.mark.asyncio
    async def test_backfill_heals_both_null_master_ids(self, mock_supabase):
        """Existing row has both master IDs NULL; candidate has both resolved."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=False)

        existing_row = {
            'id': 'row-2',
            'game_uid': 'gs:2026-02-21:499398:456',
            'home_team_master_id': None,
            'away_team_master_id': None,
        }

        select_mock = Mock()
        select_mock.data = [existing_row]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = select_mock

        update_mock = Mock()
        update_mock.data = [{'id': 'row-2'}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = update_mock

        candidates = [{
            'game_uid': 'gs:2026-02-21:499398:456',
            'home_team_master_id': 'home-master-2',
            'away_team_master_id': 'away-master-2',
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 1
        mock_supabase.table.return_value.update.assert_called_once_with(
            {'home_team_master_id': 'home-master-2', 'away_team_master_id': 'away-master-2'}
        )

    @pytest.mark.asyncio
    async def test_backfill_does_not_overwrite_existing_ids(self, mock_supabase):
        """Existing row already has both master IDs — no update should occur."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=False)

        existing_row = {
            'id': 'row-3',
            'game_uid': 'gs:2026-02-20:111:222',
            'home_team_master_id': 'existing-home',
            'away_team_master_id': 'existing-away',
        }

        select_mock = Mock()
        select_mock.data = [existing_row]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = select_mock

        candidates = [{
            'game_uid': 'gs:2026-02-20:111:222',
            'home_team_master_id': 'different-home',
            'away_team_master_id': 'different-away',
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 0
        mock_supabase.table.return_value.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfill_skipped_in_dry_run(self, mock_supabase):
        """Dry-run mode must not write anything."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=True)

        candidates = [{
            'game_uid': 'gs:2026-02-20:499398:123',
            'home_team_master_id': 'some-master',
            'away_team_master_id': None,
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 0
        mock_supabase.table.return_value.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfill_skipped_for_modular11(self, mock_supabase):
        """Modular11 must never run duplicate-link backfill writes."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=False)
        pipeline.provider_code = 'modular11'

        candidates = [{
            'game_uid': 'modular11:2026-02-20:74:249:U14:HD',
            'home_team_master_id': 'home-master',
            'away_team_master_id': 'away-master',
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 0
        mock_supabase.table.return_value.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfill_no_insert_occurs(self, mock_supabase):
        """Backfill must never insert new rows — only update existing ones."""
        pipeline = self._build_pipeline(mock_supabase, dry_run=False)

        existing_row = {
            'id': 'row-4',
            'game_uid': 'gs:2026-02-20:777:888',
            'home_team_master_id': None,
            'away_team_master_id': 'existing-away',
        }

        select_mock = Mock()
        select_mock.data = [existing_row]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = select_mock

        update_mock = Mock()
        update_mock.data = [{'id': 'row-4'}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = update_mock

        candidates = [{
            'game_uid': 'gs:2026-02-20:777:888',
            'home_team_master_id': 'new-home-master',
            'away_team_master_id': 'different-away',  # should NOT overwrite existing
        }]

        count = await pipeline._backfill_duplicate_team_links(candidates)

        assert count == 1
        # Only home_team_master_id should be updated (away already exists)
        mock_supabase.table.return_value.update.assert_called_once_with(
            {'home_team_master_id': 'new-home-master'}
        )
        # Verify no insert was called
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_metrics_includes_backfill_field(self):
        """ImportMetrics.to_dict() must include duplicate_links_backfilled."""
        metrics = ImportMetrics()
        metrics.duplicate_links_backfilled = 5
        result = metrics.to_dict()
        assert result['duplicate_links_backfilled'] == 5


class TestFutureDateHelper:
    """Tests for the _is_future_game helper used by the scheduled-game carveout."""

    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    def _make_pipeline(self, mock_supabase):
        return EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)

    def test_future_date_returns_true(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        future = (date.today() + timedelta(days=7)).isoformat()
        assert pipeline._is_future_game({"game_date": future}) is True

    def test_today_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        today = date.today().isoformat()
        assert pipeline._is_future_game({"game_date": today}) is False

    def test_past_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        past = (date.today() - timedelta(days=7)).isoformat()
        assert pipeline._is_future_game({"game_date": past}) is False

    def test_missing_game_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        assert pipeline._is_future_game({}) is False

    def test_unparseable_date_returns_false(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        assert pipeline._is_future_game({"game_date": "not-a-date"}) is False


class TestShouldAcceptForInsert:
    """Tests for _should_accept_for_insert and its interaction with _has_valid_scores."""

    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    def _make_pipeline(self, mock_supabase):
        return EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)

    def test_has_valid_scores_rejects_past_null(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        past_game = {
            "game_uid": "past-null-001",
            "game_date": (date.today() - timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._has_valid_scores(past_game) is False

    def test_should_accept_for_insert_keeps_future_null(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        future_game = {
            "game_uid": "future-null-001",
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(future_game) is True

    def test_should_accept_for_insert_rejects_past_null(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        past_game = {
            "game_uid": "past-null-002",
            "game_date": (date.today() - timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(past_game) is False

    def test_should_accept_for_insert_keeps_played_game(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        played = {
            "game_uid": "played-001",
            "game_date": (date.today() - timedelta(days=2)).isoformat(),
            "home_score": 2,
            "away_score": 1,
        }
        assert pipeline._should_accept_for_insert(played) is True

    def test_should_accept_for_insert_rejects_today_null(self, mock_supabase):
        """Today's NULL-score games are score-entry lag, not scheduled — reject."""
        pipeline = self._make_pipeline(mock_supabase)
        today_game = {
            "game_uid": "today-null-001",
            "game_date": date.today().isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(today_game) is False


class TestValidateAndDedupFutureCarveout:
    """Verify the NULL-score filter carveout for future-dated (scheduled) games."""

    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    @pytest.mark.asyncio
    async def test_future_scoreless_game_passes_filter(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        future_date = (date.today() + timedelta(days=14)).isoformat()
        games = [{
            "game_uid": "future-001",
            "team_id": "team-a",
            "opponent_id": "team-b",
            "game_date": future_date,
            "goals_for": None,
            "goals_against": None,
            "provider": "gotsport",
            "home_away": "H",
        }]
        valid, invalid, stats = await pipeline._validate_and_dedup(games, run_validation=False)
        assert stats["skipped_empty_scores"] == 0
        assert len(valid) == 1

    @pytest.mark.asyncio
    async def test_past_scoreless_game_still_skipped(self, mock_supabase):
        pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
        past_date = (date.today() - timedelta(days=7)).isoformat()
        games = [{
            "game_uid": "past-001",
            "team_id": "team-a",
            "opponent_id": "team-b",
            "game_date": past_date,
            "goals_for": None,
            "goals_against": None,
            "provider": "gotsport",
            "home_away": "H",
        }]
        valid, invalid, stats = await pipeline._validate_and_dedup(games, run_validation=False)
        assert stats["skipped_empty_scores"] == 1
        assert len(valid) == 0


class TestScheduledGameValidatorCarveout:
    """validate_game must accept future-dated NULL-score games (scheduled)
    and still reject past-dated NULL-score games and partial-score games."""

    def _validator(self):
        return EnhancedDataValidator()

    def _scheduled_source(self, future_days=7):
        return {
            "team_id": "team-a",
            "opponent_id": "team-b",
            "home_away": "H",
            "goals_for": None,
            "goals_against": None,
            "game_date": (date.today() + timedelta(days=future_days)).isoformat(),
            "game_uid": "sched-source-0001",
        }

    def _scheduled_transformed(self, future_days=7):
        return {
            "home_team_id": "team-a",
            "away_team_id": "team-b",
            "home_score": None,
            "away_score": None,
            "game_date": (date.today() + timedelta(days=future_days)).isoformat(),
            "game_uid": "sched-trans-0001",
        }

    def test_source_format_scheduled_game_validates(self):
        is_valid, errors = self._validator().validate_game(self._scheduled_source())
        assert is_valid, f"Scheduled source-format game rejected: {errors}"

    def test_transformed_format_scheduled_game_validates(self):
        is_valid, errors = self._validator().validate_game(self._scheduled_transformed())
        assert is_valid, f"Scheduled transformed-format game rejected: {errors}"

    def test_past_dated_null_scores_still_rejected_source(self):
        game = self._scheduled_source()
        game["game_date"] = (date.today() - timedelta(days=7)).isoformat()
        is_valid, errors = self._validator().validate_game(game)
        assert not is_valid
        assert any("goals_for" in e or "goals_against" in e for e in errors)

    def test_past_dated_null_scores_still_rejected_transformed(self):
        game = self._scheduled_transformed()
        game["game_date"] = (date.today() - timedelta(days=7)).isoformat()
        is_valid, errors = self._validator().validate_game(game)
        assert not is_valid
        assert any("home_score" in e or "away_score" in e for e in errors)

    def test_partial_score_future_still_rejected_source(self):
        """One score present, the other None — not a scheduled-game shape."""
        game = self._scheduled_source()
        game["goals_for"] = 2  # partial
        is_valid, errors = self._validator().validate_game(game)
        assert not is_valid
        assert any("goals_against" in e for e in errors)

    def test_partial_score_future_still_rejected_transformed(self):
        game = self._scheduled_transformed()
        game["home_score"] = 2  # partial
        is_valid, errors = self._validator().validate_game(game)
        assert not is_valid
        assert any("away_score" in e for e in errors)


class TestShouldAcceptForInsertStrictness:
    """_should_accept_for_insert must reject partial-score or malformed
    future-dated rows even though _has_valid_scores returns False on them."""

    @pytest.fixture
    def mock_supabase(self):
        supabase = Mock()
        provider_result = Mock()
        provider_result.data = {'id': 'test-provider-uuid'}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        return supabase

    def _make_pipeline(self, mock_supabase):
        return EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)

    def test_future_partial_score_rejected(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        game = {
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": 2,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(game) is False

    def test_future_malformed_score_rejected(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        game = {
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": "abc",
            "away_score": "xyz",
        }
        assert pipeline._should_accept_for_insert(game) is False

    def test_future_both_null_accepted(self, mock_supabase):
        pipeline = self._make_pipeline(mock_supabase)
        game = {
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": None,
            "away_score": None,
        }
        assert pipeline._should_accept_for_insert(game) is True

    def test_future_empty_string_scores_accepted(self, mock_supabase):
        """Empty strings count as empty per _is_empty_score — treat as scheduled."""
        pipeline = self._make_pipeline(mock_supabase)
        game = {
            "game_date": (date.today() + timedelta(days=7)).isoformat(),
            "home_score": "",
            "away_score": "",
        }
        assert pipeline._should_accept_for_insert(game) is True


# Run with: pytest tests/test_enhanced_pipeline.py -v

