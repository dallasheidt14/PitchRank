"""
TGS-specific game matcher with enhanced fuzzy matching for team name matching.

This matcher extends GameHistoryMatcher to provide more aggressive fuzzy matching
specifically for TGS teams, allowing better matching to existing teams in the database.
"""
import logging
import re
import uuid
from typing import Dict, Optional, Set
from datetime import datetime
from supabase import Client

from src.models.game_matcher import GameHistoryMatcher

logger = logging.getLogger(__name__)


class TGSGameMatcher(GameHistoryMatcher):
    """
    TGS-specific team matcher with enhanced fuzzy matching.
    
    Key differences from base matcher:
    1. Lower fuzzy threshold (0.75 vs 0.85) for more aggressive matching
    2. Enhanced team name normalization for TGS naming patterns
    3. Better handling of ECNL, RL, and other TGS-specific suffixes
    4. More lenient matching to help match TGS teams to existing database teams
    5. Creates new teams when no match found (similar to Modular11)
    """
    
    def __init__(self, supabase: Client, provider_id: Optional[str] = None, alias_cache: Optional[Dict] = None):
        """Initialize TGS matcher with same interface as base matcher"""
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache)
        # Lower thresholds for more aggressive matching
        # Default: fuzzy_threshold=0.85, auto_approve=0.90, review=0.75
        # TGS: More lenient to match more teams
        self.fuzzy_threshold = 0.75  # Lower minimum score (was 0.85)
        self.auto_approve_threshold = 0.91  # Auto-approve only very high confidence matches
        self.review_threshold = 0.70  # Lower review threshold (was 0.75)
        logger.info(
            f"Initialized TGSGameMatcher with enhanced fuzzy matching "
            f"(fuzzy: {self.fuzzy_threshold}, auto-approve: {self.auto_approve_threshold}, review: {self.review_threshold})"
        )
    
    def _extract_age_tokens(self, name: str) -> Set[str]:
        """
        Extract age group tokens from team name (e.g., "14b", "u11", "b12", "g13").
        
        Examples:
        - "RSL-AZ 14b North" -> {"14b", "14"}
        - "14b GSA" -> {"14b", "14"}
        - "U11 Elite" -> {"u11", "11"}
        - "B2012 Academy" -> {"b2012", "2012", "b12", "12"}
        """
        if not name:
            return set()
        
        tokens = set()
        name_lower = name.lower()
        
        # Pattern 1: Age + letter (e.g., "14b", "13a", "12c", "14B", "13A")
        # name_lower is already lowercase, so [a-z] will match both "14b" and "14B" (after lowercasing)
        matches = re.findall(r'\b(\d{1,2}[a-z])\b', name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r'\d+', match)
            if num_match:
                tokens.add(num_match.group())
        
        # Pattern 2: U + number (e.g., "u11", "u12")
        matches = re.findall(r'\b(u\d{1,2})\b', name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r'\d+', match)
            if num_match:
                tokens.add(num_match.group())
        
        # Pattern 3: B/G + number (e.g., "b12", "g13", "B12", "G13")
        # name_lower is already lowercase
        matches = re.findall(r'\b([bg]\d{1,2})\b', name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r'\d+', match)
            if num_match:
                tokens.add(num_match.group())
        
        # Pattern 4: B/G + birth year (e.g., "B2015", "G2012", "b2013")
        # name_lower is already lowercase
        matches = re.findall(r'\b([bg]20[01]\d)\b', name_lower)
        tokens.update(matches)
        # Also extract just the year part
        for match in matches:
            year_match = re.search(r'20[01]\d', match)
            if year_match:
                year = year_match.group()
                tokens.add(year)
                # Also add last 2 digits (e.g., "2015" -> "15")
                if len(year) == 4:
                    tokens.add(year[2:])
                # Also add B/G + last 2 digits (e.g., "B2015" -> "b15")
                tokens.add(match[0] + year[2:])
        
        # Pattern 5: Birth year + B/G (e.g., "2013G", "2012B", "2014g")
        # name_lower is already lowercase
        matches = re.findall(r'\b(20[01]\d[bg])\b', name_lower)
        tokens.update(matches)
        for match in matches:
            year_match = re.search(r'20[01]\d', match)
            if year_match:
                year = year_match.group()
                tokens.add(year)
                if len(year) == 4:
                    tokens.add(year[2:])
                # Also add B/G + last 2 digits (e.g., "2013G" -> "g13")
                tokens.add(match[-1] + year[2:])
        
        # Pattern 6: Birth year standalone (e.g., "2012", "2013")
        matches = re.findall(r'\b(20[01]\d)\b', name_lower)
        tokens.update(matches)
        # Also extract last 2 digits (e.g., "2012" -> "12")
        for match in matches:
            if len(match) == 4:
                tokens.add(match[2:])
        
        return tokens
    
    def _normalize_team_name(self, name: str, club_name: Optional[str] = None) -> str:
        """
        Enhanced normalization for TGS team names.
        
        Handles TGS-specific patterns:
        - ECNL suffixes (e.g., "Team Name ECNL G12" -> "Team Name")
        - RL suffixes (e.g., "Team Name RL Southwest" -> "Team Name")
        - Age group suffixes (e.g., "Team Name G12" -> "Team Name")
        - Embedded club names (e.g., "Folsom Lake Surf- FLS 13B Premier I" -> "FLS 13B Premier I")
        - Common TGS naming patterns
        
        Args:
            name: Team name to normalize
            club_name: Optional club name to strip from the beginning of team name
        """
        if not name:
            return ''
        
        # CRITICAL: Strip everything before the first dash BEFORE base normalization
        # Base normalization removes punctuation, so we must strip first
        # TGS format: "Folsom Lake Surf- FLS 13B Premier I" -> "FLS 13B Premier I"
        # SAFEST APPROACH: Strip everything before the first dash (any dash type)
        dash_chars = ['-', '–', '—']
        for dash in dash_chars:
            if dash in name:
                # Split on first dash and take everything after it
                parts = name.split(dash, 1)
                if len(parts) > 1:
                    name = parts[1].strip()
                    break
        
        # Now do base normalization (which removes punctuation, expands abbreviations, etc.)
        normalized = super()._normalize_team_name(name)
        
        # Remove TGS-specific suffixes (case-insensitive)
        tgs_suffixes = [
            ' ecnl', ' ecnl g12', ' ecnl g13', ' ecnl g14', ' ecnl g15', ' ecnl g16',
            ' ecnl b12', ' ecnl b13', ' ecnl b14', ' ecnl b15', ' ecnl b16',
            ' rl', ' rl southwest', ' rl west', ' rl east', ' rl central',
            ' g12', ' g13', ' g14', ' g15', ' g16', ' g17', ' g18',
            ' b12', ' b13', ' b14', ' b15', ' b16', ' b17', ' b18',
            ' u12', ' u13', ' u14', ' u15', ' u16', ' u17', ' u18',
            ' academy', ' acad', ' ac',
            ' - orozco', ' - smith',  # Coach names
        ]
        
        # Sort by length (longest first) to match longer suffixes first
        tgs_suffixes.sort(key=len, reverse=True)
        for suffix in tgs_suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                break
        
        # Remove common prefixes that might interfere
        prefixes = ['ecnl ', 'rl ', 'g12 ', 'g13 ', 'b12 ', 'b13 ']
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
        
        # Compress whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """
        Enhanced match scoring for TGS with special handling for club name matches.
        
        Key improvements:
        1. Significant boost when club names match perfectly
        2. Age token extraction and matching (e.g., "14b" in both names)
        3. Better handling of embedded club names in team names
        4. Strips club name from team name before comparison
        """
        # Normalize team names by stripping club name prefix
        provider_name_raw = provider_team.get('team_name', '')
        candidate_name_raw = candidate.get('team_name', '')
        provider_club = provider_team.get('club_name', '').strip() if provider_team.get('club_name') else None
        candidate_club = candidate.get('club_name', '').strip() if candidate.get('club_name') else None
        
        # Strip club name from provider team name (TGS often includes it)
        provider_name_normalized = self._normalize_team_name(provider_name_raw, provider_club)
        
        # CRITICAL: Strip club name from candidate team name BEFORE normalization
        # This prevents "ALBION SC Santa Monica" from becoming "albion soccer club santa monica"
        # which then can't be matched against the normalized club name
        candidate_name_for_stripping = candidate_name_raw
        if candidate_club:
            # Try to strip club name from raw team name (before normalization)
            candidate_club_lower = candidate_club.lower().strip()
            candidate_name_lower_raw = candidate_name_raw.lower()
            
            # Remove standalone SC/FC/SA from club name for matching
            club_words_for_stripping = candidate_club_lower.split()
            club_words_for_stripping = [w for w in club_words_for_stripping if w not in ['sc', 'fc', 'sa']]
            club_norm_for_stripping = ' '.join(club_words_for_stripping)
            
            # Try to remove club name from team name (handle various formats)
            if candidate_name_lower_raw.startswith(club_norm_for_stripping):
                # Remove from start
                remaining = candidate_name_raw[len(club_norm_for_stripping):].strip()
                if remaining.startswith('-') or remaining.startswith('–') or remaining.startswith('—'):
                    remaining = remaining[1:].strip()
                if remaining:
                    candidate_name_for_stripping = remaining
            elif club_norm_for_stripping in candidate_name_lower_raw:
                # Remove from anywhere
                candidate_name_for_stripping = candidate_name_lower_raw.replace(club_norm_for_stripping, '', 1).strip()
                if candidate_name_for_stripping.startswith('-') or candidate_name_for_stripping.startswith('–') or candidate_name_for_stripping.startswith('—'):
                    candidate_name_for_stripping = candidate_name_for_stripping[1:].strip()
                # Also handle "SC" or "FC" that might be left
                candidate_name_for_stripping = ' '.join([w for w in candidate_name_for_stripping.split() if w not in ['sc', 'fc', 'sa']])
        
        # Now normalize the candidate name (after club stripping)
        candidate_name_normalized = self._normalize_team_name(candidate_name_for_stripping)
        
        # Additional stripping after normalization (fallback)
        if candidate_club:
            candidate_club_lower = candidate_club.lower().strip()
            candidate_name_lower = candidate_name_normalized.lower()
            
            # Normalize club name for matching (remove suffixes and standalone SC/FC/SA)
            club_norm = candidate_club_lower
            # Remove standalone SC/FC/SA words
            club_words = club_norm.split()
            club_words = [w for w in club_words if w not in ['sc', 'fc', 'sa']]
            club_norm = ' '.join(club_words)
            # Remove common suffix patterns
            for suffix in [' sc', ' fc', ' sa', ' soccer club', ' football club', ' academy']:
                if club_norm.endswith(suffix):
                    club_norm = club_norm[:-len(suffix)].strip()
            
            # First, try direct match at start
            if candidate_name_lower.startswith(club_norm):
                # Remove club name prefix
                remaining = candidate_name_normalized[len(club_norm):].strip()
                # Also remove any leading dash or space
                if remaining.startswith('-') or remaining.startswith('–') or remaining.startswith('—'):
                    remaining = remaining[1:].strip()
                if remaining:
                    candidate_name_normalized = remaining
            elif club_norm in candidate_name_lower:
                # Club name appears somewhere in team name - remove it
                # Replace with space and clean up
                candidate_name_normalized = candidate_name_lower.replace(club_norm, '').strip()
                # Clean up extra spaces and dashes
                candidate_name_normalized = ' '.join(candidate_name_normalized.split())
                if candidate_name_normalized.startswith('-') or candidate_name_normalized.startswith('–') or candidate_name_normalized.startswith('—'):
                    candidate_name_normalized = candidate_name_normalized[1:].strip()
            else:
                # Try with abbreviation expansion (e.g., "SD" -> "San Diego")
                # Expand common abbreviations in team name for comparison
                state_abbreviations = {
                    'sd': 'san diego', 'az': 'arizona', 'ca': 'california', 'tx': 'texas',
                    'fl': 'florida', 'ny': 'new york', 'nj': 'new jersey', 'pa': 'pennsylvania',
                    'il': 'illinois', 'oh': 'ohio', 'nc': 'north carolina', 'ga': 'georgia',
                    'va': 'virginia', 'wa': 'washington', 'or': 'oregon', 'co': 'colorado',
                    'ut': 'utah', 'nv': 'nevada', 'md': 'maryland', 'ma': 'massachusetts',
                    'mi': 'michigan', 'tn': 'tennessee', 'in': 'indiana', 'mo': 'missouri',
                    'wi': 'wisconsin', 'mn': 'minnesota', 'sc': 'south carolina', 'al': 'alabama',
                    'la': 'louisiana', 'ky': 'kentucky', 'ok': 'oklahoma', 'ct': 'connecticut',
                    'ia': 'iowa', 'ar': 'arkansas', 'ms': 'mississippi', 'ks': 'kansas',
                    'nm': 'new mexico', 'ne': 'nebraska', 'wv': 'west virginia', 'id': 'idaho',
                    'hi': 'hawaii', 'nh': 'new hampshire', 'me': 'maine', 'mt': 'montana',
                    'ri': 'rhode island', 'de': 'delaware', 'nd': 'north dakota', 'ak': 'alaska',
                    'dc': 'district of columbia', 'vt': 'vermont', 'wy': 'wyoming'
                }
                
                # Expand abbreviations in team name
                team_words = candidate_name_normalized.lower().split()
                expanded_team_words = []
                for word in team_words:
                    if word in state_abbreviations:
                        expanded_team_words.append(state_abbreviations[word])
                    else:
                        expanded_team_words.append(word)
                expanded_team_name = ' '.join(expanded_team_words)
                
                # Now check if expanded team name starts with club name
                if expanded_team_name.startswith(candidate_club_lower):
                    # Find where club name ends in original team name
                    # We need to be smart about this - find the position after expansion
                    club_len_in_expanded = len(candidate_club_lower)
                    # Count characters up to that point in expanded version
                    # This is approximate, but should work for most cases
                    remaining = candidate_name_normalized
                    # Try to remove club name by matching word boundaries
                    club_words = candidate_club_lower.split()
                    team_words_list = candidate_name_normalized.lower().split()
                    if len(team_words_list) >= len(club_words):
                        # Check if first N words match club name (after expansion)
                        first_words = ' '.join(team_words_list[:len(club_words)])
                        first_words_expanded = ' '.join([
                            state_abbreviations.get(w, w) for w in team_words_list[:len(club_words)]
                        ])
                        if first_words_expanded == candidate_club_lower:
                            # Remove first N words
                            remaining = ' '.join(team_words_list[len(club_words):]).strip()
                            if remaining:
                                candidate_name_normalized = remaining
        
        # Create normalized provider team dict for base scoring
        provider_team_normalized = provider_team.copy()
        provider_team_normalized['team_name'] = provider_name_normalized
        candidate_normalized = candidate.copy()
        candidate_normalized['team_name'] = candidate_name_normalized
        
        # Start with base scoring using normalized names
        base_score = super()._calculate_match_score(provider_team_normalized, candidate_normalized)
        
        # Extract age tokens from normalized team names
        provider_tokens = self._extract_age_tokens(provider_name_normalized)
        candidate_tokens = self._extract_age_tokens(candidate_name_normalized)
        
        # Check club name match
        provider_club = provider_team.get('club_name', '').strip().lower() if provider_team.get('club_name') else ''
        candidate_club = candidate.get('club_name', '').strip().lower() if candidate.get('club_name') else ''
        
        club_match = False
        if provider_club and candidate_club:
            # Normalize club names for comparison (remove common suffixes, expand abbreviations)
            def normalize_club_for_match_internal(name):
                name = name.lower().strip()
                
                # CRITICAL: Remove common suffixes FIRST (before abbreviation expansion)
                # This prevents "SC" from being expanded to "South Carolina" when it's "Soccer Club"
                # Handle both " Club SC" and "SC" as standalone word (anywhere in the name)
                words = name.split()
                
                # Remove standalone "SC", "FC", "SA" anywhere in the name (these are club suffixes, not state abbreviations)
                # Check both at the end and in the middle
                words = [w for w in words if w not in ['sc', 'fc', 'sa']]
                
                # Also remove common suffix patterns
                name = ' '.join(words)
                for suffix in [' sc', ' fc', ' sa', ' soccer club', ' football club', ' academy']:
                    if name.endswith(suffix):
                        name = name[:-len(suffix)].strip()
                
                # Expand common state abbreviations (AFTER removing suffixes)
                # Note: "SC", "FC", "SA" are NOT in this list to avoid conflicts
                state_abbreviations = {
                    'az': 'arizona',
                    'ca': 'california',
                    'tx': 'texas',
                    'fl': 'florida',
                    'ny': 'new york',
                    'nj': 'new jersey',
                    'pa': 'pennsylvania',
                    'il': 'illinois',
                    'oh': 'ohio',
                    'nc': 'north carolina',
                    'ga': 'georgia',
                    'va': 'virginia',
                    'wa': 'washington',
                    'or': 'oregon',
                    'co': 'colorado',
                    'ut': 'utah',
                    'nv': 'nevada',
                    'md': 'maryland',
                    'ma': 'massachusetts',
                    'mi': 'michigan',
                    'tn': 'tennessee',
                    'in': 'indiana',
                    'mo': 'missouri',
                    'wi': 'wisconsin',
                    'mn': 'minnesota',
                    # 'sc': 'south carolina',  # REMOVED - treat as club suffix, not state
                    'al': 'alabama',
                    'la': 'louisiana',
                    'ky': 'kentucky',
                    'ok': 'oklahoma',
                    'ct': 'connecticut',
                    'ia': 'iowa',
                    'ar': 'arkansas',
                    'ms': 'mississippi',
                    'ks': 'kansas',
                    'nm': 'new mexico',
                    'ne': 'nebraska',
                    'wv': 'west virginia',
                    'id': 'idaho',
                    'hi': 'hawaii',
                    'nh': 'new hampshire',
                    'me': 'maine',
                    'mt': 'montana',
                    'ri': 'rhode island',
                    'de': 'delaware',
                    'sd': 'san diego',  # Changed from 'south dakota' - SD is more commonly San Diego in soccer context
                    'nd': 'north dakota',
                    'ak': 'alaska',
                    'dc': 'district of columbia',
                    'vt': 'vermont',
                    'wy': 'wyoming'
                }
                
                # Expand abbreviations at word boundaries
                words = name.split()
                expanded_words = []
                for word in words:
                    # Check if word is a state abbreviation
                    if word in state_abbreviations:
                        expanded_words.append(state_abbreviations[word])
                    else:
                        expanded_words.append(word)
                name = ' '.join(expanded_words)
                
                return name
            
            provider_club_norm = normalize_club_for_match_internal(provider_club)
            candidate_club_norm = normalize_club_for_match_internal(candidate_club)
            club_match = provider_club_norm == candidate_club_norm
            
            # Debug logging
            if club_match:
                logger.debug(
                    f"TGS club match detected: '{provider_club}' -> '{provider_club_norm}' "
                    f"matches '{candidate_club}' -> '{candidate_club_norm}'"
                )
        
        # Boost scoring when club names match
        if club_match:
            # Age token overlap boost
            age_token_overlap = len(provider_tokens & candidate_tokens) > 0
            
            if age_token_overlap:
                # Perfect scenario: club matches + age tokens match
                # Boost by 0.25 (enough to push borderline matches over threshold)
                # This handles cases like "RSL-AZ 14b North" vs "14b GSA"
                boost = 0.25
                logger.debug(
                    f"TGS club+age boost: '{provider_name_normalized}' vs '{candidate_name_normalized}' "
                    f"(club match + age tokens: {provider_tokens & candidate_tokens}, boost: {boost})"
                )
            else:
                # Club matches but no age token overlap - still boost but less
                # This handles cases where team names are very different but clubs match
                boost = 0.18
                logger.debug(
                    f"TGS club boost: '{provider_name_normalized}' vs '{candidate_name_normalized}' "
                    f"(club match, no age token overlap, boost: {boost})"
                )
            
            # Apply boost (cap at 1.0)
            base_score = min(1.0, base_score + boost)
        
        return base_score
    
    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Enhanced fuzzy matching for TGS teams with lower threshold.
        
        Uses the same logic as base matcher but with:
        - Lower threshold (0.75) for more matches
        - Enhanced normalization for TGS naming patterns
        - Special scoring boost for club name matches
        """
        try:
            # Normalize age_group to lowercase (DB uses 'u13', source may have 'U13')
            age_group_normalized = age_group.lower() if age_group else age_group
            
            # Get candidate teams including club_name
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender, state_code'
            ).eq('age_group', age_group_normalized).eq('gender', gender).execute()
            
            best_match = None
            best_score = 0.0
            
            # Prepare provider team dict for scoring (with TGS normalization)
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
                
                # Use enhanced TGS scoring (with club name boost)
                score = self._calculate_match_score(provider_team, candidate)
                
                # Lower threshold for TGS (0.75 vs 0.85)
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = {
                        'team_id': team['team_id_master'],
                        'team_name': team['team_name'],
                        'confidence': round(score, 3)
                    }
            
            if best_match:
                logger.debug(
                    f"TGS fuzzy match: '{team_name}' -> '{best_match['team_name']}' "
                    f"(score: {best_match['confidence']}, club: {club_name})"
                )
            
            return best_match
            
        except Exception as e:
            logger.error(f"TGS fuzzy match error: {e}")
            return None
    
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
        Override base _match_team to create new teams when no match found (like Modular11).
        
        Strategy:
        1. Try base matching (direct ID, alias, fuzzy)
        2. If no match found, create new team
        3. Return matched: True with new team ID
        """
        # First, try base matching
        base_result = super()._match_team(
            provider_id, provider_team_id, team_name, age_group, gender, club_name
        )
        
        # If matched, return immediately
        if base_result.get('matched'):
            return base_result
        
        # No match found - create new team (like Modular11)
        if team_name and age_group and gender:
            logger.info(
                f"[TGS] ⚠️ No match found for '{team_name}' ({age_group}, {gender}), creating new team"
            )
            try:
                new_team_id = self._create_new_tgs_team(
                    team_name=team_name,
                    club_name=club_name,
                    age_group=age_group,
                    gender=gender,
                    provider_id=provider_id,
                    provider_team_id=provider_team_id
                )
                
                # Create alias for new team
                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method='import',  # System-created during import
                    confidence=1.0,  # New team = 100% confidence
                    age_group=age_group,
                    gender=gender,
                    review_status='approved'
                )
                
                logger.info(
                    f"[TGS] Created new team: {team_name} ({age_group}, {gender}) -> {new_team_id}"
                )
                
                return {
                    'matched': True,
                    'team_id': new_team_id,
                    'method': 'import',
                    'confidence': 1.0
                }
            except Exception as e:
                logger.error(f"[TGS] Error creating new team for {team_name}: {e}")
                # Fall through to return base result
        else:
            logger.debug(
                f"[TGS] Cannot create new team - missing required fields: "
                f"team_name={bool(team_name)}, age_group={bool(age_group)}, gender={bool(gender)}"
            )
        
        # Fallback: return base result (shouldn't happen if we have required fields)
        return base_result
    
    def _create_new_tgs_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None
    ) -> str:
        """
        Create a new team in the teams table for TGS.
        
        If a team with the same provider_id and provider_team_id already exists,
        return that team's ID instead of creating a duplicate.
        
        Returns the team_id_master UUID.
        """
        try:
            # provider_team_id is REQUIRED (NOT NULL constraint)
            # Use provided provider_team_id or generate one
            if not provider_team_id:
                import hashlib
                provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}".encode()).hexdigest()[:16]
            
            # Check if team with this provider_id + provider_team_id already exists
            if provider_id:
                try:
                    existing = self.db.table('teams').select('team_id_master').eq(
                        'provider_id', provider_id
                    ).eq('provider_team_id', provider_team_id).single().execute()
                    
                    if existing.data:
                        logger.debug(
                            f"[TGS] Team with provider_team_id {provider_team_id} already exists, "
                            f"using existing team {existing.data['team_id_master']}"
                        )
                        return existing.data['team_id_master']
                except Exception:
                    # No existing team found, continue to create new one
                    pass
            
            # Generate new UUID
            team_id_master = str(uuid.uuid4())
            
            # Normalize age_group
            age_group_normalized = age_group.lower() if age_group else age_group
            
            # Normalize gender
            gender_normalized = 'Male' if gender.upper() in ('M', 'MALE', 'BOYS', 'B') else 'Female'
            
            # Clean team name (strip club name prefix if present)
            clean_team_name = team_name
            if club_name and team_name.startswith(club_name):
                # Remove club name prefix
                remaining = team_name[len(club_name):].strip()
                if remaining.startswith('-') or remaining.startswith('–') or remaining.startswith('—'):
                    remaining = remaining[1:].strip()
                if remaining:
                    clean_team_name = remaining
            
            # Insert new team
            team_data = {
                'team_id_master': team_id_master,
                'team_name': clean_team_name,
                'club_name': club_name or clean_team_name,
                'age_group': age_group_normalized,
                'gender': gender_normalized,
                'provider_id': provider_id,  # Required for TGS teams
                'provider_team_id': provider_team_id,  # REQUIRED (NOT NULL)
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            self.db.table('teams').insert(team_data).execute()
            
            logger.info(
                f"[TGS] Created new team: {clean_team_name} ({age_group_normalized}, {gender_normalized})"
            )
            
            return team_id_master
            
        except Exception as e:
            # If duplicate key error, try to find existing team
            if 'duplicate key' in str(e).lower() or '23505' in str(e):
                logger.debug(f"[TGS] Duplicate key error, looking up existing team: {e}")
                if provider_id and provider_team_id:
                    try:
                        existing = self.db.table('teams').select('team_id_master').eq(
                            'provider_id', provider_id
                        ).eq('provider_team_id', provider_team_id).single().execute()
                        
                        if existing.data:
                            logger.info(
                                f"[TGS] Found existing team with provider_team_id {provider_team_id}, "
                                f"using {existing.data['team_id_master']}"
                            )
                            return existing.data['team_id_master']
                    except Exception as lookup_error:
                        logger.error(f"[TGS] Error looking up existing team: {lookup_error}")
            
            logger.error(f"[TGS] Error creating new team: {e}")
            raise

