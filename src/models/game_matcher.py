"""Game matching system with fuzzy matching and alias support"""
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from difflib import SequenceMatcher
import logging
import uuid
import string
from dataclasses import dataclass

from supabase import Client
from config.settings import MATCHING_CONFIG

logger = logging.getLogger(__name__)

# UUID namespace for deterministic game UIDs
GAME_UID_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # Standard DNS namespace


@dataclass
class MatchResult:
    """Structured match result for team matching"""
    master_team_id: str
    confidence: float
    provider_team_name: str
    details: Dict[str, Any]


class MatchingThresholds:
    """Enforced matching thresholds"""
    AUTO_LINK = 0.90      # Automatically link
    MANUAL_REVIEW = 0.75  # Queue for review  
    BLOCK = 0.75          # Reject below this


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
        team1_id: str,
        team2_id: str
    ) -> str:
        """
        Generate deterministic game UID using sorted team IDs (no scores).
        
        Same game will produce the same UID regardless of which team's perspective
        or the scores. Format: {provider}:{date}:{sorted_team1}:{sorted_team2}
        
        Args:
            provider: Provider code (e.g., 'gotsport')
            game_date: Game date in YYYY-MM-DD format
            team1_id: First team provider ID
            team2_id: Second team provider ID
        
        Returns:
            Game UID string (e.g., 'gotsport:2025-06-01:3841:4719')
        """
        # Sort team IDs so order doesn't matter
        # Ensure team IDs are strings and remove any .0 from float conversion
        team1_str = str(int(float(str(team1_id)))) if team1_id else ''
        team2_str = str(int(float(str(team2_id)))) if team2_id else ''
        sorted_teams = sorted([team1_str, team2_str])
        
        # Create deterministic UID without scores
        game_uid = f"{provider}:{game_date}:{sorted_teams[0]}:{sorted_teams[1]}"
        
        return game_uid

    def match_game_history(self, game_data: Dict) -> Dict:
        """
        Match a game history record to master teams.
        
        Handles both source format (team_id/opponent_id) and transformed format (home_team_id/away_team_id).
        If transformed format is already provided, use it directly.
        
        Returns:
            Dict with game record ready for insertion including:
            - home_team_master_id: matched home team ID
            - away_team_master_id: matched away team ID
            - match_status: 'matched', 'partial', or 'failed'
        """
        # Get provider ID
        provider_id = self._get_provider_id(game_data.get('provider'))
        
        # Check if game is already transformed (has home_team_id/away_team_id)
        if 'home_team_id' in game_data and 'away_team_id' in game_data:
            # Already transformed - use directly
            home_provider_id = game_data.get('home_provider_id') or game_data.get('home_team_id', '')
            away_provider_id = game_data.get('away_provider_id') or game_data.get('away_team_id', '')
            
            # Match home team
            home_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=home_provider_id,
                team_name=game_data.get('home_team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('home_club_name') or game_data.get('club_name')
            )
            
            # Match away team
            away_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=away_provider_id,
                team_name=game_data.get('away_team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('away_club_name') or game_data.get('opponent_club_name')
            )
            
            home_team_master_id = home_match.get('team_id')
            away_team_master_id = away_match.get('team_id')
            home_score = game_data.get('home_score')
            away_score = game_data.get('away_score')
            
        else:
            # Source format - transform and match
            # Match team
            team_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=game_data.get('team_id'),
                team_name=game_data.get('team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('club_name') or game_data.get('team_club_name')
            )
            
            # Match opponent
            opponent_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=game_data.get('opponent_id'),
                team_name=game_data.get('opponent_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('opponent_club_name')
            )
            
            # Determine home/away teams based on home_away flag
            home_away = game_data.get('home_away', 'H').upper()
            
            if home_away == 'H':
                # team_id is home, opponent_id is away
                home_team_master_id = team_match.get('team_id')
                away_team_master_id = opponent_match.get('team_id')
                home_provider_id = game_data.get('team_id', '')
                away_provider_id = game_data.get('opponent_id', '')
                home_score = game_data.get('goals_for')
                away_score = game_data.get('goals_against')
            else:
                # team_id is away, opponent_id is home
                home_team_master_id = opponent_match.get('team_id')
                away_team_master_id = team_match.get('team_id')
                home_provider_id = game_data.get('opponent_id', '')
                away_provider_id = game_data.get('team_id', '')
                home_score = game_data.get('goals_against')
                away_score = game_data.get('goals_for')
        
        # Determine overall match status
        if home_team_master_id and away_team_master_id:
            match_status = 'matched'
        elif home_team_master_id or away_team_master_id:
            match_status = 'partial'
        else:
            match_status = 'failed'
        
        # Game UID should already be set by _validate_games, but generate if missing
        if not game_data.get('game_uid'):
            provider_code = game_data.get('provider', '')
            home_id = home_provider_id if 'home_provider_id' in game_data else (game_data.get('home_team_id') or '')
            away_id = away_provider_id if 'away_provider_id' in game_data else (game_data.get('away_team_id') or '')
            game_uid = self.generate_game_uid(
                provider=provider_code,
                game_date=game_data.get('game_date', ''),
                team1_id=home_id,
                team2_id=away_id
            )
        else:
            game_uid = game_data.get('game_uid')
        
        # Build game record for new schema
        game_record = {
            'game_uid': game_uid,
            'home_team_master_id': home_team_master_id,
            'away_team_master_id': away_team_master_id,
            'home_provider_id': home_provider_id if 'home_provider_id' in game_data else (game_data.get('home_team_id') or ''),
            'away_provider_id': away_provider_id if 'away_provider_id' in game_data else (game_data.get('away_team_id') or ''),
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
        gender: Optional[str],
        club_name: Optional[str] = None
    ) -> Dict:
        """
        Match a team using provider ID, alias map, and fuzzy matching.
        Now prioritizes DIRECT ID matching first.
        
        Returns:
            Dict with:
            - matched: bool
            - team_id: str if matched
            - method: str ('direct_id', 'provider_id', 'alias', 'fuzzy', None)
            - confidence: float (0.0-1.0)
        """
        # Strategy 1: Direct provider ID match (NEW - highest priority)
        if provider_team_id:
            alias_match = self._match_by_provider_id(provider_id, provider_team_id)
            if alias_match:
                # Check if this is a direct_id match type
                match_type = alias_match.get('match_method', 'provider_id')
                if match_type == 'direct_id':
                    return {
                        'matched': True,
                        'team_id': alias_match['team_id_master'],
                        'method': 'direct_id',
                        'confidence': 1.0
                    }
                else:
                    # Legacy provider_id match
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
            fuzzy_match = self._fuzzy_match_team(team_name, age_group, gender, club_name)
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
        """Match by exact provider ID in alias map (direct ID matching)"""
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method'
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
        gender: str,
        club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """Fuzzy match team name against master teams with club name weighting"""
        try:
            # Get candidate teams including club_name
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender, state_code'
            ).eq('age_group', age_group).eq('gender', gender).execute()
            
            best_match = None
            best_score = 0.0
            
            # Prepare provider team dict for scoring
            provider_team = {
                'team_name': team_name,
                'club_name': club_name,
                'age_group': age_group,
                'state_code': None  # Will be extracted from game data if available
            }
            
            for team in result.data:
                # Use weighted scoring which includes club name
                candidate = {
                    'team_name': team.get('team_name', ''),
                    'club_name': team.get('club_name'),
                    'age_group': team.get('age_group', ''),
                    'state_code': team.get('state_code')
                }
                
                score = self._calculate_match_score(provider_team, candidate)
                
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = {
                        'team_id': team['team_id_master'],
                        'team_name': team['team_name'],
                        'confidence': round(score, 3)
                    }
            
            return best_match
            
        except Exception as e:
            logger.error(f"Fuzzy match error: {e}")
            return None

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate string similarity using SequenceMatcher with normalization"""
        # Always normalize both inputs before comparison
        str1 = self._normalize_team_name(str1)
        str2 = self._normalize_team_name(str2)
        
        # Direct match
        if str1 == str2:
            return 1.0
        
        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _normalize_team_name(self, name: str) -> str:
        """Normalize team name for comparison with expanded suffixes and abbreviation expansion"""
        if not name:
            return ''
        
        # Convert to lowercase
        name = name.lower().strip()
        
        # Remove punctuation
        name = name.translate(str.maketrans('', '', string.punctuation))
        
        # Expand common abbreviations (only full word matches to avoid expanding within words)
        abbreviations = {
            'ys': 'youth soccer',
            'fc': 'football club',
            'sc': 'soccer club',
            'sa': 'soccer academy',
            'ac': 'academy'
        }
        
        # Replace abbreviations with full forms (only if word matches exactly)
        words = name.split()
        expanded_words = []
        for word in words:
            if word in abbreviations:
                expanded_words.append(abbreviations[word])
            else:
                expanded_words.append(word)
        name = ' '.join(expanded_words)
        
        # Remove common suffixes (now expanded)
        suffixes = ['fc', 'sc', 'sa', 'ys', 'academy', 'soccer club', 'football club', 'youth soccer']
        # Sort by length (longest first) to match longer suffixes first
        suffixes.sort(key=len, reverse=True)
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)].strip()
                break
        
        # Compress whitespace and remove extra spaces
        name = ' '.join(name.split())
        
        return name
    
    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Calculate match score with multiple weighted factors including club name"""
        
        # Get weights from config with defaults
        weights = MATCHING_CONFIG.get('weights', {
            'team': 0.65,
            'club': 0.25,
            'age': 0.05,
            'location': 0.05
        })
        
        # Team name similarity
        provider_name = provider_team.get('team_name', '')
        candidate_name = candidate.get('team_name', '')
        team_score = self._calculate_similarity(provider_name, candidate_name) * weights['team']
        
        # Club name similarity (25% weight)
        club_score = 0.0
        provider_club = provider_team.get('club_name')
        candidate_club = candidate.get('club_name')
        
        if provider_club and candidate_club:
            # Both club names present - calculate similarity
            club_similarity = self._calculate_similarity(provider_club, candidate_club)
            club_score = club_similarity * weights['club']
            
            # Boost for identical clubs (after normalization)
            if club_similarity == 1.0:
                club_boost = MATCHING_CONFIG.get('club_boost_identical', 0.05)
                club_score += club_boost
        # If either club missing, ignore club weighting (no penalty)
        
        # Location match (5% weight)
        location_score = 0.0
        provider_state = provider_team.get('state_code') or provider_team.get('state', '')
        candidate_state = candidate.get('state_code') or candidate.get('state', '')
        if provider_state and candidate_state:
            if provider_state.upper() == candidate_state.upper():
                location_score = weights['location']
        
        # Age group match (5% weight)
        age_score = 0.0
        provider_age = str(provider_team.get('age_group', '')).lower()
        candidate_age = str(candidate.get('age_group', '')).lower()
        if provider_age and candidate_age:
            if provider_age == candidate_age:
                age_score = weights['age']
        
        final_score = team_score + club_score + location_score + age_score
        
        # Cap at 1.0 (in case boost pushes it over)
        return min(final_score, 1.0)

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

