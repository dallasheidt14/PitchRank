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

from src.models.game_matcher import GameHistoryMatcher, MATCHING_CONFIG

# Import rapidfuzz for similarity scoring
try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

# Import shared team-name utilities
try:
    from src.utils.team_name_utils import (
        extract_distinctions,
        extract_team_variant as extract_variant_shared,
        extract_club_from_team_name as extract_club_structured,
        has_ecnl_rl,
        has_ecnl_only,
    )
    HAVE_TEAM_NAME_UTILS = True
except ImportError:
    HAVE_TEAM_NAME_UTILS = False

# Import club normalizer for canonical club comparison
try:
    from src.utils.club_normalizer import (
        normalize_to_club,
        similarity_score as club_similarity_score,
    )
    HAVE_CLUB_NORMALIZER = True
except ImportError:
    HAVE_CLUB_NORMALIZER = False

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

        TGS-specific pre-processing (dash stripping) runs first, then
        delegates to the shared ``normalize_name_for_matching()`` via the
        base class.
        """
        if not name:
            return ''

        # CRITICAL: Strip everything before the first dash BEFORE base
        # normalization.  TGS format:
        #   "Folsom Lake Surf- FLS 13B Premier I" → "FLS 13B Premier I"
        dash_chars = ['-', '–', '—']
        for dash in dash_chars:
            if dash in name:
                parts = name.split(dash, 1)
                if len(parts) > 1 and parts[1].strip():
                    name = parts[1].strip()
                    break

        # Delegate to base (which uses shared normalize_name_for_matching)
        return super()._normalize_team_name(name)
    
    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """
        Enhanced match scoring for TGS with club name matching via canonical
        registry and age token overlap boost.
        """
        # Normalize team names by stripping club name prefix
        provider_name_raw = provider_team.get('team_name', '')
        candidate_name_raw = candidate.get('team_name', '')
        provider_club = provider_team.get('club_name', '').strip() if provider_team.get('club_name') else None
        candidate_club = candidate.get('club_name', '').strip() if candidate.get('club_name') else None

        # Strip club name from provider team name (TGS often includes it)
        provider_name_normalized = self._normalize_team_name(provider_name_raw, provider_club)

        # Strip club from candidate name before normalization
        candidate_name_for_norm = candidate_name_raw
        if candidate_club:
            club_core = re.sub(r'\b(sc|fc|sa)\b', '', candidate_club.lower()).strip()
            cand_lower = candidate_name_raw.lower()
            if club_core and cand_lower.startswith(club_core):
                remaining = candidate_name_raw[len(club_core):].strip().lstrip('-–—').strip()
                if remaining:
                    candidate_name_for_norm = remaining

        candidate_name_normalized = self._normalize_team_name(candidate_name_for_norm)

        # Create normalized dicts for base scoring
        provider_team_normalized = provider_team.copy()
        provider_team_normalized['team_name'] = provider_name_normalized
        candidate_normalized = candidate.copy()
        candidate_normalized['team_name'] = candidate_name_normalized

        # Start with base scoring (includes club similarity, team sim, age, location)
        base_score = super()._calculate_match_score(provider_team_normalized, candidate_normalized)

        # --- Club match via canonical registry ---
        club_match = False
        club_sim = 0.0
        if provider_club and candidate_club:
            if HAVE_CLUB_NORMALIZER:
                prov_result = normalize_to_club(provider_club)
                cand_result = normalize_to_club(candidate_club)
                if prov_result.matched_canonical and cand_result.matched_canonical:
                    club_match = prov_result.club_id == cand_result.club_id
                    club_sim = 1.0 if club_match else 0.0
                else:
                    club_sim = club_similarity_score(provider_club, candidate_club)
                    club_match = club_sim >= 0.85
            else:
                # Lightweight fallback
                club_sim = self._calculate_similarity(provider_club, candidate_club)
                club_match = club_sim >= 0.85

        # --- Age token overlap boost ---
        if club_match:
            provider_tokens = self._extract_age_tokens(provider_name_normalized)
            candidate_tokens = self._extract_age_tokens(candidate_name_normalized)
            age_token_overlap = len(provider_tokens & candidate_tokens) > 0

            if age_token_overlap:
                boost = 0.25
            else:
                boost = 0.18
            base_score = min(1.0, base_score + boost)

        # --- Club+variant boost (from config) ---
        if club_sim >= 0.8:
            prov_variant = extract_variant_shared(provider_name_raw) if HAVE_TEAM_NAME_UTILS else None
            cand_variant = extract_variant_shared(candidate_name_raw) if HAVE_TEAM_NAME_UTILS else None
            if prov_variant and cand_variant and prov_variant == cand_variant:
                cv_boost = MATCHING_CONFIG.get('club_variant_match_boost', 0.15)
                base_score = min(1.0, base_score + cv_boost)

        return base_score
    
    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Enhanced fuzzy matching for TGS teams with gated candidate funnel.

        Uses:
        - Club-filtered query first (new — TGS previously queried ALL teams)
        - Distinction-based hard rejection before scoring
        - Lower threshold (0.75) for more matches
        - Deterministic tie-breaking on (variant_match, club_sim)
        """
        try:
            age_group_normalized = age_group.lower() if age_group else age_group

            # --- Club extraction ---
            if not club_name and HAVE_TEAM_NAME_UTILS:
                club_name = extract_club_structured(team_name)

            # --- Provider distinctions for hard rejection ---
            provider_distinctions = None
            provider_variant = None
            if HAVE_TEAM_NAME_UTILS:
                provider_distinctions = extract_distinctions(team_name)
                provider_variant = provider_distinctions.get("coach_name")

            # --- Gated candidate retrieval ---
            club_filtered = False
            result = None
            if club_name:
                result = self.db.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code'
                ).eq('age_group', age_group_normalized).eq('gender', gender).ilike(
                    'club_name', club_name
                ).limit(100).execute()
                if result and result.data:
                    club_filtered = True

            # Broad fallback only when club extraction failed
            if not club_filtered:
                result = self.db.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code'
                ).eq('age_group', age_group_normalized).eq('gender', gender).limit(2000).execute()

            best_match = None
            best_score = 0.0
            best_tiebreak = (False, 0.0)

            provider_team = {
                'team_name': team_name,
                'club_name': club_name,
                'age_group': age_group,
                'state_code': None
            }

            club_variant_boost = MATCHING_CONFIG.get('club_variant_match_boost', 0.15)

            for team in (result.data if result else []):
                cand_name = team.get('team_name', '')

                # --- Gate: distinction-based hard rejection ---
                if HAVE_TEAM_NAME_UTILS and provider_distinctions is not None:
                    cand_distinctions = extract_distinctions(cand_name)
                    if provider_distinctions["colors"] != cand_distinctions["colors"]:
                        continue
                    if provider_distinctions["directions"] != cand_distinctions["directions"]:
                        continue
                    if provider_distinctions["programs"] != cand_distinctions["programs"]:
                        continue
                    if provider_distinctions["team_number"] != cand_distinctions["team_number"]:
                        continue
                    if provider_distinctions["location_codes"] != cand_distinctions["location_codes"]:
                        continue
                    if provider_distinctions["squad_words"] != cand_distinctions["squad_words"]:
                        continue
                    cand_coach = cand_distinctions.get("coach_name")
                    if (provider_distinctions.get("coach_name")
                            and cand_coach
                            and provider_distinctions["coach_name"] != cand_coach):
                        continue
                    cand_variant = cand_coach
                else:
                    cand_variant = None

                candidate = {
                    'team_name': cand_name,
                    'club_name': team.get('club_name'),
                    'age_group': team.get('age_group', ''),
                    'state_code': team.get('state_code')
                }

                score = self._calculate_match_score(provider_team, candidate)

                # --- Deterministic tie-breaking ---
                variant_match = (provider_variant is not None
                                 and cand_variant is not None
                                 and provider_variant == cand_variant)
                cand_club = team.get('club_name', '')
                club_sim = 0.0
                if club_name and cand_club:
                    if HAVE_CLUB_NORMALIZER:
                        club_sim = club_similarity_score(club_name, cand_club)
                    else:
                        club_sim = self._calculate_similarity(club_name, cand_club)

                tiebreak = (variant_match, club_sim)

                if score >= self.fuzzy_threshold:
                    if (score > best_score + 0.001
                            or (abs(score - best_score) <= 0.001 and tiebreak > best_tiebreak)):
                        best_score = score
                        best_tiebreak = tiebreak
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
    
    def _match_by_provider_id(
        self,
        provider_id: str,
        provider_team_id: str,
        age_group: Optional[str] = None,
        gender: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Override base method to skip age_group validation for TGS.

        Handles semicolon-separated provider_team_ids in alias map entries.
        For example, if alias has "123456;789012", this will match lookup for "123456".

        Unlike Modular11 where the same provider_team_id (club_id) is used for multiple
        age groups, TGS provider_team_id is unique per team. Therefore, we don't need
        age_group validation - if the provider_team_id matches, it's the correct team.

        This prevents valid matches from being rejected due to:
        - Year rollover (U13 → U14)
        - Age group data inconsistencies
        - Teams playing up/down age groups
        """
        if not provider_team_id:
            return None

        team_id_str = str(provider_team_id).strip()

        # Check cache first (if available)
        # Cache should already have semicolon-separated IDs expanded (done in enhanced_pipeline.py)
        if self.alias_cache and team_id_str in self.alias_cache:
            cached = self.alias_cache[team_id_str]
            # Skip age_group validation for TGS - provider_team_id is unique per team
            if cached.get('match_method') == 'direct_id':
                return {
                    'team_id_master': cached['team_id_master'],
                    'review_status': cached.get('review_status', 'approved'),
                    'match_method': 'direct_id'
                }
            # Fallback to any cached match
            return {
                'team_id_master': cached['team_id_master'],
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
                # Skip age_group validation for TGS - provider_team_id is unique
                return result.data[0]
        except Exception as e:
            logger.debug(f"No exact direct_id match found: {e}")

        # Tier 2: Check for semicolon-separated aliases containing this ID
        # This handles merged teams where provider_team_id is "123456;789012"
        try:
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
                        logger.debug(f"Matched {team_id_str} via semicolon-separated alias: {alias['provider_team_id']}")
                        return {
                            'team_id_master': alias['team_id_master'],
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
                # Skip age_group validation for TGS - provider_team_id is unique
                return result.data[0]
        except Exception as e:
            logger.debug(f"No alias map match found: {e}")
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
                # Use 'direct_id' if provider_team_id exists (like GotSport/Modular11)
                # This ensures consistent matching behavior across providers
                match_method = 'direct_id' if provider_team_id else 'import'

                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method=match_method,
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
                    'method': match_method,  # Use same method as alias creation
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

