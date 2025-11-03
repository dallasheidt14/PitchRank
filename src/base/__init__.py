"""Base classes for PitchRank components"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TeamData:
    """Standardized team data structure"""
    provider_id: str
    provider_team_id: str
    name: str
    club: Optional[str]
    state: Optional[str]
    age_group: str
    gender: str
    meta: Dict = None

@dataclass
class GameData:
    """Standardized game data structure"""
    provider_id: str
    team_id: str
    opponent_id: str
    team_name: str
    opponent_name: str
    game_date: str
    home_away: str
    goals_for: Optional[int]
    goals_against: Optional[int]
    result: Optional[str]
    competition: Optional[str]
    venue: Optional[str]
    meta: Dict = None

class BaseProvider(ABC):
    """Base class for all data providers"""
    
    def __init__(self, provider_code: str):
        self.provider_code = provider_code
        
    @abstractmethod
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """Scrape games for a specific team"""
        pass
        
    @abstractmethod
    def validate_team_id(self, team_id: str) -> bool:
        """Validate if team ID exists in provider"""
        pass

class BaseValidator(ABC):
    """Base class for data validators"""
    
    @abstractmethod
    def validate(self, data: Dict) -> tuple[bool, Optional[str]]:
        """Validate data, return (is_valid, error_message)"""
        pass

class BaseRankingEngine(ABC):
    """Base class for ranking engines"""
    
    @abstractmethod
    def calculate_power_score(self, team_data: Dict) -> float:
        """Calculate team's power score"""
        pass
        
    @abstractmethod
    def calculate_sos(self, team_data: Dict, opponents: List[Dict]) -> float:
        """Calculate strength of schedule"""
        pass