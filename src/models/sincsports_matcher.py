"""
SincSports-specific game matcher with enhanced fuzzy matching for team name matching.

This matcher extends GameHistoryMatcher to provide SincSports-aware normalization
and the same gated-funnel / distinction-based matching improvements used by the
TGS matcher.

SincSports naming patterns:
  - Team names often lead with age/gender: "U12 PRE ECNL BOYS RED"
  - Club names are provided separately (not embedded in team_name)
  - Team IDs are alphanumeric: "NCM14762", "SCM14140"
  - Parenthesised age prefixes: "14 (12U) CSA UM Elite"
  - Dash-separated suffixes: "FCC 2014 Boys Gold - BA"
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

# Regex patterns for stripping leading age/gender tokens that SincSports
# places at the front of team names (e.g. "U12 PRE ECNL BOYS RED").
_SINCSPORTS_AGE_PREFIX_RE = re.compile(
    r'^'
    r'(?:'
    r'U-?\d{1,2}'               # U12, U-12
    r'|\d{1,2}\s*\(?\d{1,2}U\)?' # "14 (12U)" or "14 12U"
    r'|\d{4}'                    # Birth year: 2014
    r')'
    r'\s*',
    re.IGNORECASE,
)

_SINCSPORTS_GENDER_TOKEN_RE = re.compile(
    r'\b(?:boys?|girls?|men|women|male|female|coed)\b',
    re.IGNORECASE,
)

# Parenthesised age like "(12U)" that appears mid-name
_PAREN_AGE_RE = re.compile(r'\(\d{1,2}U\)', re.IGNORECASE)


class SincSportsGameMatcher(GameHistoryMatcher):
    """
    SincSports-specific team matcher with enhanced fuzzy matching.

    Key differences from the base matcher:
    1. Strips leading age/gender tokens from team names before normalisation
    2. Lower fuzzy threshold (0.75 vs 0.85) — same as TGS
    3. Gated candidate funnel (club-filtered query first)
    4. Distinction-based hard rejection (colors, programs, etc.)
    5. Club + variant boost, deterministic tie-breaking
    6. Creates new teams when no match is found
    """

    def __init__(
        self,
        supabase: Client,
        provider_id: Optional[str] = None,
        alias_cache: Optional[Dict] = None,
    ):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache)
        # Lower thresholds for more aggressive matching
        self.fuzzy_threshold = 0.75
        self.auto_approve_threshold = 0.91
        self.review_threshold = 0.70
        logger.info(
            f"Initialized SincSportsGameMatcher with enhanced fuzzy matching "
            f"(fuzzy: {self.fuzzy_threshold}, auto-approve: {self.auto_approve_threshold}, "
            f"review: {self.review_threshold})"
        )

    # ------------------------------------------------------------------
    # Age-token extraction (mirrors TGS)
    # ------------------------------------------------------------------
    def _extract_age_tokens(self, name: str) -> Set[str]:
        """
        Extract age group tokens from team name.

        Handles SincSports patterns like "U12 PRE ECNL BOYS RED",
        "14 (12U) CSA UM Elite", "2014 Boys Gold".
        """
        if not name:
            return set()

        tokens: Set[str] = set()
        name_lower = name.lower()

        # U + number
        for m in re.findall(r'\b(u\d{1,2})\b', name_lower):
            tokens.add(m)
            num = re.search(r'\d+', m)
            if num:
                tokens.add(num.group())

        # age + letter (14b, 13a)
        for m in re.findall(r'\b(\d{1,2}[a-z])\b', name_lower):
            tokens.add(m)
            num = re.search(r'\d+', m)
            if num:
                tokens.add(num.group())

        # B/G + number
        for m in re.findall(r'\b([bg]\d{1,2})\b', name_lower):
            tokens.add(m)
            num = re.search(r'\d+', m)
            if num:
                tokens.add(num.group())

        # B/G + birth year
        for m in re.findall(r'\b([bg]20[01]\d)\b', name_lower):
            tokens.add(m)
            year = re.search(r'20[01]\d', m).group()
            tokens.add(year)
            tokens.add(year[2:])
            tokens.add(m[0] + year[2:])

        # Birth year standalone
        for m in re.findall(r'\b(20[01]\d)\b', name_lower):
            tokens.add(m)
            tokens.add(m[2:])

        return tokens

    # ------------------------------------------------------------------
    # Name normalisation — SincSports-specific preprocessing
    # ------------------------------------------------------------------
    def _normalize_team_name(self, name: str, club_name: Optional[str] = None) -> str:
        """
        Enhanced normalisation for SincSports team names.

        SincSports puts age/gender at the *front*:
            "U12 PRE ECNL BOYS RED"  ->  "PRE ECNL RED"
            "14 (12U) CSA UM Elite"  ->  "CSA UM Elite"
            "FCC 2014 Boys Gold - BA" -> "FCC Gold - BA" (birth year + gender stripped)

        After SincSports-specific stripping, we delegate to the base class
        which in turn uses the shared ``normalize_name_for_matching()``.
        """
        if not name:
            return ''

        # Step 1: Strip parenthesised age like "(12U)"
        name = _PAREN_AGE_RE.sub('', name).strip()

        # Step 2: Strip leading age token (U12, 14, 2014, etc.)
        name = _SINCSPORTS_AGE_PREFIX_RE.sub('', name).strip()

        # Step 3: Strip remaining leading numeric-only prefix left over
        # e.g. "14 CSA UM Elite" after paren removal -> "CSA UM Elite"
        name = re.sub(r'^\d{1,4}\s+', '', name).strip()

        # Step 4: Strip gender tokens (BOYS, GIRLS, etc.)
        name = _SINCSPORTS_GENDER_TOKEN_RE.sub('', name).strip()

        # Step 5: Collapse multiple spaces
        name = re.sub(r'\s{2,}', ' ', name).strip()

        # Delegate to base (shared normalize_name_for_matching)
        return super()._normalize_team_name(name)

    # ------------------------------------------------------------------
    # Match scoring — club registry + age token overlap
    # ------------------------------------------------------------------
    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """
        Enhanced match scoring with canonical club comparison and age-token
        overlap boost (mirrors TGS).
        """
        provider_name_raw = provider_team.get('team_name', '')
        candidate_name_raw = candidate.get('team_name', '')
        provider_club = (provider_team.get('club_name') or '').strip() or None
        candidate_club = (candidate.get('club_name') or '').strip() or None

        # Normalise names (SincSports preprocessing + shared normalisation)
        provider_name_normalized = self._normalize_team_name(provider_name_raw, provider_club)

        # Strip club prefix from candidate name before normalisation
        candidate_name_for_norm = candidate_name_raw
        if candidate_club:
            club_core = re.sub(r'\b(sc|fc|sa)\b', '', candidate_club.lower()).strip()
            cand_lower = candidate_name_raw.lower()
            if club_core and cand_lower.startswith(club_core):
                remaining = candidate_name_raw[len(club_core):].strip().lstrip('-\u2013\u2014').strip()
                if remaining:
                    candidate_name_for_norm = remaining

        candidate_name_normalized = self._normalize_team_name(candidate_name_for_norm)

        # Build normalised dicts for base scoring
        provider_team_normalized = provider_team.copy()
        provider_team_normalized['team_name'] = provider_name_normalized
        candidate_normalized = candidate.copy()
        candidate_normalized['team_name'] = candidate_name_normalized

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

        # --- Club + variant boost ---
        if club_sim >= 0.8:
            prov_variant = extract_variant_shared(provider_name_raw) if HAVE_TEAM_NAME_UTILS else None
            cand_variant = extract_variant_shared(candidate_name_raw) if HAVE_TEAM_NAME_UTILS else None
            if prov_variant and cand_variant and prov_variant == cand_variant:
                cv_boost = MATCHING_CONFIG.get('club_variant_match_boost', 0.15)
                base_score = min(1.0, base_score + cv_boost)

        return base_score

    # ------------------------------------------------------------------
    # Fuzzy matching — gated funnel with distinction-based rejection
    # ------------------------------------------------------------------
    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Enhanced fuzzy matching for SincSports teams.

        Uses:
        - Club-filtered query first (gated funnel)
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
                'state_code': None,
            }

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
                    if (
                        provider_distinctions.get("coach_name")
                        and cand_coach
                        and provider_distinctions["coach_name"] != cand_coach
                    ):
                        continue
                    cand_variant = cand_coach
                else:
                    cand_variant = None

                candidate = {
                    'team_name': cand_name,
                    'club_name': team.get('club_name'),
                    'age_group': team.get('age_group', ''),
                    'state_code': team.get('state_code'),
                }

                score = self._calculate_match_score(provider_team, candidate)

                # --- Deterministic tie-breaking ---
                variant_match = (
                    provider_variant is not None
                    and cand_variant is not None
                    and provider_variant == cand_variant
                )
                cand_club = team.get('club_name', '')
                club_sim = 0.0
                if club_name and cand_club:
                    if HAVE_CLUB_NORMALIZER:
                        club_sim = club_similarity_score(club_name, cand_club)
                    else:
                        club_sim = self._calculate_similarity(club_name, cand_club)

                tiebreak = (variant_match, club_sim)

                if score >= self.fuzzy_threshold:
                    if (
                        score > best_score + 0.001
                        or (abs(score - best_score) <= 0.001 and tiebreak > best_tiebreak)
                    ):
                        best_score = score
                        best_tiebreak = tiebreak
                        best_match = {
                            'team_id': team['team_id_master'],
                            'team_name': team['team_name'],
                            'confidence': round(score, 3),
                        }

            if best_match:
                logger.debug(
                    f"SincSports fuzzy match: '{team_name}' -> '{best_match['team_name']}' "
                    f"(score: {best_match['confidence']}, club: {club_name})"
                )

            return best_match

        except Exception as e:
            logger.error(f"SincSports fuzzy match error: {e}")
            return None

    # ------------------------------------------------------------------
    # Provider-ID matching — skip age_group validation
    # ------------------------------------------------------------------
    def _match_by_provider_id(
        self,
        provider_id: str,
        provider_team_id: str,
        age_group: Optional[str] = None,
        gender: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Override base method to skip age_group validation for SincSports.

        SincSports provider_team_ids (e.g. "NCM14762") are unique per team,
        so if the ID matches we don't need age_group validation — the same
        rationale as TGS.
        """
        if not provider_team_id:
            return None

        team_id_str = str(provider_team_id).strip()

        # Check cache first
        if self.alias_cache and team_id_str in self.alias_cache:
            cached = self.alias_cache[team_id_str]
            if cached.get('match_method') == 'direct_id':
                return {
                    'team_id_master': cached['team_id_master'],
                    'review_status': cached.get('review_status', 'approved'),
                    'match_method': 'direct_id',
                }
            return {
                'team_id_master': cached['team_id_master'],
                'review_status': cached.get('review_status', 'approved'),
                'match_method': cached.get('match_method'),
            }

        # Tier 1: Direct ID match — exact match
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method'
            ).eq('provider_id', provider_id).eq(
                'provider_team_id', team_id_str
            ).eq('match_method', 'direct_id').eq(
                'review_status', 'approved'
            ).limit(1).execute()

            if result.data:
                return result.data[0]
        except Exception as e:
            logger.debug(f"No exact direct_id match found: {e}")

        # Tier 2: Any approved alias map entry — exact match (fallback)
        try:
            result = self.db.table('team_alias_map').select(
                'team_id_master, review_status, match_method'
            ).eq('provider_id', provider_id).eq(
                'provider_team_id', team_id_str
            ).eq('review_status', 'approved').limit(1).execute()

            if result.data:
                return result.data[0]
        except Exception as e:
            logger.debug(f"No alias map match found: {e}")

        return None

    # ------------------------------------------------------------------
    # Team matching — create new team when no match found
    # ------------------------------------------------------------------
    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
    ) -> Dict:
        """
        Override base _match_team to create new teams when no match found
        (same strategy as TGS).
        """
        # First, try base matching (direct ID, alias, fuzzy)
        base_result = super()._match_team(
            provider_id, provider_team_id, team_name, age_group, gender, club_name
        )

        if base_result.get('matched'):
            return base_result

        # No match found — create new team
        if team_name and age_group and gender:
            logger.info(
                f"[SincSports] No match found for '{team_name}' ({age_group}, {gender}), "
                f"creating new team"
            )
            try:
                new_team_id = self._create_new_sincsports_team(
                    team_name=team_name,
                    club_name=club_name,
                    age_group=age_group,
                    gender=gender,
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                )

                match_method = 'direct_id' if provider_team_id else 'import'

                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method=match_method,
                    confidence=1.0,
                    age_group=age_group,
                    gender=gender,
                    review_status='approved',
                )

                logger.info(
                    f"[SincSports] Created new team: {team_name} ({age_group}, {gender}) "
                    f"-> {new_team_id}"
                )

                return {
                    'matched': True,
                    'team_id': new_team_id,
                    'method': match_method,
                    'confidence': 1.0,
                }
            except Exception as e:
                logger.error(f"[SincSports] Error creating new team for {team_name}: {e}")
        else:
            logger.debug(
                f"[SincSports] Cannot create new team — missing required fields: "
                f"team_name={bool(team_name)}, age_group={bool(age_group)}, "
                f"gender={bool(gender)}"
            )

        return base_result

    # ------------------------------------------------------------------
    # Team creation helper
    # ------------------------------------------------------------------
    def _create_new_sincsports_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
    ) -> str:
        """
        Create a new team in the teams table for SincSports.

        Returns the team_id_master UUID.
        """
        try:
            # provider_team_id is REQUIRED (NOT NULL constraint)
            if not provider_team_id:
                import hashlib
                provider_team_id = hashlib.md5(
                    f"{team_name}_{age_group}_{gender}".encode()
                ).hexdigest()[:16]

            # Check if team with this provider_id + provider_team_id already exists
            if provider_id:
                try:
                    existing = self.db.table('teams').select('team_id_master').eq(
                        'provider_id', provider_id
                    ).eq('provider_team_id', provider_team_id).single().execute()

                    if existing.data:
                        logger.debug(
                            f"[SincSports] Team with provider_team_id {provider_team_id} "
                            f"already exists, using existing team "
                            f"{existing.data['team_id_master']}"
                        )
                        return existing.data['team_id_master']
                except Exception:
                    pass  # No existing team found

            team_id_master = str(uuid.uuid4())
            age_group_normalized = age_group.lower() if age_group else age_group
            gender_normalized = 'Male' if gender.upper() in ('M', 'MALE', 'BOYS', 'B') else 'Female'

            # Clean team name — strip club name prefix if present
            clean_team_name = team_name
            if club_name and team_name.lower().startswith(club_name.lower()):
                remaining = team_name[len(club_name):].strip()
                if remaining and remaining[0] in '-\u2013\u2014':
                    remaining = remaining[1:].strip()
                if remaining:
                    clean_team_name = remaining

            team_data = {
                'team_id_master': team_id_master,
                'team_name': clean_team_name,
                'club_name': club_name or clean_team_name,
                'age_group': age_group_normalized,
                'gender': gender_normalized,
                'provider_id': provider_id,
                'provider_team_id': provider_team_id,
                'created_at': datetime.utcnow().isoformat() + 'Z',
            }

            self.db.table('teams').insert(team_data).execute()

            logger.info(
                f"[SincSports] Created new team: {clean_team_name} "
                f"({age_group_normalized}, {gender_normalized})"
            )

            return team_id_master

        except Exception as e:
            # Handle duplicate key errors gracefully
            if 'duplicate key' in str(e).lower() or '23505' in str(e):
                logger.debug(f"[SincSports] Duplicate key error, looking up existing team: {e}")
                if provider_id and provider_team_id:
                    try:
                        existing = self.db.table('teams').select('team_id_master').eq(
                            'provider_id', provider_id
                        ).eq('provider_team_id', provider_team_id).single().execute()

                        if existing.data:
                            logger.info(
                                f"[SincSports] Found existing team with "
                                f"provider_team_id {provider_team_id}, "
                                f"using {existing.data['team_id_master']}"
                            )
                            return existing.data['team_id_master']
                    except Exception as lookup_error:
                        logger.error(
                            f"[SincSports] Error looking up existing team: {lookup_error}"
                        )

            logger.error(f"[SincSports] Error creating new team: {e}")
            raise
