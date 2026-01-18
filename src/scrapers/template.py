"""Template for new scraper implementations

This template provides a starting point for implementing new data source scrapers.
Copy this file and rename it to match your provider (e.g., sincsports.py).

Required methods to implement:
- scrape_team_games(): Fetch and parse games for a team
- validate_team_id(): Check if a team ID exists

Optional methods to override:
- _init_http_session(): Customize HTTP session configuration
- _game_data_to_dict(): Customize data conversion
"""
from typing import List, Optional, Dict
from datetime import datetime, date
import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.scrapers.base import BaseScraper
from src.base import GameData

logger = logging.getLogger(__name__)


class TemplateScraper(BaseScraper):
    """
    Template scraper - replace with actual provider name
    
    To implement:
    1. Replace 'TemplateScraper' with your provider name (e.g., 'SincSportsScraper')
    2. Update BASE_URL with the provider's base URL
    3. Implement scrape_team_games() method
    4. Implement validate_team_id() method
    5. Add any provider-specific helper methods
    6. Update config/settings.py to register the provider
    """
    
    BASE_URL = "https://example.com/api"  # Update with actual base URL
    
    def __init__(self, supabase_client, provider_code: str = 'template'):
        """
        Initialize the scraper
        
        Args:
            supabase_client: Supabase client instance
            provider_code: Provider code (must match config/settings.py)
        """
        super().__init__(supabase_client, provider_code)
        
        # Configuration (can be overridden via environment variables)
        self.delay_min = float(os.getenv('TEMPLATE_DELAY_MIN', '1.5'))
        self.delay_max = float(os.getenv('TEMPLATE_DELAY_MAX', '2.5'))
        self.max_retries = int(os.getenv('TEMPLATE_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('TEMPLATE_TIMEOUT', '30'))
        
        # Initialize HTTP session
        self.session = self._init_http_session()
        
        logger.info(f"Initialized {self.__class__.__name__}")
    
    def _init_http_session(self) -> requests.Session:
        """
        Initialize HTTP session with retry logic and connection pooling
        
        Override this method if you need:
        - Custom headers
        - Authentication
        - Proxy configuration
        - SSL certificate handling
        """
        session = requests.Session()
        
        # Configure retry strategy
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "HEAD"]
            )
        )
        
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set default headers
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        return session
    
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """
        Scrape games for a specific team
        
        This is the main method you need to implement. It should:
        1. Normalize/validate the team_id
        2. Build the API URL or web scraping request
        3. Fetch the data (with retry logic)
        4. Parse the response into GameData objects
        5. Filter games by since_date (if provided)
        6. Return the list of GameData objects
        
        Args:
            team_id: Provider-specific team ID (string format)
            since_date: Only scrape games after this date (for incremental updates)
                      If None, scrape all available games
        
        Returns:
            List of GameData objects
        
        Example implementation patterns:
        
        Pattern 1: REST API
        ----------
        api_url = f"{self.BASE_URL}/teams/{team_id}/games"
        params = {}
        if since_date:
            params['since'] = since_date.isoformat()
        
        response = self.session.get(api_url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        
        games = []
        for match in data.get('matches', []):
            game = self._parse_api_match(match, team_id, since_date)
            if game:
                games.append(game)
        
        return games
        
        Pattern 2: Web Scraping (HTML)
        ----------
        from bs4 import BeautifulSoup
        
        team_url = f"{self.BASE_URL}/teams/{team_id}"
        response = self.session.get(team_url, timeout=self.timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        games = []
        
        for row in soup.select('table.games tr'):
            game = self._parse_table_row(row, team_id, since_date)
            if game:
                games.append(game)
        
        return games
        """
        # TODO: Implement scraping logic
        logger.warning(f"scrape_team_games() not implemented for team {team_id}")
        return []
    
    def _parse_api_match(self, match: Dict, team_id: str, since_date: Optional[date]) -> Optional[GameData]:
        """
        Parse a single match from API response into GameData
        
        This is a helper method - implement based on your API's data structure.
        
        Args:
            match: Raw match data from API (dict)
            team_id: Team ID for this match
            since_date: Filter date (skip if match is before this date)
        
        Returns:
            GameData object or None if match should be skipped
        """
        # TODO: Implement parsing logic
        # Example structure:
        try:
            # Extract date
            match_date_str = match.get('date', '')
            if not match_date_str:
                return None
            
            # Parse date
            game_date = datetime.strptime(match_date_str, '%Y-%m-%d').date()
            
            # Filter by date
            if since_date and game_date < since_date:
                return None
            
            # Extract scores
            goals_for = match.get('goals_for')
            goals_against = match.get('goals_against')
            
            # Determine result
            result = self._determine_result(goals_for, goals_against)
            
            # Extract opponent info
            opponent_name = match.get('opponent_name', 'Unknown')
            opponent_id = str(match.get('opponent_id', ''))
            
            # Determine home/away
            home_away = 'H' if match.get('is_home') else 'A'
            
            return GameData(
                provider_id=self.provider_code,
                team_id=str(team_id),
                opponent_id=opponent_id,
                team_name='',  # Will be filled from team data
                opponent_name=opponent_name,
                game_date=game_date.strftime('%Y-%m-%d'),
                home_away=home_away,
                goals_for=goals_for,
                goals_against=goals_against,
                result=result,
                competition=match.get('competition', ''),
                venue=match.get('venue', ''),
                meta={
                    'source_url': f"{self.BASE_URL}/teams/{team_id}",
                    'scraped_at': datetime.now().isoformat()
                }
            )
        except Exception as e:
            logger.warning(f"Error parsing match: {e}")
            return None
    
    def _determine_result(self, goals_for: Optional[int], goals_against: Optional[int]) -> str:
        """
        Determine game result based on scores
        
        Returns:
            'W' for win, 'L' for loss, 'D' for draw, 'U' for unknown
        """
        if goals_for is None or goals_against is None:
            return 'U'
        
        if goals_for > goals_against:
            return 'W'
        elif goals_for < goals_against:
            return 'L'
        else:
            return 'D'
    
    def validate_team_id(self, team_id: str) -> bool:
        """
        Validate if team ID exists in provider
        
        This method should make a lightweight request to check if the team exists.
        It's used for validation before attempting full scraping.
        
        Args:
            team_id: Provider-specific team ID
        
        Returns:
            True if team exists, False otherwise
        
        Example:
        ----
        try:
            # Make a lightweight request (e.g., team details endpoint)
            api_url = f"{self.BASE_URL}/teams/{team_id}"
            response = self.session.get(api_url, timeout=10)
            return response.status_code == 200
        except Exception:
            return False
        """
        # TODO: Implement validation
        logger.warning(f"validate_team_id() not implemented")
        return False
    
    def _game_data_to_dict(self, game: GameData, team_id: str) -> Dict:
        """
        Convert GameData to import format dictionary
        
        Override this method if you need to add provider-specific fields.
        The base implementation handles standard fields.
        
        Args:
            game: GameData object
            team_id: Provider team ID
        
        Returns:
            Dictionary ready for database import
        """
        # Call parent implementation
        base_dict = super()._game_data_to_dict(game, team_id)
        
        # Add any provider-specific fields here
        # Example:
        # base_dict['custom_field'] = game.meta.get('custom_field', '')
        
        return base_dict

