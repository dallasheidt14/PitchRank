"""
Modular11 Events Spider

Scrapes MLS NEXT event games from https://www.modular11.com/events/

This spider:
1. Scrapes the events list page to get event IDs
2. For each event within the date range, scrapes games for all age groups (U13-U17)
3. Parses matches from event schedule pages

Usage:
    cd scrapers/modular11_scraper
    scrapy crawl modular11_events -a days_back=365
"""
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Generator, Any
from urllib.parse import urljoin, urlparse, parse_qs

import scrapy
from scrapy.http import Response, FormRequest

from modular11_scraper.items import Modular11GameItem


logger = logging.getLogger(__name__)


class Modular11EventsSpider(scrapy.Spider):
    """
    Spider for scraping Modular11.com event games.
    
    Events are tournaments like:
    - MLS NEXT Cup
    - MLS NEXT Fest
    - Generation Adidas Cup
    - MLS NEXT Flex
    - Invitational IDs
    
    This spider:
    1. Scrapes the events list page to get event IDs and dates
    2. Filters events within the specified date range
    3. For each event, scrapes schedule pages for all age groups (U13-U17)
    4. Parses matches from schedule pages
    5. Yields TWO items per game (home + away perspective)
    """
    
    name = "modular11_events"
    allowed_domains = ["www.modular11.com", "modular11.com"]
    
    # Events list page
    EVENTS_URL = "https://www.modular11.com/events/"
    
    # API endpoint for event matches (similar to league API but different URL)
    API_URL = "https://www.modular11.com/events/league/get_matches"
    
    # Age group ID mapping (same as schedule spider)
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
        *args,
        **kwargs
    ):
        """
        Initialize the spider with configurable parameters.
        
        Args:
            age_min: Minimum age group (default: 13 for U13)
            age_max: Maximum age group (default: 17 for U17)
            days_back: Number of days to look back (default: 365)
        """
        super().__init__(*args, **kwargs)
        
        self.age_min = int(age_min)
        self.age_max = int(age_max)
        self.days_back = int(days_back)
        
        # Calculate date range
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=self.days_back)
        self.cutoff_date = self.start_date.date()
        
        # Build list of age group IDs to request
        self.age_group_ids = []
        for age in range(self.age_min, self.age_max + 1):
            if age in self.AGE_GROUP_IDS:
                self.age_group_ids.append(self.AGE_GROUP_IDS[age])
        
        # Statistics
        self.stats = {
            'events_found': 0,
            'events_in_range': 0,
            'events_scraped': 0,
            'games_scraped': 0,
            'games_skipped_no_score': 0,
            'games_skipped_date_filter': 0,
            'games_skipped_parse_error': 0,
            'pages_processed': 0,
        }
        
        logger.info(f"Initialized Modular11 Events spider:")
        logger.info(f"  Age range: U{self.age_min} - U{self.age_max}")
        logger.info(f"  Age group IDs: {self.age_group_ids}")
        logger.info(f"  Date range: {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}")
    
    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Start by scraping the events list page."""
        yield scrapy.Request(
            url=self.EVENTS_URL,
            callback=self.parse_events_list,
            dont_filter=True
        )
    
    def parse_events_list(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """
        Parse the events list page to extract event IDs and dates.
        
        Events are in a table with columns: Title, Date, Description
        Each event row has a link to the event detail page.
        """
        logger.info("Parsing events list page")
        
        # Find all event rows in the table
        # The table structure: table > tbody > tr with js-redirect attribute
        event_rows = response.xpath('//table//tr[@js-redirect]')
        
        # If no rows with js-redirect, try all tr elements
        if not event_rows:
            event_rows = response.css('table tbody tr')
        
        events_found = 0
        events_in_range = 0
        
        for row in event_rows:
            events_found += 1
            
            # Get all cells in the row
            cells = row.css('td')
            cell_count = len(cells)
            
            if cell_count < 3:
                logger.debug(f"Row {events_found}: Not enough cells ({cell_count})")
                continue
            
            # Extract event URL from js-redirect attribute on <tr>
            # Format: /events/event/view/playoffs/{event_id} or /events/event/view/ga/{event_id} or /events/event/view/groupplay/{event_id}
            title_link = row.xpath('./@js-redirect').get()
            if not title_link:
                # Fallback: try to find link in cells
                title_link = row.css('a::attr(href)').get()
            
            if not title_link:
                logger.debug(f"Row {events_found}: No js-redirect or link found")
                continue
            
            # Extract event title from second cell (index 1)
            title_cell = cells[1]
            title_text = title_cell.css('::text').get()
            if not title_text:
                title_text = row.css('a::text').get()
            
            if not title_text:
                logger.debug(f"Row {events_found}: No title text found")
                continue
            
            title_text = title_text.strip()
            
            # Extract event date from third cell (index 2)
            date_cell = cells[2]
            date_text = date_cell.css('::text').get()
            
            if not date_text:
                # Try getting all text from the row and finding date pattern
                all_text = ' '.join(row.css('td::text').getall())
                date_match = re.search(r'(\d{2}-\d{2}-\d{4})', all_text)
                if date_match:
                    date_text = date_match.group(1)
            
            if not date_text:
                logger.debug(f"Row {events_found}: No date found, link: {title_link}")
                continue
            
            # Parse date (format: MM-DD-YYYY)
            try:
                event_date = datetime.strptime(date_text.strip(), '%m-%d-%Y').date()
            except ValueError:
                logger.warning(f"Could not parse date '{date_text}' for event '{title_text}', link: {title_link}")
                continue
            
            # Extract event ID from URL
            # URL formats:
            # - /events/event/view/playoffs/{event_id}
            # - /events/event/view/ga/{event_id}
            # - /events/event/view/groupplay/{event_id}
            event_id_match = re.search(r'/events/event/view/[^/]+/(\d+)', title_link)
            if not event_id_match:
                logger.warning(f"Could not extract event ID from URL: {title_link}")
                continue
            
            event_id = event_id_match.group(1)
            event_name = title_text.strip() if title_text else f"Event {event_id}"
            
            # Check if event is within date range
            # Note: We want events that occurred within the date range, not just events listed on that date
            # So we check if the event date is >= cutoff_date
            if event_date < self.cutoff_date:
                logger.debug(f"Skipping event '{event_name}' (date: {event_date}, before cutoff: {self.cutoff_date})")
                continue
            
            events_in_range += 1
            logger.info(f"Found event: {event_name} (ID: {event_id}, Date: {event_date})")
            
            # Update stats
            self.stats['events_scraped'] += 1
            
            # For each age group, use the API to get matches
            # The API endpoint is: /events/league/get_matches
            # Parameters: tournament={event_id}, age={age_id}, match_type=1 (events), status=all
            for age_id in self.age_group_ids:
                age_group = self.AGE_ID_TO_GROUP.get(age_id, f"ID:{age_id}")
                
                # Build API request - it's a GET request with query parameters
                from urllib.parse import urlencode
                params = {
                    'open_page': '0',
                    'academy': '0',
                    'tournament': event_id,  # Event ID is used as tournament ID
                    'gender': '1',  # Male (MLS NEXT is boys-only)
                    'age': age_id,
                    'brackets': '',
                    'groups': '',
                    'group': '',
                    'match_number': '0',
                    'status': 'all',  # Get all matches including completed
                    'match_type': '1',  # Events (vs 2 for league)
                    'schedule': '0',
                    'team': '0',
                    'teamPlayer': '0',
                    'location': '0',
                    'fields': '',
                    'as_referee': '0',
                    'start_date': self.start_date.strftime('%Y-%m-%d %H:%M:%S'),
                    'end_date': self.end_date.strftime('%Y-%m-%d %H:%M:%S'),
                }
                url = f"{self.API_URL}?{urlencode(params)}"
                
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_event_schedule_api,
                    meta={
                        'event_id': event_id,
                        'event_name': event_name,
                        'event_date': event_date.isoformat(),
                        'age_id': age_id,
                        'age_group': age_group,
                        'page': 0,
                    },
                    dont_filter=True
                )
        
        self.stats['events_found'] = events_found
        self.stats['events_in_range'] = events_in_range
        logger.info(f"Found {events_found} events, {events_in_range} within date range")
    
    def parse_event_schedule_api(self, response: Response) -> Generator[Modular11GameItem, None, None]:
        """
        Parse API response for event matches.
        
        The API returns HTML with match rows in a table format, similar to league schedule.
        We reuse the parsing logic from the schedule spider.
        """
        event_id = response.meta['event_id']
        event_name = response.meta['event_name']
        event_date = response.meta['event_date']
        age_id = response.meta['age_id']
        age_group = response.meta['age_group']
        current_page = response.meta.get('page', 0)
        
        logger.info(f"Processing API response for event '{event_name}' ({event_id}), age group {age_group}, page {current_page + 1}")
        
        # Extract pagination info
        pagination_match = re.search(r'(\d+)\s*page\s*out\s*of\s*(\d+)', response.text)
        if pagination_match:
            total_pages = int(pagination_match.group(2))
        else:
            total_pages = current_page + 1
        
        # Find all match rows (same structure as league schedule)
        match_rows = response.xpath('//div[contains(@class, "table-content-row") and contains(@class, "hidden-xs")]')
        
        if not match_rows:
            logger.warning(f"No match rows found for event '{event_name}' ({event_id}), age group {age_group}, page {current_page + 1}")
            return
        
        logger.info(f"Found {len(match_rows)} matches on page {current_page + 1}")
        self.stats['pages_processed'] += 1
        
        scraped_at = datetime.now().isoformat()
        
        for row in match_rows:
            try:
                match_data = self._parse_match_row(row, scraped_at, event_id, event_name)
                
                if match_data is None:
                    continue
                
                # Yield home and away perspective items
                for item in self._create_perspective_items(match_data, event_id, event_name):
                    yield item
                    self.stats['games_scraped'] += 1
                    
            except Exception as e:
                logger.error(f"Error parsing match row for event '{event_name}': {e}", exc_info=True)
                self.stats['games_skipped_parse_error'] += 1
                continue
        
        # Handle pagination
        if current_page + 1 < total_pages:
            logger.info(f"Requesting event '{event_name}' ({event_id}), age group {age_group}, page {current_page + 2} of {total_pages}")
            from urllib.parse import urlencode
            params = {
                'open_page': str(current_page + 1),
                'academy': '0',
                'tournament': event_id,
                'gender': '1',
                'age': age_id,
                'brackets': '',
                'groups': '',
                'group': '',
                'match_number': '0',
                'status': 'all',
                'match_type': '1',
                'schedule': '0',
                'team': '0',
                'teamPlayer': '0',
                'location': '0',
                'fields': '',
                'as_referee': '0',
                'start_date': self.start_date.strftime('%Y-%m-%d %H:%M:%S'),
                'end_date': self.end_date.strftime('%Y-%m-%d %H:%M:%S'),
            }
            url = f"{self.API_URL}?{urlencode(params)}"
            
            yield scrapy.Request(
                url=url,
                callback=self.parse_event_schedule_api,
                meta={
                    'event_id': event_id,
                    'event_name': event_name,
                    'event_date': event_date,
                    'age_id': age_id,
                    'age_group': age_group,
                    'page': current_page + 1,
                },
                dont_filter=True
            )
    
    def _parse_match_row(self, row, scraped_at: str, event_id: str, event_name: str) -> Optional[Dict]:
        """
        Parse a single match row from the API response.
        
        Reuses logic from schedule spider but adapts for events.
        Emulates the league schedule spider structure as much as possible.
        """
        # Extract team-specific divisions from row data attributes (like league spider)
        # These differentiate HD/AD/Elite tiers within the same club
        home_division = row.xpath('./@js-match-group_home').get('')
        away_division = row.xpath('./@js-match-group_away').get('')
        match_bracket = row.xpath('./@js-match-bracket').get('')  # Championship, Premier, Showcase, Best Of
        
        # Extract Match ID and Gender from first column
        first_col = row.xpath('.//div[contains(@class, "col-sm-1") and contains(@class, "pad-0")][1]')
        match_id = first_col.xpath('./text()').get('').strip()
        gender_text = first_col.xpath('./br/following-sibling::text()').get('').strip()
        
        gender = 'M' if 'MALE' in gender_text.upper() else 'F' if 'FEMALE' in gender_text.upper() else 'M'
        
        # Extract date and venue from second column
        date_col = row.xpath('.//div[contains(@class, "col-sm-2")][1]')
        date_text = date_col.xpath('./text()').get('').strip()
        venue = date_col.xpath('.//p[@data-title]/@data-title').get('') or \
                date_col.xpath('.//div[contains(@class, "container-location")]//p/text()').get('').strip()
        
        # Parse date (format: "01/13/24 09:00am")
        game_date = self._parse_date(date_text)
        if game_date is None:
            return None
        
        # Compare dates (convert datetime to date if needed)
        game_date_only = game_date.date() if isinstance(game_date, datetime) else game_date
        if game_date_only < self.cutoff_date:
            self.stats['games_skipped_date_filter'] += 1
            return None
        
        # Extract age group
        age_col = row.xpath('.//div[contains(@class, "col-sm-1") and contains(@class, "pad-0")][2]')
        age_group = age_col.xpath('./text()').get('').strip()
        
        # Extract competition and division (like league spider)
        comp_div_col = row.xpath('.//div[contains(@class, "col-sm-2")][2]')
        comp_div_texts = [t.strip() for t in comp_div_col.xpath('.//text()').getall() if t.strip()]
        competition = comp_div_texts[0] if len(comp_div_texts) > 0 else event_name
        division_text = comp_div_texts[1] if len(comp_div_texts) > 1 else match_bracket or 'Event'
        
        # Derive MLS NEXT division (HD or AD) from bracket/competition
        # Use bracket first, then competition name, then division text
        mls_division = self._derive_tier_from_bracket(match_bracket, competition, division_text)
        
        # Extract teams
        teams_container = row.xpath('.//div[contains(@class, "col-sm-6")]//div[contains(@class, "container-teams-info")]')
        
        home_team_name = teams_container.xpath(
            './/div[contains(@class, "container-first-team")]//p/@data-title'
        ).get('') or teams_container.xpath(
            './/div[contains(@class, "container-first-team")]//p/text()'
        ).get('').strip()
        
        away_team_name = teams_container.xpath(
            './/div[contains(@class, "container-second-team")]//p/@data-title'
        ).get('') or teams_container.xpath(
            './/div[contains(@class, "container-second-team")]//p/text()'
        ).get('').strip()
        
        # Extract team IDs from image URLs
        home_image_style = teams_container.xpath(
            './/div[contains(@class, "container-first-team")]/following-sibling::div[1]//div[contains(@class, "club-photo")]/@style'
        ).get('')
        away_image_style = teams_container.xpath(
            './/div[contains(@class, "container-second-team")]/preceding-sibling::div[1]//div[contains(@class, "club-photo")]/@style'
        ).get('')
        
        home_team_id = self._extract_academy_id(home_image_style) or f"event_{event_id}_{home_team_name}"
        away_team_id = self._extract_academy_id(away_image_style) or f"event_{event_id}_{away_team_name}"
        
        # Extract score - try multiple selectors
        score_span = teams_container.xpath('.//div[contains(@class, "container-score")]//span[contains(@class, "score-match-table")]')
        if not score_span:
            # Try alternative selector
            score_span = teams_container.xpath('.//div[contains(@class, "container-score")]')
        
        score_text = score_span.xpath('string(.)').get('').strip() if score_span else ''
        
        # If no score text, try getting all text from the score container
        if not score_text:
            score_container = teams_container.xpath('.//div[contains(@class, "container-score")]')
            if score_container:
                score_text = ' '.join(score_container.xpath('.//text()').getall()).strip()
        
        home_score, away_score = self._parse_score(score_text)
        if home_score is None or away_score is None:
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
            'mls_next_division': mls_division,  # HD or AD - derived from bracket
            'match_bracket': match_bracket,  # Championship, Premier, Showcase, Best Of
            'home_division': home_division,  # Team's specific division (e.g., "Playoff")
            'away_division': away_division,  # Opponent's specific division
            'event_name': event_name,
            'home_team_name': home_team_name,
            'home_team_id': home_team_id,
            'away_team_name': away_team_name,
            'away_team_id': away_team_id,
            'home_score': home_score,
            'away_score': away_score,
            'scraped_at': scraped_at,
        }
    
    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """Parse date string from Modular11 format (e.g., "01/13/24 09:00am")."""
        if not date_text:
            return None
        
        # Try various date formats
        formats = [
            '%m/%d/%y %I:%M%p',  # 01/13/24 09:00am
            '%m/%d/%Y %I:%M%p',  # 01/13/2024 09:00am
            '%m/%d/%y %H:%M',    # 01/13/24 09:00
            '%m/%d/%Y %H:%M',    # 01/13/2024 09:00
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_text.strip(), fmt)
            except ValueError:
                continue
        
        return None
    
    def _parse_score(self, score_text: str) -> tuple:
        """
        Parse score text.
        
        Handles formats like:
        - "2 : 2" (regular score)
        - "2&nbsp:&nbsp2" (with HTML entities)
        - "2 : 2 (2 : 3)" (regular score with penalty shootout in parentheses)
        - "4 : 0" (regular score)
        - "TBD" or "Bye" (no score)
        """
        if not score_text:
            return None, None
        
        # Normalize HTML entities and whitespace
        # Replace &nbsp; with space, and normalize all whitespace
        import html
        score_text = html.unescape(score_text)  # Converts &nbsp; to space
        score_text = ' '.join(score_text.split())  # Normalize whitespace
        
        score_text_upper = score_text.upper()
        if 'TBD' in score_text_upper or 'BYE' in score_text_upper:
            return None, None
        
        # First, try to find the main score (before parentheses if they exist)
        # Pattern: "X : Y" or "X : Y (Z : W)" - we want X and Y
        score_match = re.search(r'(\d+)\s*[:]\s*(\d+)', score_text)
        if score_match:
            # Get the first match (main score, not penalty shootout)
            # If there are multiple matches, the first one is the regular time score
            return score_match.group(1), score_match.group(2)
        
        return None, None
    
    def _extract_academy_id(self, image_style: str) -> Optional[str]:
        """Extract academy ID from image URL in style attribute."""
        if not image_style:
            return None
        
        # Pattern: url('https://...cloudfront.net/academy/{academy_id}/...')
        match = re.search(r'/academy/(\d+)/', image_style)
        if match:
            return match.group(1)
        
        return None
    
    def _derive_tier_from_bracket(self, bracket: str, competition: str, division_text: str) -> str:
        """
        Derive MLS NEXT division (HD or AD) from event bracket/competition.
        
        Event bracket structure:
        - Championship = HD (top tier, best teams)
        - Best Of = HD (top tier)
        - HD Showcase = HD (top tier showcase)
        - Premier = AD (second tier)
        - Showcase = AD (second tier, developmental)
        - AD Showcase = AD (second tier showcase)
        - Flex = AD (second tier)
        
        Args:
            bracket: Bracket type from js-match-bracket attribute (Championship, Premier, Showcase, Best Of)
            competition: Competition text from page (may include "HD Showcase", "AD Showcase", etc.)
            division_text: Division text from page
            
        Returns:
            "HD", "AD", or empty string if cannot determine
        """
        # Combine all text for analysis
        all_text = f"{bracket} {competition} {division_text}".upper()
        comp_upper = competition.upper() if competition else ''
        bracket_upper = bracket.upper() if bracket else ''
        
        # Explicit HD indicators (top tier)
        # Check for "HD Showcase" or competition starting with "HD"
        if 'HD SHOWCASE' in all_text or (comp_upper.startswith('HD ') and 'SHOWCASE' in comp_upper):
            return 'HD'
        if comp_upper == 'HD' or comp_upper.startswith('HD '):
            return 'HD'
        if 'CHAMPIONSHIP' in bracket_upper or 'CHAMPIONSHIP' in comp_upper:
            return 'HD'
        if 'BEST OF' in all_text or 'BESTOF' in all_text:
            return 'HD'
        if 'PRO PLAYER PATHWAY' in all_text:
            return 'HD'
        
        # Explicit AD indicators (second tier)
        # Check for "AD Showcase" or competition starting with "AD"
        if 'AD SHOWCASE' in all_text or (comp_upper.startswith('AD ') and 'SHOWCASE' in comp_upper):
            return 'AD'
        if comp_upper == 'AD' or comp_upper.startswith('AD '):
            return 'AD'
        if 'PREMIER' in bracket_upper or 'PREMIER' in comp_upper:
            return 'AD'
        if 'FLEX' in comp_upper:
            return 'AD'
        
        # Showcase without prefix - typically AD (second tier)
        if 'SHOWCASE' in comp_upper and 'HD' not in all_text:
            return 'AD'
        
        # Playoffs - derive from bracket or competition context
        # If bracket is "Championship" with "Playoff" division, it's HD
        # If bracket is "Premier" with "Playoff" division, it's AD
        if 'PLAYOFF' in division_text.upper() or 'PLAYOFF' in comp_upper:
            if 'CHAMPIONSHIP' in bracket_upper or 'CHAMPIONSHIP' in comp_upper:
                return 'HD'
            if 'PREMIER' in bracket_upper or 'PREMIER' in comp_upper:
                return 'AD'
            # If just "Playoffs" without context, check if competition has clues
            if 'CHAMPIONSHIP' in all_text:
                return 'HD'
            if 'PREMIER' in all_text:
                return 'AD'
        
        # Group Play - typically AD (second tier, group stage)
        if 'GROUP PLAY' in all_text or 'GROUP' in comp_upper:
            return 'AD'
        
        # Consolation - typically AD (second tier)
        if 'CONSOLATION' in all_text:
            return 'AD'
        
        # Default - cannot determine (use empty string like league spider)
        return ''
    
    def _extract_club_and_team_name(self, full_name: str) -> tuple:
        """
        Extract club name and team name from a full team name.
        
        Handles cases where team names may have AD/HG/HD suffixes:
        - "Team Name AD" -> club="Team Name", team="Team Name AD"
        - "Team Name HG" -> club="Team Name", team="Team Name HG"
        - "Team Name HD" -> club="Team Name", team="Team Name HD"
        - "Team Name" -> club="Team Name", team="Team Name"
        
        Args:
            full_name: Full team name as scraped
            
        Returns:
            Tuple of (club_name, team_name)
        """
        if not full_name:
            return '', ''
        
        # Check for common division suffixes at the end
        # Pattern: ends with space + (AD|HG|HD) + optional whitespace
        suffix_pattern = re.compile(r'\s+(AD|HG|HD)\s*$', re.IGNORECASE)
        match = suffix_pattern.search(full_name)
        
        if match:
            # Has suffix - separate club name from team name
            club_name = full_name[:match.start()].strip()
            team_name = full_name.strip()  # Keep full name with suffix
            return club_name, team_name
        else:
            # No suffix - use same for both
            return full_name.strip(), full_name.strip()
    
    def _create_perspective_items(self, match_data: Dict, event_id: str, event_name: str) -> Generator[Modular11GameItem, None, None]:
        """
        Create home and away perspective items from match data.
        
        Emulates the league schedule spider's item creation logic.
        """
        # Get the MLS NEXT division (HD or AD) from match data
        mls_division = match_data.get('mls_next_division', '')
        
        # Common fields (like league spider)
        common = {
            'provider': 'modular11',
            'age_group': match_data['age_group'],
            'gender': match_data['gender'],
            'state': '',  # State not available in events
            'competition': match_data['competition'],
            'division_name': match_data['division_name'],
            'event_name': match_data.get('event_name', event_name),
            'venue': match_data['venue'] or '',
            'game_date': match_data['game_date'],
            'match_id': match_data['match_id'],
            'source_url': f"https://www.modular11.com/events/event/view/playoffs/{event_id}",
            'scraped_at': match_data['scraped_at'],
            'mls_division': mls_division,  # HD or AD
        }
        
        home_score = match_data['home_score']
        away_score = match_data['away_score']
        age_group = match_data['age_group']
        
        # Use the MLS NEXT division (HD/AD) as the primary tier indicator (like league spider)
        tier = mls_division  # HD or AD
        
        # Extract club names (handling AD/HG/HD suffixes if present)
        home_club_raw, _ = self._extract_club_and_team_name(match_data['home_team_name'])
        away_club_raw, _ = self._extract_club_and_team_name(match_data['away_team_name'])
        
        # Construct full team names with age group AND tier (e.g., "Houston Rangers U13 HD")
        # This matches the league schedule spider format exactly
        home_club = home_club_raw
        away_club = away_club_raw
        
        # Include tier in team name for better differentiation (like league spider)
        home_team_full = f"{home_club} {age_group} {tier}".strip() if tier else f"{home_club} {age_group}".strip()
        away_team_full = f"{away_club} {age_group} {tier}".strip() if tier else f"{away_club} {age_group}".strip()
        
        # Home perspective
        home_item = Modular11GameItem(**common)
        home_item['team_id'] = match_data['home_team_id']
        home_item['team_id_source'] = match_data['home_team_id']
        home_item['team_name'] = home_team_full  # Full team name with age group and tier
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
        away_item['team_name'] = away_team_full   # Full team name with age group and tier
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
    
    def _compute_result(self, goals_for: int, goals_against: int) -> str:
        """Compute match result from score (like league spider)."""
        if goals_for > goals_against:
            return 'W'
        elif goals_for < goals_against:
            return 'L'
        else:
            return 'D'
    
    def parse_event_schedule(self, response: Response) -> Generator[Modular11GameItem, None, None]:
        """
        Parse an event schedule page to extract match data.
        
        Based on the page structure, matches are in a table with structure:
        - Match ID in first column
        - Date/Time in second column  
        - Age Group in third column
        - Competition/Division in fourth column
        - Home Team and Away Team with score in last columns
        """
        event_id = response.meta['event_id']
        event_name = response.meta['event_name']
        event_date = response.meta['event_date']
        age_id = response.meta['age_id']
        age_group = response.meta['age_group']
        
        logger.info(f"Processing schedule for event '{event_name}' ({event_id}), age group {age_group}")
        
        # Find all match rows - based on browser inspection, matches are in table rows
        # Skip header row
        match_rows = response.css('table tbody tr, table tr')
        
        matches_found = 0
        
        for row in match_rows:
            try:
                # Extract match ID from first cell (or first element with numeric ID)
                match_id_elem = row.css('td:first-child, [class*="match"]:first-child')
                match_id_text = ' '.join(match_id_elem.css('::text').getall()).strip()
                
                # Try to find match ID in any cell
                if not match_id_text or not match_id_text.isdigit():
                    all_cells = row.css('td')
                    for cell in all_cells:
                        cell_text = ' '.join(cell.css('::text').getall()).strip()
                        if cell_text.isdigit() and len(cell_text) >= 4:  # Match IDs are usually 4+ digits
                            match_id_text = cell_text
                            break
                
                if not match_id_text or not match_id_text.isdigit():
                    continue
                
                match_id = match_id_text.strip()
                
                # Extract date/time from Details column
                # Look for date pattern in the row (format: MM/DD/YY HH:MMam/pm)
                all_text = ' '.join(row.css('::text').getall())
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}:\d{2}(?:am|pm|AM|PM))', all_text)
                if not date_match:
                    # Try without time
                    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', all_text)
                    if not date_match:
                        continue
                
                game_date_str = date_match.group(1)
                
                try:
                    # Try MM/DD/YYYY format first
                    if len(game_date_str.split('/')[2]) == 4:
                        game_date = datetime.strptime(game_date_str, '%m/%d/%Y').date()
                    else:
                        # MM/DD/YY format
                        game_date = datetime.strptime(game_date_str, '%m/%d/%y').date()
                except ValueError:
                    logger.warning(f"Could not parse date '{game_date_str}' for match {match_id}")
                    continue
                
                # Check date range
                if game_date < self.cutoff_date:
                    self.stats['games_skipped_date_filter'] += 1
                    continue
                
                # Extract venue from Details column
                venue = None
                venue_match = re.search(r'(\d+\s*-\s*[^0-9]+(?:Complex|Park|Field|Stadium|Soccer))', all_text, re.IGNORECASE)
                if venue_match:
                    venue = venue_match.group(1).strip()
                
                # Find score pattern (format: "X : Y" - note the quotes in HTML)
                # Also handle penalty shootouts: "2 : 2" "(3 : 2)"
                score_pattern = re.compile(r'"(\d+)\s*[:]\s*(\d+)"')
                score_match = score_pattern.search(all_text)
                
                # If no score with quotes, try without quotes
                if not score_match:
                    score_pattern_no_quotes = re.compile(r'(\d+)\s*[:]\s*(\d+)')
                    score_match = score_pattern_no_quotes.search(all_text)
                
                if not score_match:
                    # Check for TBD or Bye (games not played yet)
                    if 'TBD' in all_text or 'Bye' in all_text:
                        self.stats['games_skipped_no_score'] += 1
                        continue
                    # No score found
                    self.stats['games_skipped_no_score'] += 1
                    continue
                
                home_score = score_match.group(1)
                away_score = score_match.group(2)
                
                # Extract team names from paragraph elements
                # Based on browser inspection: teams are in <p> tags, score is between them
                team_paragraphs = row.css('p')
                team_names = []
                for p in team_paragraphs:
                    text = ' '.join(p.css('::text').getall()).strip()
                    # Filter out empty, numeric, or common non-team text
                    if text and len(text) > 2 and \
                       not re.match(r'^\d+$', text) and \
                       not re.match(r'^\d+\s*[:]\s*\d+', text) and \
                       text not in ['TBD', 'Bye', 'MALE', '-']:
                        team_names.append(text)
                
                if len(team_names) < 2:
                    logger.debug(f"Could not extract team names for match {match_id}, found: {team_names}")
                    continue
                
                # First paragraph is home team, last paragraph is away team
                home_team_name = team_names[0]
                away_team_name = team_names[-1]
                
                # Skip if opponent is "Bye"
                if away_team_name == 'Bye' or home_team_name == 'Bye':
                    self.stats['games_skipped_no_score'] += 1
                    continue
                
                # Extract competition/division from cells
                competition = event_name
                division_name = "Event"
                
                # Look for division info in cells (e.g., "Best Of", "Showcase", "Playoffs")
                for cell_text in cell_texts:
                    if any(term in cell_text for term in ['Best Of', 'Showcase', 'Playoffs', 'Teamlist']):
                        division_name = cell_text.strip()
                        break
                
                # Create game items (one for each team's perspective)
                scraped_at = datetime.now().isoformat()
                
                # Home team perspective
                home_item = Modular11GameItem(
                    provider='modular11',
                    team_id=f"event_{event_id}_{home_team_name}",
                    team_id_source=f"event_{event_id}_{home_team_name}",
                    team_name=home_team_name,
                    club_name=home_team_name,
                    opponent_id=f"event_{event_id}_{away_team_name}",
                    opponent_id_source=f"event_{event_id}_{away_team_name}",
                    opponent_name=away_team_name,
                    opponent_club_name=away_team_name,
                    age_group=age_group,
                    gender='M',
                    state='',
                    competition=competition,
                    division_name=division_name,
                    event_name=event_name,
                    venue=venue or '',
                    mls_division='',  # Events don't have HD/AD division
                    game_date=game_date.isoformat(),
                    home_away='H',
                    goals_for=home_score,
                    goals_against=away_score,
                    result='W' if int(home_score) > int(away_score) else 'L' if int(home_score) < int(away_score) else 'D',
                    match_id=match_id,
                    source_url=response.url,
                    scraped_at=scraped_at,
                )
                yield home_item
                
                # Away team perspective
                away_item = Modular11GameItem(
                    provider='modular11',
                    team_id=f"event_{event_id}_{away_team_name}",
                    team_id_source=f"event_{event_id}_{away_team_name}",
                    team_name=away_team_name,
                    club_name=away_team_name,
                    opponent_id=f"event_{event_id}_{home_team_name}",
                    opponent_id_source=f"event_{event_id}_{home_team_name}",
                    opponent_name=home_team_name,
                    opponent_club_name=home_team_name,
                    age_group=age_group,
                    gender='M',
                    state='',
                    competition=competition,
                    division_name=division_name,
                    event_name=event_name,
                    venue=venue or '',
                    mls_division='',
                    game_date=game_date.isoformat(),
                    home_away='A',
                    goals_for=away_score,
                    goals_against=home_score,
                    result='W' if int(away_score) > int(home_score) else 'L' if int(away_score) < int(home_score) else 'D',
                    match_id=match_id,
                    source_url=response.url,
                    scraped_at=scraped_at,
                )
                yield away_item
                
                matches_found += 1
                self.stats['games_scraped'] += 1
                
            except Exception as e:
                logger.error(f"Error parsing match row: {e}", exc_info=True)
                self.stats['games_skipped_parse_error'] += 1
                continue
        
        self.stats['pages_processed'] += 1
        
        if matches_found == 0:
            logger.warning(f"No matches found on schedule page for event '{event_name}' ({event_id}), age group {age_group}")
        else:
            logger.info(f"Found {matches_found} matches for event '{event_name}' ({event_id}), age group {age_group}")
        
        # Check for pagination
        # Look for "Next" link
        next_links = response.css('a')
        for link in next_links:
            link_text = ' '.join(link.css('::text').getall()).strip().lower()
            if 'next' in link_text:
                next_url = link.css('::attr(href)').get()
                if next_url:
                    yield scrapy.Request(
                        url=urljoin(response.url, next_url),
                        callback=self.parse_event_schedule,
                        meta=response.meta,
                        dont_filter=True
                    )
                    break
    
    def closed(self, reason):
        """Log statistics when spider closes."""
        logger.info("=" * 60)
        logger.info("Modular11 Events Spider Statistics:")
        logger.info(f"  Events found: {self.stats['events_found']}")
        logger.info(f"  Events in date range: {self.stats['events_in_range']}")
        logger.info(f"  Events scraped: {self.stats['events_scraped']}")
        logger.info(f"  Total games scraped: {self.stats['games_scraped']}")
        logger.info(f"  Games skipped (no score): {self.stats['games_skipped_no_score']}")
        logger.info(f"  Games skipped (date filter): {self.stats['games_skipped_date_filter']}")
        logger.info(f"  Games skipped (parse error): {self.stats['games_skipped_parse_error']}")
        logger.info(f"  Pages processed: {self.stats['pages_processed']}")
        logger.info("=" * 60)

