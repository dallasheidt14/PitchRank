"""Test suite for enhanced ETL pipeline"""
import pytest
import asyncio
from datetime import datetime, timedelta
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
        valid, invalid = await pipeline._validate_games(games)
        
        assert len(valid) == 2
        assert len(invalid) == 1
        assert 'validation_errors' in invalid[0]
    
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
        
        # Test future date (beyond 1 day)
        future_date = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
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


# Run with: pytest tests/test_enhanced_pipeline.py -v

