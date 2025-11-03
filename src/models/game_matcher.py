"""Game matching system with fuzzy matching and alias support"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from difflib import SequenceMatcher
import logging
import uuid

from supabase import Client
from config.settings import MATCHING_CONFIG

logger = logging.getLogger(__name__)

# UUID namespace for deterministic game UIDs
GAME_UID_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # Standard DNS namespace


class GameHistoryMatcher:
    """Match game history records to master teams using fuzzy matching and aliases"""

    def __init__(self, supabase: Client):
        self.db = supabase
        self.fuzzy_threshold = MATCHING_CONFIG['fuzzy_threshold']
        self.auto_approve_threshold = MATCHING_CONFIG['auto_approve_threshold']
        self.review_threshold = MATCHING_CONFIG['review_threshold']
        self.max_age_diff = MATCHING_CONFIG['max_age_diff']
    
    @staticmethod
    def generate_game_uid(
        provider: str,
        game_date: str,
        home_team_id: str,
        away_team_id: str,
        home_score: Optional[int],
        away_score: Optional[int]
    ) -> str:
        """
        Generate deterministic UUID for a game.
        
        Same game data will always produce the same UUID, preventing duplicates.
        
        Args:
            provider: Provider code (e.g., 'gotsport')
            game_date: Game date in YYYY-MM-DD format
            home_team_id: Home team provider ID
            away_team_id: Away team provider ID
            home_score: Home team score (None if unknown)
            away_score: Away team score (None if unknown)
        
        Returns:
            UUID string
        """
        # Normalize scores to string (handle None)
        home_score_str = str(home_score) if home_score is not None else 'null'
        away_score_str = str(away_score) if away_score is not None else 'null'
        
        # Create deterministic string
        uid_string = f"{provider}|{game_date}|{home_team_id}|{away_team_id}|{home_score_str}|{away_score_str}"
        
        # Generate UUID5 (deterministic)
        game_uid = uuid.uuid5(GAME_UID_NAMESPACE, uid_string)
        
        return str(game_uid)

    def match_game_history(self, game_data: Dict) -> Dict:
        """
        Match a game history record to master teams.
        
        Returns:
            Dict with game record ready for insertion including:
            - team_id_master: matched team ID
            - opponent_id_master: matched opponent ID
            - match_status: 'matched', 'partial', or 'failed'
            - team_match_method: how team was matched
            - opponent_match_method: how opponent was matched
            - team_match_confidence: confidence score for team match
            - opponent_match_confidence: confidence score for opponent match
        """
        # Get provider ID
        provider_id = self._get_provider_id(game_data.get('provider'))
        
        # Match team
        team_match = self._match_team(
            provider_id=provider_id,
            provider_team_id=game_data.get('team_id'),
            team_name=game_data.get('team_name'),
            age_group=game_data.get('age_group'),
            gender=game_data.get('gender')
        )
        
        # Match opponent
        opponent_match = self._match_team(
            provider_id=provider_id,
            provider_team_id=game_data.get('opponent_id'),
            team_name=game_data.get('opponent_name'),
            age_group=game_data.get('age_group'),  # Usually same age group
            gender=game_data.get('gender')
        )
        
        # Determine overall match status
        if team_match['matched'] and opponent_match['matched']:
            match_status = 'matched'
        elif team_match['matched'] or opponent_match['matched']:
            match_status = 'partial'
        else:
            match_status = 'failed'
        
        # Determine home/away teams based on home_away flag
        home_away = game_data.get('home_away', 'H').upper()
        
        if home_away == 'H':
            # Team is home, opponent is away
            home_team_id = team_match.get('team_id')
            away_team_id = opponent_match.get('team_id')
            home_provider_id = game_data.get('team_id', '')
            away_provider_id = game_data.get('opponent_id', '')
            home_score = game_data.get('goals_for')
            away_score = game_data.get('goals_against')
        else:
            # Team is away, opponent is home
            home_team_id = opponent_match.get('team_id')
            away_team_id = team_match.get('team_id')
            home_provider_id = game_data.get('opponent_id', '')
            away_provider_id = game_data.get('team_id', '')
            home_score = game_data.get('goals_against')
            away_score = game_data.get('goals_for')
        
        # Generate deterministic game UID
        provider_code = game_data.get('provider', '')
        game_uid = self.generate_game_uid(
            provider=provider_code,
            game_date=game_data.get('game_date', ''),
            home_team_id=home_provider_id,
            away_team_id=away_provider_id,
            home_score=home_score,
            away_score=away_score
        )
        
        # Build game record for new schema
        game_record = {
            'game_uid': game_uid,
            'home_team_master_id': home_team_id,
            'away_team_master_id': away_team_id,
            'home_provider_id': home_provider_id,
            'away_provider_id': away_provider_id,
            'home_score': home_score,
            'away_score': away_score,
            'result': game_data.get('result'),
            'game_date': game_data.get('game_date'),
            'competition': game_data.get('competition'),
            'division_name': game_data.get('division_name'),
            'event_name': game_data.get('event_name'),
            'venue': game_data.get('venue'),
            'provider_id': provider_id,
            'source_url': game_data.get('source_url'),
            'scraped_at': game_data.get('scraped_at'),
            'match_status': match_status,  # Keep for tracking
            'raw_data': game_data  # Store original for debugging
        }
        
        return game_record

    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str]
    ) -> Dict:
        """
        Match a team using provider ID, alias map, and fuzzy matching.
        
        Returns:
            Dict with:
            - matched: bool
            - team_id: str if matched
            - method: str ('provider_id', 'alias', 'fuzzy', None)
            - confidence: float (0.0-1.0)
        """
        # Strategy 1: Direct provider ID match
        if provider_team_id:
            alias_match = self._match_by_provider_id(provider_id, provider_team_id)
            if alias_match:
                return {
                    'matched': True,
                    'team_id': alias_match['team_id_master'],
                    'method': 'provider_id',
                    'confidence': 1.0
                }
        
        # Strategy 2: Check existing alias map
        if provider_team_id or team_name:
            alias_match = self._match_by_alias(provider_id, provider_team_id, team_name, age_group, gender)
            if alias_match and alias_match['confidence'] >= self.auto_approve_threshold:
                return {
                    'matched': True,
                    'team_id': alias_match['team_id_master'],
                    'method': 'alias',
                    'confidence': alias_match['confidence']
                }
        
        # Strategy 3: Fuzzy match against master teams
        if team_name and age_group and gender:
            fuzzy_match = self._fuzzy_match_team(team_name, age_group, gender)
            if fuzzy_match:
                confidence = fuzzy_match['confidence']
                
                # Auto-approve high confidence matches (0.9+)
                if confidence >= self.auto_approve_threshold:
                    # Create alias automatically
                    self._create_alias(
                        provider_id=provider_id,
                        provider_team_id=provider_team_id,
                        team_name=team_name,
                        team_id_master=fuzzy_match['team_id'],
                        match_method='fuzzy_auto',
                        confidence=confidence,
                        age_group=age_group,
                        gender=gender,
                        review_status='approved'
                    )
                    return {
                        'matched': True,
                        'team_id': fuzzy_match['team_id'],
                        'method': 'fuzzy_auto',
                        'confidence': confidence
                    }
                
                # Flag for review if between 0.75-0.9
                elif confidence >= self.review_threshold:
                    self._create_alias(
                        provider_id=provider_id,
                        provider_team_id=provider_team_id,
                        team_name=team_name,
                        team_id_master=fuzzy_match['team_id'],
                        match_method='fuzzy_review',
                        confidence=confidence,
                        age_group=age_group,
                        gender=gender,
                        review_status='pending'
                    )
                    return {
                        'matched': False,  # Not matched until reviewed
                        'team_id': None,
                        'method': 'fuzzy_review',
                        'confidence': confidence
                    }
                
                # Reject matches below 0.75 (don't create alias)
                else:
                    logger.debug(f"Match rejected: confidence {confidence} below threshold {self.review_threshold}")
                    return {
                        'matched': False,
                        'team_id': None,
                        'method': None,
                        'confidence': confidence
                    }
        
        # No match found
        return {
            'matched': False,
            'team_id': None,
            'method': None,
            'confidence': 0.0
        }

    def _match_by_provider_id(self, provider_id: str, provider_team_id: str) -> Optional[Dict]:
        """Match by exact provider ID in alias map"""
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status'
            ).eq('provider_id', provider_id).eq(
                'provider_team_id', provider_team_id
            ).eq('review_status', 'approved').single().execute()
            
            if result.data:
                return result.data
        except Exception as e:
            logger.debug(f"No provider ID match found: {e}")
        return None

    def _match_by_alias(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str]
    ) -> Optional[Dict]:
        """Match using existing alias map with name/ID lookup"""
        try:
            # Build query
            query = self.db.table('team_alias_map').select('*').eq(
                'provider_id', provider_id
            ).eq('review_status', 'approved')
            
            # Try provider_team_id first
            if provider_team_id:
                query = query.eq('provider_team_id', provider_team_id)
            
            # Or match by name if available
            elif team_name:
                query = query.ilike('team_name', f"%{team_name}%")
            
            result = query.limit(1).execute()
            
            if result.data:
                alias = result.data[0]
                
                # Check age group and gender match
                if age_group and alias.get('age_group') != age_group:
                    return None
                if gender and alias.get('gender') != gender:
                    return None
                
                return {
                    'team_id_master': alias['team_id_master'],
                    'confidence': alias.get('match_confidence', 0.9)
                }
        except Exception as e:
            logger.debug(f"Alias match error: {e}")
        return None

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str
    ) -> Optional[Dict]:
        """Fuzzy match team name against master teams"""
        try:
            # Get candidate teams
            result = self.db.table('teams').select(
                'team_id_master, team_name, age_group, gender'
            ).eq('age_group', age_group).eq('gender', gender).execute()
            
            best_match = None
            best_score = 0.0
            
            for team in result.data:
                # Calculate similarity
                score = self._calculate_similarity(team_name, team['team_name'])
                
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = {
                        'team_id': team['team_id_master'],
                        'team_name': team['team_name'],
                        'confidence': score
                    }
            
            return best_match
            
        except Exception as e:
            logger.error(f"Fuzzy match error: {e}")
            return None

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate string similarity using SequenceMatcher"""
        # Normalize strings
        str1 = str1.lower().strip()
        str2 = str2.lower().strip()
        
        # Direct match
        if str1 == str2:
            return 1.0
        
        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, str1, str2).ratio()

    def _create_alias(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: str,
        team_id_master: str,
        match_method: str,
        confidence: float,
        age_group: str,
        gender: str,
        review_status: str = 'approved'
    ):
        """Create or update team alias map entry"""
        try:
            # Check if alias already exists
            query = self.db.table('team_alias_map').select('id')
            
            if provider_team_id:
                query = query.eq('provider_id', provider_id).eq(
                    'provider_team_id', provider_team_id
                )
            else:
                query = query.eq('provider_id', provider_id).eq(
                    'team_name', team_name
                ).eq('age_group', age_group).eq('gender', gender)
            
            existing = query.execute()
            
            alias_data = {
                'provider_id': provider_id,
                'provider_team_id': provider_team_id,
                'team_id_master': team_id_master,
                'team_name': team_name,
                'age_group': age_group,
                'gender': gender,
                'match_method': match_method,
                'match_confidence': confidence,
                'review_status': review_status,
                'created_at': datetime.now().isoformat()
            }
            
            if existing.data:
                # Update existing
                self.db.table('team_alias_map').update(alias_data).eq(
                    'id', existing.data[0]['id']
                ).execute()
            else:
                # Create new
                self.db.table('team_alias_map').insert(alias_data).execute()
                
        except Exception as e:
            logger.error(f"Error creating alias: {e}")

    def _get_provider_id(self, provider_code: Optional[str]) -> str:
        """Get provider UUID from code"""
        if not provider_code:
            raise ValueError("Provider code is required")
        
        try:
            result = self.db.table('providers').select('id').eq(
                'code', provider_code
            ).single().execute()
            return result.data['id']
        except Exception as e:
            logger.error(f"Provider not found: {provider_code}")
            raise ValueError(f"Provider not found: {provider_code}") from e

