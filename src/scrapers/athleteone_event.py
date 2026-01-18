"""AthleteOne/TGS event scraper - extracts teams from events and scrapes games"""
from typing import List, Optional, Dict, Set
from datetime import datetime
import logging

from src.scrapers.athleteone_scraper import AthleteOneScraper
from src.providers.athleteone_client import AthleteOneClient
from src.providers.athleteone_html_parser import parse_conference_schedule_html, ParsedAthleteOneGame
from src.base import GameData

logger = logging.getLogger(__name__)


class AthleteOneEventScraper:
    """
    Scraper for AthleteOne/TGS events
    
    This scraper:
    1. Fetches conference schedules for events
    2. Extracts teams from the schedule HTML
    3. Scrapes games for those teams (from conference schedules)
    4. Filters games by team
    """
    
    def __init__(self, client: Optional[AthleteOneClient] = None):
        """
        Initialize the AthleteOne event scraper
        
        Args:
            client: Optional AthleteOneClient instance. If None, creates a new one.
        """
        self.client = client or AthleteOneClient()
        self.conference_scraper = AthleteOneScraper(client=self.client)
    
    def extract_teams_from_conference_schedule(
        self,
        org_id: str,
        org_season_id: str,
        event_id: str,
        flight_id: str,
        load_from_file: Optional[str] = None,
    ) -> Dict[str, Set[str]]:
        """
        Extract unique teams from a conference schedule
        
        Args:
            org_id: Organization ID
            org_season_id: Organization season ID
            event_id: Event ID
            flight_id: Flight ID
            load_from_file: Optional path to load HTML from file
        
        Returns:
            Dictionary mapping team_id -> set of team_names (in case names vary)
        """
        # Fetch conference schedule HTML
        html, _ = self.client.get_conference_schedule_html(
            org_id=org_id,
            org_season_id=org_season_id,
            event_id=event_id,
            flight_id=flight_id,
            load_from_file=load_from_file,
        )
        
        # Parse games
        parsed_games = parse_conference_schedule_html(html)
        
        # Extract unique teams
        teams: Dict[str, Set[str]] = {}
        
        for game in parsed_games:
            # Home team
            if game.home_team_id:
                if game.home_team_id not in teams:
                    teams[game.home_team_id] = set()
                teams[game.home_team_id].add(game.home_team_name)
            
            # Away team
            if game.away_team_id:
                if game.away_team_id not in teams:
                    teams[game.away_team_id] = set()
                teams[game.away_team_id].add(game.away_team_name)
        
        logger.info(f"Extracted {len(teams)} unique teams from conference schedule")
        return teams
    
    def scrape_event_games(
        self,
        org_id: str,
        org_season_id: str,
        event_id: str,
        flight_id: str,
        since_date: Optional[datetime] = None,
        team_filter: Optional[List[str]] = None,
        load_from_file: Optional[str] = None,
    ) -> List[GameData]:
        """
        Scrape games from an event's conference schedule
        
        Optionally filter by specific teams if team_filter is provided.
        If team_filter is None, returns all games from the schedule.
        
        Args:
            org_id: Organization ID
            org_season_id: Organization season ID
            event_id: Event ID
            flight_id: Flight ID
            since_date: Optional filter to only include games after this date
            team_filter: Optional list of team IDs to filter games for
            load_from_file: Optional path to load HTML from file
        
        Returns:
            List of GameData objects
        """
        # Fetch conference schedule
        games = self.conference_scraper.scrape_conference_games(
            org_id=org_id,
            org_season_id=org_season_id,
            event_id=event_id,
            flight_id=flight_id,
            since_date=since_date,
            load_from_file=load_from_file,
        )
        
        # Filter by team if requested
        if team_filter:
            team_set = set(team_filter)
            filtered_games = [
                game for game in games
                if game.team_id in team_set
            ]
            logger.info(f"Filtered {len(games)} games to {len(filtered_games)} games for {len(team_filter)} teams")
            return filtered_games
        
        return games
    
    def scrape_event_by_teams(
        self,
        org_id: str,
        org_season_id: str,
        event_id: str,
        flight_id: str,
        since_date: Optional[datetime] = None,
        max_teams: Optional[int] = None,
        load_from_file: Optional[str] = None,
    ) -> List[GameData]:
        """
        Scrape games for teams found in an event
        
        This method:
        1. Extracts teams from the conference schedule
        2. Scrapes games for those teams (from the same schedule)
        3. Limits to max_teams if specified
        
        Args:
            org_id: Organization ID
            org_season_id: Organization season ID
            event_id: Event ID
            flight_id: Flight ID
            since_date: Optional filter to only include games after this date
            max_teams: Optional limit on number of teams to process
            load_from_file: Optional path to load HTML from file
        
        Returns:
            List of GameData objects
        """
        # Extract teams from schedule
        teams = self.extract_teams_from_conference_schedule(
            org_id=org_id,
            org_season_id=org_season_id,
            event_id=event_id,
            flight_id=flight_id,
            load_from_file=load_from_file,
        )
        
        team_ids = list(teams.keys())
        
        if max_teams:
            team_ids = team_ids[:max_teams]
            logger.info(f"Limited to first {max_teams} teams")
        
        logger.info(f"Scraping games for {len(team_ids)} teams from event")
        
        # Scrape games for these teams
        return self.scrape_event_games(
            org_id=org_id,
            org_season_id=org_season_id,
            event_id=event_id,
            flight_id=flight_id,
            since_date=since_date,
            team_filter=team_ids,
            load_from_file=load_from_file,
        )















