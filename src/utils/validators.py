"""Data validation for PitchRank"""
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import re

from src.base import BaseValidator
from src.utils.enhanced_validators import parse_game_date

class GameValidator(BaseValidator):
    """Validate game data"""
    
    def validate(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """Validate game data"""
        errors = []
        
        # Required fields
        required = ['provider', 'team_id', 'opponent_id', 'game_date']
        for field in required:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
                
        # Validate date format
        if 'game_date' in data:
            try:
                parse_game_date(data['game_date'])
            except ValueError:
                errors.append(f"Invalid date format: {data['game_date']}")
                
        # Validate scores
        for field in ['goals_for', 'goals_against']:
            if field in data and data[field] is not None:
                try:
                    score = int(data[field])
                    if score < 0:
                        errors.append(f"Invalid score: {field} = {score}")
                except (ValueError, TypeError):
                    errors.append(f"Invalid score format: {field} = {data[field]}")
                    
        # Validate result
        if 'result' in data and data['result'] not in ['W', 'L', 'D', 'U', None]:
            errors.append(f"Invalid result: {data['result']}")
            
        return len(errors) == 0, '; '.join(errors) if errors else None

class TeamValidator(BaseValidator):
    """Validate team data"""
    
    def validate(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """Validate team data"""
        errors = []
        
        # Required fields
        required = ['team_name', 'provider_team_id']
        for field in required:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
                
        # Validate age group
        if 'age_group' in data:
            if not re.match(r'^u\d{2}$', data['age_group']):
                errors.append(f"Invalid age group format: {data['age_group']}")
                
        # Validate gender
        if 'gender' in data and data['gender'] not in ['Male', 'Female']:
            errors.append(f"Invalid gender: {data['gender']}")
            
        # Validate state code
        if 'state_code' in data and len(data.get('state_code') or '') != 2:
            errors.append(f"Invalid state code: {data['state_code']}")
            
        return len(errors) == 0, '; '.join(errors) if errors else None