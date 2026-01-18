"""Surf Sports tournament scraper

This scraper:
1. Finds tournament links from surfsports.com
2. Navigates to totalglobalsports.com event pages
3. Extracts schedule IDs for each age group/flight
4. Scrapes game data from individual schedule pages
"""
from typing import List, Optional, Dict, Set, Tuple
from datetime import datetime, date
import logging
import os
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.base import GameData

logger = logging.getLogger(__name__)


class SurfSportsScraper(BaseScraper):
    """
    Scraper for Surf Sports tournaments hosted on Total Global Sports
    
    This scraper scrapes game history from all Surf Sports tournaments by:
    1. Finding tournament links from surfsports.com
    2. Extracting schedule IDs from totalglobalsports.com event pages
    3. Scraping game data from individual schedule pages
    """
    
    SURFSPORTS_BASE = "https://surfsports.com"
    TGS_BASE = "https://public.totalglobalsports.com"
    
    def __init__(self, supabase_client, provider_code: str = 'surfsports'):
        """
        Initialize the scraper
        
        Args:
            supabase_client: Supabase client instance
            provider_code: Provider code (must match config/settings.py)
        """
        super().__init__(supabase_client, provider_code)
        
        # Configuration
        self.delay_min = float(os.getenv('SURFSPORTS_DELAY_MIN', '1.0'))
        self.delay_max = float(os.getenv('SURFSPORTS_DELAY_MAX', '2.0'))
        self.max_retries = int(os.getenv('SURFSPORTS_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('SURFSPORTS_TIMEOUT', '30'))
        
        # Initialize HTTP session
        self.session = self._init_http_session()
        
        logger.info(f"Initialized {self.__class__.__name__}")
    
    def _init_http_session(self) -> requests.Session:
        """Initialize HTTP session with retry logic"""
        session = requests.Session()
        
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
        
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        return session
    
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None) -> List[GameData]:
        """
        Scrape games for a specific team
        
        Note: This scraper is designed for tournament-wide scraping.
        For team-specific scraping, use scrape_tournament_games() instead.
        
        Args:
            team_id: Not used in tournament scraper
            since_date: Only scrape games after this date
        
        Returns:
            Empty list (use scrape_tournament_games() for actual scraping)
        """
        logger.warning("scrape_team_games() not implemented for SurfSports. Use scrape_tournament_games() instead.")
        return []
    
    def scrape_tournament_games(
        self,
        event_id: Optional[str] = None,
        gender_filter: Optional[str] = None,
        age_group_filter: Optional[str] = None,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games from Surf Sports tournaments
        
        Args:
            event_id: Specific event ID to scrape (e.g., "4067"). If None, scrapes all tournaments
            gender_filter: Filter by gender ("B" for boys, "G" for girls). If None, scrapes all
            age_group_filter: Filter by age group (e.g., "2012"). If None, scrapes all
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects
        """
        all_games: List[GameData] = []
        
        if event_id:
            # Scrape specific event
            logger.info(f"Scraping event {event_id}")
            games = self._scrape_event_games(event_id, gender_filter, age_group_filter, since_date)
            all_games.extend(games)
        else:
            # Find all tournaments from surfsports.com
            logger.info("Finding all tournaments from surfsports.com")
            event_urls = self._find_tournament_event_urls()
            
            logger.info(f"Found {len(event_urls)} tournaments to scrape")
            
            for event_url in event_urls:
                # Extract event ID from URL
                match = re.search(r'/event/(\d+)/', event_url)
                if not match:
                    logger.warning(f"Could not extract event ID from {event_url}")
                    continue
                
                event_id = match.group(1)
                logger.info(f"Scraping event {event_id} from {event_url}")
                
                try:
                    games = self._scrape_event_games(event_id, gender_filter, age_group_filter, since_date)
                    all_games.extend(games)
                    time.sleep(1)  # Rate limiting between events
                except Exception as e:
                    logger.error(f"Error scraping event {event_id}: {e}")
                    continue
        
        logger.info(f"Total games scraped: {len(all_games)}")
        return all_games
    
    def _find_tournament_event_urls(self) -> List[str]:
        """
        Find all tournament event URLs from surfsports.com
        
        Returns:
            List of totalglobalsports.com event URLs
        """
        event_urls: Set[str] = set()
        
        try:
            # Get main page
            response = self.session.get(self.SURFSPORTS_BASE, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all links to totalglobalsports.com
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                # Look for totalglobalsports.com links
                if 'totalglobalsports.com' in href or 'public.totalglobalsports.com' in href:
                    # Check if it's an event/schedules URL
                    if '/event/' in href and ('/schedules' in href or '/standings' in href):
                        # Normalize URL
                        if href.startswith('/'):
                            href = f"{self.TGS_BASE}{href}"
                        elif not href.startswith('http'):
                            href = f"{self.TGS_BASE}/{href}"
                        
                        # Extract base event URL (schedules-standings)
                        match = re.search(r'(/public/event/\d+/schedules-standings)', href)
                        if match:
                            event_urls.add(f"{self.TGS_BASE}{match.group(1)}")
            
            # Also check tournament-specific pages (college-cup, surf-cup, etc.)
            tournament_pages = [
                '/college-cup/',
                '/surf-cup/',
                '/surf-challenge/',
            ]
            
            for page_path in tournament_pages:
                try:
                    page_url = f"{self.SURFSPORTS_BASE}{page_path}"
                    response = self.session.get(page_url, timeout=self.timeout)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Find totalglobalsports links
                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '')
                        if 'totalglobalsports.com' in href and '/event/' in href:
                            if href.startswith('/'):
                                href = f"{self.TGS_BASE}{href}"
                            elif not href.startswith('http'):
                                href = f"{self.TGS_BASE}/{href}"
                            
                            match = re.search(r'(/public/event/\d+/schedules-standings)', href)
                            if match:
                                event_urls.add(f"{self.TGS_BASE}{match.group(1)}")
                    
                    time.sleep(0.5)  # Rate limiting
                except Exception as e:
                    logger.warning(f"Error checking tournament page {page_path}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error finding tournament URLs: {e}")
        
        return list(event_urls)
    
    def _scrape_event_games(
        self,
        event_id: str,
        gender_filter: Optional[str] = None,
        age_group_filter: Optional[str] = None,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games from a specific event
        
        Args:
            event_id: Event ID (e.g., "4067")
            gender_filter: Filter by gender ("B" or "G")
            age_group_filter: Filter by age group (e.g., "2012")
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects
        """
        games: List[GameData] = []
        
        # Get event schedules-standings page and extract schedule IDs using Selenium
        try:
            schedule_ids = self._extract_schedule_ids_with_selenium(
                event_id, gender_filter, age_group_filter
            )
            
            if not schedule_ids:
                logger.warning(f"No schedule IDs found for event {event_id}")
                return games
            
            # Get event name (try API first, fallback to default)
            event_name = f"Event {event_id}"
            try:
                event_details_url = f"https://api.athleteone.com/api/Event/get-event-details-by-eventID/{event_id}"
                response = self.session.get(event_details_url, timeout=self.timeout)
                if response.status_code == 200:
                    data = response.json()
                    event_name = data.get('eventName', event_name)
            except:
                pass
            
            logger.info(f"Scraping event: {event_name}")
            logger.info(f"Found {len(schedule_ids)} schedule pages to scrape")
            
            # Scrape each schedule page
            for schedule_id in schedule_ids:
                try:
                    schedule_games = self._scrape_schedule_page(
                        event_id, schedule_id, event_name, since_date
                    )
                    games.extend(schedule_games)
                    time.sleep(0.5)  # Rate limiting
                except Exception as e:
                    logger.warning(f"Error scraping schedule {schedule_id}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error scraping event {event_id}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return games
    
    def _extract_schedule_ids_with_selenium(
        self,
        event_id: str,
        gender_filter: Optional[str] = None,
        age_group_filter: Optional[str] = None
    ) -> List[str]:
        """
        Extract schedule IDs using Selenium to render JavaScript
        
        Args:
            event_id: Event ID
            gender_filter: Filter by gender ("B" or "G")
            age_group_filter: Filter by age group (e.g., "2012")
        
        Returns:
            List of schedule IDs
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            logger.error("Selenium not installed. Install with: pip install selenium")
            logger.info("Falling back to manual schedule ID extraction...")
            # Fallback: return known schedule IDs for event 4067
            if event_id == '4067':
                return self._get_known_schedule_ids_4067(gender_filter, age_group_filter)
            return []
        
        schedule_ids: Set[str] = set()
        
        try:
            # Setup Chrome options
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            driver = webdriver.Chrome(options=chrome_options)
            
            try:
                url = f"{self.TGS_BASE}/public/event/{event_id}/schedules-standings"
                driver.get(url)
                
                # Wait for tables to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
                
                # Get page source and parse
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                schedule_ids = set(self._extract_schedule_ids_from_html(
                    soup, gender_filter, age_group_filter
                ))
                
            finally:
                driver.quit()
        
        except Exception as e:
            logger.warning(f"Error using Selenium: {e}")
            # Fallback to known schedule IDs
            if event_id == '4067':
                return self._get_known_schedule_ids_4067(gender_filter, age_group_filter)
        
        return list(schedule_ids)
    
    def _get_known_schedule_ids_4067(
        self,
        gender_filter: Optional[str] = None,
        age_group_filter: Optional[str] = None
    ) -> List[str]:
        """
        Get known schedule IDs for event 4067 (from browser inspection)
        
        Returns:
            List of schedule IDs
        """
        # Known schedule IDs from browser inspection
        known_schedules = {
            'B2012': ['35450', '35464', '35478'],
            'B2013': ['35449', '35463', '35477'],
            'B2014': ['35448', '35462'],
            'B2015': ['35447', '35461'],
            'B2016': ['35446', '35460'],
            'B2017': ['35445'],
            'B2018': ['35444'],
            'G2012': ['35457', '35471', '35485'],
            'G2013': ['35456', '36726', '35470', '35484'],
            'G2014': ['35455', '35469'],
            'G2015': ['35454', '35468', '35482'],
            'G2016': ['35453'],
            'G2017': ['35452'],
            'G2018': ['35451'],
        }
        
        schedule_ids = []
        for age_group, ids in known_schedules.items():
            match = re.match(r'^([BG])(\d{4})$', age_group)
            if not match:
                continue
            
            gender = match.group(1)
            age = match.group(2)
            
            # Apply filters
            if gender_filter and gender != gender_filter:
                continue
            if age_group_filter and age != age_group_filter:
                continue
            
            schedule_ids.extend(ids)
        
        return schedule_ids
    
    def _extract_schedule_ids_from_html(
        self,
        soup: BeautifulSoup,
        gender_filter: Optional[str] = None,
        age_group_filter: Optional[str] = None
    ) -> List[str]:
        """
        Extract schedule IDs from the schedules-standings page
        
        Args:
            soup: BeautifulSoup object of the schedules-standings page
            gender_filter: Filter by gender ("B" or "G")
            age_group_filter: Filter by age group (e.g., "2012")
        
        Returns:
            List of schedule IDs
        """
        schedule_ids: Set[str] = set()
        
        # Find all tables with age groups
        tables = soup.find_all('table')
        logger.debug(f"Found {len(tables)} tables on schedules-standings page")
        
        for table in tables:
            # Find age group header (e.g., "B2012", "G2013")
            header_row = table.find('tr')
            if not header_row:
                continue
            
            # Get age group from first cell
            first_cell = header_row.find('td') or header_row.find('th')
            if not first_cell:
                continue
            
            age_group_text = first_cell.get_text(strip=True)
            logger.debug(f"Found age group text: {age_group_text}")
            
            # Parse age group (e.g., "B2012" -> gender="B", age="2012")
            match = re.match(r'^([BG])(\d{4})$', age_group_text)
            if not match:
                logger.debug(f"Age group text '{age_group_text}' doesn't match pattern")
                continue
            
            gender = match.group(1)
            age_group = match.group(2)
            logger.debug(f"Parsed: gender={gender}, age_group={age_group}")
            
            # Apply filters
            if gender_filter and gender != gender_filter:
                logger.debug(f"Skipping {gender}{age_group} - doesn't match gender filter")
                continue
            if age_group_filter and age_group != age_group_filter:
                logger.debug(f"Skipping {gender}{age_group} - doesn't match age filter")
                continue
            
            # Find all schedule links in this table
            rows = table.find_all('tr')[1:]  # Skip header row
            logger.debug(f"Found {len(rows)} rows in {gender}{age_group} table")
            
            for row in rows:
                # Find "Schedules | Standings" cell
                cells = row.find_all('td')
                if len(cells) < 1:
                    continue
                
                # Look for links to schedules
                schedule_cell = cells[0]
                links = schedule_cell.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    # Extract schedule ID from URL like /public/event/4067/schedules/35450 or /standings/35450
                    match = re.search(r'/(?:schedules|standings)/(\d+)', href)
                    if match:
                        schedule_id = match.group(1)
                        schedule_ids.add(schedule_id)
                        logger.debug(f"Found schedule ID: {schedule_id} for {gender}{age_group}")
        
        logger.info(f"Extracted {len(schedule_ids)} schedule IDs")
        return list(schedule_ids)
    
    def _scrape_schedule_page(
        self,
        event_id: str,
        schedule_id: str,
        event_name: str,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games from a single schedule page
        
        Args:
            event_id: Event ID
            schedule_id: Schedule ID
            event_name: Event name for metadata
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects
        """
        games: List[GameData] = []
        
        schedule_url = f"{self.TGS_BASE}/public/event/{event_id}/schedules/{schedule_id}"
        
        try:
            # Use Selenium to render JavaScript
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                
                chrome_options = Options()
                chrome_options.add_argument('--headless')
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                
                driver = webdriver.Chrome(options=chrome_options)
                
                try:
                    driver.get(schedule_url)
                    # Wait for table to load
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "table"))
                    )
                    html = driver.page_source
                finally:
                    driver.quit()
                
                soup = BeautifulSoup(html, 'html.parser')
            except ImportError:
                # Fallback to regular requests (won't work for JS-rendered pages)
                response = self.session.get(schedule_url, timeout=self.timeout)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find game tables
            tables = soup.find_all('table')
            
            for table in tables:
                # Find header row
                header_row = table.find('thead')
                if not header_row:
                    header_row = table.find('tr')
                
                if not header_row:
                    continue
                
                # Check if this is a game table (has GM#, GAME INFO, TEAM & VENUE, DETAILS columns)
                headers = [th.get_text(strip=True).upper() for th in header_row.find_all(['th', 'td'])]
                if 'GAME INFO' not in ' '.join(headers) or 'TEAM & VENUE' not in ' '.join(headers):
                    continue
                
                # Column structure: GM# | GAME INFO | TEAM & VENUE | DETAILS
                # GAME INFO column (index 1) contains: date, time, competition
                # TEAM & VENUE column (index 2) contains: home team link, away team link, venue link
                # DETAILS column (index 3) contains: score (two numbers), "Box Score" link
                
                # Parse game rows
                rows = table.find_all('tr')[1:]  # Skip header
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 4:
                        continue
                    
                    # Skip "No Records Found" rows
                    if len(cells) == 1 and 'no records' in cells[0].get_text(strip=True).lower():
                        continue
                    
                    # Extract date and time from GAME INFO column (index 1)
                    game_info_cell = cells[1]
                    game_info_divs = game_info_cell.find_all('div', recursive=False)
                    
                    game_date = None
                    game_time = None
                    
                    if len(game_info_divs) >= 1:
                        date_text = game_info_divs[0].get_text(strip=True)
                        game_date = self._parse_date(date_text)
                    
                    if len(game_info_divs) >= 2:
                        time_text = game_info_divs[1].get_text(strip=True)
                        game_time = self._parse_time(time_text)
                    
                    # Combine date and time
                    game_datetime = None
                    if game_date:
                        if game_time:
                            game_datetime = datetime.combine(game_date, game_time)
                        else:
                            game_datetime = datetime.combine(game_date, datetime.min.time())
                    
                    # Filter by date
                    if since_date and game_datetime and game_datetime < since_date:
                        continue
                    
                    # Extract teams from TEAM & VENUE column (index 2)
                    team_venue_cell = cells[2]
                    team_links = team_venue_cell.find_all('a', href=re.compile(r'/individual-team/'))
                    
                    home_team = None
                    away_team = None
                    
                    if len(team_links) >= 1:
                        home_team = team_links[0].get_text(strip=True)
                    
                    if len(team_links) >= 2:
                        away_team = team_links[1].get_text(strip=True)
                    
                    if not home_team or not away_team:
                        continue
                    
                    # Extract venue from TEAM & VENUE column
                    venue_link = team_venue_cell.find('a', href=re.compile(r'/game-complex/'))
                    venue = None
                    if venue_link:
                        venue = venue_link.get_text(strip=True)
                    
                    # Extract score from DETAILS column (index 3)
                    details_cell = cells[3]
                    details_divs = details_cell.find_all('div', recursive=False)
                    
                    goals_for = None
                    goals_against = None
                    
                    if len(details_divs) >= 2:
                        try:
                            goals_for = int(details_divs[0].get_text(strip=True))
                            goals_against = int(details_divs[1].get_text(strip=True))
                        except (ValueError, IndexError):
                            pass
                    
                    # Create GameData for home team
                    if game_datetime:
                        game = GameData(
                            provider_id=self.provider_code,
                            team_id=home_team,  # Using team name as ID for now
                            opponent_id=away_team,
                            team_name=home_team,
                            opponent_name=away_team,
                            game_date=game_datetime.strftime('%Y-%m-%d'),
                            home_away='H',
                            goals_for=goals_for,
                            goals_against=goals_against,
                            result=self._determine_result(goals_for, goals_against),
                            competition=event_name,
                            venue=venue,
                            meta={
                                'source_url': schedule_url,
                                'scraped_at': datetime.now().isoformat(),
                                'event_id': event_id,
                                'schedule_id': schedule_id
                            }
                        )
                        games.append(game)
                        
                        # Create GameData for away team
                        game_away = GameData(
                            provider_id=self.provider_code,
                            team_id=away_team,
                            opponent_id=home_team,
                            team_name=away_team,
                            opponent_name=home_team,
                            game_date=game_datetime.strftime('%Y-%m-%d'),
                            home_away='A',
                            goals_for=goals_against,
                            goals_against=goals_for,
                            result=self._determine_result(goals_against, goals_for),
                            competition=event_name,
                            venue=venue,
                            meta={
                                'source_url': schedule_url,
                                'scraped_at': datetime.now().isoformat(),
                                'event_id': event_id,
                                'schedule_id': schedule_id
                            }
                        )
                        games.append(game_away)
        
        except Exception as e:
            logger.error(f"Error scraping schedule page {schedule_url}: {e}")
        
        return games
    
    def _parse_date(self, date_text: str) -> Optional[date]:
        """Parse date from text"""
        if not date_text:
            return None
        
        # Try various date formats
        date_formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%m-%d-%Y',
            '%B %d, %Y',
            '%b %d, %Y',
            '%d %B %Y',
            '%d %b %Y',
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_text.strip(), fmt).date()
            except ValueError:
                continue
        
        return None
    
    def _parse_time(self, time_text: str) -> Optional[datetime.time]:
        """Parse time from text"""
        if not time_text:
            return None
        
        time_formats = [
            '%H:%M',
            '%I:%M %p',
            '%I:%M%p',
        ]
        
        for fmt in time_formats:
            try:
                return datetime.strptime(time_text.strip(), fmt).time()
            except ValueError:
                continue
        
        return None
    
    def _parse_score(self, score_text: str) -> Tuple[Optional[int], Optional[int]]:
        """Parse score from text (e.g., "3-2", "3:2", "3 - 2")"""
        if not score_text:
            return None, None
        
        # Try to extract scores
        match = re.search(r'(\d+)\s*[-:]\s*(\d+)', score_text)
        if match:
            try:
                goals_for = int(match.group(1))
                goals_against = int(match.group(2))
                return goals_for, goals_against
            except ValueError:
                pass
        
        return None, None
    
    def _determine_result(self, goals_for: Optional[int], goals_against: Optional[int]) -> str:
        """Determine game result"""
        if goals_for is None or goals_against is None:
            return 'U'
        
        if goals_for > goals_against:
            return 'W'
        elif goals_for < goals_against:
            return 'L'
        else:
            return 'D'
    
    def validate_team_id(self, team_id: str) -> bool:
        """Validate team ID (not applicable for tournament scraper)"""
        return True

