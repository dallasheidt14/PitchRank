"""HTML parser for AthleteOne/TGS conference schedule pages"""
import re
import hashlib
from dataclasses import dataclass
from typing import List, Optional, Tuple
from datetime import datetime
from bs4 import BeautifulSoup, Tag, NavigableString
import logging

logger = logging.getLogger(__name__)


# STRICT PARSING LOGIC ENABLED
# Note: home_team_id and away_team_id are NOT required - we generate them if missing
REQUIRED_FIELDS = [
    "match_id",
    "home_team_name",
    "away_team_name",
    "venue",
]


@dataclass
class ParsedAthleteOneGame:
    """Parsed game data from AthleteOne/TGS HTML"""
    match_id: str
    home_team_id: Optional[str]
    home_team_name: str
    away_team_id: Optional[str]
    away_team_name: str
    home_score: Optional[int]
    away_score: Optional[int]
    game_datetime: Optional[datetime]
    competition: Optional[str]
    venue: Optional[str]
    field: Optional[str]


def _generate_team_id(name: str) -> str:
    """
    Generate a team ID from team name when HTML doesn't provide one
    
    Uses hash-based approach consistent with scraper:
    - Hash team name and use first 12 chars
    - Format: athone:{hash}
    
    Args:
        name: Team name
    
    Returns:
        Generated team ID string
    """
    raw = name.lower().strip()
    if not raw or raw in ["unknown home", "unknown away"]:
        # Fallback for invalid names
        return f"athone:unknown_{hashlib.md5(raw.encode()).hexdigest()[:8]}"
    return "athone:" + hashlib.md5(raw.encode()).hexdigest()[:12]


def _is_valid(parsed: ParsedAthleteOneGame, logger=None):
    """
    Validate parsed game data meets required fields and consistency rules
    
    Args:
        parsed: ParsedAthleteOneGame object to validate
        logger: Optional logger instance
    
    Returns:
        True if valid, False otherwise
    """
    # Check required fields are all present and not empty
    for field in REQUIRED_FIELDS:
        if not getattr(parsed, field, None):
            if logger:
                logger.warning(f"[SKIP] Missing required field: {field}")
            return False
    
    # Consistency rules
    if parsed.home_score is None and parsed.away_score is not None:
        if logger:
            logger.warning("[SKIP] Inconsistent score: missing home_score")
        return False
    
    if parsed.away_score is None and parsed.home_score is not None:
        if logger:
            logger.warning("[SKIP] Inconsistent score: missing away_score")
        return False

    # If game has no scores at all, it must have a date/time
    if parsed.home_score is None and parsed.away_score is None:
        if parsed.game_datetime is None:
            if logger:
                logger.warning("[SKIP] Scheduled game missing game_datetime")
            return False
    
    return True


# Centralized selector constants for easy adjustment
# Updated to match exact AthleteOne HTML structure
GAME_ROW_SELECTORS = [
    # Primary: rows with individual-team-item spans (exact structure)
    lambda tag: tag.select('span.individual-team-item'),
    # Data attribute selector
    lambda tag: tag.get('data-match-id') is not None,
    # Box score item selector
    lambda tag: tag.select_one('.box-score-item[data-match-id]') is not None,
    # Fallback: class-based
    {'class': lambda x: x and 'game-preview-item' in x},
    {'class': lambda x: x and 'game' in x.lower()},
]

TEAM_NAME_SELECTORS = [
    '.team-name',
    '.team-info',
    '.home-team',
    '.away-team',
    '.team-column.home-team',
    '.team-column.away-team',
]

SCORE_SELECTORS = [
    '.score-column',
    '.score-info',
    '.score',
]

DATE_SELECTORS = [
    '.game-date',
    '.date-info',
]

TIME_SELECTORS = [
    '.game-time',
    '.time-info',
]

VENUE_SELECTORS = [
    '.venue-info',
    '.location-info',
    '.field',
    '.venue',
    '.complex',
]

COMPETITION_SELECTORS = [
    '.flight-name',
]

# Regex patterns
SCORE_PATTERN = re.compile(r'(\d+)\s*-\s*(\d+)')
DATE_PATTERN = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})')
# Also match "Aug 30, 2025" format
DATE_PATTERN_MONTH_NAME = re.compile(r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})', re.IGNORECASE)
TIME_PATTERN = re.compile(r'(\d{1,2}):(\d{2})\s*(AM|PM)', re.IGNORECASE)


def _normalize_text(text: str) -> str:
    """Normalize text: strip whitespace and collapse spaces"""
    if not text:
        return ""
    return ' '.join(text.strip().split())


def _find_game_rows(soup: BeautifulSoup) -> List[Tag]:
    """
    Find all game rows using multiple fallback strategies
    
    Returns:
        List of BeautifulSoup Tag elements representing game rows
    """
    rows = []
    
    # Strategy 1: Look for rows with individual-team-item spans (exact AthleteOne structure)
    rows_with_teams = soup.find_all(lambda tag: tag.select('span.individual-team-item'))
    if rows_with_teams:
        logger.debug(f"Found {len(rows_with_teams)} game rows with individual-team-item spans")
        rows.extend(rows_with_teams)
    
    # Strategy 2: Look for elements with data-match-id
    if not rows:
        rows_with_match_id = soup.find_all(lambda tag: tag.get('data-match-id'))
        if rows_with_match_id:
            logger.debug(f"Found {len(rows_with_match_id)} game rows with data-match-id")
            rows.extend(rows_with_match_id)
    
    # Strategy 3: Look for box-score-item elements
    if not rows:
        box_score_rows = soup.find_all(lambda tag: tag.select_one('.box-score-item[data-match-id]'))
        if box_score_rows:
            logger.debug(f"Found {len(box_score_rows)} game rows with box-score-item")
            rows.extend(box_score_rows)
    
    # Strategy 4: Fallback - class-based selectors
    if not rows:
        for selector in GAME_ROW_SELECTORS:
            if isinstance(selector, dict):
                found = soup.find_all(**selector)
                if found:
                    logger.debug(f"Found {len(found)} game rows using class selector")
                    rows.extend(found)
                    break
    
    # Remove duplicates while preserving order
    seen = set()
    unique_rows = []
    for row in rows:
        row_id = id(row)
        if row_id not in seen:
            seen.add(row_id)
            unique_rows.append(row)
    
    logger.info(f"Found {len(unique_rows)} unique game rows")
    return unique_rows


def _extract_ids(row: Tag) -> dict:
    """
    Extract IDs from row data attributes
    
    Match ID can come from:
    - row.get('data-match-id')
    - .box-score-item[data-match-id]
    
    Event ID from:
    - .individual-team-item[data-event-id]
    """
    # Try to get match_id from row or box-score-item
    match_id = row.get('data-match-id', '')
    if not match_id:
        box_score = row.select_one('.box-score-item[data-match-id]')
        if box_score:
            match_id = box_score.get('data-match-id', '')
    
    # Get event_id from individual-team-item
    event_id = None
    team_item = row.select_one('.individual-team-item')
    if team_item:
        event_id = team_item.get('data-event-id')
    
    return {
        'match_id': match_id,
        'event_id': event_id,
    }


def _extract_score(row: Tag) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract score from row
    
    Exact selector: td div[style*='margin-bottom']
    First div = home score, second div = away score
    
    Returns:
        Tuple of (home_score, away_score) or (None, None) if not found
    """
    # Primary method: Look for score divs with margin-bottom style
    score_divs = row.select("td div[style*='margin-bottom']")
    
    if len(score_divs) >= 2:
        try:
            home_score = int(score_divs[0].text.strip())
            away_score = int(score_divs[1].text.strip())
            return home_score, away_score
        except (ValueError, AttributeError):
            pass
    
    # Fallback: Search entire row text for score pattern
    row_text = _normalize_text(row.get_text())
    match = SCORE_PATTERN.search(row_text)
    if match:
        try:
            home_score = int(match.group(1))
            away_score = int(match.group(2))
            return home_score, away_score
        except ValueError:
            pass
    
    return None, None


def _extract_team_names_and_ids(row: Tag) -> Tuple[str, Optional[str], str, Optional[str]]:
    """
    Extract home and away team names and IDs from row
    
    Exact selector: span.individual-team-item
    First span = home team, second span = away team
    
    Returns:
        Tuple of (home_team_name, home_team_id, away_team_name, away_team_id)
    """
    team_spans = row.select("span.individual-team-item")
    
    home_name = ""
    home_team_id = None
    away_name = ""
    away_team_id = None
    
    if len(team_spans) >= 2:
        # First span is home team
        home_span = team_spans[0]
        home_name = _normalize_text(home_span.text.strip())
        home_team_id = home_span.get('data-team-id')
        
        # Second span is away team
        away_span = team_spans[1]
        away_name = _normalize_text(away_span.text.strip())
        away_team_id = away_span.get('data-team-id')
    elif len(team_spans) == 1:
        # Only one team found - assume it's home
        home_span = team_spans[0]
        home_name = _normalize_text(home_span.text.strip())
        home_team_id = home_span.get('data-team-id')
        away_name = "Unknown Away"
    
    return home_name or "Unknown Home", home_team_id, away_name or "Unknown Away", away_team_id


def _extract_datetime(row: Tag) -> Optional[datetime]:
    """
    Extract date and time from row and combine into datetime
    
    Handles table structure where date/time is in second <td> column:
    <td>
      <div>Aug 30, 2025</div>  <!-- date -->
      <div>11:00 AM</div>      <!-- time -->
      <div>B2010 - ECNL</div>  <!-- competition -->
    </td>
    
    Returns:
        datetime object or None if not found
    """
    date_str = None
    time_str = None
    
    # Strategy 1: Look for date/time in second <td> column (GAME INFO column)
    # This is the table structure used by AthleteOne
    tds = row.find_all('td')
    if len(tds) >= 2:
        # Second <td> contains date/time/competition
        game_info_td = tds[1]
        divs = game_info_td.find_all('div')
        
        # First div is date (format: "Aug 30, 2025")
        if len(divs) >= 1:
            date_str = _normalize_text(divs[0].get_text())
        
        # Second div is time (format: "11:00 AM")
        if len(divs) >= 2:
            time_str = _normalize_text(divs[1].get_text())
    
    # Strategy 2: Try class-based selectors (fallback)
    if not date_str:
        for selector in DATE_SELECTORS:
            date_elem = row.select_one(selector)
            if date_elem:
                date_str = _normalize_text(date_elem.get_text())
                break
    
    # Strategy 3: Search entire row for date pattern (MM/DD/YYYY)
    if not date_str:
        row_text = row.get_text()
        match = DATE_PATTERN.search(row_text)
        if match:
            date_str = f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
    
    # Strategy 4: Search for month name format ("Aug 30, 2025")
    if not date_str:
        row_text = row.get_text()
        match = DATE_PATTERN_MONTH_NAME.search(row_text)
        if match:
            date_str = f"{match.group(1)} {match.group(2)}, {match.group(3)}"
    
    # Extract time
    if not time_str:
        for selector in TIME_SELECTORS:
            time_elem = row.select_one(selector)
            if time_elem:
                time_str = _normalize_text(time_elem.get_text())
                break
    
    # Fallback: search entire row for time pattern
    if not time_str:
        row_text = row.get_text()
        match = TIME_PATTERN.search(row_text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            am_pm = match.group(3).upper()
            if am_pm == 'PM' and hour != 12:
                hour += 12
            elif am_pm == 'AM' and hour == 12:
                hour = 0
            time_str = f"{hour:02d}:{minute:02d}"
    
    # Combine date and time
    if date_str:
        try:
            month = None
            day = None
            year = None
            
            # Try MM/DD/YYYY format first
            date_match = DATE_PATTERN.search(date_str)
            if date_match:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                year = int(date_match.group(3))
            else:
                # Try "Aug 30, 2025" format
                month_match = DATE_PATTERN_MONTH_NAME.search(date_str)
                if month_match:
                    month_name = month_match.group(1).lower()[:3]
                    day = int(month_match.group(2))
                    year = int(month_match.group(3))
                    
                    # Convert month name to number
                    month_map = {
                        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                    }
                    month = month_map.get(month_name)
            
            if month and day and year:
                # Parse time if available
                hour = 0
                minute = 0
                
                if time_str:
                    time_match = TIME_PATTERN.search(time_str)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        am_pm = time_match.group(3).upper()
                        if am_pm == 'PM' and hour != 12:
                            hour += 12
                        elif am_pm == 'AM' and hour == 12:
                            hour = 0
                    else:
                        # Try to parse as HH:MM
                        time_parts = time_str.split(':')
                        if len(time_parts) == 2:
                            try:
                                hour = int(time_parts[0])
                                minute = int(time_parts[1])
                            except ValueError:
                                pass
                
                return datetime(year, month, day, hour, minute)
        except (ValueError, AttributeError, KeyError) as e:
            logger.warning(f"Error parsing datetime from '{date_str}' / '{time_str}': {e}")
    
    return None


def _extract_venue_field(row: Tag) -> Tuple[Optional[str], Optional[str], dict]:
    """
    Extract venue and field information from row
    
    Exact selector: span.game-complex-item
    
    Returns:
        Tuple of (venue, field, venue_meta_dict)
    """
    venue_span = row.select_one("span.game-complex-item")
    
    venue = None
    field = None
    venue_meta = {}
    
    if venue_span:
        venue_text = _normalize_text(venue_span.text.strip())
        
        # Extract venue metadata
        venue_meta['venue_id'] = venue_span.get('data-venue-id')
        venue_meta['complex_id'] = venue_span.get('data-complex-id')
        venue_meta['zip'] = venue_span.get('data-zip')
        
        # Try to separate venue and field
        # Format is typically: "Venue Name - Field X"
        if ' - ' in venue_text:
            parts = venue_text.split(' - ', 1)
            venue = parts[0].strip()
            field = parts[1].strip()
        elif 'Field' in venue_text or 'field' in venue_text:
            # Try to extract field
            field_match = re.search(r'(.+?)\s*-\s*(Field\s+\w+)', venue_text, re.IGNORECASE)
            if field_match:
                venue = field_match.group(1).strip()
                field = field_match.group(2).strip()
            else:
                # Field is part of the name
                venue = venue_text
        else:
            venue = venue_text
    
    return venue, field, venue_meta


def _extract_competition(row: Tag) -> Optional[str]:
    """
    Extract competition/flight name from row
    
    In table structure, competition is in third <div> of second <td>:
    <td>
      <div>Aug 30, 2025</div>
      <div>11:00 AM</div>
      <div>B2010 - ECNL</div>  <!-- competition -->
    </td>
    """
    # Strategy 1: Look in second <td> column, third <div>
    tds = row.find_all('td')
    if len(tds) >= 2:
        game_info_td = tds[1]
        divs = game_info_td.find_all('div')
        if len(divs) >= 3:
            competition_text = _normalize_text(divs[2].get_text())
            if competition_text:
                return competition_text
    
    # Strategy 2: Try class-based selectors (fallback)
    for selector in COMPETITION_SELECTORS:
        elem = row.select_one(selector)
        if elem:
            return _normalize_text(elem.get_text())
    
    return None


def _parse_date_header(date_header_text: str) -> Optional[datetime]:
    """
    Parse date header like "Sunday Sep 21, 2025"
    
    Args:
        date_header_text: Text from date header div
    
    Returns:
        datetime object or None if parsing fails
    """
    # Try to parse formats like "Sunday Sep 21, 2025" or "Sep 21, 2025"
    date_patterns = [
        r'([A-Za-z]+)\s+([A-Za-z]+)\s+(\d+),\s+(\d{4})',  # "Sunday Sep 21, 2025"
        r'([A-Za-z]+)\s+(\d+),\s+(\d{4})',  # "Sep 21, 2025"
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_header_text)
        if match:
            try:
                if len(match.groups()) == 4:
                    # Format: "Sunday Sep 21, 2025"
                    month_name = match.group(2)
                    day = int(match.group(3))
                    year = int(match.group(4))
                else:
                    # Format: "Sep 21, 2025"
                    month_name = match.group(1)
                    day = int(match.group(2))
                    year = int(match.group(3))
                
                # Convert month name to number
                month_map = {
                    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                }
                month = month_map.get(month_name.lower()[:3])
                if month:
                    return datetime(year, month, day, 0, 0)
            except (ValueError, KeyError):
                continue
    
    return None


def _find_game_rows_with_date_headers(soup: BeautifulSoup) -> List[Tuple[Tag, Optional[datetime]]]:
    """
    Find all game rows and associate them with date headers
    
    Date headers appear as: <div class="date-header">Sunday Sep 21, 2025</div>
    All rows after a date header belong to that date until the next date header
    
    Game rows are <tr> elements that contain span.individual-team-item elements
    
    Returns:
        List of tuples: (game_row, cached_date)
    """
    # Find all potential game rows and date headers
    # Focus on <tr> elements first (table rows)
    all_elements = soup.find_all(['tr', 'div'])
    
    game_rows_with_dates = []
    current_date = None
    
    for element in all_elements:
        # Check if this is a date header
        if element.name == 'div' and 'date-header' in str(element.get('class', [])):
            date_text = _normalize_text(element.get_text())
            current_date = _parse_date_header(date_text)
            if current_date:
                logger.debug(f"Found date header: {date_text} -> {current_date.date()}")
            continue
        
        # Game rows must be <tr> elements (table rows)
        if element.name != 'tr':
            continue
        
        # Check if this <tr> contains team spans (the actual game data)
        team_spans = element.select('span.individual-team-item')
        if len(team_spans) >= 2:
            # This is a game row - it has both home and away teams
            game_rows_with_dates.append((element, current_date))
            continue
        
        # Fallback: check for box-score-item or data-match-id on the <tr> itself
        if element.select_one('.box-score-item[data-match-id]') or element.get('data-match-id'):
            # Make sure it's not just a venue span - check for team content
            if element.select('span.individual-team-item') or element.get_text().strip():
                game_rows_with_dates.append((element, current_date))
    
    return game_rows_with_dates


def parse_conference_schedule_html(html: str) -> List[ParsedAthleteOneGame]:
    """
    Parse conference schedule HTML and extract game data
    
    Uses exact selectors based on actual AthleteOne HTML structure:
    - Teams: span.individual-team-item (first = home, second = away)
    - Scores: td div[style*='margin-bottom'] (first two divs)
    - Venue: span.game-complex-item
    - Match ID: data-match-id on row or .box-score-item
    - Date: Cached from date-header divs above rows
    
    Args:
        html: HTML content from get-conference-schedules endpoint
    
    Returns:
        List of ParsedAthleteOneGame objects
    """
    soup = BeautifulSoup(html, 'html.parser')
    games = []
    
    # Find all game rows with associated dates (from date headers)
    game_rows_with_dates = _find_game_rows_with_date_headers(soup)
    
    # Fallback: if date header method didn't find rows, use original method
    if not game_rows_with_dates:
        logger.debug("Date header method found no rows, trying fallback method")
        game_rows = _find_game_rows(soup)
        game_rows_with_dates = [(row, None) for row in game_rows]
    
    if not game_rows_with_dates:
        logger.warning("No game rows found in HTML")
        return games
    
    # Extract data from each row
    for row, cached_date in game_rows_with_dates:
        try:
            # Extract IDs
            ids = _extract_ids(row)
            match_id = ids['match_id'] or f"unknown-{len(games)}"
            event_id = ids.get('event_id')
            
            # Extract team names and IDs using exact selector
            home_name, home_team_id_html, away_name, away_team_id_html = _extract_team_names_and_ids(row)
            
            # Generate team IDs if missing (required for identity resolution)
            # This matches GotSport behavior - generate IDs when provider doesn't provide stable ones
            home_team_id = home_team_id_html
            if not home_team_id:
                home_team_id = _generate_team_id(home_name)
            
            away_team_id = away_team_id_html
            if not away_team_id:
                away_team_id = _generate_team_id(away_name)
            
            # Extract scores using exact selector
            home_score, away_score = _extract_score(row)
            
            # Extract datetime - use cached date from header if row doesn't have time
            game_datetime = _extract_datetime(row)
            if not game_datetime and cached_date:
                # Use cached date (time will be 00:00)
                game_datetime = cached_date
            
            # Extract venue/field using exact selector
            venue, field, venue_meta = _extract_venue_field(row)
            
            # Extract competition
            competition = _extract_competition(row)
            
            game = ParsedAthleteOneGame(
                match_id=match_id,
                home_team_id=home_team_id,
                home_team_name=home_name,
                away_team_id=away_team_id,
                away_team_name=away_name,
                home_score=home_score,
                away_score=away_score,
                game_datetime=game_datetime,
                competition=competition,
                venue=venue,
                field=field,
            )
            
            # STRICT MODE: Validate data quality before adding
            # Note: team IDs are always present (generated if needed), so validation focuses on actual game data
            if not _is_valid(game, logger=logger):
                continue  # STRICT MODE DROP
            
            games.append(game)
            logger.debug(f"Parsed game: {home_name} vs {away_name} (match_id: {match_id}, date: {game_datetime})")
            
        except Exception as e:
            logger.error(f"Error parsing game row: {e}", exc_info=True)
            continue
    
    logger.info(f"Successfully parsed {len(games)} games from HTML")
    return games

