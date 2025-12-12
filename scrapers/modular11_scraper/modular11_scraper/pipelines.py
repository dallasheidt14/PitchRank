"""
Scrapy pipelines for Modular11 scraper.

Handles normalization, validation, and CSV output of scraped game data.
"""
import csv
import logging
import os
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from scrapy import Spider
from scrapy.exceptions import DropItem

from modular11_scraper.items import Modular11GameItem


logger = logging.getLogger(__name__)


class Modular11Pipeline:
    """
    Pipeline for processing Modular11 game items.
    
    Responsibilities:
    1. Normalize fields (strip whitespace, format dates, normalize age/gender)
    2. Validate required fields are present
    3. Compute result if not set
    4. Filter by date window
    5. Write to CSV output file
    """
    
    # CSV field order matching import_games_enhanced.py expectations
    FIELDNAMES = [
        "provider",
        "team_id",
        "team_id_source",
        "team_name",
        "club_name",
        "opponent_id",
        "opponent_id_source",
        "opponent_name",
        "opponent_club_name",
        "age_group",
        "gender",
        "state",
        "competition",
        "division_name",
        "event_name",
        "venue",
        "mls_division",  # "HD" (Homegrown) or "AD" (Academy) - for differentiating team tiers
        "game_date",
        "home_away",
        "goals_for",
        "goals_against",
        "result",
        "source_url",
        "scraped_at",
    ]
    
    # Required fields for a valid item
    REQUIRED_FIELDS = [
        'team_id',
        'opponent_id',
        'home_away',
        'game_date',
        'goals_for',
        'goals_against',
    ]
    
    # Valid age groups
    VALID_AGE_GROUPS = {'U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18', 'U19'}
    
    def __init__(self):
        """Initialize the pipeline."""
        self.csv_file = None
        self.csv_writer = None
        self.items_written = 0
        self.items_dropped = 0
        self.cutoff_date = None
    
    def open_spider(self, spider: Spider):
        """
        Called when spider opens. Initialize CSV output.
        
        Args:
            spider: The spider instance
        """
        # Calculate cutoff date
        days_back = getattr(spider, 'days_back', 365)
        self.cutoff_date = date.today() - timedelta(days=int(days_back))
        
        # Determine output path
        output_dir = Path(__file__).parent.parent / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Use timestamped filename to avoid conflicts
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'modular11_results_{timestamp}.csv'
        
        # Check if file exists to determine if we need headers
        file_exists = output_file.exists() and output_file.stat().st_size > 0
        
        # Open file in append mode, but for a fresh scrape we want to overwrite
        # Use write mode to start fresh each run
        self.csv_file = open(output_file, 'w', newline='', encoding='utf-8')
        self.csv_writer = csv.DictWriter(
            self.csv_file,
            fieldnames=self.FIELDNAMES,
            extrasaction='ignore'
        )
        
        # Always write header for fresh file
        self.csv_writer.writeheader()
        
        logger.info(f"Opened CSV output: {output_file}")
        logger.info(f"Date cutoff: {self.cutoff_date}")
    
    def close_spider(self, spider: Spider):
        """
        Called when spider closes. Cleanup resources.
        
        Args:
            spider: The spider instance
        """
        if self.csv_file:
            self.csv_file.close()
            logger.info(f"Closed CSV output. Items written: {self.items_written}, dropped: {self.items_dropped}")
    
    def process_item(self, item: Modular11GameItem, spider: Spider) -> Modular11GameItem:
        """
        Process a game item.
        
        Args:
            item: The game item to process
            spider: The spider instance
            
        Returns:
            The processed item
            
        Raises:
            DropItem: If item is invalid or should be filtered out
        """
        # Normalize all string fields
        self._normalize_strings(item)
        
        # Normalize age group
        self._normalize_age_group(item)
        
        # Normalize gender
        self._normalize_gender(item)
        
        # Normalize date
        self._normalize_date(item)
        
        # Normalize scores
        self._normalize_scores(item)
        
        # Normalize home/away
        self._normalize_home_away(item)
        
        # Compute result if needed
        self._compute_result(item)
        
        # Validate required fields
        self._validate_required_fields(item)
        
        # Check date filter
        self._validate_date_window(item)
        
        # Write to CSV
        self._write_item(item)
        
        return item
    
    def _normalize_strings(self, item: Modular11GameItem):
        """Strip whitespace from all string fields."""
        for field in item.fields:
            value = item.get(field)
            if isinstance(value, str):
                item[field] = value.strip()
    
    def _normalize_age_group(self, item: Modular11GameItem):
        """
        Normalize age group to standard format (U10-U19).
        
        Handles formats like: U14, u14, U14B, U14 Boys, 14U, etc.
        """
        age_group = item.get('age_group', '')
        if not age_group:
            return
        
        # Extract numeric age
        match = re.search(r'(\d{1,2})', str(age_group))
        if match:
            age_num = int(match.group(1))
            if 10 <= age_num <= 19:
                item['age_group'] = f'U{age_num}'
            else:
                logger.warning(f"Unusual age number: {age_num}")
                item['age_group'] = f'U{age_num}'
        else:
            logger.warning(f"Could not parse age group: {age_group}")
    
    def _normalize_gender(self, item: Modular11GameItem):
        """
        Normalize gender to 'Male' or 'Female'.
        
        Note: The import pipeline validator expects full words ('Male', 'Female', 
        'Boys', 'Girls', 'Coed'), not abbreviations.
        
        Handles: Male, Female, Boys, Girls, M, F, MALE, FEMALE, Coed, etc.
        """
        gender = item.get('gender', '')
        if not gender:
            item['gender'] = 'Male'  # Default to Male for MLS NEXT
            return
        
        gender_upper = str(gender).upper().strip()
        
        if gender_upper in ('M', 'MALE', 'BOY', 'BOYS', 'B'):
            item['gender'] = 'Male'
        elif gender_upper in ('F', 'FEMALE', 'GIRL', 'GIRLS', 'G'):
            item['gender'] = 'Female'
        else:
            # Default to Male for MLS NEXT (boys-only league)
            item['gender'] = 'Male'
    
    def _normalize_date(self, item: Modular11GameItem):
        """
        Normalize date to YYYY-MM-DD format.
        
        Handles various input formats.
        """
        game_date = item.get('game_date', '')
        if not game_date:
            return
        
        # If already in correct format, validate it
        if re.match(r'^\d{4}-\d{2}-\d{2}$', game_date):
            return
        
        # Try to parse various formats
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%m/%d/%y',
            '%d/%m/%Y',
            '%d/%m/%y',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(game_date, fmt)
                item['game_date'] = dt.strftime('%Y-%m-%d')
                return
            except ValueError:
                continue
        
        logger.warning(f"Could not normalize date: {game_date}")
    
    def _normalize_scores(self, item: Modular11GameItem):
        """
        Ensure goals_for and goals_against are numeric strings.
        """
        for field in ('goals_for', 'goals_against'):
            value = item.get(field, '')
            if value == '' or value is None:
                continue
            
            try:
                # Convert to int then back to string to ensure clean format
                item[field] = str(int(float(value)))
            except (ValueError, TypeError):
                logger.warning(f"Could not normalize {field}: {value}")
                item[field] = ''
    
    def _normalize_home_away(self, item: Modular11GameItem):
        """
        Normalize home/away to H or A.
        """
        home_away = item.get('home_away', '')
        if not home_away:
            return
        
        ha_upper = str(home_away).upper().strip()
        
        if ha_upper in ('H', 'HOME'):
            item['home_away'] = 'H'
        elif ha_upper in ('A', 'AWAY'):
            item['home_away'] = 'A'
        else:
            logger.warning(f"Unknown home_away value: {home_away}")
    
    def _compute_result(self, item: Modular11GameItem):
        """
        Compute or validate the result field.
        """
        goals_for = item.get('goals_for', '')
        goals_against = item.get('goals_against', '')
        
        if goals_for == '' or goals_against == '':
            item['result'] = 'U'  # Unknown
            return
        
        try:
            gf = int(goals_for)
            ga = int(goals_against)
            
            if gf > ga:
                item['result'] = 'W'
            elif gf < ga:
                item['result'] = 'L'
            else:
                item['result'] = 'D'
        except (ValueError, TypeError):
            item['result'] = 'U'
    
    def _validate_required_fields(self, item: Modular11GameItem):
        """
        Validate that all required fields are present and non-empty.
        
        Raises:
            DropItem: If a required field is missing
        """
        missing = []
        for field in self.REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or value == '':
                missing.append(field)
        
        if missing:
            self.items_dropped += 1
            raise DropItem(f"Missing required fields: {', '.join(missing)}")
    
    def _validate_date_window(self, item: Modular11GameItem):
        """
        Validate that game date is within the allowed window.
        
        Raises:
            DropItem: If game is older than cutoff date
        """
        game_date_str = item.get('game_date', '')
        if not game_date_str:
            return
        
        try:
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
            if game_date < self.cutoff_date:
                self.items_dropped += 1
                raise DropItem(f"Game date {game_date} is before cutoff {self.cutoff_date}")
        except ValueError:
            pass  # Date parsing handled elsewhere
    
    def _write_item(self, item: Modular11GameItem):
        """
        Write item to CSV file.
        
        Args:
            item: The game item to write
        """
        # Convert item to dict with only the fields we want
        row = {field: item.get(field, '') for field in self.FIELDNAMES}
        
        self.csv_writer.writerow(row)
        self.items_written += 1
        
        # Flush periodically for reliability
        if self.items_written % 100 == 0:
            self.csv_file.flush()
            logger.debug(f"Written {self.items_written} items to CSV")

