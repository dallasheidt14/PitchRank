"""Game matching system with fuzzy matching and alias support"""
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from difflib import SequenceMatcher
import logging
import re
import uuid
import string
import time
from dataclasses import dataclass

from supabase import Client
from config.settings import MATCHING_CONFIG

# Import club normalizer for enhanced club name matching
try:
    from src.utils.club_normalizer import (
        normalize_club_name as normalize_club,
        normalize_to_club,
        are_same_club,
        similarity_score as club_similarity_score,
    )
    HAVE_CLUB_NORMALIZER = True
except ImportError:
    HAVE_CLUB_NORMALIZER = False

logger = logging.getLogger(__name__)

# UUID namespace for deterministic game UIDs
GAME_UID_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # Standard DNS namespace

# --- Team variant detection (ported from find_queue_matches.py) ---
# Colors that indicate DIFFERENT teams within the same club
TEAM_COLORS = {'red', 'blue', 'white', 'black', 'gold', 'grey', 'gray', 'green',
               'orange', 'purple', 'yellow', 'navy', 'maroon', 'silver', 'pink', 'sky'}

# Directions that indicate DIFFERENT teams within the same club
TEAM_DIRECTIONS = {'north', 'south', 'east', 'west', 'central'}

# Known non-coach words used to filter false positives in coach name detection
_NON_COACH_WORDS = frozenset({
    'ecnl', 'boys', 'girls', 'academy', 'united', 'elite', 'club', 'futbol',
    'soccer', 'youth', 'rush', 'surf', 'select', 'premier', 'gold', 'blue',
    'white', 'black', 'grey', 'gray', 'green', 'maroon', 'navy', 'lafc', 'futeca',
    'selection', 'fire', 'storm', 'fusion', 'athletico', 'atletico', 'fc', 'sc',
    'real', 'inter', 'sporting', 'united',
})

_REGION_CODES = frozenset({
    'ctx', 'phx', 'atx', 'dal', 'hou', 'san', 'sdg', 'sfv', 'oc', 'ie',
    'la', 'bay', 'nyc', 'nj', 'dmv', 'pnw', 'sea', 'pdx', 'slc', 'den',
    'chi', 'stl', 'kc', 'min', 'det', 'cle', 'pit', 'atl', 'mia', 'orl',
    'tam', 'ral', 'cha', 'dc', 'md', 'va', 'pa', 'ma', 'ct', 'ri', 'vt',
    'nh', 'me', 'az', 'ca', 'tx', 'fl', 'ny', 'ga', 'nc', 'sc',
    'co', 'ut', 'nv', 'wa', 'or', 'id', 'mt', 'wy', 'nm', 'ok', 'ks',
    'ne', 'sd', 'nd', 'mn', 'wi', 'mi', 'il', 'in', 'oh', 'ky', 'tn',
    'al', 'ms', 'ar', 'mo', 'ia', 'ecnl', 'rl', 'ea', 'npl',
    'usys', 'ayso', 'scdsl', 'dpl', 'mls', 'ussda', 'pre',
})

_PROGRAM_NAMES = frozenset({
    'aspire', 'rise', 'revolution', 'evolution', 'dynasty', 'legacy', 'impact',
    'force', 'thunder', 'lightning', 'blaze', 'inferno', 'phoenix', 'predators',
    'raptors', 'lions', 'tigers', 'bears', 'eagles', 'hawks', 'falcons', 'united',
    'strikers', 'raiders', 'warriors', 'knights', 'spartans', 'titans', 'trojans',
})

# Age/year patterns used for club extraction and variant detection
_AGE_PATTERNS = [
    r'\bU-?\d{1,2}\b',           # U14, U-14
    r'\b[BG]?\d{4}[BG]?\b',     # 2014, B2014, 2014B, G2015, 2015G
    r'\b[BG]\d{2}(?!\d)\b',     # B14, G15 (not followed by more digits)
    r'\b\d{2}[BG](?!\d)\b',     # 14B, 15G (not followed by more digits)
]


def extract_team_variant(name: str) -> Optional[str]:
    """Extract team variant (color, direction, coach name, roman numeral) from team name.

    Teams like 'FC Dallas 2014 Blue' and 'FC Dallas 2014 Gold' are DIFFERENT teams.
    Also 'Select North' and 'Select South' are DIFFERENT teams.
    Coach names like 'Atletico Dallas 15G Riedell' and 'Atletico Dallas 15G Davis'
    are DIFFERENT teams.

    Returns the variant identifier or None.
    """
    if not name:
        return None

    name_lower = name.lower()
    words = name_lower.split()

    # Check for color ANYWHERE in name
    for word in words:
        word_clean = word.strip('-()[]')
        if word_clean in TEAM_COLORS:
            return word_clean

    # Check for direction variants
    for word in words:
        word_clean = word.strip('-()[]')
        if word_clean in TEAM_DIRECTIONS:
            return word_clean

    # Check for roman numerals or letter variants (I, II, III, A, B)
    roman_match = re.search(r'\b(i{1,3}|iv|v|vi{0,3})\b', name_lower)
    if roman_match:
        return roman_match.group(1)

    # Coach name detection: look for names AFTER age/year in the team name
    age_end_pos = -1
    for pattern in _AGE_PATTERNS:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            age_end_pos = match.end()
            break

    if age_end_pos > 0:
        after_age = name[age_end_pos:].strip()
        # Remove region markers in parentheses: "(CTX)" -> ""
        after_age_clean = re.sub(r'\s*\([^)]+\)\s*$', '', after_age).strip()
        after_words = after_age_clean.split()

        for word in after_words:
            word_clean = word.strip('-()[].,').lower()
            if not word_clean or len(word_clean) < 3:
                continue
            if word_clean in _NON_COACH_WORDS:
                continue
            if word_clean in _REGION_CODES:
                continue
            if word_clean in _PROGRAM_NAMES:
                continue
            if word_clean in TEAM_COLORS:
                continue
            if word_clean in TEAM_DIRECTIONS:
                continue
            if word_clean.isdigit() or re.match(r'^[bug]?\d+', word_clean):
                continue
            # Looks like a coach name
            return word_clean

    # Check for coach names in parentheses: "2014 (Holohan)" but NOT regions like "(CTX)"
    coach_match = re.search(r'\(([a-z]+)\)\s*$', name_lower)
    if coach_match:
        word = coach_match.group(1)
        if word not in _REGION_CODES:
            return word

    # Fallback: ALL CAPS word after year
    coach_after_year = re.search(r'20\d{2}\s+([A-Z]{4,})\b', name)
    if coach_after_year:
        word = coach_after_year.group(1).lower()
        if word not in _NON_COACH_WORDS and word not in _REGION_CODES and word not in _PROGRAM_NAMES:
            return word

    # Fallback: capitalized name at end after age
    name_parts = name.split()
    if len(name_parts) >= 2:
        last_part = name_parts[-1]
        last_clean = last_part.strip('()[]').lower()
        if (last_part[0].isupper()
                and last_clean not in TEAM_COLORS
                and last_clean not in _NON_COACH_WORDS
                and last_clean not in _REGION_CODES
                and last_clean not in _PROGRAM_NAMES
                and not re.match(r'^[BG]?\d+', last_part)):
            return last_clean

    return None


def extract_club_from_team_name(provider_team_name: str) -> Optional[str]:
    """Extract club name from a provider team name by splitting on age/year patterns.

    Examples:
        "FC Tampa Rangers FCTS 2015 Falcons" -> "FC Tampa Rangers FCTS"
        "Phoenix Rising FC B2014 Black"       -> "Phoenix Rising FC"
        "Real Salt Lake AZ ECNL 2014 Red"     -> "Real Salt Lake AZ"
    """
    if not provider_team_name:
        return None

    name = provider_team_name.strip()

    # Find earliest age pattern match
    earliest_pos = len(name)
    for pattern in _AGE_PATTERNS:
        match = re.search(pattern, name, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()

    # Extract club name before the age pattern
    club_name = name[:earliest_pos].strip() if earliest_pos < len(name) else name

    # Remove common league/tier suffixes
    league_suffixes = [
        r'\s+(ECNL-RL|ECNL RL|ECRL)\s*$',
        r'\s+ECNL\s*$',
        r'\s+RL\s*$',
        r'\s+PRE-ECNL\s*$',
        r'\s+PRE\s*$',
        r'\s+COMP\s*$',
        r'\s+GA\s*$',
        r'\s+MLS NEXT\s*$',
        r'\s+ACADEMY\s*$',
        r'\s+SELECT\s*$',
        r'\s+PREMIER\s*$',
        r'\s+ELITE\s*$',
    ]
    for suffix_pattern in league_suffixes:
        club_name = re.sub(suffix_pattern, '', club_name, flags=re.IGNORECASE)

    # Remove trailing hyphens, dots, extra whitespace
    club_name = club_name.strip(' -.')

    # Remove duplicate words (e.g., "Kingman SC Kingman SC" -> "Kingman SC")
    words = club_name.split()
    if len(words) >= 4:
        mid = len(words) // 2
        first_half = ' '.join(words[:mid])
        second_half = ' '.join(words[mid:mid * 2])
        if first_half.lower() == second_half.lower():
            club_name = first_half

    club_name = ' '.join(club_name.split())

    if not club_name or len(club_name) < 3:
        return None

    return club_name


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
    
    def __init__(self, supabase: Client, provider_id: Optional[str] = None, alias_cache: Optional[Dict] = None):
        self.db = supabase
        self.fuzzy_threshold = MATCHING_CONFIG['fuzzy_threshold']
        self.auto_approve_threshold = MATCHING_CONFIG['auto_approve_threshold']
        self.review_threshold = MATCHING_CONFIG['review_threshold']
        self.max_age_diff = MATCHING_CONFIG['max_age_diff']
        self._provider_id_cache: Dict[str, str] = {}  # Cache provider_id by code
        self.alias_cache = alias_cache or {}  # Cache for alias map lookups
        if provider_id:
            # Cache the provider_id if provided (for the provider_code used in this pipeline)
            # We'll need to know the code, but for now just store it as a fallback
            self._cached_provider_id = provider_id
        else:
            self._cached_provider_id = None
    
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
        # Normalize team IDs to strings (handle None, empty, and string 'None' cases)
        def normalize_team_id(team_id):
            if not team_id or team_id == '' or str(team_id).strip().lower() == 'none':
                return ''
            try:
                return str(int(float(str(team_id))))
            except (ValueError, TypeError):
                return str(team_id).strip()
        
        team1_str = normalize_team_id(team1_id)
        team2_str = normalize_team_id(team2_id)
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
            # Convert to strings (may be floats from CSV)
            home_provider_id_raw = game_data.get('home_provider_id') or game_data.get('home_team_id', '')
            away_provider_id_raw = game_data.get('away_provider_id') or game_data.get('away_team_id', '')
            # Convert floats to int strings (e.g., 544491.0 -> "544491")
            try:
                home_provider_id = str(int(float(home_provider_id_raw))) if home_provider_id_raw and str(home_provider_id_raw).strip() else ''
            except (ValueError, TypeError):
                home_provider_id = str(home_provider_id_raw).strip() if home_provider_id_raw else ''
            try:
                away_provider_id = str(int(float(away_provider_id_raw))) if away_provider_id_raw and str(away_provider_id_raw).strip() else ''
            except (ValueError, TypeError):
                away_provider_id = str(away_provider_id_raw).strip() if away_provider_id_raw else ''
            
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
            
            # Extract team_id and opponent_id, converting floats to strings if needed
            team_id_raw = game_data.get('team_id', '')
            opponent_id_raw = game_data.get('opponent_id', '')
            
            # Convert floats to int strings (CSV may have 544491.0 -> "544491")
            try:
                team_id = str(int(float(team_id_raw))) if team_id_raw and str(team_id_raw).strip() else ''
            except (ValueError, TypeError):
                team_id = str(team_id_raw).strip() if team_id_raw else ''
            try:
                opponent_id = str(int(float(opponent_id_raw))) if opponent_id_raw and str(opponent_id_raw).strip() else ''
            except (ValueError, TypeError):
                opponent_id = str(opponent_id_raw).strip() if opponent_id_raw else ''
            
            if home_away == 'H':
                # team_id is home, opponent_id is away
                home_team_master_id = team_match.get('team_id')
                away_team_master_id = opponent_match.get('team_id')
                home_provider_id = team_id
                away_provider_id = opponent_id
                home_score = game_data.get('goals_for')
                away_score = game_data.get('goals_against')
            else:
                # team_id is away, opponent_id is home
                home_team_master_id = opponent_match.get('team_id')
                away_team_master_id = team_match.get('team_id')
                home_provider_id = opponent_id
                away_provider_id = team_id
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
            # Use the home_provider_id and away_provider_id we already determined
            game_uid = self.generate_game_uid(
                provider=provider_code,
                game_date=game_data.get('game_date', ''),
                team1_id=home_provider_id,
                team2_id=away_provider_id
            )
        else:
            game_uid = game_data.get('game_uid')
        
        # Build game record for new schema
        # Ensure provider IDs are strings (they should already be from conversion above)
        # Handle edge case where they might still be floats from transformed format
        try:
            home_provider_id_final = str(int(float(home_provider_id))) if home_provider_id and str(home_provider_id).strip() else ''
        except (ValueError, TypeError):
            home_provider_id_final = str(home_provider_id).strip() if home_provider_id else ''
        try:
            away_provider_id_final = str(int(float(away_provider_id))) if away_provider_id and str(away_provider_id).strip() else ''
        except (ValueError, TypeError):
            away_provider_id_final = str(away_provider_id).strip() if away_provider_id else ''
        
        game_record = {
            'game_uid': game_uid,
            'home_team_master_id': home_team_master_id,
            'away_team_master_id': away_team_master_id,
            'home_provider_id': home_provider_id_final,
            'away_provider_id': away_provider_id_final,
            # Include original team_id/opponent_id for fallback in _bulk_insert_games
            'team_id': game_data.get('team_id', ''),
            'opponent_id': game_data.get('opponent_id', ''),
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
            alias_match = self._match_by_provider_id(provider_id, provider_team_id, age_group, gender)
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
                    # Insert into review queue instead of creating alias
                    self._create_review_queue_entry(
                        provider_id=provider_id,
                        provider_team_id=provider_team_id,
                        provider_team_name=team_name,
                        suggested_master_team_id=fuzzy_match['team_id'],
                        confidence_score=confidence,
                        match_details={
                            'age_group': age_group,
                            'gender': gender,
                            'club_name': club_name,
                            'match_method': 'fuzzy'
                        }
                    )
                    return {
                        'matched': False,  # Not matched until reviewed
                        'team_id': None,
                        'method': 'fuzzy_review',
                        'confidence': confidence
                    }
                
                # Low confidence - still add to review queue with suggestion
                else:
                    logger.debug(f"Low confidence match ({confidence:.2f}), adding to review queue")
                    self._create_review_queue_entry(
                        provider_id=provider_id,
                        provider_team_id=provider_team_id,
                        provider_team_name=team_name,
                        suggested_master_team_id=fuzzy_match['team_id'],
                        confidence_score=confidence,
                        match_details={
                            'age_group': age_group,
                            'gender': gender,
                            'club_name': club_name,
                            'match_method': 'fuzzy_low_confidence'
                        }
                    )
                    return {
                        'matched': False,
                        'team_id': None,
                        'method': 'fuzzy_review_low',
                        'confidence': confidence
                    }
        
        # No fuzzy match found at all - still add to review queue without suggestion
        if team_name and age_group and gender:
            logger.debug(f"No fuzzy match found for {team_name}, adding to review queue")
            self._create_review_queue_entry(
                provider_id=provider_id,
                provider_team_id=provider_team_id,
                provider_team_name=team_name,
                suggested_master_team_id=None,
                confidence_score=0.75,  # DB constraint requires >= 0.75 for review queue
                match_details={
                    'age_group': age_group,
                    'gender': gender,
                    'club_name': club_name,
                    'match_method': 'no_match'
                }
            )
        else:
            logger.debug(f"Cannot fuzzy match: missing required fields (team_name={bool(team_name)}, age_group={bool(age_group)}, gender={bool(gender)})")
        
        return {
            'matched': False,
            'team_id': None,
            'method': None,
            'confidence': 0.0
        }

    def _match_by_provider_id(
        self,
        provider_id: str,
        provider_team_id: str,
        age_group: Optional[str] = None,
        gender: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Match by provider ID - checks team_alias_map (canonical source).

        Handles semicolon-separated provider_team_ids in alias map entries.
        For example, if alias has "123456;789012", this will match lookup for "123456".

        CRITICAL: For providers like Modular11 where the same provider_team_id (club ID)
        is used for multiple age groups, we MUST validate age_group to prevent
        U16 games from matching to U13 teams.
        """
        if not provider_team_id:
            return None

        team_id_str = str(provider_team_id).strip()

        # Check cache first (if available)
        # Cache should already have semicolon-separated IDs expanded (done in enhanced_pipeline.py)
        if self.alias_cache and team_id_str in self.alias_cache:
            cached = self.alias_cache[team_id_str]
            team_id_master = cached['team_id_master']

            # Validate age_group if provided
            if age_group:
                if not self._validate_team_age_group(team_id_master, age_group, gender):
                    logger.debug(
                        f"Provider ID {provider_team_id} matched to team {team_id_master} "
                        f"but age_group mismatch (game: {age_group}, team: ?). Rejecting match."
                    )
                    return None

            # Prefer direct_id matches
            if cached.get('match_method') == 'direct_id':
                return {
                    'team_id_master': team_id_master,
                    'review_status': cached.get('review_status', 'approved'),
                    'match_method': 'direct_id'
                }
            # Fallback to any cached match
            return {
                'team_id_master': team_id_master,
                'review_status': cached.get('review_status', 'approved'),
                'match_method': cached.get('match_method')
            }

        # Tier 1: Direct ID match - exact match (from team importer)
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method'
            ).eq('provider_id', provider_id).eq(
                'provider_team_id', team_id_str
            ).eq('match_method', 'direct_id').eq(
                'review_status', 'approved'
            ).limit(1).execute()

            if result.data:
                match = result.data[0]
                team_id_master = match['team_id_master']
                # Validate age_group if provided
                if age_group:
                    if not self._validate_team_age_group(team_id_master, age_group, gender):
                        logger.debug(
                            f"Provider ID {provider_team_id} matched to team {team_id_master} "
                            f"but age_group mismatch (game: {age_group}). Rejecting match."
                        )
                        return None
                return match
        except Exception as e:
            logger.debug(f"No exact direct_id match found: {e}")

        # Tier 2: Check for semicolon-separated aliases containing this ID
        # This handles merged teams where provider_team_id is "123456;789012"
        try:
            # Use LIKE to find aliases containing this ID
            # Pattern: starts with ID, ends with ID, or ID is in middle (surrounded by semicolons)
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method, provider_team_id'
            ).eq('provider_id', provider_id).eq(
                'review_status', 'approved'
            ).like('provider_team_id', f'%{team_id_str}%').execute()

            if result.data:
                # Verify this is actually a match (not a substring of a different ID)
                for alias in result.data:
                    alias_ids = str(alias['provider_team_id']).split(';')
                    alias_ids = [id.strip() for id in alias_ids]
                    if team_id_str in alias_ids:
                        team_id_master = alias['team_id_master']
                        # Validate age_group if provided
                        if age_group:
                            if not self._validate_team_age_group(team_id_master, age_group, gender):
                                logger.debug(
                                    f"Provider ID {provider_team_id} matched to team {team_id_master} "
                                    f"but age_group mismatch (game: {age_group}). Rejecting match."
                                )
                                continue  # Try next alias
                        logger.debug(f"Matched {team_id_str} via semicolon-separated alias: {alias['provider_team_id']}")
                        return {
                            'team_id_master': team_id_master,
                            'review_status': alias.get('review_status', 'approved'),
                            'match_method': alias.get('match_method')
                        }
        except Exception as e:
            logger.debug(f"No semicolon-separated alias match found: {e}")

        # Tier 3: Any approved alias map entry - exact match (fallback)
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method'
            ).eq('provider_id', provider_id).eq(
                'provider_team_id', team_id_str
            ).eq('review_status', 'approved').limit(1).execute()

            if result.data:
                match = result.data[0]
                team_id_master = match['team_id_master']
                # Validate age_group if provided
                if age_group:
                    if not self._validate_team_age_group(team_id_master, age_group, gender):
                        logger.debug(
                            f"Provider ID {provider_team_id} matched to team {team_id_master} "
                            f"but age_group mismatch (game: {age_group}). Rejecting match."
                        )
                        return None
                return match
        except Exception as e:
            logger.debug(f"No alias map match found: {e}")
        return None
    
    def _validate_team_age_group(
        self, 
        team_id_master: str, 
        expected_age_group: str, 
        expected_gender: Optional[str] = None
    ) -> bool:
        """
        Validate that a master team's age_group matches the expected age_group.
        
        Returns True if age_group matches (or if age_group is not provided),
        False if there's a mismatch.
        """
        try:
            # Normalize age_group for comparison (U13 vs u13)
            expected_age_normalized = expected_age_group.lower() if expected_age_group else None
            
            # Get team's age_group from database
            team_result = self.db.table('teams').select(
                'age_group, gender'
            ).eq('team_id_master', team_id_master).single().execute()
            
            if not team_result.data:
                logger.warning(f"Team {team_id_master} not found in database")
                return False
            
            team_age = team_result.data.get('age_group', '').lower() if team_result.data.get('age_group') else None
            team_gender = team_result.data.get('gender')
            
            # Check age_group match
            if expected_age_normalized and team_age:
                if expected_age_normalized != team_age:
                    return False
            
            # Check gender match if provided
            if expected_gender and team_gender:
                if expected_gender != team_gender:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating team age_group: {e}")
            # On error, be conservative and reject the match
            return False

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
        """Fuzzy match team name against master teams.

        Enhanced with logic ported from the auto-merge script:
        - Variant rejection: teams with different colors/directions/coaches are never matched
        - Club extraction: derive club name from the provider team name when not supplied
        - Club-first filtering: narrow candidates by club_name before scoring
        - League boost/penalty: ECNL vs ECNL-RL mismatches are penalized
        """
        try:
            # Normalize age_group to lowercase (DB uses 'u13', source may have 'U13')
            age_group_normalized = age_group.lower() if age_group else age_group

            # --- Club extraction (from auto-merge) ---
            # If no club_name was supplied, try to extract it from the team name
            if not club_name:
                extracted = extract_club_from_team_name(team_name)
                if extracted:
                    club_name = extracted

            # --- Variant extraction (from auto-merge) ---
            provider_variant = extract_team_variant(team_name)

            # --- League marker detection (from auto-merge) ---
            name_lower = team_name.lower() if team_name else ''
            provider_has_rl = (' rl' in name_lower or '-rl' in name_lower
                               or 'ecnl rl' in name_lower or 'ecnl-rl' in name_lower)
            provider_has_ecnl = 'ecnl' in name_lower and not provider_has_rl

            # --- Candidate retrieval ---
            # Try club-first filtering to narrow the candidate set
            result = None
            if club_name:
                result = self.db.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code'
                ).eq('age_group', age_group_normalized).eq('gender', gender).ilike(
                    'club_name', club_name
                ).limit(50).execute()

            # Fall back to broad query if club filter yielded nothing
            if not result or not result.data:
                result = self.db.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code'
                ).eq('age_group', age_group_normalized).eq('gender', gender).execute()

            best_match = None
            best_score = 0.0

            # Prepare provider team dict for weighted scoring
            provider_team = {
                'team_name': team_name,
                'club_name': club_name,
                'age_group': age_group,
                'state_code': None
            }

            for team in result.data:
                # --- Variant rejection (from auto-merge) ---
                candidate_variant = extract_team_variant(team.get('team_name', ''))
                if provider_variant != candidate_variant:
                    # Different color/direction/coach = different team, skip
                    continue

                # Use weighted scoring which includes club name
                candidate = {
                    'team_name': team.get('team_name', ''),
                    'club_name': team.get('club_name'),
                    'age_group': team.get('age_group', ''),
                    'state_code': team.get('state_code')
                }

                score = self._calculate_match_score(provider_team, candidate)

                # --- League boost / penalty (from auto-merge) ---
                cand_lower = team.get('team_name', '').lower()
                cand_has_rl = (' rl' in cand_lower or '-rl' in cand_lower
                               or 'ecnl rl' in cand_lower or 'ecnl-rl' in cand_lower)
                cand_has_ecnl = 'ecnl' in cand_lower and not cand_has_rl

                if provider_has_rl and cand_has_rl:
                    score = min(1.0, score + 0.05)
                elif provider_has_ecnl and cand_has_ecnl and not cand_has_rl:
                    score = min(1.0, score + 0.05)
                elif provider_has_rl != cand_has_rl:
                    score = max(0.0, score - 0.08)

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
        """Normalize team name for comparison.

        Strips league/tier markers, normalizes age formats, expands
        abbreviations, and removes common suffixes - matching the logic
        used in the auto-merge script for consistency.
        """
        if not name:
            return ''

        # Convert to lowercase
        name = name.lower().strip()

        # Strip league/tier markers (from auto-merge script)
        name = re.sub(r'\s*(ecnl-rl|ecnl rl|ecrl|ecnl|pre-ecnl|pre ecnl|mls next|ga|rl)\s*', ' ', name)

        # Replace dashes with spaces for consistency
        name = re.sub(r'\s*-\s*', ' ', name)

        # Normalize age formats (B2014 -> 2014, 2014B -> 2014, U 14 -> u14)
        name = re.sub(r'\b[bg]\s*(\d{2,4})\b', r'\1', name)
        name = re.sub(r'\b(\d{2,4})\s*[bg]\b', r'\1', name)
        name = re.sub(r'\bu\s*(\d+)\b', r'u\1', name)

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
            # Both club names present - calculate similarity with smart normalization
            if HAVE_CLUB_NORMALIZER:
                # Use enhanced club normalizer module
                provider_result = normalize_to_club(provider_club)
                candidate_result = normalize_to_club(candidate_club)

                # If both match to canonical clubs, compare club_ids
                if provider_result.matched_canonical and candidate_result.matched_canonical:
                    if provider_result.club_id == candidate_result.club_id:
                        club_similarity = 1.0
                    else:
                        # Different canonical clubs
                        club_similarity = 0.0
                else:
                    # Use similarity score from normalizer
                    club_similarity = club_similarity_score(provider_club, candidate_club)
            else:
                # Fallback to basic normalization
                from rapidfuzz import fuzz

                def normalize_club_name_basic(name):
                    """Basic normalize club name by removing common suffixes/prefixes"""
                    name_lower = name.lower().strip()

                    suffixes_to_strip = [' sa', ' sc', ' fc', ' cf', ' ac', ' afc',
                                         ' soccer club', ' football club', ' soccer academy',
                                         ' futbol club', ' athletic club', ' soccer', ' academy']
                    for suffix in sorted(suffixes_to_strip, key=len, reverse=True):
                        if name_lower.endswith(suffix):
                            name_lower = name_lower[:-len(suffix)].strip()
                            break

                    prefixes_to_strip = ['fc ', 'cf ', 'ac ', 'afc ']
                    for prefix in prefixes_to_strip:
                        if name_lower.startswith(prefix):
                            name_lower = name_lower[len(prefix):].strip()
                            break

                    return name_lower

                provider_club_norm = normalize_club_name_basic(provider_club)
                candidate_club_norm = normalize_club_name_basic(candidate_club)

                scores = []
                if provider_club_norm == candidate_club_norm:
                    scores.append(1.0)
                scores.append(fuzz.partial_ratio(provider_club_norm, candidate_club_norm) / 100.0)
                scores.append(fuzz.token_set_ratio(provider_club_norm, candidate_club_norm) / 100.0)
                if provider_club_norm in candidate_club_norm or candidate_club_norm in provider_club_norm:
                    scores.append(0.95)
                if provider_club_norm.split() and candidate_club_norm.split():
                    first_word_match = fuzz.ratio(
                        provider_club_norm.split()[0],
                        candidate_club_norm.split()[0]
                    ) / 100.0
                    if first_word_match >= 0.9:
                        scores.append(0.9)

                club_similarity = max(scores) if scores else 0.0

            club_score = club_similarity * weights['club']

            # Boost for high confidence clubs
            if club_similarity >= 0.90:
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
            # Check if alias already exists (by provider_id + provider_team_id)
            existing = None
            if provider_team_id:
                existing = self.db.table('team_alias_map').select('id').eq(
                    'provider_id', provider_id
                ).eq(
                    'provider_team_id', provider_team_id
                ).execute()

            # Only include columns that exist in team_alias_map table
            alias_data = {
                'provider_id': provider_id,
                'provider_team_id': provider_team_id,
                'team_id_master': team_id_master,
                'match_method': match_method,
                'match_confidence': confidence,
                'review_status': review_status,
                'created_at': datetime.now().isoformat()
            }
            
            if existing and existing.data:
                # Update existing
                self.db.table('team_alias_map').update(alias_data).eq(
                    'id', existing.data[0]['id']
                ).execute()
            else:
                # Create new
                self.db.table('team_alias_map').insert(alias_data).execute()
                
        except Exception as e:
            logger.error(f"Error creating alias: {e}")

    def _create_review_queue_entry(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        provider_team_name: str,
        suggested_master_team_id: Optional[str],
        confidence_score: float,
        match_details: Dict
    ):
        """Insert match into team_match_review_queue for manual review.
        
        All unmatched teams go here - with or without suggested matches.
        """
        try:
            # Get provider code (team_match_review_queue uses VARCHAR provider_id)
            provider_result = self.db.table('providers').select('code').eq('id', provider_id).single().execute()
            provider_code = provider_result.data['code'] if provider_result.data else None
            
            if not provider_code:
                logger.warning(f"Could not find provider code for {provider_id}")
                return
            
            review_entry = {
                'provider_id': provider_code,  # VARCHAR code, not UUID
                'provider_team_id': str(provider_team_id) if provider_team_id else None,
                'provider_team_name': provider_team_name,
                'suggested_master_team_id': suggested_master_team_id,
                'confidence_score': float(confidence_score),
                'match_details': match_details,
                'status': 'pending'
            }
            
            # Check if entry already exists
            existing = self.db.table('team_match_review_queue').select('id').eq(
                'provider_id', provider_code
            ).eq('provider_team_id', str(provider_team_id)).eq('status', 'pending').execute()
            
            if not existing.data:
                self.db.table('team_match_review_queue').insert(review_entry).execute()
                logger.info(f"Created review queue entry for {provider_team_name} (confidence: {confidence_score:.2f})")
        except Exception as e:
            logger.error(f"Error creating review queue entry: {e}")

    def _get_provider_id(self, provider_code: Optional[str]) -> str:
        """Get provider UUID from code with retry logic and caching"""
        if not provider_code:
            raise ValueError("Provider code is required")
        
        # Check cache first
        if provider_code in self._provider_id_cache:
            return self._provider_id_cache[provider_code]
        
        # Use cached provider_id if available (from initialization)
        if self._cached_provider_id and provider_code:
            self._provider_id_cache[provider_code] = self._cached_provider_id
            return self._cached_provider_id
        
        # Retry logic with exponential backoff
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                result = self.db.table('providers').select('id').eq(
                    'code', provider_code
                ).single().execute()
                provider_id = result.data['id']
                # Cache it
                self._provider_id_cache[provider_code] = provider_id
                return provider_id
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"Provider lookup failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Provider not found after {max_retries} attempts: {provider_code}")
                    raise ValueError(f"Provider not found: {provider_code}") from e

