"""SincSports scraper implementation"""
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
import logging
import time
import random
import re
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.base import GameData

logger = logging.getLogger(__name__)


class SincSportsScraper(BaseScraper):
    """Scraper for SincSports using web scraping"""
    
    BASE_URL = "https://soccer.sincsports.com"
    
    def __init__(self, supabase_client, provider_code: str = 'sincsports'):
        super().__init__(supabase_client, provider_code)
        
        # Configuration
        self.delay_min = float(os.getenv('SINCSPORTS_DELAY_MIN', '2.0'))
        self.delay_max = float(os.getenv('SINCSPORTS_DELAY_MAX', '3.0'))
        self.max_retries = int(os.getenv('SINCSPORTS_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('SINCSPORTS_TIMEOUT', '30'))
        self.retry_delay = float(os.getenv('SINCSPORTS_RETRY_DELAY', '2.0'))
        
        # Session setup
        self.session = self._init_http_session()
        
        # Club name cache
        self.club_cache: Dict[str, str] = {}
        
        logger.info(f"Initialized SincSportsScraper")
    
    def extract(self, context, days_back: Optional[int] = None) -> List[Dict]:
        """
        Extract games from SincSports teams.
        
        Overrides base extract() to use configurable date range instead of last_scrape_date.
        
        Args:
            context: Context dict (unused for SincSports)
            days_back: Number of days to look back from today (default: 365 days)
        
        Returns:
            List of game dictionaries ready for import
        """
        teams = self._get_teams_to_scrape()
        all_games = []
        
        # Default to 365 days if not specified
        if days_back is None:
            days_back = 365
        
        for team in teams:
            try:
                # Scrape games using configurable date range (no last_scrape_date)
                games = self.scrape_team_games(
                    team['provider_team_id'],
                    days_back=days_back
                )
                
                # Convert GameData to dict format for import
                for game in games:
                    game_dict = self._game_data_to_dict(game, team['provider_team_id'])
                    if game_dict:
                        all_games.append(game_dict)
                
                # Log scrape (but don't update last_scraped_at - that's for GotSport only)
                logger.info(f"Scraped {len(games)} games for team {team['provider_team_id']}")
                
            except Exception as e:
                logger.error(f"Error scraping team {team['provider_team_id']}: {e}")
                self.errors.append({
                    'team_id': team['provider_team_id'],
                    'error': str(e)
                })
        
        return all_games
    
    def _init_http_session(self) -> requests.Session:
        """Initialize HTTP session with retry logic"""
        session = requests.Session()
        
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
        
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Set headers to mimic browser
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        return session
    
    def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None, days_back: Optional[int] = None) -> List[GameData]:
        """
        Scrape games for a specific SincSports team
        
        Args:
            team_id: SincSports team ID (e.g., 'NCM14762')
            since_date: Only scrape games after this date (optional, overrides days_back)
            days_back: Number of days to look back from today (default: 365 days)
        
        Returns:
            List of GameData objects
        """
        games_url = f"{self.BASE_URL}/team/games.aspx?teamid={team_id}"
        
        # Determine date cutoff
        if since_date:
            # Use provided since_date
            since_date_obj = since_date.date() if isinstance(since_date, datetime) else since_date
        elif days_back is not None:
            # Use days_back parameter
            since_date_obj = date.today() - timedelta(days=days_back)
        else:
            # Default: scrape games from last 365 days
            since_date_obj = date.today() - timedelta(days=365)
        
        games = []
        
        # Retry logic
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(games_url, timeout=self.timeout)
                response.raise_for_status()
                
                # Parse HTML
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract team info from page
                team_info = self._extract_team_info(soup, team_id)
                
                # Parse games from HTML
                parsed_games = self._parse_games_from_html(soup, team_id, team_info, since_date_obj)
                games.extend(parsed_games)
                
                logger.info(f"Found {len(games)} games for team {team_id}")
                break
                
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    logger.warning(f"Team {team_id} not found (404) - skipping")
                    return []
                
                if attempt < self.max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Failed after {self.max_retries} attempts: {e}")
                    raise
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Error scraping team {team_id}: {e}")
                    raise
        
        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))
        
        return games
    
    def _extract_team_info(self, soup: BeautifulSoup, team_id: str) -> Dict:
        """Extract team information from the games page"""
        team_info = {
            'team_name': None,
            'club_name': None,
            'age_group': None,
            'gender': None
        }
        
        # Try to find team name (in header link)
        team_name_link = soup.find('a', id=re.compile(r'.*teamHeader.*lnkTeamName'))
        if team_name_link:
            team_info['team_name'] = team_name_link.get_text(strip=True)
        
        # Try to find club name
        club_link = soup.find('a', id=re.compile(r'.*teamHeader.*lnkClub'))
        if club_link:
            team_info['club_name'] = club_link.get_text(strip=True)
        
        # Try to find age/gender info
        age_label = soup.find('span', id=re.compile(r'.*teamHeader.*lblAge'))
        if age_label:
            age_text = age_label.get_text(strip=True)
            # Parse "U12 BORN IN 2014 BOYS"
            team_info['age_group'] = self._parse_age_group(age_text)
            team_info['gender'] = self._parse_gender(age_text)
        
        return team_info
    
    def _parse_age_group(self, age_text: str) -> Optional[str]:
        """Parse age group from text like 'U12 BORN IN 2014 BOYS'"""
        # Look for U## pattern
        match = re.search(r'U(\d+)', age_text, re.IGNORECASE)
        if match:
            age_num = match.group(1)
            return f"u{age_num}"
        return None
    
    def _parse_gender(self, age_text: str) -> Optional[str]:
        """Parse gender from text"""
        age_text_lower = age_text.lower()
        if 'boys' in age_text_lower or 'men' in age_text_lower:
            return 'Male'
        elif 'girls' in age_text_lower or 'women' in age_text_lower:
            return 'Female'
        return None
    
    def _parse_games_from_html(self, soup: BeautifulSoup, team_id: str, team_info: Dict, since_date: date) -> List[GameData]:
        """Parse games from the HTML structure"""
        games = []
        
        # Find the event table container
        event_container = soup.find('div', id='eventTbl')
        if not event_container:
            logger.warning(f"No event table found for team {team_id}")
            return games
        
        # Find all event sections (each tournament/event)
        # Events are direct children div.row of eventTbl
        event_sections = []
        for row in event_container.find_all('div', class_='row', recursive=False):
            # Skip blurred sections (VIP content)
            style = row.get('style', '')
            if 'blur' in style.lower():
                logger.debug("Skipping blurred VIP content")
                continue
            event_sections.append(row)
        
        for event_section in event_sections:
            # Extract tournament/event name
            event_link = event_section.find('a', href=re.compile(r'/team/Team\.aspx'))
            event_name = event_link.get_text(strip=True) if event_link else None
            
            # Find division name
            division_link = event_section.find('a', href=re.compile(r'/schedule\.aspx'))
            division_name = division_link.get_text(strip=True) if division_link else None
            
            # Find games in this event
            # Games are nested in col-md-7 or col-md-10 within the event section
            game_container = event_section.find('div', class_=re.compile(r'col-md-[7-9]|col-md-10'))
            if not game_container:
                continue
            
            # Find all nested div.row elements that contain games
            # Games can be in:
            # 1. Individual rows with 4 columns (col-1 rank, col-9 date+opponent, col-1 score, col-1 result)
            # 2. Combined rows with multiple games (16 columns = 4 games)
            game_rows = game_container.find_all('div', class_='row', recursive=True)
            
            # Track processed games to avoid duplicates
            seen_games = set()
            
            for row in game_rows:
                # Check if this row contains a game (has date, opponent link, score)
                opponent_links = row.find_all('a', href=re.compile(r'/team/Team\.aspx.*teamid='))
                if not opponent_links:
                    continue
                
                # Get all columns
                cols = row.find_all('div', class_=re.compile(r'col-\d+'))
                
                # If we have exactly 4 columns, it's a single game row
                if len(cols) == 4:
                    game = self._parse_game_row(row, team_id, team_info, event_name, division_name, since_date)
                    if game:
                        # Create unique key to avoid duplicates
                        game_key = (game.game_date, game.opponent_id)
                        if game_key not in seen_games:
                            seen_games.add(game_key)
                            games.append(game)
                # If we have multiple of 4 columns (e.g., 16 = 4 games), split into individual games
                elif len(cols) > 4 and len(cols) % 4 == 0:
                    # Split into groups of 4 columns and parse each as a separate game
                    num_games = len(cols) // 4
                    for i in range(num_games):
                        start_idx = i * 4
                        game_cols = cols[start_idx:start_idx + 4]
                        
                        # Parse game directly from column group
                        game = self._parse_game_from_cols(game_cols, team_id, team_info, event_name, division_name, since_date)
                        if game:
                            # Create unique key to avoid duplicates
                            game_key = (game.game_date, game.opponent_id)
                            if game_key not in seen_games:
                                seen_games.add(game_key)
                                games.append(game)
        
        return games
    
    def _parse_game_from_cols(self, cols, team_id: str, team_info: Dict, event_name: Optional[str], division_name: Optional[str], since_date: date) -> Optional[GameData]:
        """Parse a game from a list of 4 columns (rank, date+opponent, score, result)"""
        if len(cols) != 4:
            return None
        
        try:
            # Column structure: [rank, date+opponent, score, result]
            rank_col = cols[0]
            date_opponent_col = cols[1]
            score_col = cols[2]
            result_col = cols[3]
            
            # Extract date
            # The date is at the start of the column text, before the opponent link
            # Format: "08/24/25<opponent link>" or "08/24/2514 (12U)" (concatenated)
            # We need to extract just the date part, not match digits from team names
            date_text = date_opponent_col.get_text(strip=True)
            # Match date pattern from start - only match 2-digit years (MM/DD/YY format)
            # Use ^ anchor to ensure we start at the beginning
            date_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2})', date_text)
            if not date_match:
                return None
            
            month, day, year = date_match.groups()
            
            # Convert 2-digit year to 4-digit
            if len(year) == 2:
                year_int = int(year)
                # Current year is 2025, so years 00-25 are 2000-2025, 26-99 are 2026-2099
                # But more conservatively: assume years 00-50 are 2000-2050
                if year_int <= 50:
                    year = '20' + year
                else:
                    year = '19' + year
            elif len(year) == 4:
                # Already 4-digit, but validate it's reasonable
                year_int = int(year)
                if year_int < 2000 or year_int > 2100:
                    # If it's way out of range, might be a parsing error
                    return None
            
            try:
                game_date = date(int(year), int(month), int(day))
                # Sanity check: date should be reasonable (between 2000 and 2100)
                if not (2000 <= game_date.year <= 2100):
                    return None
            except (ValueError, TypeError):
                return None
            
            # Filter by date
            if game_date < since_date:
                return None
            
            # Extract opponent
            opponent_link = date_opponent_col.find('a', href=re.compile(r'/team/Team\.aspx.*teamid='))
            if not opponent_link:
                return None
            
            opponent_name = opponent_link.get_text(strip=True)
            href = opponent_link.get('href', '')
            teamid_match = re.search(r'teamid=([A-Z0-9]+)', href)
            opponent_id = teamid_match.group(1) if teamid_match else None
            
            # Extract score
            score_text = score_col.get_text(strip=True)
            score_match = re.search(r'(\d+)\s*[-:]\s*(\d+)', score_text)
            goals_for = None
            goals_against = None
            if score_match:
                goals_for = int(score_match.group(1))
                goals_against = int(score_match.group(2))
            
            # Extract result
            result_text = result_col.get_text(strip=True)
            # Normalize result: 'T' (Tie) -> 'D' (Draw) to match database constraint
            if result_text == 'T':
                result_text = 'D'
            result = result_text if result_text in ['W', 'L', 'D'] else None
            
            # Determine result if not found
            if not result and goals_for is not None and goals_against is not None:
                if goals_for > goals_against:
                    result = 'W'
                elif goals_for < goals_against:
                    result = 'L'
                else:
                    result = 'D'
            elif not result:
                result = 'U'
            
            # Build competition name
            competition_parts = []
            if event_name:
                competition_parts.append(event_name)
            if division_name:
                competition_parts.append(division_name)
            competition = ' - '.join(competition_parts) if competition_parts else None
            
            game = GameData(
                provider_id=self.provider_code,
                team_id=str(team_id),
                opponent_id=str(opponent_id) if opponent_id else '',
                team_name=team_info.get('team_name', ''),
                opponent_name=opponent_name or 'Unknown',
                game_date=game_date.strftime('%Y-%m-%d'),
                home_away='H',  # Default
                goals_for=goals_for,
                goals_against=goals_against,
                result=result,
                competition=competition,
                venue=None,
                meta={
                    'source_url': f"{self.BASE_URL}/team/games.aspx?teamid={team_id}",
                    'scraped_at': datetime.now().isoformat(),
                    'club_name': team_info.get('club_name'),
                    'opponent_club_name': None
                }
            )
            
            # Fetch opponent club name if we have opponent_id
            if opponent_id and not game.meta.get('opponent_club_name'):
                opponent_club_name = self._fetch_club_name_for_team_id(opponent_id)
                if opponent_club_name:
                    game.meta['opponent_club_name'] = opponent_club_name
            
            return game
            
        except Exception as e:
            logger.warning(f"Error parsing game from columns: {e}")
            return None
    
    def _parse_game_row(self, row, team_id: str, team_info: Dict, event_name: Optional[str], division_name: Optional[str], since_date: date) -> Optional[GameData]:
        """Parse a single game row"""
        try:
            # Find all columns in the row
            cols = row.find_all('div', class_=re.compile(r'col-\d+'))
            if len(cols) != 4:
                return None
            
            # Use the column-based parser
            return self._parse_game_from_cols(cols, team_id, team_info, event_name, division_name, since_date)
            
            # Extract date (usually in second column)
            game_date = None
            opponent_id = None
            opponent_name = None
            score_text = None
            result = None
            
            # First pass: extract date and opponent
            for col in cols:
                text = col.get_text(strip=True)
                
                # Look for date (MM/DD/YY format)
                date_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', text)
                if date_match:
                    month, day, year = date_match.groups()
                    # Convert 2-digit year to 4-digit
                    if len(year) == 2:
                        year_int = int(year)
                        # Assume years 00-50 are 2000-2050, 51-99 are 1951-1999
                        if year_int <= 50:
                            year = '20' + year
                        else:
                            year = '19' + year
                    try:
                        parsed_date = date(int(year), int(month), int(day))
                        # Sanity check: date should be reasonable (between 2000 and 2100)
                        if 2000 <= parsed_date.year <= 2100:
                            game_date = parsed_date
                    except ValueError:
                        logger.warning(f"Invalid date: {month}/{day}/{year}")
                        continue
                
                # Look for opponent link
                opponent_link = col.find('a', href=re.compile(r'/team/Team\.aspx.*teamid='))
                if opponent_link:
                    opponent_name = opponent_link.get_text(strip=True)
                    # Extract team ID from href
                    href = opponent_link.get('href', '')
                    teamid_match = re.search(r'teamid=([A-Z0-9]+)', href)
                    if teamid_match:
                        opponent_id = teamid_match.group(1)
            
            # Second pass: extract score and result from all columns
            # Scores are typically in columns with text-align:right style
            for i, col in enumerate(cols):
                text = col.get_text(strip=True)
                style = col.get('style', '')
                
                # Look for score (format: X-Y or X:Y)
                # Scores are usually in right-aligned columns
                score_match = re.search(r'(\d+)\s*[-:]\s*(\d+)', text)
                if score_match:
                    # Prefer columns with text-align:right (more likely to be scores)
                    if 'text-align:right' in style.replace(' ', '') or 'text-align: right' in style:
                        if not score_text:  # Only take first match
                            score_text = f"{score_match.group(1)}-{score_match.group(2)}"
                    elif not score_text:  # Fallback: any column with score pattern
                        score_text = f"{score_match.group(1)}-{score_match.group(2)}"
                
                # Look for result (W, L, T, D) - usually in left-aligned columns
                if text.strip() in ['W', 'L', 'T', 'D'] and not result:
                    result = text.strip()
            
            # Validate we have required data
            if not game_date:
                return None
            
            # Filter by date
            if game_date < since_date:
                return None
            
            # Parse score
            goals_for = None
            goals_against = None
            if score_text:
                parts = re.split(r'[-:]', score_text)
                if len(parts) == 2:
                    try:
                        goals_for = int(parts[0].strip())
                        goals_against = int(parts[1].strip())
                    except ValueError:
                        pass
            
            # Determine result if not found
            if not result and goals_for is not None and goals_against is not None:
                if goals_for > goals_against:
                    result = 'W'
                elif goals_for < goals_against:
                    result = 'L'
                else:
                    result = 'D'
            elif not result:
                result = 'U'  # Unknown
            
            # Determine home/away (we don't have this info, default to 'H')
            # TODO: Try to determine from context if possible
            home_away = 'H'
            
            # Build competition name
            competition_parts = []
            if event_name:
                competition_parts.append(event_name)
            if division_name:
                competition_parts.append(division_name)
            competition = ' - '.join(competition_parts) if competition_parts else None
            
            return GameData(
                provider_id=self.provider_code,
                team_id=str(team_id),
                opponent_id=str(opponent_id) if opponent_id else '',
                team_name=team_info.get('team_name', ''),
                opponent_name=opponent_name or 'Unknown',
                game_date=game_date.strftime('%Y-%m-%d'),
                home_away=home_away,
                goals_for=goals_for,
                goals_against=goals_against,
                result=result,
                competition=competition,
                venue=None,  # Not available in this format
                meta={
                    'source_url': f"{self.BASE_URL}/team/games.aspx?teamid={team_id}",
                    'scraped_at': datetime.now().isoformat(),
                    'club_name': team_info.get('club_name'),
                    'opponent_club_name': None  # Will be fetched if opponent_id available
                }
            )
            
            # Fetch opponent club name if we have opponent_id
            if opponent_id and not game.meta.get('opponent_club_name'):
                opponent_club_name = self._fetch_club_name_for_team_id(opponent_id)
                if opponent_club_name:
                    game.meta['opponent_club_name'] = opponent_club_name
            
            return game
            
        except Exception as e:
            logger.warning(f"Error parsing game row: {e}")
            return None
    
    def _fetch_club_name_for_team_id(self, team_id: str) -> str:
        """Fetch club name for a given team ID by visiting team page"""
        # Check cache first
        if team_id in self.club_cache:
            return self.club_cache[team_id]
        
        try:
            team_url = f"{self.BASE_URL}/team/default.aspx?teamid={team_id}"
            response = self.session.get(team_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for club name link (same pattern as our team)
            club_link = soup.find('a', id=re.compile(r'.*teamHeader.*lnkClub'))
            if club_link:
                club_name = club_link.get_text(strip=True)
                if club_name:
                    self.club_cache[team_id] = club_name
                    logger.debug(f"Fetched club name for team {team_id}: {club_name}")
                    return club_name
            
            return ''
        except Exception as e:
            logger.debug(f"Failed to fetch club name for team {team_id}: {e}")
            return ''
    
    def validate_team_id(self, team_id: str) -> bool:
        """Validate if team ID exists in SincSports"""
        try:
            team_url = f"{self.BASE_URL}/team/default.aspx?teamid={team_id}"
            response = self.session.get(team_url, timeout=10)
            
            # Check if page loads successfully and contains team info
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                # Look for team name link (indicates valid team page)
                team_name_link = soup.find('a', id=re.compile(r'.*teamHeader.*lnkTeamName'))
                return team_name_link is not None
            
            return False
        except Exception:
            return False
    
    def _determine_result(self, goals_for: Optional[int], goals_against: Optional[int]) -> str:
        """Determine game result based on scores"""
        if goals_for is None or goals_against is None:
            return 'U'
        
        if goals_for > goals_against:
            return 'W'
        elif goals_for < goals_against:
            return 'L'
        else:
            return 'D'
    
    def _game_data_to_dict(self, game: GameData, team_id: str) -> Dict:
        """Convert GameData to import format dictionary"""
        meta = game.meta or {}
        base_dict = super()._game_data_to_dict(game, team_id)
        # Add club names from meta
        base_dict['club_name'] = meta.get('club_name', '')
        base_dict['opponent_club_name'] = meta.get('opponent_club_name', '')
        return base_dict

