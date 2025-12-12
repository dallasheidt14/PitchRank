"""
Modular11 Schedule Spider

Scrapes youth soccer match results from https://www.modular11.com/schedule
using the internal API endpoint.

Supports BOTH MLS NEXT divisions:
- HD (Homegrown Division) - Top tier teams (tournament_id=12)
- AD (Academy Division) - Second tier teams (tournament_id=35)

Usage:
    # Scrape only Homegrown Division (HD):
    scrapy crawl modular11_schedule -a division=HD
    
    # Scrape only Academy Division (AD):
    scrapy crawl modular11_schedule -a division=AD
    
    # Scrape BOTH divisions (default):
    scrapy crawl modular11_schedule -a division=both

Full example:
    cd scrapers/modular11_scraper
    scrapy crawl modular11_schedule -a age_min=13 -a age_max=17 -a days_back=365 -a division=both
"""
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Generator, Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import FormRequest, Response

from modular11_scraper.items import Modular11GameItem


logger = logging.getLogger(__name__)


class Modular11ScheduleSpider(scrapy.Spider):
    """
    Spider for scraping Modular11.com schedule data.
    
    Modular11 is the platform for MLS NEXT youth soccer league.
    
    MLS NEXT has TWO divisions:
    - Homegrown Division (HD) - Top tier teams (MLS academies, Pro Player Pathway)
    - Academy Division (AD) - Second tier teams (regional academies)
    
    This spider:
    1. Posts to the internal API to fetch match data for each division
    2. Parses HTML response for match details
    3. Yields TWO items per game (home + away perspective)
    4. Tags each game with its division (HD or AD)
    5. Handles pagination automatically
    """
    
    name = "modular11_schedule"
    allowed_domains = ["www.modular11.com", "modular11.com"]
    
    # API endpoint
    API_URL = "https://www.modular11.com/public_schedule/league/get_matches"
    
    # Tournament IDs for each division
    # HD = Homegrown Division (top tier)
    # AD = Academy Division (second tier)
    TOURNAMENT_IDS = {
        'HD': '12',   # Homegrown Division - tournament_id=12
        'AD': '35',   # Academy Division - tournament_id=35
    }
    
    # Age group ID mapping (discovered from site inspection)
    # These are the same for both HD and AD
    AGE_GROUP_IDS = {
        13: "21",   # U13
        14: "22",   # U14
        15: "33",   # U15
        16: "14",   # U16
        17: "15",   # U17
        19: "26",   # U19 (not used by default)
    }
    
    # Reverse mapping for parsing
    AGE_ID_TO_GROUP = {v: f"U{k}" for k, v in AGE_GROUP_IDS.items()}
    
    def __init__(
        self,
        age_min: int = 13,
        age_max: int = 17,
        days_back: int = 365,
        division: str = 'both',
        *args,
        **kwargs
    ):
        """
        Initialize the spider with configurable parameters.
        
        Args:
            age_min: Minimum age group (default: 13 for U13)
            age_max: Maximum age group (default: 17 for U17)
            days_back: Number of days to look back (default: 365)
            division: Which division to scrape:
                      'HD' = Homegrown Division only (top tier)
                      'AD' = Academy Division only (second tier)
                      'both' = Both divisions (default)
        """
        super().__init__(*args, **kwargs)
        
        self.age_min = int(age_min)
        self.age_max = int(age_max)
        self.days_back = int(days_back)
        
        # Parse division parameter
        division_upper = division.upper().strip()
        if division_upper == 'HD':
            self.divisions_to_scrape = ['HD']
        elif division_upper == 'AD':
            self.divisions_to_scrape = ['AD']
        else:
            # Default: scrape both
            self.divisions_to_scrape = ['HD', 'AD']
        
        # Calculate date range
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.days_back)
        self.cutoff_date = self.start_date.date()
        
        # Build list of age group IDs to request
        self.age_group_ids = []
        for age in range(self.age_min, self.age_max + 1):
            if age in self.AGE_GROUP_IDS:
                self.age_group_ids.append(self.AGE_GROUP_IDS[age])
        
        # Statistics - track by division
        self.stats = {
            'games_scraped': 0,
            'games_scraped_HD': 0,
            'games_scraped_AD': 0,
            'games_skipped_no_score': 0,
            'games_skipped_date_filter': 0,
            'games_skipped_parse_error': 0,
            'pages_processed': 0,
        }
        
        logger.info(f"Initialized Modular11 spider:")
        logger.info(f"  Divisions: {', '.join(self.divisions_to_scrape)}")
        logger.info(f"  Age range: U{self.age_min} - U{self.age_max}")
        logger.info(f"  Age group IDs: {self.age_group_ids}")
        logger.info(f"  Date range: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}")
    
    def start_requests(self) -> Generator[FormRequest, None, None]:
        """Generate initial request to the API."""
        yield self._build_request(page=0)
    
    def _build_request(self, page: int = 0) -> FormRequest:
        """
        Build a FormRequest for the API.
        
        Args:
            page: Page number (0-indexed)
            
        Returns:
            FormRequest to the API endpoint
        """
        # Build form data
        formdata = {
            'open_page': str(page),
            'academy': '0',  # All academies
            'tournament': '12',  # MLS NEXT tournament ID
            'gender': '0',  # All genders (though MLS NEXT is boys-only)
            'brackets': '',
            'groups': '',
            'group': '',
            'match_number': '0',
            'status': 'all',  # Get all matches including completed
            'match_type': '2',  # League matches
            'schedule': '0',
            'team': '0',
            'teamPlayer': '0',
            'location': '0',
            'as_referee': '0',
            'start_date': self.start_date.strftime('%Y-%m-%d %H:%M:%S'),
            'end_date': self.end_date.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Add age group IDs (as array)
        # Note: We need to pass multiple age[] params
        # FormRequest handles this by passing a list
        
        return FormRequest(
            url=self.API_URL,
            formdata=formdata,
            callback=self.parse,
            meta={'page': page, 'age_ids': self.age_group_ids},
            dont_filter=True,
        )
    
    def _build_request_for_age(self, age_id: str, division: str, page: int = 0) -> scrapy.Request:
        """
        Build a GET Request for a specific age group and division.
        
        Args:
            age_id: The age group ID to request
            division: 'HD' or 'AD' - which division to request
            page: Page number (0-indexed)
            
        Returns:
            Request to the API endpoint (GET method)
        """
        tournament_id = self.TOURNAMENT_IDS.get(division, '12')
        
        # Build query parameters for GET request
        params = {
            'open_page': str(page),
            'academy': '0',
            'tournament': tournament_id,  # Different tournament ID per division
            'gender': '0',
            'age': age_id,  # Single age group (was age[] for POST, now just age for GET)
            'brackets': '',
            'groups': '',
            'group': '',
            'match_number': '0',
            'status': 'all',
            'match_type': '2',
            'schedule': '0',
            'team': '0',
            'teamPlayer': '0',
            'location': '0',
            'as_referee': '0',
            'start_date': self.start_date.strftime('%Y-%m-%d %H:%M:%S'),
            'end_date': self.end_date.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        url = f"{self.API_URL}?{urlencode(params)}"
        
        return scrapy.Request(
            url=url,
            callback=self.parse,
            meta={'page': page, 'age_id': age_id, 'division': division},
            dont_filter=True,
        )
    
    def start_requests(self) -> Generator[FormRequest, None, None]:
        """Generate initial requests - one per division/age group combination."""
        for division in self.divisions_to_scrape:
            for age_id in self.age_group_ids:
                age_group = self.AGE_ID_TO_GROUP.get(age_id, f"ID:{age_id}")
                logger.info(f"Starting request for {division} division, age group {age_group}")
                yield self._build_request_for_age(age_id, division=division, page=0)
    
    def parse(self, response: Response) -> Generator[Any, None, None]:
        """
        Parse API response HTML.
        
        The response contains match rows in a table format.
        Each row contains match details that we extract.
        """
        age_id = response.meta.get('age_id')
        division = response.meta.get('division', 'HD')  # HD or AD
        current_page = response.meta.get('page', 0)
        
        # Extract pagination info to determine total pages
        # Pattern: "1 page out of 83" - we need the second number (total pages)
        pagination_match = re.search(r'(\d+)\s*page\s*out\s*of\s*(\d+)', response.text)
        if pagination_match:
            total_pages = int(pagination_match.group(2))
            logger.debug(f"Pagination [{division}]: page {pagination_match.group(1)} of {total_pages}")
        else:
            # If no pagination info found, assume this is the only/last page
            total_pages = current_page + 1
            logger.debug(f"No pagination info found [{division}], assuming {total_pages} total pages")
        
        # Find all match rows (desktop version)
        match_rows = response.xpath('//div[contains(@class, "table-content-row") and contains(@class, "hidden-xs")]')
        
        if not match_rows:
            logger.warning(f"No match rows found [{division}] on page {current_page + 1}")
            # Check if we got an error message
            error_msg = response.xpath('//div[@style="font-weight: bold;color:red;"]//text()').getall()
            if error_msg:
                logger.error(f"API error [{division}]: {' '.join(error_msg)}")
            return
        
        age_group = self.AGE_ID_TO_GROUP.get(age_id, age_id)
        logger.info(f"Processing [{division}] {age_group} page {current_page + 1}: {len(match_rows)} matches found")
        self.stats['pages_processed'] += 1
        
        scraped_at = datetime.utcnow().isoformat()
        
        for row in match_rows:
            try:
                # Parse match data from row, include division
                match_data = self._parse_match_row(row, scraped_at, division)
                
                if match_data is None:
                    continue
                
                # Yield home and away perspective items
                for item in self._create_perspective_items(match_data):
                    yield item
                    self.stats['games_scraped'] += 1
                    self.stats[f'games_scraped_{division}'] += 1
                    
            except Exception as e:
                logger.error(f"Error parsing match row [{division}]: {e}")
                self.stats['games_skipped_parse_error'] += 1
                continue
        
        # Handle pagination - request next page if exists
        if current_page + 1 < total_pages:
            logger.info(f"Requesting [{division}] {age_group} page {current_page + 2} of {total_pages}")
            yield self._build_request_for_age(age_id, division=division, page=current_page + 1)
        else:
            logger.info(f"Completed scraping [{division}] {age_group}: {current_page + 1} pages")
    
    def _parse_match_row(self, row, scraped_at: str, division: str = 'HD') -> Optional[Dict]:
        """
        Parse a single match row and extract all data.
        
        Args:
            row: Scrapy Selector for the match row
            scraped_at: ISO timestamp string
            division: 'HD' or 'AD' - which division this match is from
            
        Returns:
            Dictionary with match data, or None if should be skipped
        """
        # Extract team-specific divisions from row data attributes
        # These differentiate HD/AD/Elite tiers within the same club
        home_division = row.xpath('./@js-match-group_home').get('')
        away_division = row.xpath('./@js-match-group_away').get('')
        match_bracket = row.xpath('./@js-match-bracket').get('')  # League, MLS NEXT Flex, etc.
        
        # Extract Match ID and Gender from first column
        first_col = row.xpath('.//div[contains(@class, "col-sm-1") and contains(@class, "pad-0")][1]')
        match_id = first_col.xpath('./text()').get('').strip()
        gender_text = first_col.xpath('./br/following-sibling::text()').get('').strip()
        
        # Normalize gender
        if 'MALE' in gender_text.upper():
            gender = 'M'
        elif 'FEMALE' in gender_text.upper():
            gender = 'F'
        else:
            gender = 'M'  # Default to male for MLS NEXT
        
        # Extract date and venue from second column
        date_col = row.xpath('.//div[contains(@class, "col-sm-2")][1]')
        date_text = date_col.xpath('./text()').get('').strip()
        venue = date_col.xpath('.//p[@data-title]/@data-title').get('')
        if not venue:
            venue = date_col.xpath('.//div[contains(@class, "container-location")]//p/text()').get('').strip()
        
        # Parse date (format: "01/13/24 09:00am")
        game_date = self._parse_date(date_text)
        if game_date is None:
            logger.warning(f"Could not parse date: {date_text}")
            self.stats['games_skipped_parse_error'] += 1
            return None
        
        # Check date filter
        if game_date < self.cutoff_date:
            self.stats['games_skipped_date_filter'] += 1
            return None
        
        # Extract age group from third column
        age_col = row.xpath('.//div[contains(@class, "col-sm-1") and contains(@class, "pad-0")][2]')
        age_group = age_col.xpath('./text()').get('').strip()
        
        # Extract competition and division
        # The structure is: Competition text <br> Division text
        comp_div_col = row.xpath('.//div[contains(@class, "col-sm-2")][2]')
        
        # Get all text content and split by newlines
        comp_div_texts = comp_div_col.xpath('.//text()').getall()
        comp_div_texts = [t.strip() for t in comp_div_texts if t.strip()]
        
        competition = comp_div_texts[0] if len(comp_div_texts) > 0 else ''
        division_text = comp_div_texts[1] if len(comp_div_texts) > 1 else ''
        
        # Extract teams container
        teams_container = row.xpath('.//div[contains(@class, "col-sm-6")]//div[contains(@class, "container-teams-info")]')
        
        # Home team
        home_team_name = teams_container.xpath(
            './/div[contains(@class, "container-first-team")]//p/@data-title'
        ).get('')
        if not home_team_name:
            home_team_name = teams_container.xpath(
                './/div[contains(@class, "container-first-team")]//p/text()'
            ).get('').strip()
        
        # Away team
        away_team_name = teams_container.xpath(
            './/div[contains(@class, "container-second-team")]//p/@data-title'
        ).get('')
        if not away_team_name:
            away_team_name = teams_container.xpath(
                './/div[contains(@class, "container-second-team")]//p/text()'
            ).get('').strip()
        
        # Extract team IDs from image URLs
        home_image_style = teams_container.xpath(
            './/div[contains(@class, "container-first-team")]/following-sibling::div[1]//div[contains(@class, "club-photo")]/@style'
        ).get('')
        away_image_style = teams_container.xpath(
            './/div[contains(@class, "container-second-team")]/preceding-sibling::div[1]//div[contains(@class, "club-photo")]/@style'
        ).get('')
        
        home_team_id = self._extract_academy_id(home_image_style) or self._generate_team_id(home_team_name)
        away_team_id = self._extract_academy_id(away_image_style) or self._generate_team_id(away_team_name)
        
        # Extract score
        score_span = teams_container.xpath('.//div[contains(@class, "container-score")]//span[contains(@class, "score-match-table")]')
        score_text = score_span.xpath('string(.)').get('').strip()
        
        # Parse score (format: "0 : 4" or "TBD")
        home_score, away_score = self._parse_score(score_text)
        
        if home_score is None or away_score is None:
            # Skip games without scores (unplayed)
            self.stats['games_skipped_no_score'] += 1
            return None
        
        return {
            'match_id': match_id,
            'game_date': game_date.strftime('%Y-%m-%d'),
            'venue': venue,
            'age_group': age_group,
            'gender': gender,
            'competition': competition,
            'division_name': division_text,  # The parsed division text from the page
            'mls_next_division': division,  # HD or AD - which MLS NEXT division
            'match_bracket': match_bracket,  # League, MLS NEXT Flex, etc.
            'home_division': home_division,  # Team's specific division (e.g., "Southwest (Pro Player Pathway)")
            'away_division': away_division,  # Opponent's specific division
            'home_team_name': home_team_name,
            'home_team_id': home_team_id,
            'away_team_name': away_team_name,
            'away_team_id': away_team_id,
            'home_score': home_score,
            'away_score': away_score,
            'scraped_at': scraped_at,
        }
    
    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """
        Parse date string from Modular11 format.
        
        Args:
            date_text: Date string like "01/13/24 09:00am"
            
        Returns:
            date object or None if parsing fails
        """
        if not date_text:
            return None
        
        # Try various formats
        formats = [
            '%m/%d/%y %I:%M%p',      # 01/13/24 09:00am
            '%m/%d/%Y %I:%M%p',      # 01/13/2024 09:00am
            '%m/%d/%y %I:%M %p',     # 01/13/24 09:00 am
            '%m/%d/%Y %I:%M %p',     # 01/13/2024 09:00 am
        ]
        
        # Clean up the text
        date_text = date_text.strip().lower().replace(' ', ' ')
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_text, fmt.lower())
                return dt.date()
            except ValueError:
                continue
        
        # Try regex extraction
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', date_text)
        if match:
            month, day, year = match.groups()
            if len(year) == 2:
                year = '20' + year
            try:
                return datetime(int(year), int(month), int(day)).date()
            except ValueError:
                pass
        
        return None
    
    def _parse_score(self, score_text: str) -> tuple:
        """
        Parse score string.
        
        Args:
            score_text: Score string like "0 : 4" or "TBD"
            
        Returns:
            Tuple of (home_score, away_score) or (None, None) if not played
        """
        if not score_text or 'TBD' in score_text.upper():
            return None, None
        
        # Clean up HTML entities and whitespace
        score_text = score_text.replace('&nbsp', ' ').replace('\xa0', ' ')
        score_text = re.sub(r'\s+', ' ', score_text).strip()
        
        # Try various score formats
        patterns = [
            r'(\d+)\s*:\s*(\d+)',      # 0:4 or 0 : 4
            r'(\d+)\s*-\s*(\d+)',      # 0-4 or 0 - 4
            r'(\d+)\s+(\d+)',          # 0 4
        ]
        
        for pattern in patterns:
            match = re.search(pattern, score_text)
            if match:
                return int(match.group(1)), int(match.group(2))
        
        return None, None
    
    def _extract_academy_id(self, style_text: str) -> Optional[str]:
        """
        Extract academy ID from background-image URL in style attribute.
        
        Args:
            style_text: CSS style string containing background-image URL
            
        Returns:
            Academy ID string or None
        """
        if not style_text:
            return None
        
        # Pattern: /academy/{id}/
        match = re.search(r'/academy/(\d+)/', style_text)
        if match:
            return match.group(1)
        
        return None
    
    def _generate_team_id(self, team_name: str) -> str:
        """
        Generate a deterministic team ID from team name.
        
        Args:
            team_name: Team display name
            
        Returns:
            Slugified team ID
        """
        if not team_name:
            return 'unknown'
        
        # Slugify: lowercase, replace spaces and special chars
        slug = team_name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        
        return f"name:{slug}" if slug else 'unknown'
    
    def _create_perspective_items(self, match_data: Dict) -> Generator[Modular11GameItem, None, None]:
        """
        Create two items for home and away perspectives.
        
        Args:
            match_data: Dictionary with parsed match data
            
        Yields:
            Two Modular11GameItem instances (home and away perspectives)
        """
        # Get the MLS NEXT division (HD or AD) from the request
        mls_division = match_data.get('mls_next_division', '')
        
        # Common fields
        common = {
            'provider': 'modular11',
            'age_group': match_data['age_group'],
            'gender': match_data['gender'],
            'state': '',  # State not available in API
            'competition': match_data['competition'],
            'division_name': match_data['division_name'],
            'event_name': match_data['competition'],
            'venue': match_data['venue'],
            'game_date': match_data['game_date'],
            'match_id': match_data['match_id'],
            'source_url': self.API_URL,
            'scraped_at': match_data['scraped_at'],
            'mls_division': mls_division,  # HD or AD
        }
        
        home_score = match_data['home_score']
        away_score = match_data['away_score']
        age_group = match_data['age_group']
        
        # Use the MLS NEXT division (HD/AD) as the primary tier indicator
        # This is more reliable than deriving from the division text
        tier = mls_division  # HD or AD
        
        # Construct full team names with age group AND tier (e.g., "Tampa Bay United U13 HD")
        home_club = match_data['home_team_name']
        away_club = match_data['away_team_name']
        
        # Include tier in team name for better differentiation
        home_team_full = f"{home_club} {age_group} {tier}".strip()
        away_team_full = f"{away_club} {age_group} {tier}".strip()
        
        # Home perspective
        home_item = Modular11GameItem(**common)
        home_item['team_id'] = match_data['home_team_id']
        home_item['team_id_source'] = match_data['home_team_id']
        home_item['team_name'] = home_team_full  # Full team name with age group
        home_item['club_name'] = home_club        # Just the club name
        home_item['opponent_id'] = match_data['away_team_id']
        home_item['opponent_id_source'] = match_data['away_team_id']
        home_item['opponent_name'] = away_team_full
        home_item['opponent_club_name'] = away_club
        home_item['home_away'] = 'H'
        home_item['goals_for'] = str(home_score)
        home_item['goals_against'] = str(away_score)
        home_item['result'] = self._compute_result(home_score, away_score)
        
        yield home_item
        
        # Away perspective
        away_item = Modular11GameItem(**common)
        away_item['team_id'] = match_data['away_team_id']
        away_item['team_id_source'] = match_data['away_team_id']
        away_item['team_name'] = away_team_full   # Full team name with age group
        away_item['club_name'] = away_club         # Just the club name
        away_item['opponent_id'] = match_data['home_team_id']
        away_item['opponent_id_source'] = match_data['home_team_id']
        away_item['opponent_name'] = home_team_full
        away_item['opponent_club_name'] = home_club
        away_item['home_away'] = 'A'
        away_item['goals_for'] = str(away_score)
        away_item['goals_against'] = str(home_score)
        away_item['result'] = self._compute_result(away_score, home_score)
        
        yield away_item
    
    def _derive_tier(self, division: str) -> str:
        """
        Derive team tier from division name.
        
        MLS NEXT Tier Structure:
        - HD (Homegrown Division) = Top tier - MLS club academies, Pro Player Pathway
        - AD (Academy Division) = Second tier - Regular regional divisions
        
        Args:
            division: Division string like "MLS Academy", "Southwest (Pro Player Pathway)", "Florida"
            
        Returns:
            "HD", "AD", or empty string if cannot determine
        """
        if not division:
            return ''
        
        division_upper = division.upper()
        
        # HD indicators (top tier)
        if 'MLS ACADEMY' in division_upper:
            return 'HD'
        if 'PRO PLAYER PATHWAY' in division_upper:
            return 'HD'
        if 'HOMEGROWN' in division_upper:
            return 'HD'
        
        # Regular regional divisions are AD (second tier)
        regional_keywords = [
            'SOUTHWEST', 'SOUTHEAST', 'NORTHEAST', 'NORTHWEST',
            'CENTRAL', 'EAST', 'WEST', 'FLORIDA', 'MID-AMERICA',
            'MID-ATLANTIC', 'FRONTIER'
        ]
        
        for keyword in regional_keywords:
            if keyword in division_upper and 'PRO PLAYER' not in division_upper:
                return 'AD'
        
        # Default - cannot determine
        return ''
    
    def _compute_result(self, goals_for: int, goals_against: int) -> str:
        """Compute match result from score."""
        if goals_for > goals_against:
            return 'W'
        elif goals_for < goals_against:
            return 'L'
        else:
            return 'D'
    
    def closed(self, reason: str):
        """Called when spider is closed. Log statistics."""
        logger.info("=" * 60)
        logger.info("Modular11 Spider Statistics:")
        logger.info(f"  Divisions scraped: {', '.join(self.divisions_to_scrape)}")
        logger.info(f"  Total games scraped (rows): {self.stats['games_scraped']}")
        logger.info(f"    - HD (Homegrown): {self.stats.get('games_scraped_HD', 0)}")
        logger.info(f"    - AD (Academy): {self.stats.get('games_scraped_AD', 0)}")
        logger.info(f"  Games skipped (no score): {self.stats['games_skipped_no_score']}")
        logger.info(f"  Games skipped (date filter): {self.stats['games_skipped_date_filter']}")
        logger.info(f"  Games skipped (parse error): {self.stats['games_skipped_parse_error']}")
        logger.info(f"  Pages processed: {self.stats['pages_processed']}")
        logger.info(f"  Close reason: {reason}")
        logger.info("=" * 60)

