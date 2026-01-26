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
        """Extract games from provider and convert to dict format"""
        teams = self._get_teams_to_scrape()
        all_games = []
        
        for team in teams:
            try:
                # Get last scrape date
                last_scrape = self._get_last_scrape_date(team['team_id_master'])
                
                # Scrape new games (returns GameData objects)
                games = self.scrape_team_games(
                    team['provider_team_id'],
                    since_date=last_scrape
                )
                
                # Convert GameData to dict format for import
                for game in games:
                    game_dict = self._game_data_to_dict(game, team['provider_team_id'])
                    if game_dict:
                        all_games.append(game_dict)
                
                # Log scrape
                self._log_team_scrape(team['team_id_master'], len(games))
                
            except Exception as e:
                logger.error(f"Error scraping team {team['provider_team_id']}: {e}")
                self.errors.append({
                    'team_id': team['provider_team_id'],
                    'error': str(e)
                })
        
        return all_games
    
    def _game_data_to_dict(self, game: GameData, team_id: str) -> Dict:
        """Convert GameData to import format dictionary"""
        return {
            'provider': self.provider_code,
            'team_id': str(team_id),
            'team_id_source': str(team_id),
            'opponent_id': str(game.opponent_id) if game.opponent_id else '',
            'opponent_id_source': str(game.opponent_id) if game.opponent_id else '',
            'team_name': game.team_name or '',
            'opponent_name': game.opponent_name or '',
            'game_date': game.game_date,
            'home_away': game.home_away,
            'goals_for': game.goals_for,
            'goals_against': game.goals_against,
            'result': game.result or 'U',
            'competition': game.competition or '',
            'venue': game.venue or '',
            'source_url': game.meta.get('source_url', '') if game.meta else '',
            'scraped_at': game.meta.get('scraped_at', datetime.now().isoformat()) if game.meta else datetime.now().isoformat()
        }
        
    def _get_teams_to_scrape(self) -> List[Dict]:
        """Get teams that need scraping (not scraped in last 7 days)"""
        # Use the database function to get teams needing scraping
        try:
            # Get provider_id first to pass to RPC for proper filtering
            provider_id = self._get_provider_id()

            # Paginate RPC call to handle >1000 teams (Supabase default limit)
            all_team_ids = []
            page_size = 1000
            offset = 0

            while True:
                # Pass provider_id to filter at DB level (fixes cross-provider contamination bug)
                result = self.db.rpc('get_teams_to_scrape', {'p_provider_id': provider_id}).range(
                    offset, offset + page_size - 1
                ).execute()

                if not result.data:
                    break

                all_team_ids.extend([row['team_id'] for row in result.data])

                if len(result.data) < page_size:
                    break

                offset += page_size
                logger.info(f"Fetched {len(all_team_ids)} teams to scrape so far...")

            if all_team_ids:
                # Get full team records for these teams (already filtered by provider in RPC)
                # Batch fetch to handle >1000 teams and URL length limits
                # Each UUID is ~36 chars, so batch size of 100 keeps URLs manageable
                all_teams = []
                batch_size = 100
                for i in range(0, len(all_team_ids), batch_size):
                    batch_ids = all_team_ids[i:i + batch_size]
                    teams_result = self.db.table('teams').select('*').in_(
                        'team_id_master', batch_ids
                    ).eq('provider_id', provider_id).execute()
                    if teams_result.data:
                        all_teams.extend(teams_result.data)

                logger.info(f"Total teams to scrape: {len(all_teams)}")
                return all_teams
            return []
        except Exception as e:
            logger.warning(f"Could not use get_teams_to_scrape function: {e}")
            # Fallback: get teams not scraped in last 7 days with pagination
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()

            all_teams = []
            page_size = 1000
            offset = 0

            while True:
                result = self.db.table('teams').select('*').eq(
                    'provider_id', self._get_provider_id()
                ).or_(
                    'last_scraped_at.is.null,last_scraped_at.lt.' + cutoff_date
                ).range(offset, offset + page_size - 1).execute()

                if not result.data:
                    break

                all_teams.extend(result.data)

                if len(result.data) < page_size:
                    break

                offset += page_size

            return all_teams
        
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