"""Enhanced data validation for PitchRank imports"""
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime, date
import re
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from config.settings import AGE_GROUPS


def parse_game_date(date_str: str) -> date:
    """
    Parse game date from multiple formats (handles GotSport CSVs and standard formats).
    
    Supported formats:
    - YYYY-MM-DD (ISO format)
    - M/D/YYYY (US format, e.g., 7/13/2025)
    - M/D/YY (US format with 2-digit year, e.g., 7/13/25)
    
    Args:
        date_str: Date string in any supported format
        
    Returns:
        date object parsed from the date string
        
    Raises:
        ValueError: If date string doesn't match any supported format
    """
    date_str = str(date_str).strip()
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    raise ValueError(f"Invalid date format: {date_str}")


class EnhancedDataValidator:
    """Comprehensive data validation for imports with detailed error reporting"""
    
    def __init__(self):
        # Get valid age groups from config (convert keys to uppercase for compatibility)
        # U10-U18 tracked; birth years derived dynamically from current year
        _age_groups_lower = [age.lower() for age in AGE_GROUPS.keys()]
        self.valid_age_groups = frozenset(
            _age_groups_lower + [age.upper() for age in _age_groups_lower]
        )

        self.valid_genders = frozenset(['Male', 'Female', 'Boys', 'Girls', 'Coed'])
        
    def validate_team(self, team: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate team data with comprehensive checks"""
        errors = []
        
        # Required fields
        if not team.get('team_name') and not team.get('name'):
            errors.append("Team name is required")
        else:
            team_name = team.get('team_name') or team.get('name', '')
            if len(team_name) < 3:
                errors.append(f"Team name too short: '{team_name}' (minimum 3 characters)")
            elif len(team_name) > 100:
                errors.append(f"Team name too long: '{team_name}' (maximum 100 characters)")
        
        # Validate provider_team_id if provided
        if 'provider_team_id' in team and team['provider_team_id']:
            provider_id = str(team['provider_team_id']).strip()
            if len(provider_id) == 0:
                errors.append("provider_team_id cannot be empty")
        
        # Validate state code (if provided)
        if 'state_code' in team and team.get('state_code'):
            state_code = str(team['state_code']).strip()
            if not re.match(r'^[A-Z]{2}$', state_code):
                errors.append(f"Invalid state code: '{state_code}' (must be exactly 2 uppercase letters)")
        
        # Validate state name (if provided)
        if 'state' in team and team.get('state'):
            state = str(team['state']).strip()
            if len(state) < 2 or len(state) > 50:
                errors.append(f"Invalid state name length: '{state}' (must be 2-50 characters)")
        
        # Validate age group
        if 'age_group' in team and team.get('age_group'):
            age_group = str(team['age_group']).strip().lower()
            if age_group not in self.valid_age_groups:
                errors.append(f"Invalid age group: '{team['age_group']}' (must be one of {sorted(self.valid_age_groups)[:10]})")
        
        # Validate gender
        if 'gender' in team and team.get('gender'):
            gender = str(team['gender']).strip()
            if gender not in self.valid_genders:
                errors.append(f"Invalid gender: '{gender}' (must be one of {self.valid_genders})")
        
        # Validate club_name length if provided
        if 'club_name' in team and team.get('club_name'):
            club_name = str(team['club_name']).strip()
            if len(club_name) > 100:
                errors.append(f"Club name too long: '{club_name}' (maximum 100 characters)")
        
        return len(errors) == 0, errors
    
    def validate_game(self, game: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate game data with comprehensive checks.
        
        Handles source data format:
        - team_id, opponent_id, home_away, goals_for, goals_against
        
        Or transformed format:
        - home_team_id, away_team_id, home_score, away_score
        """
        errors = []
        
        # Check if this is source format (team_id/opponent_id) or transformed format
        has_source_format = 'team_id' in game and 'opponent_id' in game
        has_transformed_format = 'home_team_id' in game and 'away_team_id' in game
        
        if has_source_format:
            # Source format validation
            team_id = game.get('team_id')
            opponent_id = game.get('opponent_id')
            home_away = game.get('home_away')
            goals_for = game.get('goals_for')
            goals_against = game.get('goals_against')
            
            # Required fields for source format
            if not team_id:
                errors.append("Missing required field: team_id")
            elif not str(team_id).strip():
                errors.append("Empty team ID: team_id")
            
            if not opponent_id:
                errors.append("Missing required field: opponent_id")
            elif not str(opponent_id).strip():
                errors.append("Empty opponent ID: opponent_id")
            
            if not home_away:
                errors.append("Missing required field: home_away")
            elif home_away.upper() not in ['H', 'A']:
                errors.append(f"Invalid home_away value: '{home_away}' (must be 'H' or 'A')")
            
            if goals_for is None:
                errors.append("Missing required field: goals_for")
            
            if goals_against is None:
                errors.append("Missing required field: goals_against")
            
            if not game.get('game_date'):
                errors.append("Missing required field: game_date")
            
            if errors:
                return False, errors
            
            # Validate teams are different
            if str(team_id) == str(opponent_id):
                errors.append(f"Team and opponent cannot be the same: '{team_id}'")
            
            # Validate scores
            # Handle None, empty string, and string 'None' cases
            if goals_for is None or goals_for == '' or str(goals_for).strip().lower() == 'none':
                # Null scores are allowed (unknown result)
                pass
            else:
                try:
                    goals_for_int = int(float(goals_for))
                    if goals_for_int < 0:
                        errors.append(f"goals_for cannot be negative: {goals_for_int}")
                    if goals_for_int > 50:
                        errors.append(f"Unusually high goals_for detected: {goals_for_int} (verify data accuracy)")
                except (ValueError, TypeError):
                    errors.append(f"Scores must be integers: goals_for={goals_for}")
            
            if goals_against is None or goals_against == '' or str(goals_against).strip().lower() == 'none':
                # Null scores are allowed (unknown result)
                pass
            else:
                try:
                    goals_against_int = int(float(goals_against))
                    if goals_against_int < 0:
                        errors.append(f"goals_against cannot be negative: {goals_against_int}")
                    if goals_against_int > 50:
                        errors.append(f"Unusually high goals_against detected: {goals_against_int} (verify data accuracy)")
                except (ValueError, TypeError):
                    errors.append(f"Scores must be integers: goals_against={goals_against}")
        
        elif has_transformed_format:
            # Transformed format validation (legacy support)
            home_team_id = game.get('home_team_id') or game.get('home_provider_id')
            away_team_id = game.get('away_team_id') or game.get('away_provider_id')
            
            if not home_team_id:
                errors.append("Missing required field: home_team_id or home_provider_id")
            elif not str(home_team_id).strip():
                errors.append("Empty team ID: home_team_id")
            
            if not away_team_id:
                errors.append("Missing required field: away_team_id or away_provider_id")
            elif not str(away_team_id).strip():
                errors.append("Empty team ID: away_team_id")
            
            if 'home_score' not in game or game['home_score'] is None:
                errors.append("Missing required field: home_score")
            if 'away_score' not in game or game['away_score'] is None:
                errors.append("Missing required field: away_score")
            
            if not game.get('game_date'):
                errors.append("Missing required field: game_date")
            
            if errors:
                return False, errors
            
            # Validate teams are different
            if str(home_team_id) == str(away_team_id):
                errors.append(f"Home and away teams cannot be the same: '{home_team_id}'")
            
            # Validate scores
            try:
                home_score = int(game['home_score'])
                away_score = int(game['away_score'])
                
                if home_score < 0:
                    errors.append(f"Home score cannot be negative: {home_score}")
                if away_score < 0:
                    errors.append(f"Away score cannot be negative: {away_score}")
                
                if home_score > 50:
                    errors.append(f"Unusually high home score detected: {home_score} (verify data accuracy)")
                if away_score > 50:
                    errors.append(f"Unusually high away score detected: {away_score} (verify data accuracy)")
            except (ValueError, TypeError):
                errors.append(f"Scores must be integers: home_score={game.get('home_score')}, away_score={game.get('away_score')}")
        else:
            # Neither format found
            errors.append("Game must have either (team_id, opponent_id) or (home_team_id, away_team_id)")
            return False, errors
        
        if errors:  # Skip other validations if required fields missing
            return False, errors
        
        # Validate game_uid format (if present - may be generated later)
        if 'game_uid' in game and game.get('game_uid'):
            game_uid = str(game['game_uid']).strip()
            if not re.match(r'^[\w\-:]{10,}$', game_uid):
                errors.append(f"Invalid game_uid format: '{game_uid}' (must be at least 10 alphanumeric characters, dashes, colons, or underscores)")
        
        # Validate date (common for both formats)
        try:
            game_date_str = str(game['game_date']).strip()
            game_date = parse_game_date(game_date_str)
            
            # Check date is reasonable (not too far in past or future)
            if game_date.year < 2000:
                errors.append(f"Game date too far in past: {game_date_str} (year must be >= 2000)")
            elif game_date > datetime.now().date():
                # Allow up to 1 day in the future for scheduled games
                if (game_date - datetime.now().date()).days > 1:
                    errors.append(f"Game date too far in future: {game_date_str} (must be within 1 day of today)")
                    
        except ValueError as e:
            errors.append(f"Invalid date format: '{game_date_str}' - {str(e)}")
        
        # Validate age group and gender if provided
        if 'age_group' in game and game.get('age_group'):
            age_group = str(game['age_group']).strip().lower()
            if age_group not in self.valid_age_groups:
                errors.append(f"Invalid age group: '{game['age_group']}' (must be one of {sorted(self.valid_age_groups)[:10]})")
                
        if 'gender' in game and game.get('gender'):
            gender = str(game['gender']).strip()
            if gender not in self.valid_genders:
                errors.append(f"Invalid gender: '{gender}' (must be one of {self.valid_genders})")
        
        # Validate state codes if provided
        if 'state_code' in game and game.get('state_code'):
            state_code = str(game['state_code']).strip()
            if not re.match(r'^[A-Z]{2}$', state_code):
                errors.append(f"Invalid state code: '{state_code}' (must be exactly 2 uppercase letters)")
        
        return len(errors) == 0, errors
    
    def validate_import_batch(self, items: List[Dict[str, Any]], 
                            item_type: str = 'game') -> Dict[str, Any]:
        """Validate a batch of items and return summary"""
        valid_items = []
        invalid_items = []
        
        validator = self.validate_game if item_type == 'game' else self.validate_team
        
        for item in items:
            is_valid, errors = validator(item)
            if is_valid:
                valid_items.append(item)
            else:
                item_copy = item.copy()
                item_copy['validation_errors'] = errors
                invalid_items.append(item_copy)
        
        total = len(items)
        valid_count = len(valid_items)
        invalid_count = len(invalid_items)
        
        return {
            'valid': valid_items,
            'invalid': invalid_items,
            'summary': {
                'total': total,
                'valid_count': valid_count,
                'invalid_count': invalid_count,
                'validation_rate': valid_count / total if total > 0 else 0.0
            }
        }

