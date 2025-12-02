"""GotSport Event/Tournament scraper - scrapes games from a specific event"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import SSLError as Urllib3SSLError
from requests.exceptions import SSLError as RequestsSSLError
from typing import List, Optional, Dict, Set, Tuple
from datetime import datetime, date, timezone
from dataclasses import dataclass
import logging
import time
import random
import os
import re
from bs4 import BeautifulSoup

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

from src.scrapers.gotsport import GotSportScraper
from src.base import GameData

logger = logging.getLogger(__name__)


@dataclass
class EventTeam:
    """Team information within an event bracket/group"""
    team_id: str
    team_name: str
    bracket_name: str
    group_name: Optional[str] = None  # Group name (e.g., "Group A", "Pool A")
    age_group: Optional[str] = None  # Team's ACTUAL age group (e.g., "U11")
    gender: Optional[str] = None
    division: Optional[str] = None
    playing_up: bool = False  # True if team is playing in a bracket above their age group


class GotSportEventScraper:
    """
    Scraper for GotSport events/tournaments
    
    This scraper:
    1. Extracts team IDs from an event page
    2. Uses the existing GotSportScraper to get games for those teams
    3. Filters games to only include those from the specified event
    """
    
    BASE_URL = "https://system.gotsport.com"
    EVENT_BASE = "https://system.gotsport.com/org_event/events"
    
    def __init__(self, supabase_client, provider_code: str = 'gotsport'):
        """
        Initialize the event scraper
        
        Args:
            supabase_client: Supabase client instance
            provider_code: Provider code (default: 'gotsport')
        """
        self.supabase_client = supabase_client
        self.provider_code = provider_code
        
        # Use the existing team scraper for actual game scraping
        self.team_scraper = GotSportScraper(supabase_client, provider_code)
        
        # Configuration
        self.delay_min = float(os.getenv('GOTSPORT_DELAY_MIN', '1.5'))
        self.delay_max = float(os.getenv('GOTSPORT_DELAY_MAX', '2.5'))
        self.max_retries = int(os.getenv('GOTSPORT_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('GOTSPORT_TIMEOUT', '30'))
        self.retry_delay = float(os.getenv('GOTSPORT_RETRY_DELAY', '2.0'))
        
        # Session setup
        self.session = self._init_http_session()
        
        logger.info("Initialized GotSportEventScraper")
    
    def _init_http_session(self) -> requests.Session:
        """Initialize HTTP session with retry logic"""
        session = requests.Session()
        
        verify_ssl = True
        if CERTIFI_AVAILABLE:
            verify_ssl = certifi.where()
        
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
        session.verify = verify_ssl
        
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        return session
    
    def extract_event_teams(self, event_id: str) -> List[str]:
        """
        Extract team IDs from an event page
        
        Args:
            event_id: GotSport event ID (e.g., "40550")
        
        Returns:
            List of team IDs found in the event
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        team_ids: Set[str] = set()
        
        logger.info(f"Extracting teams from event {event_id}: {event_url}")
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(event_url, timeout=self.timeout)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Method 1: Look for team links in the HTML
                # GotSport typically uses links like /teams/{team_id} or /team/{team_id}
                team_links = soup.find_all('a', href=re.compile(r'/teams?/\d+'))
                for link in team_links:
                    href = link.get('href', '')
                    match = re.search(r'/teams?/(\d+)', href)
                    if match:
                        team_ids.add(match.group(1))
                
                # Method 2: Look for team IDs in data attributes
                elements_with_team_id = soup.find_all(attrs={'data-team-id': True})
                for elem in elements_with_team_id:
                    team_id = elem.get('data-team-id')
                    if team_id and team_id.isdigit():
                        team_ids.add(team_id)
                
                # Method 3: Look for jsonTeamRegs JSON data (primary method for GotSport events)
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        # Look for jsonTeamRegs = [...] pattern
                        # Use proper bracket matching to handle large/nested JSON arrays
                        json_match = re.search(r'jsonTeamRegs\s*=\s*(\[)', script.string, re.DOTALL)
                        if json_match:
                            try:
                                import json
                                # Find the start position
                                start_pos = json_match.start(1)
                                # Find the matching closing bracket
                                bracket_count = 0
                                in_string = False
                                escape_next = False
                                end_pos = start_pos
                                
                                for i in range(start_pos, len(script.string)):
                                    char = script.string[i]
                                    
                                    if escape_next:
                                        escape_next = False
                                        continue
                                    
                                    if char == '\\':
                                        escape_next = True
                                        continue
                                    
                                    if char == '"' and not escape_next:
                                        in_string = not in_string
                                        continue
                                    
                                    if not in_string:
                                        if char == '[':
                                            bracket_count += 1
                                        elif char == ']':
                                            bracket_count -= 1
                                            if bracket_count == 0:
                                                end_pos = i + 1
                                                break
                                
                                # Extract the full JSON array
                                json_str = script.string[start_pos:end_pos]
                                teams_json = json.loads(json_str)
                                for team in teams_json:
                                    team_id = str(team.get('id', ''))
                                    if team_id and team_id.isdigit():
                                        team_ids.add(team_id)
                                logger.debug(f"Extracted {len(teams_json)} teams from jsonTeamRegs")
                            except (json.JSONDecodeError, Exception) as e:
                                logger.warning(f"Failed to parse jsonTeamRegs: {e}")
                        
                        # Also look for patterns like "team_id": 123456 or team_id: 123456
                        matches = re.findall(r'["\']?team_id["\']?\s*[:=]\s*(\d+)', script.string, re.IGNORECASE)
                        team_ids.update(matches)
                        
                        # Also look for URLs with team IDs
                        url_matches = re.findall(r'teams?/(\d+)', script.string)
                        team_ids.update(url_matches)
                
                # Method 4: Look for team IDs in class names or IDs
                team_elements = soup.find_all(class_=re.compile(r'team', re.I))
                for elem in team_elements:
                    # Check if element has an ID that looks like a team ID
                    elem_id = elem.get('id', '')
                    if elem_id and elem_id.isdigit() and len(elem_id) >= 4:
                        team_ids.add(elem_id)
                
                if team_ids:
                    logger.info(f"Found {len(team_ids)} unique team IDs in event {event_id}")
                    break
                else:
                    logger.warning(f"No team IDs found in event {event_id} (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logger.error(f"Event {event_id} not found (404)")
                    return []
                if attempt < self.max_retries - 1:
                    logger.warning(f"HTTP error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"HTTP error after {self.max_retries} attempts: {e}")
                    raise
                    
            except (RequestsSSLError, Urllib3SSLError) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"SSL error (attempt {attempt + 1}): {e}, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    self.session.close()
                    self.session = self._init_http_session()
                    continue
                else:
                    logger.error(f"SSL error after {self.max_retries} attempts: {e}")
                    raise
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Error after {self.max_retries} attempts: {e}")
                    raise
        
        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))
        
        return list(team_ids)
    
    def extract_event_teams_by_bracket(self, event_id: str) -> Dict[str, List[EventTeam]]:
        """
        Extract teams from an event page, organized by bracket/group
        
        Args:
            event_id: GotSport event ID (e.g., "40550")
        
        Returns:
            Dictionary mapping bracket/group names to lists of EventTeam objects
            Format: { "SUPER PRO - U9B": [EventTeam(...), ...], ... }
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        brackets: Dict[str, List[EventTeam]] = {}
        
        logger.info(f"Extracting teams by bracket from event {event_id}: {event_url}")
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(event_url, timeout=self.timeout)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for bracket/division sections
                # GotSport typically organizes by age group and division (e.g., "SUPER PRO - U9B")
                
                # Method 1: Look for schedule/division headers
                # Common patterns: h3, h4, h5 with bracket names, or divs with class containing "bracket", "division", "group"
                bracket_headers = soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6'], string=re.compile(
                    r'(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|PREMIER|CHAMPIONSHIP|DIVISION|GROUP|BRACKET)',
                    re.IGNORECASE
                ))
                
                # Method 2: Look for age group headers (U7, U8, U9, etc.)
                age_headers = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'U\d+\s+(Schedule|Boys|Girls|B|G)', re.IGNORECASE))
                
                # Method 3: Look for division/bracket containers
                # Common class names: bracket, division, group, pool, flight
                bracket_containers = soup.find_all(
                    class_=re.compile(r'(bracket|division|group|pool|flight|schedule)', re.I)
                )
                
                # Method 4: Parse the structure - look for sections that contain team lists
                # GotSport often has structure like:
                # <div class="schedule-section">
                #   <h3>SUPER PRO - U9B</h3>
                #   <div>...teams...</div>
                # </div>
                
                # Primary method: Extract from jsonTeamRegs and organize by bracket
                # Look for jsonTeamRegs JSON data
                scripts = soup.find_all('script')
                teams_data = []
                
                for script in scripts:
                    if script.string:
                        # Look for jsonTeamRegs = [...] pattern
                        # Use proper bracket matching to handle large/nested JSON arrays
                        json_match = re.search(r'jsonTeamRegs\s*=\s*(\[)', script.string, re.DOTALL)
                        if json_match:
                            try:
                                import json
                                # Find the start position
                                start_pos = json_match.start(1)
                                # Find the matching closing bracket
                                bracket_count = 0
                                in_string = False
                                escape_next = False
                                end_pos = start_pos
                                
                                for i in range(start_pos, len(script.string)):
                                    char = script.string[i]
                                    
                                    if escape_next:
                                        escape_next = False
                                        continue
                                    
                                    if char == '\\':
                                        escape_next = True
                                        continue
                                    
                                    if char == '"' and not escape_next:
                                        in_string = not in_string
                                        continue
                                    
                                    if not in_string:
                                        if char == '[':
                                            bracket_count += 1
                                        elif char == ']':
                                            bracket_count -= 1
                                            if bracket_count == 0:
                                                end_pos = i + 1
                                                break
                                
                                # Extract the full JSON array
                                json_str = script.string[start_pos:end_pos]
                                teams_json = json.loads(json_str)
                                teams_data = teams_json
                                logger.debug(f"Found {len(teams_json)} teams in jsonTeamRegs")
                                break
                            except (json.JSONDecodeError, Exception) as e:
                                logger.warning(f"Failed to parse jsonTeamRegs: {e}")
                
                # If we found teams in jsonTeamRegs, organize them
                if teams_data:
                    # Look for bracket/division information in the HTML structure
                    # GotSport typically shows brackets like "SUPER PRO - U9B" in headers
                    all_headers = soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6', 'b', 'strong'])
                    bracket_map = {}  # Map team IDs to bracket names
                    
                    # Try to find bracket names and associate with teams
                    # Look for headers that contain bracket information
                    for header in all_headers:
                        header_text = header.get_text(strip=True)
                        # Look for bracket patterns like "SUPER PRO - U9B", "GOLD - U8B", etc.
                        if re.search(r'(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|PREMIER|CHAMPIONSHIP)', header_text, re.I):
                            # This looks like a bracket header
                            # Look for team links or data near this header
                            parent = header.find_parent()
                            if parent:
                                # Look for team IDs in nearby elements (within the same section)
                                # Check siblings and children
                                team_links = parent.find_all('a', href=re.compile(r'/teams?/\d+'))
                                for link in team_links:
                                    href = link.get('href', '')
                                    match = re.search(r'/teams?/(\d+)', href)
                                    if match:
                                        bracket_map[match.group(1)] = header_text
                                
                                # Also check in the same container for any team references
                                # Look for data attributes or IDs that might reference teams
                                team_refs = parent.find_all(attrs={'data-team-id': True})
                                for ref in team_refs:
                                    team_id = ref.get('data-team-id')
                                    if team_id and team_id.isdigit():
                                        bracket_map[team_id] = header_text
                    
                    # Also look for bracket names in button text or schedule links
                    # GotSport often uses buttons for bracket selection
                    bracket_buttons = soup.find_all(['button', 'a'], string=re.compile(
                        r'(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE).*U\d+', re.I
                    ))
                    for button in bracket_buttons:
                        bracket_text = button.get_text(strip=True)
                        if bracket_text:
                            # Find teams associated with this bracket button
                            # Look in the same section or following content
                            parent = button.find_parent()
                            if parent:
                                team_links = parent.find_all('a', href=re.compile(r'/teams?/\d+'))
                                for link in team_links:
                                    href = link.get('href', '')
                                    match = re.search(r'/teams?/(\d+)', href)
                                    if match:
                                        if match.group(1) not in bracket_map:
                                            bracket_map[match.group(1)] = bracket_text
                    
                    # Organize teams by bracket
                    for team in teams_data:
                        team_id = str(team.get('id', ''))
                        if not team_id or not team_id.isdigit():
                            continue
                        
                        # Try to find bracket name
                        bracket_name = bracket_map.get(team_id)
                        if not bracket_name:
                            # Try to infer from team data
                            age_group = team.get('display_age_group', '')
                            gender = team.get('display_gender', '')
                            if age_group and gender:
                                # Try to find matching bracket
                                for header_text in bracket_map.values():
                                    if age_group in header_text and (gender[0].upper() in header_text or 'B' in header_text or 'G' in header_text):
                                        bracket_name = header_text
                                        break
                            
                        if not bracket_name:
                            # Create bracket name from team data
                            age_group = team.get('display_age_group', 'Unknown')
                            gender_code = 'B' if 'Male' in team.get('display_gender', '') or team.get('gender', '').lower() == 'm' else 'G'
                            bracket_name = f"{age_group}{gender_code}"
                        
                        if bracket_name not in brackets:
                            brackets[bracket_name] = []
                        
                        # Extract team info
                        team_name = team.get('full_name', f"Team {team_id}")
                        gender_display = team.get('display_gender', '')
                        gender_code = 'M' if 'Male' in gender_display or team.get('gender', '').lower() == 'm' else 'F'
                        
                        # Determine ACTUAL age group (not bracket age)
                        # Method 1: Try to infer from team name (look for birth year)
                        actual_age_group = None
                        birth_year_match = re.search(r'\b(20\d{2})\b', team_name)
                        if birth_year_match:
                            birth_year = int(birth_year_match.group(1))
                            # Calculate age group: U11 = 2015, U12 = 2014, etc.
                            # Age group is the year they turn that age, not current age
                            current_year = 2025
                            # For 2025: U11 = 2015 birth year, U12 = 2014 birth year
                            # Formula: age_group = current_year - birth_year + 1
                            age_group_number = current_year - birth_year + 1
                            if 7 <= age_group_number <= 19:  # Valid age range
                                actual_age_group = f"U{age_group_number}"
                        
                        # Method 2: Use display_age_group if it seems reasonable
                        # But be careful - it might be the bracket age, not actual age
                        if not actual_age_group:
                            display_age = team.get('display_age_group', '')
                            # Only trust it if team name doesn't contradict it
                            if display_age and not birth_year_match:
                                actual_age_group = display_age
                        
                        # Method 3: Use numeric age field if available (might be actual age)
                        if not actual_age_group:
                            numeric_age = team.get('age')
                            if numeric_age and isinstance(numeric_age, int) and 7 <= numeric_age <= 19:
                                actual_age_group = f"U{numeric_age}"
                        
                        # Fallback: Use bracket age (not ideal, but better than nothing)
                        if not actual_age_group:
                            bracket_age_match = re.search(r'U(\d+)', bracket_name, re.I)
                            if bracket_age_match:
                                actual_age_group = f"U{bracket_age_match.group(1)}"
                            else:
                                actual_age_group = 'Unknown'
                        
                        # Determine if team is playing up
                        playing_up = False
                        if actual_age_group and bracket_name:
                            # Extract age number from bracket name (e.g., "U12B" -> 12)
                            bracket_age_match = re.search(r'U(\d+)', bracket_name, re.I)
                            actual_age_match = re.search(r'U(\d+)', actual_age_group, re.I)
                            
                            if bracket_age_match and actual_age_match:
                                bracket_age = int(bracket_age_match.group(1))
                                actual_age = int(actual_age_match.group(1))
                                # Playing up if bracket age > actual age
                                playing_up = bracket_age > actual_age
                        
                        brackets[bracket_name].append(EventTeam(
                            team_id=team_id,
                            team_name=team_name,
                            bracket_name=bracket_name,
                            age_group=actual_age_group,  # Use actual age group, not bracket age
                            gender=gender_code,
                            division=bracket_name,
                            playing_up=playing_up
                        ))
                
                # Fallback: Try to find bracket structure by looking for headers followed by team lists
                if not brackets:
                    current_bracket = None
                    all_headers = soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6'])
                    for header in all_headers:
                        header_text = header.get_text(strip=True)
                        
                        # Check if this looks like a bracket/division name
                        if re.search(r'(SUPER|ELITE|PRO|BLACK|GOLD|SILVER|BRONZE|U\d+)', header_text, re.I):
                            current_bracket = header_text
                            if current_bracket not in brackets:
                                brackets[current_bracket] = []
                            
                            # Look for teams in the following siblings or parent container
                            parent = header.find_parent()
                            if parent:
                                # Look for team links in this section
                                team_links = parent.find_all('a', href=re.compile(r'/teams?/\d+'))
                                for link in team_links:
                                    href = link.get('href', '')
                                    match = re.search(r'/teams?/(\d+)', href)
                                    if match:
                                        team_id = match.group(1)
                                        team_name = link.get_text(strip=True) or link.get('title', '') or f"Team {team_id}"
                                        
                                        # Extract age/gender from bracket name if possible
                                        age_group = None
                                        gender = None
                                        if re.search(r'U(\d+)', header_text, re.I):
                                            age_match = re.search(r'U(\d+)', header_text, re.I)
                                            age_group = f"U{age_match.group(1)}"
                                        if re.search(r'\b(B|Boys|M|Male)\b', header_text, re.I):
                                            gender = 'M'
                                        elif re.search(r'\b(G|Girls|F|Female)\b', header_text, re.I):
                                            gender = 'F'
                                        
                                        brackets[current_bracket].append(EventTeam(
                                            team_id=team_id,
                                            team_name=team_name,
                                            bracket_name=current_bracket,
                                            age_group=age_group,
                                            gender=gender,
                                            division=current_bracket
                                        ))
                
                # If we didn't find organized brackets, try a simpler approach:
                # Extract all teams and try to infer brackets from the page structure
                if not brackets:
                    logger.debug("No bracket structure found, extracting all teams...")
                    team_ids = self.extract_event_teams(event_id)
                    
                    # Try to find any bracket/division context for teams
                    # Look for team links and their surrounding context
                    team_links = soup.find_all('a', href=re.compile(r'/teams?/\d+'))
                    for link in team_links:
                        href = link.get('href', '')
                        match = re.search(r'/teams?/(\d+)', href)
                        if match:
                            team_id = match.group(1)
                            team_name = link.get_text(strip=True) or f"Team {team_id}"
                            
                            # Try to find the nearest bracket/division header
                            bracket_name = "Unknown Bracket"
                            parent = link.find_parent()
                            if parent:
                                # Look for headers in parent chain
                                for ancestor in parent.parents:
                                    header = ancestor.find(['h2', 'h3', 'h4', 'h5', 'h6'])
                                    if header:
                                        header_text = header.get_text(strip=True)
                                        if header_text and len(header_text) < 100:  # Reasonable header length
                                            bracket_name = header_text
                                            break
                            
                            if bracket_name not in brackets:
                                brackets[bracket_name] = []
                            
                            brackets[bracket_name].append(EventTeam(
                                team_id=team_id,
                                team_name=team_name,
                                bracket_name=bracket_name,
                                division=bracket_name
                            ))
                
                if brackets:
                    total_teams = sum(len(teams) for teams in brackets.values())
                    logger.info(f"Found {total_teams} teams in {len(brackets)} brackets for event {event_id}")
                    break
                else:
                    logger.warning(f"No teams found in event {event_id} (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logger.error(f"Event {event_id} not found (404)")
                    return {}
                if attempt < self.max_retries - 1:
                    logger.warning(f"HTTP error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"HTTP error after {self.max_retries} attempts: {e}")
                    raise
                    
            except (RequestsSSLError, Urllib3SSLError) as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"SSL error (attempt {attempt + 1}): {e}, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    self.session.close()
                    self.session = self._init_http_session()
                    continue
                else:
                    logger.error(f"SSL error after {self.max_retries} attempts: {e}")
                    raise
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"Error after {self.max_retries} attempts: {e}")
                    raise
        
        # Rate limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))
        
        return brackets
    
    def extract_team_ids_from_schedules(self, event_id: str) -> Set[str]:
        """
        Extract team IDs from schedule pages (more reliable than event registration page)
        
        Args:
            event_id: GotSport event ID
        
        Returns:
            Set of team IDs found in schedule pages
        """
        team_ids: Set[str] = set()
        event_url = f"{self.EVENT_BASE}/{event_id}"
        
        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all schedule links
            schedule_links = soup.find_all('a', href=re.compile(r'/schedules\?.*'))
            
            for link in schedule_links:
                href = link.get('href', '')
                # Schedule URLs can be:
                # /org_event/events/{event_id}/schedules?age=12&gender=m
                # /org_event/events/{event_id}/schedules?group=366834
                if 'schedules?' in href:
                    # Make absolute URL if needed
                    if href.startswith('/'):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href
                    
                    try:
                        schedule_response = self.session.get(schedule_url, timeout=self.timeout)
                        schedule_response.raise_for_status()
                        schedule_soup = BeautifulSoup(schedule_response.text, 'html.parser')
                        
                        # Extract team IDs from schedule page URLs
                        # Look for links like: schedules?team=3616623
                        team_urls = schedule_soup.find_all('a', href=re.compile(r'schedules\?team=\d+'))
                        for team_link in team_urls:
                            match = re.search(r'team=(\d+)', team_link.get('href', ''))
                            if match:
                                team_ids.add(match.group(1))
                        
                        # Also look in the HTML content for team IDs
                        # Some pages have team IDs in data attributes or other places
                        all_links = schedule_soup.find_all('a', href=True)
                        for link in all_links:
                            href = link.get('href', '')
                            # Look for any URL pattern with team ID
                            match = re.search(r'team[=_](\d+)', href, re.I)
                            if match:
                                team_ids.add(match.group(1))
                        
                        time.sleep(0.5)  # Rate limiting between schedule pages
                    except Exception as e:
                        logger.debug(f"Error fetching schedule page {schedule_url}: {e}")
                        continue
            
            logger.info(f"Extracted {len(team_ids)} team IDs from schedule pages")
        except Exception as e:
            logger.warning(f"Error extracting team IDs from schedules: {e}")
        
        return team_ids
    
    def extract_event_dates(self, event_id: str) -> Optional[Tuple[date, date]]:
        """
        Extract actual event start and end dates from event page or schedule pages
        
        Args:
            event_id: GotSport event ID
        
        Returns:
            Tuple of (start_date, end_date) or None if not found
        """
        event_url = f"{self.EVENT_BASE}/{event_id}"
        dates_found = []
        
        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Method 1: Look for date text in the event description/header
            # Common patterns: "December 5-7, 2025", "Dec 5-7, 2025", "12/5/2025 - 12/7/2025"
            date_patterns = [
                r'([A-Za-z]+)\s+(\d+)[-–]\s*(\d+),\s*(\d{4})',  # "December 5-7, 2025"
                r'([A-Za-z]+)\s+(\d+)\s+through\s+([A-Za-z]+)?\s*(\d+),\s*(\d{4})',  # "December 5 through 7, 2025"
                r'(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{4})',  # "12/5/2025 - 12/7/2025"
            ]
            
            # Search in main content area
            main_content = soup.find('main') or soup.find('body')
            if main_content:
                text = main_content.get_text()
                for pattern in date_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        # Try to parse the dates
                        try:
                            if len(match.groups()) == 4:  # "December 5-7, 2025"
                                month_name = match.group(1)
                                start_day = int(match.group(2))
                                end_day = int(match.group(3))
                                year = int(match.group(4))
                                
                                month_map = {
                                    'january': 1, 'february': 2, 'march': 3, 'april': 4,
                                    'may': 5, 'june': 6, 'july': 7, 'august': 8,
                                    'september': 9, 'october': 10, 'november': 11, 'december': 12,
                                    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                                    'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                                    'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                                }
                                month = month_map.get(month_name.lower()[:3])
                                if month:
                                    start_date = date(year, month, start_day)
                                    end_date = date(year, month, end_day)
                                    return (start_date, end_date)
                            elif len(match.groups()) == 6:  # "12/5/2025 - 12/7/2025"
                                start_month = int(match.group(1))
                                start_day = int(match.group(2))
                                start_year = int(match.group(3))
                                end_month = int(match.group(4))
                                end_day = int(match.group(5))
                                end_year = int(match.group(6))
                                start_date = date(start_year, start_month, start_day)
                                end_date = date(end_year, end_month, end_day)
                                return (start_date, end_date)
                        except (ValueError, KeyError):
                            continue
            
            # Method 2: Extract dates from schedule pages (more reliable)
            # Get dates from actual game schedules
            schedule_links = soup.find_all('a', href=re.compile(r'/schedules\?.*'))
            schedule_urls = set()
            
            for link in schedule_links:
                href = link.get('href', '')
                if 'schedules?' in href:
                    if href.startswith('/'):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href
                    schedule_urls.add(schedule_url)
            
            # Sample a few schedule pages to find date range
            for schedule_url in list(schedule_urls)[:3]:  # Check first 3 schedule pages
                try:
                    schedule_response = self.session.get(schedule_url, timeout=self.timeout)
                    schedule_response.raise_for_status()
                    schedule_soup = BeautifulSoup(schedule_response.text, 'html.parser')
                    
                    # Look for date headers or date cells in tables
                    # Dates appear in format "Nov 28, 2025" or "Friday, Nov 28, 2025"
                    date_elements = schedule_soup.find_all(string=re.compile(r'[A-Za-z]+\s+\d+,\s+\d{4}'))
                    for date_text in date_elements:
                        date_match = re.search(r'([A-Za-z]+)\s+(\d+),\s+(\d{4})', date_text)
                        if date_match:
                            month_name = date_match.group(1)
                            day = int(date_match.group(2))
                            year = int(date_match.group(3))
                            
                            month_map = {
                                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                                'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                                'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                            }
                            month = month_map.get(month_name.lower()[:3])
                            if month:
                                try:
                                    game_date = date(year, month, day)
                                    dates_found.append(game_date)
                                except ValueError:
                                    continue
                    
                    time.sleep(0.3)  # Rate limiting
                except Exception as e:
                    logger.debug(f"Error checking schedule page for dates: {e}")
                    continue
            
            # If we found dates from schedule pages, return the range
            if dates_found:
                start_date = min(dates_found)
                end_date = max(dates_found)
                return (start_date, end_date)
        
        except Exception as e:
            logger.debug(f"Error extracting event dates: {e}")
        
        return None
    
    def _resolve_api_team_id_from_event_page(
        self,
        event_id: str,
        registration_id: str,
        team_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve GotSport API team ID from event registration ID by following the team's event page.
        
        Flow:
        1. Go to team's event page: /org_event/events/{event_id}/schedules?team={registration_id}
        2. Find the "view rankings" link
        3. Extract API team ID from rankings URL: rankings.gotsport.com/teams/{api_team_id}
        
        Args:
            event_id: GotSport event ID
            registration_id: Event registration ID (from schedule page links)
            team_name: Optional team name for logging
        
        Returns:
            API team ID if found, None otherwise
        """
        try:
            # Step 1: Go to team's event page
            team_event_url = f"{self.EVENT_BASE}/{event_id}/schedules?team={registration_id}"
            response = self.session.get(team_event_url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Step 2: Find "view rankings" link
            # Look for links containing "rankings" or "view rankings"
            rankings_links = soup.find_all('a', href=re.compile(r'rankings\.gotsport\.com/teams/\d+', re.I))
            
            if not rankings_links:
                # Try alternative patterns - might be in text like "View Rankings"
                all_links = soup.find_all('a', href=True)
                for link in all_links:
                    href = link.get('href', '')
                    if 'rankings' in href.lower() and '/teams/' in href:
                        rankings_links.append(link)
                        break
            
            # Step 3: Extract API team ID from rankings URL
            for link in rankings_links:
                href = link.get('href', '')
                # Extract team ID from rankings URL: rankings.gotsport.com/teams/{id}
                match = re.search(r'rankings\.gotsport\.com/teams/(\d+)', href, re.I)
                if match:
                    api_team_id = match.group(1)
                    logger.debug(f"Resolved API team ID {api_team_id} from rankings link for {team_name or registration_id}")
                    return api_team_id
            
            logger.debug(f"No rankings link found for team {team_name or registration_id} on event page")
            return None
            
        except Exception as e:
            logger.debug(f"Error resolving API team ID from event page for {team_name or registration_id}: {e}")
            return None
    
    def scrape_games_from_schedule_pages(
        self,
        event_id: str,
        event_name: Optional[str] = None,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games directly from schedule pages (bypasses API team IDs)
        
        Args:
            event_id: GotSport event ID
            event_name: Optional event name for metadata
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects from schedule pages
        """
        games: List[GameData] = []
        event_url = f"{self.EVENT_BASE}/{event_id}"
        
        logger.info(f"Scraping games from schedule pages for event {event_id}")
        
        try:
            # Get the main event page to find all schedule links
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all schedule links (age/gender combinations and group-specific)
            schedule_links = soup.find_all('a', href=re.compile(r'/schedules\?.*'))
            schedule_urls = set()
            
            for link in schedule_links:
                href = link.get('href', '')
                if 'schedules?' in href:
                    if href.startswith('/'):
                        schedule_url = f"{self.BASE_URL}{href}"
                    else:
                        schedule_url = href
                    schedule_urls.add(schedule_url)
            
            logger.info(f"Found {len(schedule_urls)} schedule pages to scrape")
            
            # Cache for resolved API team IDs (registration_id -> api_team_id)
            # This avoids hitting the same team's event page multiple times
            api_team_id_cache: Dict[str, Optional[str]] = {}
            
            # Extract API team IDs and team name mapping from event page
            # This maps team names to API team IDs (from jsonTeamRegs)
            teams_by_name: Dict[str, str] = {}  # team_name -> api_team_id
            try:
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        json_match = re.search(r'jsonTeamRegs\s*=\s*(\[)', script.string, re.DOTALL)
                        if json_match:
                            import json
                            start_pos = json_match.start(1)
                            bracket_count = 0
                            in_string = False
                            escape_next = False
                            end_pos = start_pos
                            
                            for i in range(start_pos, len(script.string)):
                                char = script.string[i]
                                if escape_next:
                                    escape_next = False
                                    continue
                                if char == '\\':
                                    escape_next = True
                                    continue
                                if char == '"' and not escape_next:
                                    in_string = not in_string
                                    continue
                                if not in_string:
                                    if char == '[':
                                        bracket_count += 1
                                    elif char == ']':
                                        bracket_count -= 1
                                        if bracket_count == 0:
                                            end_pos = i + 1
                                            break
                            
                            json_str = script.string[start_pos:end_pos]
                            teams_json = json.loads(json_str)
                            for team in teams_json:
                                team_id = str(team.get('id', ''))
                                team_name = team.get('full_name', '') or team.get('name', '')
                                if team_id and team_id.isdigit() and team_name:
                                    # Normalize team name for matching (remove extra spaces, lowercase)
                                    normalized_name = ' '.join(team_name.split()).lower()
                                    teams_by_name[normalized_name] = team_id
                            logger.debug(f"Extracted {len(teams_by_name)} teams from jsonTeamRegs for name-to-ID mapping")
            except Exception as e:
                logger.warning(f"Error extracting teams from jsonTeamRegs: {e}")
            
            # Scrape games from each schedule page
            for schedule_url in schedule_urls:
                try:
                    schedule_games = self._parse_games_from_schedule_page(
                        schedule_url, event_id, event_name, since_date, teams_by_name, api_team_id_cache
                    )
                    games.extend(schedule_games)
                    logger.debug(f"Found {len(schedule_games)} games from {schedule_url}")
                    time.sleep(0.5)  # Rate limiting
                except Exception as e:
                    logger.warning(f"Error parsing schedule page {schedule_url}: {e}")
                    continue
            
            logger.info(f"Total games scraped from schedule pages: {len(games)}")
        except Exception as e:
            logger.error(f"Error scraping games from schedule pages: {e}")
        
        return games
    
    def _parse_games_from_schedule_page(
        self,
        schedule_url: str,
        event_id: str,
        event_name: Optional[str],
        since_date: Optional[datetime],
        teams_by_name: Optional[Dict[str, str]] = None,
        api_team_id_cache: Optional[Dict[str, Optional[str]]] = None
    ) -> List[GameData]:
        """Parse games from a single schedule page"""
        if api_team_id_cache is None:
            api_team_id_cache = {}
        if teams_by_name is None:
            teams_by_name = {}
        
        games: List[GameData] = []
        
        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all game tables (there may be multiple tables for different dates/brackets)
            tables = soup.find_all('table')
            
            for table in tables:
                # Find table headers to identify columns
                header_row = table.find('thead')
                if not header_row:
                    header_row = table.find('tr')
                
                if not header_row:
                    continue
                
                # Get column indices
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]
                
                # Find column indices
                try:
                    match_col = headers.index('match #')
                except ValueError:
                    match_col = None
                
                try:
                    time_col = headers.index('time')
                except ValueError:
                    time_col = None
                
                try:
                    home_col = headers.index('home team')
                except ValueError:
                    home_col = None
                
                try:
                    results_col = headers.index('results')
                except ValueError:
                    results_col = None
                
                try:
                    away_col = headers.index('away team')
                except ValueError:
                    away_col = None
                
                try:
                    location_col = headers.index('location')
                except ValueError:
                    location_col = None
                
                try:
                    division_col = headers.index('division')
                except ValueError:
                    division_col = None
                
                # If we don't have the required columns, skip this table
                if home_col is None or away_col is None:
                    continue
                
                # Parse game rows
                rows = table.find_all('tr')[1:]  # Skip header row
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < max(filter(None, [home_col, away_col, results_col])):
                        continue
                    
                    try:
                        # Extract home team
                        home_cell = cells[home_col] if home_col is not None and home_col < len(cells) else None
                        home_team_name = home_cell.get_text(strip=True) if home_cell else None
                        home_team_id = None
                        if home_cell:
                            # Try to get API team ID from link (might be /teams/{id} or team={id})
                            home_link = home_cell.find('a')
                            if home_link:
                                href = home_link.get('href', '')
                                # Check for /teams/{id} pattern (API team ID) - this is the actual API team ID
                                api_match = re.search(r'/teams?/(\d+)', href)
                                if api_match:
                                    home_team_id = api_match.group(1)
                                else:
                                    # Check for team={id} pattern (event registration ID)
                                    reg_match = re.search(r'team=(\d+)', href)
                                    if reg_match:
                                        reg_id = reg_match.group(1)
                                        # Check cache first
                                        if reg_id in api_team_id_cache:
                                            home_team_id = api_team_id_cache[reg_id]
                                        else:
                                            # Resolve API team ID by following the team's event page to rankings link
                                            home_team_id = self._resolve_api_team_id_from_event_page(event_id, reg_id, home_team_name)
                                            api_team_id_cache[reg_id] = home_team_id
                                        
                                        if not home_team_id:
                                            # Fallback to name-based mapping
                                            if teams_by_name and home_team_name:
                                                normalized_name = ' '.join(home_team_name.split()).lower()
                                                home_team_id = teams_by_name.get(normalized_name)
                                            # Last resort: use registration ID
                                            if not home_team_id:
                                                home_team_id = reg_id
                        
                        # Extract away team
                        away_cell = cells[away_col] if away_col is not None and away_col < len(cells) else None
                        away_team_name = away_cell.get_text(strip=True) if away_cell else None
                        away_team_id = None
                        if away_cell:
                            # Try to get API team ID from link (might be /teams/{id} or team={id})
                            away_link = away_cell.find('a')
                            if away_link:
                                href = away_link.get('href', '')
                                # Check for /teams/{id} pattern (API team ID) - this is the actual API team ID
                                api_match = re.search(r'/teams?/(\d+)', href)
                                if api_match:
                                    away_team_id = api_match.group(1)
                                else:
                                    # Check for team={id} pattern (event registration ID)
                                    reg_match = re.search(r'team=(\d+)', href)
                                    if reg_match:
                                        reg_id = reg_match.group(1)
                                        # Check cache first
                                        if reg_id in api_team_id_cache:
                                            away_team_id = api_team_id_cache[reg_id]
                                        else:
                                            # Resolve API team ID by following the team's event page to rankings link
                                            away_team_id = self._resolve_api_team_id_from_event_page(event_id, reg_id, away_team_name)
                                            api_team_id_cache[reg_id] = away_team_id
                                        
                                        if not away_team_id:
                                            # Fallback to name-based mapping
                                            if teams_by_name and away_team_name:
                                                normalized_name = ' '.join(away_team_name.split()).lower()
                                                away_team_id = teams_by_name.get(normalized_name)
                                            # Last resort: use registration ID
                                            if not away_team_id:
                                                away_team_id = reg_id
                        
                        if not home_team_name or not away_team_name:
                            continue
                        
                        # Extract score
                        goals_for = None
                        goals_against = None
                        if results_col is not None and results_col < len(cells):
                            score_cell = cells[results_col]
                            score_text = score_cell.get_text(strip=True)
                            # Parse score like "4 - 6" or "4-6"
                            score_match = re.search(r'(\d+)\s*[-–]\s*(\d+)', score_text)
                            if score_match:
                                goals_for = int(score_match.group(1))
                                goals_against = int(score_match.group(2))
                        
                        # Extract date/time
                        game_date_str = None
                        game_time_str = None
                        if time_col is not None and time_col < len(cells):
                            time_cell = cells[time_col]
                            time_text = time_cell.get_text(strip=True)
                            # Parse date/time like "Nov 28, 2025 4:00 PM HST"
                            # Try to parse the date
                            date_match = re.search(r'([A-Za-z]+)\s+(\d+),\s+(\d{4})', time_text)
                            if date_match:
                                month_name = date_match.group(1)
                                day = int(date_match.group(2))
                                year = int(date_match.group(3))
                                
                                month_map = {
                                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                                }
                                month = month_map.get(month_name[:3], None)
                                
                                if month:
                                    game_date_str = f"{year}-{month:02d}-{day:02d}"
                                    
                                    # Check if we should filter by date
                                    if since_date:
                                        game_date_obj = datetime.strptime(game_date_str, '%Y-%m-%d')
                                        if game_date_obj < since_date:
                                            continue
                        
                        # Extract venue
                        venue = None
                        if location_col is not None and location_col < len(cells):
                            location_cell = cells[location_col]
                            venue = location_cell.get_text(strip=True)
                        
                        # Extract division/competition
                        division = None
                        competition = None
                        if division_col is not None and division_col < len(cells):
                            division_cell = cells[division_col]
                            division = division_cell.get_text(strip=True)
                            competition = division
                        
                        # Extract age_group and gender from division/competition name
                        # Format examples: "SUPER PRO - U12B", "U14G", "U12 Boys", etc.
                        age_group = None
                        gender = None
                        if division:
                            # Try to extract U12, U14, etc.
                            age_match = re.search(r'U(\d+)', division, re.I)
                            if age_match:
                                age_group = f"U{age_match.group(1)}"
                            
                            # Try to extract gender (B=Boys/Male, G=Girls/Female)
                            # Validator expects: 'Male', 'Female', 'Boys', 'Girls', 'Coed'
                            if re.search(r'\b([BG])\b', division, re.I):
                                gender_code = re.search(r'\b([BG])\b', division, re.I).group(1).upper()
                                gender = 'Boys' if gender_code == 'B' else 'Girls'
                            elif re.search(r'\b(Boys?|Male)\b', division, re.I):
                                gender = 'Boys'
                            elif re.search(r'\b(Girls?|Female)\b', division, re.I):
                                gender = 'Girls'
                        
                        # Determine result
                        result = None
                        if goals_for is not None and goals_against is not None:
                            if goals_for > goals_against:
                                result = 'W'  # Home team wins
                            elif goals_for < goals_against:
                                result = 'L'  # Home team loses
                            else:
                                result = 'D'  # Draw
                        
                        # Create GameData for home team perspective
                        if game_date_str:
                            meta = {
                                'source_url': schedule_url,
                                'scraped_at': datetime.now().isoformat(),
                                'event_name': event_name or f"Event {event_id}",
                                'match_id': f"{event_id}_{home_team_id}_{away_team_id}_{game_date_str}" if home_team_id and away_team_id else None,
                                'age_group': age_group,
                                'gender': gender
                            }
                            
                            game = GameData(
                                provider_id=self.provider_code,
                                team_id=home_team_id or home_team_name,
                                opponent_id=away_team_id or away_team_name,
                                team_name=home_team_name,
                                opponent_name=away_team_name,
                                game_date=game_date_str,
                                home_away='H',
                                goals_for=goals_for,
                                goals_against=goals_against,
                                result=result,
                                competition=competition,
                                venue=venue,
                                meta=meta
                            )
                            games.append(game)
                            
                            # Also create GameData for away team perspective
                            away_meta = meta.copy()
                            away_meta['match_id'] = f"{event_id}_{away_team_id}_{home_team_id}_{game_date_str}" if home_team_id and away_team_id else None
                            
                            away_game = GameData(
                                provider_id=self.provider_code,
                                team_id=away_team_id or away_team_name,
                                opponent_id=home_team_id or home_team_name,
                                team_name=away_team_name,
                                opponent_name=home_team_name,
                                game_date=game_date_str,
                                home_away='A',
                                goals_for=goals_against,  # Swapped for away team
                                goals_against=goals_for,  # Swapped for away team
                                result='L' if result == 'W' else ('W' if result == 'L' else result),  # Inverted result
                                competition=competition,
                                venue=venue,
                                meta=away_meta
                            )
                            games.append(away_game)
                    
                    except Exception as e:
                        logger.debug(f"Error parsing game row: {e}")
                        continue
        
        except Exception as e:
            logger.warning(f"Error parsing schedule page {schedule_url}: {e}")
        
        return games
    
    def scrape_event_games(
        self, 
        event_id: str, 
        event_name: Optional[str] = None,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape all games from a specific event
        
        This method now scrapes games directly from schedule pages, which is more reliable
        than trying to use API team IDs (which often return 404s for event registration IDs).
        
        Args:
            event_id: GotSport event ID
            event_name: Optional event name to filter games (if None, will try to extract from page)
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects from the event
        """
        logger.info(f"Scraping games for event {event_id}")
        
        # Try to get event name from page if not provided
        if not event_name:
            try:
                event_url = f"{self.EVENT_BASE}/{event_id}"
                response = self.session.get(event_url, timeout=self.timeout)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                # Try to find event name in page title or headers
                title = soup.find('title')
                if title:
                    event_name = title.get_text(strip=True)
                if not event_name:
                    h1 = soup.find('h1')
                    if h1:
                        event_name = h1.get_text(strip=True)
            except Exception as e:
                logger.debug(f"Could not extract event name: {e}")
        
        # Scrape games directly from schedule pages
        games = self.scrape_games_from_schedule_pages(event_id, event_name, since_date)
        
        logger.info(f"Found {len(games)} games from event {event_id}")
        return games
    
    def scrape_event_by_url(
        self,
        event_url: str,
        event_name: Optional[str] = None,
        since_date: Optional[datetime] = None
    ) -> List[GameData]:
        """
        Scrape games from an event using its URL
        
        Args:
            event_url: Full URL to the event page (e.g., "https://system.gotsport.com/org_event/events/40550")
            event_name: Optional event name to filter games
            since_date: Only scrape games after this date
        
        Returns:
            List of GameData objects from the event
        """
        # Extract event ID from URL
        match = re.search(r'/events/(\d+)', event_url)
        if not match:
            raise ValueError(f"Could not extract event ID from URL: {event_url}")
        
        event_id = match.group(1)
        return self.scrape_event_games(event_id, event_name, since_date)
    
    def extract_teams_from_schedule_page(self, bracket_name: str, schedule_url: str) -> List[EventTeam]:
        """
        Extract teams from a bracket's schedule page
        
        Args:
            bracket_name: Name of the bracket (e.g., "SUPER PRO - U12B")
            schedule_url: URL to the schedule page
        
        Returns:
            List of EventTeam objects
        """
        teams = []
        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for team links in the schedule
            team_links = soup.find_all('a', href=re.compile(r'/teams?/\d+'))
            seen_team_ids = set()
            
            for link in team_links:
                href = link.get('href', '')
                match = re.search(r'/teams?/(\d+)', href)
                if match:
                    team_id = match.group(1)
                    if team_id not in seen_team_ids:
                        team_name = link.get_text(strip=True) or link.get('title', '') or f"Team {team_id}"
                        teams.append(EventTeam(
                            team_id=team_id,
                            team_name=team_name,
                            bracket_name=bracket_name
                        ))
                        seen_team_ids.add(team_id)
        except Exception as e:
            logger.warning(f"Error extracting teams from schedule page {schedule_url}: {e}")
        
        return teams
    
    def extract_teams_by_group_from_schedule_page(self, bracket_name: str, schedule_url: str) -> Dict[str, List[EventTeam]]:
        """Extract teams from a schedule page, organized by group"""
        groups: Dict[str, List[EventTeam]] = {}
        
        try:
            response = self.session.get(schedule_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for "Bracket A", "Bracket B", "Group A", "Pool A", etc.
            bracket_pattern = re.compile(r'(Bracket|Group|Pool|Flight)\s+([A-Z])', re.I)
            
            # Strategy: Find all tables and match them to their nearest preceding bracket header
            all_tables = soup.find_all('table')
            seen_team_ids = set()
            
            for table in all_tables:
                # Find the nearest bracket header before this table
                prev_header = table.find_previous(['h2', 'h3', 'h4', 'h5', 'h6', 'b', 'strong'])
                
                if prev_header:
                    prev_text = prev_header.get_text(strip=True)
                    prev_match = bracket_pattern.search(prev_text)
                    
                    if prev_match:
                        group_letter = prev_match.group(2).upper()
                        group_name = f"Group {group_letter}"
                        
                        if group_name not in groups:
                            groups[group_name] = []
                        
                        # Extract teams from this table
                        # Extract team links from this table
                        team_links = table.find_all('a', href=re.compile(r'team=\d+'))
                        for link in team_links:
                            href = link.get('href', '')
                            match = re.search(r'team=(\d+)', href)
                            if match:
                                team_id = match.group(1)
                                if team_id not in seen_team_ids:
                                    # Get team name from link text or nearby text
                                    team_name = link.get_text(strip=True)
                                    if not team_name:
                                        # Try to get from parent row
                                        parent_row = link.find_parent('tr')
                                        if parent_row:
                                            cells = parent_row.find_all('td')
                                            if len(cells) > 1:
                                                # Usually team name is in the second cell
                                                team_name = cells[1].get_text(strip=True) or f"Team {team_id}"
                                            else:
                                                team_name = link.get('title', '') or f"Team {team_id}"
                                        else:
                                            team_name = link.get('title', '') or f"Team {team_id}"
                                    
                                    # Clean up team name - remove duplicate club names
                                    # Handle cases like "Dynamos SC Dynamos SC 14B SC" -> "Dynamos SC 14B SC"
                                    if team_name:
                                        parts = team_name.split()
                                        # Remove consecutive duplicate words
                                        cleaned_parts = []
                                        prev = None
                                        for part in parts:
                                            if part != prev:
                                                cleaned_parts.append(part)
                                            prev = part
                                        team_name = ' '.join(cleaned_parts)
                                    
                                    groups[group_name].append(EventTeam(
                                        team_id=team_id,
                                        team_name=team_name,
                                        bracket_name=bracket_name,
                                        group_name=group_name
                                    ))
                                    seen_team_ids.add(team_id)
            
            # If no groups found, try alternative parsing by finding tables near bracket headers
            if not groups:
                # Find all bracket headers first
                bracket_headers = []
                for header in soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6', 'b', 'strong']):
                    header_text = header.get_text(strip=True)
                    bracket_match = bracket_pattern.search(header_text)
                    if bracket_match:
                        group_letter = bracket_match.group(2).upper()
                        bracket_headers.append((header, group_letter))
                
                # For each bracket header, find the nearest table
                for header, group_letter in bracket_headers:
                    group_name = f"Group {group_letter}"
                    if group_name not in groups:
                        groups[group_name] = []
                    
                    # Find table - look in next siblings or following elements
                    table = None
                    # Try next sibling
                    for sibling in header.next_siblings:
                        if hasattr(sibling, 'name') and sibling.name == 'table':
                            table = sibling
                            break
                    
                    # If not found, try find_next
                    if not table:
                        table = header.find_next('table')
                    
                    if table:
                        team_links = table.find_all('a', href=re.compile(r'team=\d+'))
                        for link in team_links:
                            href = link.get('href', '')
                            match = re.search(r'team=(\d+)', href)
                            if match:
                                team_id = match.group(1)
                                if team_id not in seen_team_ids:
                                    team_name = link.get_text(strip=True)
                                    if not team_name:
                                        parent_row = link.find_parent('tr')
                                        if parent_row:
                                            cells = parent_row.find_all('td')
                                            if len(cells) > 1:
                                                team_name = cells[1].get_text(strip=True) or f"Team {team_id}"
                                            else:
                                                team_name = link.get('title', '') or f"Team {team_id}"
                                        else:
                                            team_name = link.get('title', '') or f"Team {team_id}"
                                    
                                    # Clean duplicate words
                                    if team_name:
                                        parts = team_name.split()
                                        cleaned_parts = []
                                        prev = None
                                        for part in parts:
                                            if part != prev:
                                                cleaned_parts.append(part)
                                            prev = part
                                        team_name = ' '.join(cleaned_parts)
                                    
                                    groups[group_name].append(EventTeam(
                                        team_id=team_id,
                                        team_name=team_name,
                                        bracket_name=bracket_name,
                                        group_name=group_name
                                    ))
                                    seen_team_ids.add(team_id)
            
            # Final fallback: extract all teams and put them in Group A
            if not groups:
                team_links = soup.find_all('a', href=re.compile(r'team=\d+'))
                seen_team_ids = set()
                groups["Group A"] = []
                
                for link in team_links:
                    href = link.get('href', '')
                    match = re.search(r'team=(\d+)', href)
                    if match:
                        team_id = match.group(1)
                        if team_id not in seen_team_ids:
                            team_name = link.get_text(strip=True) or link.get('title', '') or f"Team {team_id}"
                            groups["Group A"].append(EventTeam(
                                team_id=team_id,
                                team_name=team_name,
                                bracket_name=bracket_name,
                                group_name="Group A"
                            ))
                            seen_team_ids.add(team_id)
            
            # If we only found one group but have multiple teams, try to split them
            # This handles cases where the HTML structure doesn't clearly separate groups
            if len(groups) == 1 and len(groups.get("Group A", [])) > 4:
                all_teams = groups["Group A"]
                total_teams = len(all_teams)
                
                # Split based on expected structure:
                # Super Pro: 2 groups of 4 (8 teams total)
                # Super Elite/Super Black: 2 groups of 3 (6 teams total)
                if total_teams == 8:
                    # Super Pro: split into 2 groups of 4
                    groups["Group A"] = all_teams[:4]
                    groups["Group B"] = all_teams[4:]
                elif total_teams == 6:
                    # Super Elite/Super Black: split into 2 groups of 3
                    groups["Group A"] = all_teams[:3]
                    groups["Group B"] = all_teams[3:]
                # Update group_name for each team
                for group_name, team_list in groups.items():
                    for team in team_list:
                        team.group_name = group_name
                            
        except Exception as e:
            logger.warning(f"Error extracting teams by group from schedule page {schedule_url}: {e}")
        
        return groups
    
    def list_event_teams(
        self,
        event_id: str = None,
        event_url: str = None
    ) -> Dict[str, List[EventTeam]]:
        """
        List all teams in an event, organized by bracket/group
        
        Args:
            event_id: GotSport event ID (e.g., "40550")
            event_url: Full URL to event page (alternative to event_id)
        
        Returns:
            Dictionary mapping bracket/group names to lists of EventTeam objects
        """
        if event_url:
            match = re.search(r'/events/(\d+)', event_url)
            if not match:
                raise ValueError(f"Could not extract event ID from URL: {event_url}")
            event_id = match.group(1)
        
        if not event_id:
            raise ValueError("Must provide either event_id or event_url")
        
        return self.extract_event_teams_by_bracket(event_id)
    
    def list_event_teams_with_groups(
        self,
        event_id: str = None,
        event_url: str = None
    ) -> Dict[str, Dict[str, List[EventTeam]]]:
        """
        List all teams in an event, organized by bracket and group (from schedule pages)
        
        Args:
            event_id: GotSport event ID (e.g., "40550")
            event_url: Full URL to event page (alternative to event_id)
        
        Returns:
            Dictionary mapping bracket names to groups, which map to lists of EventTeam objects
            Format: { "SUPER PRO - U12B": { "Group A": [EventTeam(...), ...], ... }, ... }
        """
        if event_url:
            match = re.search(r'/events/(\d+)', event_url)
            if not match:
                raise ValueError(f"Could not extract event ID from URL: {event_url}")
            event_id = match.group(1)
        
        if not event_id:
            raise ValueError("Must provide either event_id or event_url")
        
        event_url = f"{self.EVENT_BASE}/{event_id}"
        result: Dict[str, Dict[str, List[EventTeam]]] = {}
        
        logger.info(f"Extracting teams from schedule pages for event {event_id}: {event_url}")
        
        try:
            response = self.session.get(event_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all bracket headers with schedule links
            bracket_pattern = re.compile(r'(SUPER\s+(PRO|ELITE|BLACK|PLATINUM)|GOLD|SILVER|BRONZE).*?U\d+[BG]?', re.I)
            
            # Find bracket headers and their associated schedule links
            for element in soup.find_all(['strong', 'b', 'h3', 'h4', 'h5']):
                text = element.get_text(strip=True)
                if bracket_pattern.search(text):
                    bracket_name = text
                    
                    # Look for Schedule link near this bracket header
                    parent = element.find_parent()
                    if parent:
                        schedule_link = parent.find('a', href=re.compile(r'schedule', re.I))
                        if schedule_link:
                            schedule_href = schedule_link.get('href', '')
                            if not schedule_href.startswith('http'):
                                schedule_href = f"https://system.gotsport.com{schedule_href}" if schedule_href.startswith('/') else f"{event_url}/{schedule_href}"
                            
                            # Extract teams by group from schedule page
                            groups = self.extract_teams_by_group_from_schedule_page(bracket_name, schedule_href)
                            if groups:
                                result[bracket_name] = groups
                                total_teams = sum(len(teams) for teams in groups.values())
                                logger.info(f"Found {total_teams} teams in {len(groups)} groups for bracket {bracket_name}")
                            
                            # Rate limiting
                            if self.delay_min > 0 or self.delay_max > 0:
                                time.sleep(random.uniform(self.delay_min, self.delay_max))
                                
        except Exception as e:
            logger.warning(f"Error extracting teams by group from schedule pages: {e}")
        
        return result

