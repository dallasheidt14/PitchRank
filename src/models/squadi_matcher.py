"""
Squadi-specific game matcher for New Jersey youth soccer.

Hybrid design (mirrors ``PlayMetricsGameMatcher``):
- Structure: JSON-API, UUID provider_team_id unique per team, so
  ``_match_by_provider_id`` skips the age-group gate.
- State scoping: candidates are narrowed to NJ in ``_fuzzy_match_team`` and
  autocreated teams get ``state_code="NJ"``.
- Inline autocreate: after base ``_match_team`` exhausts alias / direct_id /
  fuzzy paths without matching, a fresh team row is created so no game is
  dropped.

NJYS State Cup teams overlap with TGS / GotSport / EDP rosters already in
PitchRank, so the fuzzy gate is the load-bearing path on first-import; the
direct_id alias path takes over once teams are seeded.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_normalizer import are_same_club
from src.utils.team_name_utils import extract_distinctions

logger = logging.getLogger(__name__)

STATE_CODE = "NJ"

# state_code → full state name (mirrors the scraper's ORG_REGISTRY; keep in sync
# with ``scripts/scrape_squadi_competition.py`` when new states are added).
STATE_CODE_TO_NAME: Dict[str, str] = {
    "NJ": "New Jersey",
}


class SquadiGameMatcher(GameHistoryMatcher):
    """Squadi matcher: NJ-scoped fuzzy + autocreate fallback.

    Keeps base thresholds (fuzzy=0.75, auto_approve=0.90, review=0.75) so the
    review-queue routing in the base class continues to behave the same way.
    """

    def __init__(self, supabase, provider_id=None, alias_cache=None):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache)
        self.default_state_code = STATE_CODE
        # Per-(state, age_group, gender) candidate cache for _fuzzy_match_team.
        # Without it, each unmatched team in a batch re-issues the same
        # ~200-500-row query for its bucket — dozens to thousands of identical
        # RTTs per import. Populated on first miss; kept fresh via `append`
        # inside ``_create_new_squadi_team``. Keyed by state so multi-state
        # support (other Squadi orgs) is a drop-in.
        self._candidate_cache: Dict = {}

    @staticmethod
    def _normalize_gender(gender: Optional[str]) -> Optional[str]:
        """Canonicalize gender to ``"Male"`` or ``"Female"`` for DB + cache keys."""
        if not gender:
            return None
        return "Male" if gender.upper() in ("M", "MALE", "BOYS", "B") else "Female"

    def _match_by_provider_id(
        self, provider_id: str, provider_team_id: str, age_group: Optional[str] = None, gender: Optional[str] = None
    ) -> Optional[Dict]:
        """Skip age_group validation: Squadi teamUniqueKey is a UUID unique per team.

        Mirror of ``PlayMetricsGameMatcher._match_by_provider_id`` — same rationale:
        using a stable provider-native ID, so a match is authoritative regardless
        of whether the current game's age_group differs (e.g. playing up).
        """
        if not provider_team_id:
            return None

        team_id_str = str(provider_team_id).strip()

        # Check cache first (if available); cache already has semicolon-split IDs expanded.
        if self.alias_cache and team_id_str in self.alias_cache:
            cached = self.alias_cache[team_id_str]
            return {
                "team_id_master": cached["team_id_master"],
                "review_status": cached.get("review_status", "approved"),
                "match_method": cached.get("match_method"),
            }

        # Tier 1: Direct ID match — exact
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
                return result.data[0]
        except Exception as e:
            logger.debug(f"[Squadi] No exact direct_id match: {e}")

        # Tier 2: Semicolon-separated alias (merged teams)
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
                for alias in result.data:
                    alias_ids = [i.strip() for i in str(alias["provider_team_id"]).split(";")]
                    if team_id_str in alias_ids:
                        return {
                            "team_id_master": alias["team_id_master"],
                            "review_status": alias.get("review_status", "approved"),
                            "match_method": alias.get("match_method"),
                        }
        except Exception as e:
            logger.debug(f"[Squadi] No semicolon-alias match: {e}")

        # Tier 3: Any approved alias — exact
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
                return result.data[0]
        except Exception as e:
            logger.debug(f"[Squadi] No alias map match: {e}")
        return None

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """NJ-scoped fuzzy matching with Python-side club gate.

        SQL narrows candidates to ``state_code/age_group/gender`` only — no SQL
        ``.ilike("club_name", ...)`` prefix filter because that drops legitimate
        candidates whose club_name differs by prefix (e.g. ``"Bavarian United"``
        vs ``"Bavarian Soccer Club"`` normalize to the same canonical club).
        Within the candidate set, ``are_same_club`` enforces the club gate, then
        distinction-based rejection prevents within-club variant collisions
        (Red ≠ Blue, ECNL ≠ ECRL), and finally base ``_calculate_match_score``
        assigns the weighted score.
        """
        try:
            age_group_normalized = age_group.lower() if age_group else age_group
            gender_normalized = self._normalize_gender(gender)
            club_threshold = MATCHING_CONFIG.get("affinity_club_similarity_threshold", 0.9)

            candidates = self._get_candidates(STATE_CODE, age_group_normalized, gender_normalized)
            if not candidates:
                return None

            provider_distinctions = extract_distinctions(team_name)
            provider_team = {
                "team_name": team_name,
                "club_name": club_name,
                "age_group": age_group,
                "state_code": STATE_CODE,
            }

            best_match = None
            best_score = 0.0

            for team in candidates:
                candidate_club = team.get("club_name")

                # Stage 1: canonical same-club gate.
                if club_name and candidate_club:
                    if not are_same_club(club_name, candidate_club, threshold=club_threshold):
                        continue

                # Stage 2: distinction-based hard rejection (Red ≠ Blue, ECNL ≠ ECRL, etc.).
                # Distinctions are memoized on the cached row so repeated matcher calls
                # within one import don't re-run the regex-heavy extractor.
                cand_distinctions = team.get("_distinctions")
                if cand_distinctions is None:
                    cand_distinctions = extract_distinctions(team.get("team_name", ""))
                    team["_distinctions"] = cand_distinctions
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

                cand_name = team.get("team_name", "")
                candidate = {
                    "team_name": cand_name,
                    "club_name": candidate_club,
                    "age_group": team.get("age_group"),
                    "state_code": team.get("state_code"),
                }
                score = self._calculate_match_score(provider_team, candidate)

                if score >= self.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_match = {
                        "team_id": team["team_id_master"],
                        "team_name": cand_name,
                        "confidence": round(score, 3),
                    }

            return best_match
        except Exception as e:
            logger.error(f"[Squadi] Fuzzy match error: {e}")
            return None

    def _get_candidates(
        self,
        state_code: str,
        age_group_normalized: Optional[str],
        gender_normalized: Optional[str],
    ) -> list:
        """Return the candidate set for (state, age_group, gender), fetching on first miss."""
        key = (state_code, age_group_normalized, gender_normalized)
        cached = self._candidate_cache.get(key)
        if cached is not None:
            return cached
        result = (
            self.db.table("teams")
            .select("team_id_master, team_name, club_name, age_group, gender, state_code")
            .eq("age_group", age_group_normalized)
            .eq("gender", gender_normalized)
            .eq("state_code", state_code)
            .execute()
        )
        data = list(result.data) if result and result.data else []
        self._candidate_cache[key] = data
        return data

    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
    ) -> Dict:
        """Try base matching (alias / direct_id / fuzzy). On miss, autocreate a new team."""
        base_result = super()._match_team(provider_id, provider_team_id, team_name, age_group, gender, club_name)

        if base_result.get("matched"):
            return base_result

        if team_name and age_group and gender:
            logger.info(f"[Squadi] No match for '{team_name}' ({age_group}, {gender}), creating new team")
            try:
                new_team_id = self._create_new_squadi_team(
                    team_name=team_name,
                    club_name=club_name,
                    age_group=age_group,
                    gender=gender,
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                )
                match_method = "direct_id" if provider_team_id else "import"
                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method=match_method,
                    confidence=1.0,
                    age_group=age_group,
                    gender=gender,
                    review_status="approved",
                )
                logger.info(f"[Squadi] Created: {team_name} ({age_group}, {gender}) -> {new_team_id}")
                return {
                    "matched": True,
                    "team_id": new_team_id,
                    "method": match_method,
                    "confidence": 1.0,
                    "created": True,
                }
            except Exception as e:
                logger.error(f"[Squadi] Error creating team for {team_name}: {e}")

        return base_result

    def _create_new_squadi_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
    ) -> str:
        """Create a new row in ``teams`` for a Squadi team. NJ-only for now.

        Handles the concurrent-autocreate race: two games in the same batch for
        a brand-new team can both reach this method, so we retry the lookup on
        the ``UNIQUE(provider_id, provider_team_id)`` constraint violation.
        """
        if not provider_team_id:
            import hashlib

            # MD5 for deterministic ID generation (not security).
            provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}".encode()).hexdigest()[:16]

        if provider_id:
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
                    return existing.data["team_id_master"]
            except Exception:
                pass

        team_id_master = str(uuid.uuid4())
        age_group_normalized = age_group.lower() if age_group else age_group
        gender_normalized = self._normalize_gender(gender)

        team_data = {
            "team_id_master": team_id_master,
            "team_name": team_name,
            "club_name": club_name or team_name,
            "age_group": age_group_normalized,
            "gender": gender_normalized,
            "state_code": STATE_CODE,
            "state": STATE_CODE_TO_NAME.get(STATE_CODE),
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.db.table("teams").insert(team_data).execute()
            # Keep the fuzzy-match candidate cache fresh so later rows in the same
            # batch can match against the team we just created.
            key = (STATE_CODE, age_group_normalized, gender_normalized)
            if key in self._candidate_cache:
                self._candidate_cache[key].append({**team_data, "_distinctions": None})
            return team_id_master
        except Exception as e:
            err = str(e).lower()
            if "duplicate key" in err or "23505" in err:
                logger.debug(f"[Squadi] Duplicate key on insert, looking up existing team: {e}")
                if provider_id and provider_team_id:
                    existing = (
                        self.db.table("teams")
                        .select("team_id_master")
                        .eq("provider_id", provider_id)
                        .eq("provider_team_id", provider_team_id)
                        .single()
                        .execute()
                    )
                    if existing.data:
                        return existing.data["team_id_master"]
            logger.error(f"[Squadi] Error creating new team: {e}")
            raise
