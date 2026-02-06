"""AthleteOne/TGS scraper for conference schedules"""
import hashlib
import logging
from typing import List, Optional
from datetime import datetime

from src.base import GameData
from src.providers.athleteone_client import AthleteOneClient
from src.providers.athleteone_html_parser import (
    parse_conference_schedule_html,
    ParsedAthleteOneGame,
)

logger = logging.getLogger(__name__)


class AthleteOneScraper:
    """
    Scraper for AthleteOne/TGS conference schedules
    
    This scraper fetches conference schedules from the AthleteOne API and converts
    them into GameData format. Unlike team-based scrapers, this works at the
    conference/event/flight level.
    """
    
    provider_code = "athleteone"
    
    def __init__(self, client: Optional[AthleteOneClient] = None, logger=None):
        """
        Initialize the AthleteOne scraper
        
        Args:
            client: Optional AthleteOneClient instance. If None, creates a new one.
            logger: Optional logger instance. If None, uses module logger.
        """
        self.client = client or AthleteOneClient()
        self.logger = logger or logging.getLogger(__name__)
    
    def _generate_team_id(self, team_name: str, match_id: str, prefix: str = "home") -> str:
        """
        Generate a team ID when TGS doesn't provide one
        
        Uses hash-based approach to reduce collision risk:
        - Hash team name and use first 8 chars
        - Format: athone:{hash}
        
        Args:
            team_name: Team name
            match_id: Match ID
            prefix: "home" or "away"
        
        Returns:
            Generated team ID string
        """
        if not team_name or team_name == "Unknown Home" or team_name == "Unknown Away":
            # Fallback to match_id-based ID if team name is missing
            return f"ath-one-{prefix}-{match_id}"
        
        # Generate hash from normalized team name
        normalized_name = team_name.lower().strip()
        hash_obj = hashlib.md5(normalized_name.encode())
        hash_str = hash_obj.hexdigest()[:8]
        
        return f"athone:{hash_str}"
    
    @staticmethod
    def _infer_result(
        goals_for: Optional[int],
        goals_against: Optional[int],
    ) -> Optional[str]:
        """
        Infer game result from scores
        
        Args:
            goals_for: Goals scored by the team
            goals_against: Goals scored by opponent
        
        Returns:
            "W" (win), "L" (loss), "D" (draw), or None if scores not available
        """
        if goals_for is None or goals_against is None:
            return None
        
        if goals_for > goals_against:
            return "W"
        elif goals_for < goals_against:
            return "L"
        else:
            return "D"
    
    def scrape_conference_games(
        self,
        org_id: str,
        org_season_id: str,
        event_id: str,
        flight_id: str,
        since_date: Optional[datetime] = None,
        save_html_path: Optional[str] = None,
        load_from_file: Optional[str] = None,
    ) -> List[GameData]:
        """
        Fetch conference schedule and convert to GameData format
        
        Args:
            org_id: Organization ID
            org_season_id: Organization season ID
            event_id: Event ID
            flight_id: Flight ID
            since_date: Optional filter to only include games after this date
            save_html_path: Optional path to save fetched HTML for debugging
            load_from_file: Optional path to load HTML from file (bypasses network)
        
        Returns:
            List of GameData objects (two per game: home and away perspectives)
        """
        # Fetch HTML
        html, fetch_url = self.client.get_conference_schedule_html(
            org_id=org_id,
            org_season_id=org_season_id,
            event_id=event_id,
            flight_id=flight_id,
            save_html_path=save_html_path,
            load_from_file=load_from_file,
        )
        
        # Parse HTML
        parsed_games = parse_conference_schedule_html(html)
        
        if not parsed_games:
            self.logger.warning(f"No games found in conference schedule")
            return []
        
        # Convert to GameData format
        game_data_list: List[GameData] = []
        
        for parsed_game in parsed_games:
            # Filter by since_date if provided
            if since_date and parsed_game.game_datetime:
                if parsed_game.game_datetime < since_date:
                    continue
            
            # Generate team IDs if not provided
            home_team_id = parsed_game.home_team_id
            if not home_team_id:
                home_team_id = self._generate_team_id(
                    parsed_game.home_team_name,
                    parsed_game.match_id,
                    prefix="home"
                )
            
            away_team_id = parsed_game.away_team_id
            if not away_team_id:
                away_team_id = self._generate_team_id(
                    parsed_game.away_team_name,
                    parsed_game.match_id,
                    prefix="away"
                )
            
            # Format game date
            game_date_str = None
            if parsed_game.game_datetime:
                game_date_str = parsed_game.game_datetime.date().isoformat()
            
            # Build metadata dict
            meta = {
                "source": "athleteone_conference",
                "match_id": parsed_game.match_id,
                "fetch_url": fetch_url,
                "timezone": "local",  # TGS doesn't provide timezone info
            }
            
            if parsed_game.field:
                meta["field"] = parsed_game.field
            
            # Home team perspective
            game_data_list.append(
                GameData(
                    provider_id=self.provider_code,
                    team_id=home_team_id,
                    opponent_id=away_team_id,
                    team_name=parsed_game.home_team_name,
                    opponent_name=parsed_game.away_team_name,
                    game_date=game_date_str,
                    home_away="H",
                    goals_for=parsed_game.home_score,
                    goals_against=parsed_game.away_score,
                    result=self._infer_result(
                        goals_for=parsed_game.home_score,
                        goals_against=parsed_game.away_score,
                    ),
                    competition=parsed_game.competition,
                    venue=parsed_game.venue,
                    meta=meta.copy(),
                )
            )

            # Away team perspective
            game_data_list.append(
                GameData(
                    provider_id=self.provider_code,
                    team_id=away_team_id,
                    opponent_id=home_team_id,
                    team_name=parsed_game.away_team_name,
                    opponent_name=parsed_game.home_team_name,
                    game_date=game_date_str,
                    home_away="A",
                    goals_for=parsed_game.away_score,
                    goals_against=parsed_game.home_score,
                    result=self._infer_result(
                        goals_for=parsed_game.away_score,
                        goals_against=parsed_game.home_score,
                    ),
                    competition=parsed_game.competition,
                    venue=parsed_game.venue,
                    meta=meta.copy(),
                )
            )
        
        self.logger.info(
            f"Converted {len(parsed_games)} parsed games into {len(game_data_list)} GameData entries"
        )
        
        return game_data_list

















