"""Base scraper for all providers"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
import logging

from src.base import BaseProvider, GameData
from src.etl.pipeline import ETLPipeline

logger = logging.getLogger(__name__)

class BaseScraper(BaseProvider, ETLPipeline):
    """Base scraper combining provider interface with ETL pipeline"""
    
    def __init__(self, supabase_client, provider_code: str):
        BaseProvider.__init__(self, provider_code)
        ETLPipeline.__init__(self, supabase_client, provider_code)
        
    def extract(self, context) -> List[Dict]:
        """Extract games from provider"""
        teams = self._get_teams_to_scrape()
        all_games = []
        
        for team in teams:
            try:
                # Get last scrape date
                last_scrape = self._get_last_scrape_date(team['team_id_master'])
                
                # Scrape new games
                games = self.scrape_team_games(
                    team['provider_team_id'],
                    since_date=last_scrape
                )
                
                # Log scrape
                self._log_team_scrape(team['team_id_master'], len(games))
                
                all_games.extend(games)
                
            except Exception as e:
                logger.error(f"Error scraping team {team['provider_team_id']}: {e}")
                self.errors.append({
                    'team_id': team['provider_team_id'],
                    'error': str(e)
                })
                
        return all_games
        
    def _get_teams_to_scrape(self) -> List[Dict]:
        """Get teams that need scraping (not scraped in last 7 days)"""
        # Use the database function to get teams needing scraping
        try:
            result = self.db.rpc('get_teams_to_scrape').execute()
            if result.data:
                # Filter by provider_id
                provider_id = self._get_provider_id()
                # Get full team records for these teams
                team_ids = [row['team_id'] for row in result.data]
                if team_ids:
                    teams_result = self.db.table('teams').select('*').in_(
                        'team_id_master', team_ids
                    ).eq('provider_id', provider_id).execute()
                    return teams_result.data
            return []
        except Exception as e:
            logger.warning(f"Could not use get_teams_to_scrape function: {e}")
            # Fallback: get teams not scraped in last 7 days
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()
            result = self.db.table('teams').select('*').eq(
                'provider_id', self._get_provider_id()
            ).or_(
                'last_scraped_at.is.null,last_scraped_at.lt.' + cutoff_date
            ).execute()
            return result.data
        
    def _get_last_scrape_date(self, team_id: str) -> Optional[datetime]:
        """Get last successful scrape date for team"""
        result = self.db.table('team_scrape_log').select('scraped_at').eq(
            'team_id', team_id
        ).order('scraped_at', desc=True).limit(1).execute()
        
        if result.data:
            return datetime.fromisoformat(result.data[0]['scraped_at'])
        return None
        
    def _log_team_scrape(self, team_id: str, games_found: int):
        """Log team scrape completion and update last_scraped_at"""
        now = datetime.now()
        
        # Update team's last_scraped_at
        self.db.table('teams').update({
            'last_scraped_at': now.isoformat()
        }).eq('team_id_master', team_id).execute()
        
        # Log scrape
        self.db.table('team_scrape_log').insert({
            'team_id': team_id,
            'provider_id': self._get_provider_id(),
            'scraped_at': now.isoformat(),
            'games_found': games_found,
            'status': 'success' if games_found > 0 else 'partial'
        }).execute()