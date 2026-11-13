import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from src.models.game_matcher import MATCHING_CONFIG, GameHistoryMatcher, birth_years_conflict
from src.utils.provider_ids import clean_provider_id
from supabase import Client

# Import rapidfuzz for similarity scoring
try:
    import rapidfuzz  # noqa: F401

    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

# Import shared team-name utilities
try:
    from src.utils.team_name_utils import (
        extract_club_from_team_name as extract_club_structured,
    )
    from src.utils.team_name_utils import (
        extract_distinctions,
    )
    from src.utils.team_name_utils import (
        extract_team_variant as extract_variant_shared,
    )

    HAVE_TEAM_NAME_UTILS = True
except ImportError:
    HAVE_TEAM_NAME_UTILS = False

# Import club normalizer for canonical club comparison
try:
    from src.utils.club_normalizer import (
        normalize_to_club,
    )
    from src.utils.club_normalizer import (
        similarity_score as club_similarity_score,
    )

    HAVE_CLUB_NORMALIZER = True
except ImportError:
    HAVE_CLUB_NORMALIZER = False

logger = logging.getLogger(__name__)


class ReuseRefused(Exception):
    """The row a TGS id already belongs to states the other gender from the incoming team name."""


class TGSGameMatcher(GameHistoryMatcher):
    """
    Key differences from base matcher:
    1. link_candidate and create_team decide each new TGS id before the import; _match_team finds
       a team by its TGS id alone
    2. A higher auto-link bar and TGS team name normalization
    """

    # A held link becomes a new team here, so a row the gender guard cannot read raises instead.
    unreadable_row_is_conflict = False

    def __init__(
        self,
        supabase: Client,
        provider_id: Optional[str] = None,
        alias_cache: Optional[Dict] = None,
        dry_run: bool = False,
    ):
        """Initialize TGS matcher with same interface as base matcher"""
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self.auto_approve_threshold = 0.91  # Auto-approve only very high confidence matches
        # Teams that already carry a TGS id, which no new TGS id may link to. One of them wins a
        # tie, so that refusal cannot be dodged by handing the link to an equally scored team.
        self.claimed_team_ids: Set[str] = set()
        self._cohort_cache: Dict[Tuple[str, str], List[Dict]] = {}
        logger.info(
            f"Initialized TGSGameMatcher with enhanced fuzzy matching "
            f"(fuzzy: {self.fuzzy_threshold}, auto-approve: {self.auto_approve_threshold})"
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
        matches = re.findall(r"\b(\d{1,2}[a-z])\b", name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r"\d+", match)
            if num_match:
                tokens.add(num_match.group())

        # Pattern 2: U + number (e.g., "u11", "u12")
        matches = re.findall(r"\b(u\d{1,2})\b", name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r"\d+", match)
            if num_match:
                tokens.add(num_match.group())

        # Pattern 3: B/G + number (e.g., "b12", "g13", "B12", "G13")
        # name_lower is already lowercase
        matches = re.findall(r"\b([bg]\d{1,2})\b", name_lower)
        tokens.update(matches)
        # Also extract just the number part
        for match in matches:
            num_match = re.search(r"\d+", match)
            if num_match:
                tokens.add(num_match.group())

        # Pattern 4: B/G + birth year (e.g., "B2015", "G2012", "b2013")
        # name_lower is already lowercase
        matches = re.findall(r"\b([bg]20[01]\d)\b", name_lower)
        tokens.update(matches)
        # Also extract just the year part
        for match in matches:
            year_match = re.search(r"20[01]\d", match)
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
        matches = re.findall(r"\b(20[01]\d[bg])\b", name_lower)
        tokens.update(matches)
        for match in matches:
            year_match = re.search(r"20[01]\d", match)
            if year_match:
                year = year_match.group()
                tokens.add(year)
                if len(year) == 4:
                    tokens.add(year[2:])
                # Also add B/G + last 2 digits (e.g., "2013G" -> "g13")
                tokens.add(match[-1] + year[2:])

        # Pattern 6: Birth year standalone (e.g., "2012", "2013")
        matches = re.findall(r"\b(20[01]\d)\b", name_lower)
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
            return ""

        # CRITICAL: Strip everything before the first dash BEFORE base
        # normalization.  TGS format:
        #   "Folsom Lake Surf- FLS 13B Premier I" → "FLS 13B Premier I"
        dash_chars = ["-", "–", "—"]
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
        provider_name_raw = provider_team.get("team_name", "")
        candidate_name_raw = candidate.get("team_name", "")
        provider_club = provider_team.get("club_name", "").strip() if provider_team.get("club_name") else None
        candidate_club = candidate.get("club_name", "").strip() if candidate.get("club_name") else None

        # Strip club name from provider team name (TGS often includes it)
        provider_name_normalized = self._normalize_team_name(provider_name_raw, provider_club)

        # Strip club from candidate name before normalization
        candidate_name_for_norm = candidate_name_raw
        if candidate_club:
            club_core = re.sub(r"\b(sc|fc|sa)\b", "", candidate_club.lower()).strip()
            cand_lower = candidate_name_raw.lower()
            if club_core and cand_lower.startswith(club_core):
                remaining = candidate_name_raw[len(club_core) :].strip().lstrip("-–—").strip()
                if remaining:
                    candidate_name_for_norm = remaining

        candidate_name_normalized = self._normalize_team_name(candidate_name_for_norm)

        # Create normalized dicts for base scoring
        provider_team_normalized = provider_team.copy()
        provider_team_normalized["team_name"] = provider_name_normalized
        candidate_normalized = candidate.copy()
        candidate_normalized["team_name"] = candidate_name_normalized

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
                cv_boost = MATCHING_CONFIG.get("club_variant_match_boost", 0.15)
                base_score = min(1.0, base_score + cv_boost)

        return base_score

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Enhanced fuzzy matching for TGS teams with gated candidate funnel.

        Uses:
        - Club-filtered query first, then the whole live cohort when the club names no candidate
        - Distinction-based and birth-year hard rejection before scoring
        - Deterministic tie-breaking on (claimed, variant_match, club_sim)
        """
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
        candidates = []
        if club_name:
            result = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name, age_group, gender, state_code")
                .eq("age_group", age_group_normalized)
                .eq("gender", gender)
                .eq("is_deprecated", False)
                .ilike("club_name", club_name)
                .limit(100)
                .execute()
            )
            candidates = result.data or []

        if not candidates:
            candidates = self._cohort(age_group_normalized, gender)

        best_match = None
        best_score = 0.0
        best_tiebreak = (False, False, 0.0)

        provider_team = {"team_name": team_name, "club_name": club_name, "age_group": age_group, "state_code": None}

        MATCHING_CONFIG.get("club_variant_match_boost", 0.15)

        for team in candidates:
            cand_name = team.get("team_name", "")

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
                # A wrong-year candidate must not shadow a right-year one further down.
                if birth_years_conflict(team_name, cand_name):
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
                "team_name": cand_name,
                "club_name": team.get("club_name"),
                "age_group": team.get("age_group", ""),
                "state_code": team.get("state_code"),
            }

            score = self._calculate_match_score(provider_team, candidate)

            # --- Deterministic tie-breaking ---
            variant_match = (
                provider_variant is not None and cand_variant is not None and provider_variant == cand_variant
            )
            cand_club = team.get("club_name", "")
            club_sim = 0.0
            if club_name and cand_club:
                if HAVE_CLUB_NORMALIZER:
                    club_sim = club_similarity_score(club_name, cand_club)
                else:
                    club_sim = self._calculate_similarity(club_name, cand_club)

            tiebreak = (team["team_id_master"] in self.claimed_team_ids, variant_match, club_sim)

            if score >= self.fuzzy_threshold:
                if score > best_score + 0.001 or (abs(score - best_score) <= 0.001 and tiebreak > best_tiebreak):
                    best_score = score
                    best_tiebreak = tiebreak
                    best_match = {
                        "team_id": team["team_id_master"],
                        "team_name": team["team_name"],
                        "confidence": round(score, 3),
                    }

        if best_match:
            logger.debug(
                f"TGS fuzzy match: '{team_name}' -> '{best_match['team_name']}' "
                f"(score: {best_match['confidence']}, club: {club_name})"
            )

        return best_match

    def _cohort(self, age_group: str, gender: str) -> List[Dict]:
        """Every live team of one age group and gender, read once per matcher in a fixed order."""
        key = (age_group, gender)
        if key not in self._cohort_cache:
            rows: List[Dict] = []
            while True:
                page = (
                    self.db.table("teams")
                    .select("team_id_master, team_name, club_name, age_group, gender, state_code")
                    .eq("age_group", age_group)
                    .eq("gender", gender)
                    .eq("is_deprecated", False)
                    .order("team_id_master")
                    .range(len(rows), len(rows) + 999)
                    .execute()
                    .data
                    or []
                )
                rows.extend(page)
                if len(page) < 1000:
                    break
            self._cohort_cache[key] = rows
        return self._cohort_cache[key]

    def link_candidate(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """The team a name match would link to, or None. Reads only.

        The fuzzy winner, when it clears the auto-approve threshold and the guards the base
        matcher applies before it writes a fuzzy_auto alias. A claimed winner is returned
        too, so the caller can refuse it rather than never learning it was the best match.
        """
        match = self._fuzzy_match_team(team_name, age_group, gender, club_name)
        if not match or match["confidence"] < self.auto_approve_threshold:
            return None
        year_conflict, gender_conflict = self._link_guards(team_name, match, age_group)
        return None if year_conflict or gender_conflict else match

    def _match_by_provider_id(
        self, provider_id: str, provider_team_id: str, age_group: Optional[str] = None, gender: Optional[str] = None
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
            if cached.get("match_method") == "direct_id":
                return {
                    "team_id_master": cached["team_id_master"],
                    "review_status": cached.get("review_status", "approved"),
                    "match_method": "direct_id",
                }
            # Fallback to any cached match
            return {
                "team_id_master": cached["team_id_master"],
                "review_status": cached.get("review_status", "approved"),
                "match_method": cached.get("match_method"),
            }

        # Tier 1: Direct ID match - exact match (from team importer)
        try:
            result = (
                self.db.table("team_alias_map")
                .select("team_id_master, review_status, match_method")
                .eq("provider_id", provider_id)
                .eq("provider_team_id", team_id_str)
                .eq("match_method", "direct_id")
                .eq("review_status", "approved")
                .limit(1)
                .execute()
            )

            if result.data:
                # Skip age_group validation for TGS - provider_team_id is unique
                return result.data[0]
        except Exception as e:
            logger.debug(f"No exact direct_id match found: {e}")

        # Tier 2: Check for semicolon-separated aliases containing this ID
        # This handles merged teams where provider_team_id is "123456;789012"
        try:
            result = (
                self.db.table("team_alias_map")
                .select("team_id_master, review_status, match_method, provider_team_id")
                .eq("provider_id", provider_id)
                .eq("review_status", "approved")
                .like("provider_team_id", f"%{team_id_str}%")
                .execute()
            )

            if result.data:
                # Verify this is actually a match (not a substring of a different ID)
                for alias in result.data:
                    alias_ids = str(alias["provider_team_id"]).split(";")
                    alias_ids = [id.strip() for id in alias_ids]
                    if team_id_str in alias_ids:
                        logger.debug(
                            f"Matched {team_id_str} via semicolon-separated alias: {alias['provider_team_id']}"
                        )
                        return {
                            "team_id_master": alias["team_id_master"],
                            "review_status": alias.get("review_status", "approved"),
                            "match_method": alias.get("match_method"),
                        }
        except Exception as e:
            logger.debug(f"No semicolon-separated alias match found: {e}")

        # Tier 3: Any approved alias map entry - exact match (fallback)
        try:
            result = (
                self.db.table("team_alias_map")
                .select("team_id_master, review_status, match_method")
                .eq("provider_id", provider_id)
                .eq("provider_team_id", team_id_str)
                .eq("review_status", "approved")
                .limit(1)
                .execute()
            )

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
        club_name: Optional[str] = None,
    ) -> Dict:
        """Find a TGS team by its TGS id. Never by name, and never by creating one.

        extract_and_import_tgs_teams.py links or creates every new id before the import, where it
        sees every shard's teams at once and can refuse a team that already carries a TGS id. An
        id it held back, and a blank id (a bracket placeholder), stay unmatched here.
        """
        provider_team_id = clean_provider_id(provider_team_id) or None
        alias_match = provider_team_id and self._match_by_provider_id(provider_id, provider_team_id, age_group, gender)
        if not alias_match:
            logger.debug(f"[TGS] No alias for {provider_team_id!r} ({team_name}); leaving that side unmatched")
            return {"matched": False, "team_id": None, "method": None, "confidence": 0.0}
        method = "direct_id" if alias_match.get("match_method") == "direct_id" else "provider_id"
        return {"matched": True, "team_id": alias_match["team_id_master"], "method": method, "confidence": 1.0}

    def create_team(
        self,
        provider_id: str,
        provider_team_id: str,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
    ) -> str:
        """Create the team a TGS id names and alias the id to it. Raises ReuseRefused."""
        new_team_id = self._create_new_tgs_team(
            team_name=team_name,
            club_name=club_name,
            age_group=age_group,
            gender=gender,
            provider_id=provider_id,
            provider_team_id=provider_team_id,
        )
        self._create_alias(
            provider_id=provider_id,
            provider_team_id=provider_team_id,
            team_name=team_name,
            team_id_master=new_team_id,
            match_method="direct_id",
            confidence=1.0,
            age_group=age_group,
            gender=gender,
            review_status="approved",
        )
        logger.info(f"[TGS] Created new team: {team_name} ({age_group}, {gender}) -> {new_team_id}")
        return new_team_id

    def _create_new_tgs_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: str,
    ) -> str:
        """
        Create a new team in the teams table for TGS.

        If a team with the same provider_id and provider_team_id already exists,
        return that team's ID instead of creating a duplicate, unless the gender guard refuses
        it, which raises ReuseRefused.

        Returns the team_id_master UUID.
        """
        try:
            # Check if team with this provider_id + provider_team_id already exists
            if provider_id:
                found = None
                try:
                    existing = (
                        self.db.table("teams")
                        .select("team_id_master")
                        .eq("provider_id", provider_id)
                        .eq("provider_team_id", provider_team_id)
                        .single()
                        .execute()
                    )

                    if existing.data:
                        logger.debug(
                            f"[TGS] Team with provider_team_id {provider_team_id} already exists, "
                            f"using existing team {existing.data['team_id_master']}"
                        )
                        found = existing.data["team_id_master"]
                except Exception:
                    # No existing team found, continue to create new one
                    pass
                # Outside the try, so the handler above cannot swallow ReuseRefused.
                if found:
                    return self._reusable(team_name, found)

            # Generate new UUID
            team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)

            # Normalize age_group
            age_group_normalized = age_group.lower() if age_group else age_group

            # Normalize gender
            gender_normalized = "Male" if gender.upper() in ("M", "MALE", "BOYS", "B") else "Female"

            # Clean team name (strip club name prefix if present)
            clean_team_name = team_name
            if club_name and team_name.startswith(club_name):
                # Remove club name prefix
                remaining = team_name[len(club_name) :].strip()
                if remaining.startswith("-") or remaining.startswith("–") or remaining.startswith("—"):
                    remaining = remaining[1:].strip()
                if remaining:
                    clean_team_name = remaining

            # TGS: pass clean_team_name (built above by stripping club prefix).
            # TODO: thread state_code through this signature so resolve_distinction
            # can strip state-name tokens (e.g., 'New Hampshire' for clubs that
            # don't include the state in club_name). Not load-bearing today since
            # TGS-sourced teams are typically labeled with full club names.
            from src.utils.team_name_utils import resolve_distinction

            distinction = resolve_distinction(clean_team_name, club_name, None)

            # TGS carries no per-team state, so the club is the only thing that can be
            # asked, and it answers only when all of its existing rows agree. Leaving
            # the rest NULL is deliberate: TGS created 763 stateless teams in one day,
            # and every one of them is a blank the assignment tool can fill from
            # evidence later. A guess here would instead be a wrong value that the
            # same tool then reads as its own corroboration.
            state_code, _ = self._resolve_state_from_club(club_name)

            # Insert new team
            team_data = {
                "team_id_master": team_id_master,
                "team_name": clean_team_name,
                "club_name": club_name or clean_team_name,
                "age_group": age_group_normalized,
                "gender": gender_normalized,
                "provider_id": provider_id,  # Required for TGS teams
                "provider_team_id": provider_team_id,  # REQUIRED (NOT NULL)
                "distinction": distinction,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            # state_code only, never the full-name `state` column. Four writers set that
            # column and assign_team_states reads a filled one as "a provider reported
            # this", which stops it correcting the value without a per-team record. A
            # state inferred from the club is exactly the kind it should be free to
            # correct later, so it must not look reported.
            if state_code:
                team_data["state_code"] = state_code

            if not self.dry_run:
                self.db.table("teams").insert(team_data).execute()

            logger.info(f"[TGS] Created new team: {clean_team_name} ({age_group_normalized}, {gender_normalized})")

            return team_id_master

        except ReuseRefused:
            raise
        except Exception as e:
            # If duplicate key error, try to find existing team
            if "duplicate key" in str(e).lower() or "23505" in str(e):
                logger.debug(f"[TGS] Duplicate key error, looking up existing team: {e}")
                if provider_id and provider_team_id:
                    found = None
                    try:
                        existing = (
                            self.db.table("teams")
                            .select("team_id_master")
                            .eq("provider_id", provider_id)
                            .eq("provider_team_id", provider_team_id)
                            .single()
                            .execute()
                        )

                        if existing.data:
                            logger.info(
                                f"[TGS] Found existing team with provider_team_id {provider_team_id}, "
                                f"using {existing.data['team_id_master']}"
                            )
                            found = existing.data["team_id_master"]
                    except Exception as lookup_error:
                        logger.error(f"[TGS] Error looking up existing team: {lookup_error}")
                    # Outside the try, as above.
                    if found:
                        return self._reusable(team_name, found)

            logger.error(f"[TGS] Error creating new team: {e}")
            raise

    def _reusable(self, team_name: str, team_id_master: str) -> str:
        """Return a row this TGS id already belongs to, unless it states the other gender. A row
        that cannot be read raises.

        Reusing that row is a link like any other; without this check, creating a team for a link
        the gender guard held would reuse the very row it held.
        """
        if self._genders_conflict(team_name, team_id_master):
            raise ReuseRefused(f"Gender conflict, not reusing team {team_id_master} for {team_name!r}")
        return team_id_master
