"""AthleteOne/TGS API client for fetching conference schedules"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional, Tuple
import logging
import os
from pathlib import Path

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

logger = logging.getLogger(__name__)


class AthleteOneClient:
    """Client for AthleteOne/TGS API endpoints"""
    
    BASE_URL = "https://api.athleteone.com"
    
    def __init__(self, session: Optional[requests.Session] = None):
        """
        Initialize the AthleteOne client
        
        Args:
            session: Optional requests.Session to reuse. If None, creates a new session.
        """
        self.session = session or self._init_http_session()
    
    def _init_http_session(self) -> requests.Session:
        """
        Initialize HTTP session with retry logic
        
        Returns:
            Configured requests.Session
        """
        session = requests.Session()
        
        # SSL configuration: use certifi if available
        verify_ssl = True
        if CERTIFI_AVAILABLE:
            verify_ssl = certifi.where()
            logger.debug(f"Using certifi certificates: {verify_ssl}")
        
        # Configure HTTPAdapter with retry logic
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "HEAD"]
            )
        )
        
        # Mount adapter for both HTTPS and HTTP
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set SSL verification
        session.verify = verify_ssl
        
        # Set headers (mimic browser to avoid 403 errors)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.totalglobalsports.com/',
            'Origin': 'https://www.totalglobalsports.com',
        })
        
        return session
    
    def get_conference_schedule_html(
        self,
        org_id: str,
        org_season_id: str,
        event_id: str,
        flight_id: str,
        save_html_path: Optional[str] = None,
        load_from_file: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Fetch conference schedule HTML from AthleteOne API
        
        Calls:
            GET /api/Script/get-conference-schedules/{orgID}/{orgSeasonID}/{eventID}/{flightID}/0
        
        Args:
            org_id: Organization ID
            org_season_id: Organization season ID
            event_id: Event ID
            flight_id: Flight ID
            save_html_path: Optional path to save fetched HTML for debugging
            load_from_file: Optional path to load HTML from file (bypasses network call)
        
        Returns:
            Tuple of (html_text, fetch_url)
        
        Raises:
            requests.HTTPError: If the API returns a non-200 status code
            requests.RequestException: For network errors
        """
        # Build the API URL
        url = f"{self.BASE_URL}/api/Script/get-conference-schedules/{org_id}/{org_season_id}/{event_id}/{flight_id}/0"
        
        # If loading from file, bypass network call
        if load_from_file:
            logger.info(f"Loading HTML from file: {load_from_file}")
            file_path = Path(load_from_file)
            if not file_path.exists():
                raise FileNotFoundError(f"HTML file not found: {load_from_file}")
            with open(file_path, 'r', encoding='utf-8') as f:
                html = f.read()
            logger.info(f"Loaded {len(html)} characters from file")
            return html, url
        
        # Fetch from API
        logger.info(f"Fetching conference schedule from: {url}")
        
        timeout = int(os.getenv('ATHLETEONE_TIMEOUT', '30'))
        
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            
            html = response.text
            logger.info(f"Fetched {len(html)} characters of HTML")
            
            # Save HTML to file if requested (for parser debugging)
            if save_html_path:
                file_path = Path(save_html_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                logger.info(f"Saved HTML to: {save_html_path}")
            
            return html, url
            
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching conference schedule: {e}")
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response text: {e.response.text[:500]}")
            raise
        except requests.RequestException as e:
            logger.error(f"Request error fetching conference schedule: {e}")
            raise
    
    def get_event_list(self, org_season_id: str, event_id: str) -> Tuple[str, str]:
        """
        Get list of events for an organization season
        
        Calls:
            GET /api/Script/get-event-list-by-season-id/{orgSeasonID}/{eventID}
        
        Args:
            org_season_id: Organization season ID
            event_id: Event ID
        
        Returns:
            Tuple of (response_text, fetch_url)
        
        Raises:
            requests.HTTPError: If the API returns a non-200 status code
            requests.RequestException: For network errors
        """
        url = f"{self.BASE_URL}/api/Script/get-event-list-by-season-id/{org_season_id}/{event_id}"
        
        logger.info(f"Fetching event list from: {url}")
        timeout = int(os.getenv('ATHLETEONE_TIMEOUT', '30'))
        
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text, url
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching event list: {e}")
            raise
        except requests.RequestException as e:
            logger.error(f"Request error fetching event list: {e}")
            raise
    
    def get_division_list(
        self,
        org_id: str,
        event_id: str,
        schedule_id: str,
        flight_id: str,
    ) -> Tuple[str, str]:
        """
        Get list of divisions/flights for an event
        
        Calls:
            GET /api/Script/get-division-list-by-event-id/{orgID}/{eventID}/{scheduleID}/{flightID}
        
        Args:
            org_id: Organization ID
            event_id: Event ID
            schedule_id: Schedule ID
            flight_id: Flight ID
        
        Returns:
            Tuple of (response_text, fetch_url)
        
        Raises:
            requests.HTTPError: If the API returns a non-200 status code
            requests.RequestException: For network errors
        """
        url = f"{self.BASE_URL}/api/Script/get-division-list-by-event-id/{org_id}/{event_id}/{schedule_id}/{flight_id}"
        
        logger.info(f"Fetching division list from: {url}")
        timeout = int(os.getenv('ATHLETEONE_TIMEOUT', '30'))
        
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text, url
        except requests.HTTPError as e:
            logger.error(f"HTTP error fetching division list: {e}")
            raise
        except requests.RequestException as e:
            logger.error(f"Request error fetching division list: {e}")
            raise

