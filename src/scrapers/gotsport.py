"""GotSport scraper implementation using API"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import SSLError as Urllib3SSLError
from requests.exceptions import SSLError as RequestsSSLError
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
import logging
import time
import random
import os

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

from src.scrapers.base import BaseScraper
from src.base import GameData

logger = logging.getLogger(__name__)


class GotSportScraper(BaseScraper):
    """Scraper for GotSport using their API endpoint"""
    
    BASE_URL = "https://system.gotsport.com/api/v1"
    RANKINGS_BASE = "https://rankings.gotsport.com"
    
    def __init__(self, supabase_client, provider_code: str = 'gotsport'):
        super().__init__(supabase_client, provider_code)
        
        # Configuration
        self.delay_min = float(os.getenv('GOTSPORT_DELAY_MIN', '1.5'))
        self.delay_max = float(os.getenv('GOTSPORT_DELAY_MAX', '2.5'))
        self.max_retries = int(os.getenv('GOTSPORT_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('GOTSPORT_TIMEOUT', '30'))
        self.retry_delay = float(os.getenv('GOTSPORT_RETRY_DELAY', '2.0'))
        
        # ZenRows configuration (optional)
        self.zenrows_api_key = os.getenv('ZENROWS_API_KEY')
        self.use_zenrows = bool(self.zenrows_api_key)
        
        # Session setup
        self.session = self._init_http_session()
        
        # Club name cache
        self.club_cache: Dict[str, str] = {}
        
        logger.info(f"Initialized GotSportScraper (ZenRows: {'enabled' if self.use_zenrows else 'disabled'})")
    
    def _init_http_session(self) -> requests.Session:
        """
        Initialize HTTP session with optimized connection pool for concurrent scraping
        
        SSL improvements:
        - Uses certifi for up-to-date certificates
        - Configures urllib3 SSL context for better stability
        - Connection pool recycling to avoid stale SSL connections
        
        Returns:
            Configured requests.Session with HTTPAdapter supporting up to 100 concurrent connections
        """
        session = requests.Session()
        
        # SSL configuration: use certifi if available for better certificate handling
        verify_ssl = True
        if CERTIFI_AVAILABLE:
            verify_ssl = certifi.where()
            logger.debug(f"Using certifi certificates: {verify_ssl}")
        
        # Configure HTTPAdapter with larger connection pool and SSL improvements
        adapter = HTTPAdapter(
            pool_connections=100,   # number of connection pools
            pool_maxsize=100,       # total concurrent connections
            max_retries=Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504],  # Retry on server errors
                # Retry on SSL errors (will be caught and retried)
                allowed_methods=["GET", "HEAD"]
            )
        )
        
        # Mount adapter for both HTTPS and HTTP
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set SSL verification (use certifi if available)
        session.verify = verify_ssl
        
        # Set headers
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.RANKINGS_BASE,
            'Referer': f'{self.RANKINGS_BASE}/',
            'Connection': 'keep-alive',
        })
        
        return session
    
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """
        Scrape games for a specific GotSport team using API
        
        Args:
            team_id: GotSport team ID
            since_date: Only scrape games after this date (for incremental updates)
        
        Returns:
            List of GameData objects
        """
        # Normalize team ID (handle "126693.0" -> 126693)
        try:
            normalized_team_id = int(float(str(team_id)))
        except (ValueError, TypeError):
            logger.error(f"Invalid team_id: {team_id}")
            return []
        
        # For incremental scraping: use last scrape date if available
        # For first-time scraping: use October 17, 2025 baseline
        if since_date:
            # Use the last scrape date (incremental update)
            since_date_obj = since_date.date() if isinstance(since_date, datetime) else since_date
            logger.debug(f"Incremental scrape: fetching games since {since_date_obj}")
        else:
            # First-time scrape: use October 17, 2025 baseline
            since_date_obj = date(2025, 10, 17)
            logger.debug(f"First-time scrape: fetching games since {since_date_obj} (Oct 17, 2025 baseline)")
        
        # API endpoint
        api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"
        params = {'past': 'true'}
        
        # Try to add date filtering at API level (if supported)
        # Common parameter names: since_date, from_date, date_from, since
        # Format: YYYY-MM-DD or ISO format
        if since_date_obj:
            since_date_str = since_date_obj.strftime('%Y-%m-%d')
            # Try common date parameter names (API may ignore if not supported)
            params['since_date'] = since_date_str
            params['from_date'] = since_date_str
        
        # Fetch club name first
        club_name = self._extract_club_name(normalized_team_id)
        
        games = []
        
        # Retry logic
        for attempt in range(self.max_retries):
            try:
                # Use ZenRows if configured
                if self.use_zenrows:
                    response = self._make_zenrows_request(api_url, params)
                else:
                    response = self.session.get(api_url, params=params, timeout=self.timeout)
                
                response.raise_for_status()
                data = response.json()
                
                # API returns a list directly
                if isinstance(data, list) and data:
                    matches = data
                    # Sort by date (newest first) and cap to most recent 30
                    try:
                        matches.sort(key=lambda m: m.get('match_date') or '', reverse=True)
                    except Exception:
                        pass
                    
                    logger.info(f"API returned {len(matches)} matches for team {normalized_team_id}")
                    
                    # OPTIMIZATION: Parse matches with early exit
                    # Since matches are sorted newest first, we can stop parsing once we hit a date before our cutoff
                    for match in matches[:30]:  # Cap to 30 most recent
                        # Quick date check before full parsing (early exit optimization)
                        match_date_str = match.get('match_date', '')
                        if match_date_str:
                            try:
                                game_date = datetime.fromisoformat(match_date_str.replace('Z', '+00:00')).date()
                                # If this game is before our cutoff, stop parsing (all remaining will be older)
                                if game_date < since_date_obj:
                                    logger.debug(f"Reached date cutoff at {game_date}, stopping parse for team {normalized_team_id}")
                                    break
                            except (ValueError, TypeError):
                                # If date parsing fails, continue to full parse (will be filtered there)
                                pass
                        
                        # Full parse (includes date filtering as backup)
                        game = self._parse_api_match(match, normalized_team_id, since_date_obj, club_name)
                        if game:
                            games.append(game)
                    
                    break  # Success, exit retry loop
                else:
                    logger.info(f"No matches found for team {normalized_team_id}")
                    break
                    
            except requests.exceptions.HTTPError as e:
                # Handle 404 gracefully
                if e.response is not None and e.response.status_code == 404:
                    logger.warning(f"Team {normalized_team_id} not found (404) - skipping")
                    return []
                
                # Retry for other HTTP errors
                if attempt < self.max_retries - 1:
                    logger.warning(f"API attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"API failed after {self.max_retries} attempts: {e}")
                    raise
                    
            except (RequestsSSLError, Urllib3SSLError) as e:
                # SSL-specific error handling with exponential backoff
                ssl_error_msg = str(e).lower()
                if 'bad record mac' in ssl_error_msg or 'sslv3_alert' in ssl_error_msg:
                    # Common SSL errors that can be retried
                    if attempt < self.max_retries - 1:
                        # Exponential backoff for SSL errors (longer wait)
                        wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 1.0)
                        logger.warning(f"SSL error (attempt {attempt + 1}/{self.max_retries}): {e}, retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        # Close the session to force new connection
                        self.session.close()
                        self.session = self._init_http_session()
                        continue
                    else:
                        logger.error(f"SSL error persisted after {self.max_retries} attempts: {e}")
                        raise
                else:
                    # Other SSL errors - still retry but log differently
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (1.5 ** attempt)
                        logger.warning(f"SSL error (attempt {attempt + 1}/{self.max_retries}): {e}, retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"SSL error failed after {self.max_retries} attempts: {e}")
                        raise
                        
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Request attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Request failed after {self.max_retries} attempts: {e}")
                    raise
        
        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))
        
        logger.info(f"Found {len(games)} games for team {normalized_team_id}")
        return games
    
    def _make_zenrows_request(self, url: str, params: Dict) -> requests.Response:
        """Make request through ZenRows proxy"""
        zenrows_url = "https://api.zenrows.com/v1/"
        zenrows_params = {
            'apikey': self.zenrows_api_key,
            'url': url,
            'js_render': 'false',
            'premium_proxy': 'true',
            'proxy_country': 'us'
        }
        # Merge original params into URL
        if params:
            url_with_params = f"{url}?" + "&".join([f"{k}={v}" for k, v in params.items()])
            zenrows_params['url'] = url_with_params
        
        return self.session.get(zenrows_url, params=zenrows_params, timeout=self.timeout)
    
    def _extract_club_name(self, team_id: int) -> str:
        """Extract club name from team details API"""
        try:
            api_url = f"{self.BASE_URL}/team_ranking_data/team_details"
            params = {'team_id': team_id}
            
            response = self.session.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            club_name = data.get('club_name', '')
            
            if club_name:
                self.club_cache[str(team_id)] = club_name
                logger.debug(f"Extracted club name for team {team_id}: '{club_name}'")
            
            return club_name
            
        except Exception as e:
            logger.debug(f"Failed to extract club name for team {team_id}: {e}")
            return self.club_cache.get(str(team_id), '')
    
    def _parse_api_match(self, match: Dict, team_id: int, since_date: date, club_name: str = '') -> Optional[GameData]:
        """Parse a match from the GotSport API response"""
        try:
            # Extract team info
            home_team = match.get('homeTeam', {})
            away_team = match.get('awayTeam', {})
            
            # Determine if our team is home or away
            is_home = False
            opponent = {}
            
            if home_team.get('team_id') == team_id:
                is_home = True
                opponent = away_team
            elif away_team.get('team_id') == team_id:
                is_home = False
                opponent = home_team
            else:
                logger.debug(f"Team {team_id} not found in match")
                return None
            
            # Parse date
            match_date = match.get('match_date', '')
            if not match_date:
                return None
            
            try:
                game_date = datetime.fromisoformat(match_date.replace('Z', '+00:00')).date()
            except (ValueError, TypeError):
                logger.warning(f"Invalid date format: {match_date}")
                return None
            
            # Apply date filter
            if game_date < since_date:
                return None
            
            # Extract scores
            home_score = match.get('home_score')
            away_score = match.get('away_score')
            
            # Determine goals for/against
            if is_home:
                goals_for = home_score
                goals_against = away_score
            else:
                goals_for = away_score
                goals_against = home_score
            
            # Extract opponent info
            opponent_name = opponent.get('full_name', 'Unknown')
            opponent_id = str(opponent.get('team_id', ''))
            
            # Extract opponent club
            opponent_club_name = ''
            try:
                club_obj = opponent.get('club')
                if isinstance(club_obj, dict):
                    opponent_club_name = str(club_obj.get('name', '')).strip()
            except Exception:
                pass
            
            # If missing, try to fetch
            if not opponent_club_name and opponent_id:
                opponent_club_name = self._fetch_club_name_for_team_id(opponent_id)
            
            # Extract venue
            venue = match.get('venue', {})
            venue_name = venue.get('name', '') if isinstance(venue, dict) else ''
            
            # Extract competition info
            competition_name = match.get('competition_name', '')
            division_name = match.get('division_name', '')
            event_name = match.get('event_name', '')
            
            # Determine result
            result = self._determine_result(goals_for, goals_against)
            
            return GameData(
                provider_id=self.provider_code,
                team_id=str(team_id),
                opponent_id=opponent_id,
                team_name='',  # Will be filled from team data
                opponent_name=opponent_name,
                game_date=game_date.strftime('%Y-%m-%d'),
                home_away='H' if is_home else 'A',
                goals_for=goals_for,
                goals_against=goals_against,
                result=result,
                competition=competition_name or division_name or event_name,
                venue=venue_name,
                meta={
                    'source_url': f"{self.RANKINGS_BASE}/teams/{team_id}/game-history",
                    'scraped_at': datetime.now().isoformat(),
                    'club_name': club_name,
                    'opponent_club_name': opponent_club_name
                }
            )
            
        except Exception as e:
            logger.warning(f"Error parsing API match: {e}")
            return None
    
    def _fetch_club_name_for_team_id(self, team_id: str) -> str:
        """Fetch club name for a given team ID via team details API"""
        try:
            tid = int(float(str(team_id)))
        except Exception:
            return ''
        
        # Check cache first
        if team_id in self.club_cache:
            return self.club_cache[team_id]
        
        try:
            api_url = f"{self.BASE_URL}/team_ranking_data/team_details"
            params = {'team_id': tid}
            
            response = self.session.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            club_name = str(data.get('club_name', '')).strip()
            
            if club_name:
                self.club_cache[team_id] = club_name
            
            return club_name
        except Exception:
            return ''
    
    def _determine_result(self, goals_for: Optional[int], goals_against: Optional[int]) -> str:
        """Determine game result based on scores"""
        if goals_for is None or goals_against is None:
            return 'U'  # Unknown
        
        if goals_for > goals_against:
            return 'W'  # Win
        elif goals_for < goals_against:
            return 'L'  # Loss
        else:
            return 'D'  # Draw
    
    def _game_data_to_dict(self, game: GameData, team_id: str) -> Dict:
        """Convert GameData to import format dictionary, including club names"""
        meta = game.meta or {}
        base_dict = super()._game_data_to_dict(game, team_id)
        # Add club names from meta
        base_dict['club_name'] = meta.get('club_name', '')
        base_dict['opponent_club_name'] = meta.get('opponent_club_name', '')
        return base_dict
    
    def validate_team_id(self, team_id: str) -> bool:
        """Validate if team ID exists in GotSport"""
        try:
            normalized_team_id = int(float(str(team_id)))
            api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"
            params = {'past': 'true'}
            
            response = self.session.get(api_url, params=params, timeout=10)
            return response.status_code == 200
        except Exception:
            return False
