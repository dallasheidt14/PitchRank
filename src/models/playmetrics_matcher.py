"""
PlayMetrics-specific game matcher.

Hybrid design:
- Structure mirrors ``TGSGameMatcher`` — JSON-API, integer provider_team_id
  unique per team, so ``_match_by_provider_id`` skips the age-group gate.
- State scoping is configurable per-instance via ``default_state_code``:
    * ``"WI"`` (default) — SECL flow: WI-scoped fuzzy candidates, WI autocreate.
    * ``None`` — tournament flow: no state filter on fuzzy candidates,
      autocreate resolves state from the club's existing rows in ``teams``
      (unique non-null state) or leaves it NULL when the club spans states
      or is unknown to the DB.
- Inline autocreate: after base ``_match_team`` exhausts alias / direct_id /
  fuzzy paths without matching, a fresh team row is created so no game is
  dropped.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_normalizer import are_same_club
from src.utils.team_name_utils import extract_distinctions, resolve_distinction

logger = logging.getLogger(__name__)

DEFAULT_STATE_CODE = "WI"

# state_code → full state name. Only used when ``default_state_code`` is set
# at construction; the no-state autocreate path reads the canonical ``state``
# string straight off the existing teams row instead.
STATE_CODE_TO_NAME: Dict[str, str] = {
    "WI": "Wisconsin",
}


class PlayMetricsGameMatcher(GameHistoryMatcher):
    """PlayMetrics matcher: state-scoped (or open) fuzzy + autocreate fallback.

    Keeps base thresholds (fuzzy=0.75, auto_approve=0.90, review=0.75) so the
    review-queue routing in the base class continues to behave the same way.
    """

    def __init__(
        self,
        supabase,
        provider_id=None,
        alias_cache=None,
        default_state_code=DEFAULT_STATE_CODE,
        dry_run: bool = False,
    ):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        # ``None`` opts into the multi-state tournament path. Any string
        # (e.g. ``"WI"``) preserves the original single-state SECL behavior.
        self.default_state_code = default_state_code
        # Per-(state, age_group, gender) candidate cache for _fuzzy_match_team.
        # Without it, each unmatched team in a batch re-issues the same
        # ~200-500-row query for its bucket — dozens to thousands of identical
        # RTTs per import. Populated on first miss; kept fresh via `append`
        # inside ``_create_new_playmetrics_team``. Cache keys include
        # ``state_code=None`` for the tournament path so it doesn't collide
        # with state-scoped entries.
        self._candidate_cache: Dict = {}
        # club_name → resolved (state_code, state) for autocreate. Built lazily
        # on first miss in ``_resolve_state_from_club``. Cached so repeated
        # autocreates within one batch don't re-query teams.
        self._club_state_cache: Dict[str, Optional[Tuple[Optional[str], Optional[str]]]] = {}

    @staticmethod
    def _normalize_gender(gender: Optional[str]) -> Optional[str]:
        """Canonicalize gender to ``"Male"`` or ``"Female"`` for DB + cache keys."""
        if not gender:
            return None
        return "Male" if gender.upper() in ("M", "MALE", "BOYS", "B") else "Female"

    def _match_by_provider_id(
        self, provider_id: str, provider_team_id: str, age_group: Optional[str] = None, gender: Optional[str] = None
    ) -> Optional[Dict]:
        """Skip age_group validation: PlayMetrics teams[].team.id is unique per team.

        Mirror of ``TGSGameMatcher._match_by_provider_id`` — same rationale:
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
            logger.debug(f"[PlayMetrics] No exact direct_id match: {e}")

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
            logger.debug(f"[PlayMetrics] No semicolon-alias match: {e}")

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
            logger.debug(f"[PlayMetrics] No alias map match: {e}")
        return None

    @staticmethod
    def _normalize_pm_tournament_team_name(name: str) -> str:
        """Bring a PlayMetrics tournament team_name closer to PitchRank's DB format.

        Tournament names follow a compact convention: ``{2-digit-year} {gender-word} {tier}``
        (e.g. ``"15 Boys Pre-MLS Academy North | Tan"``, ``"07/08 Boys North Meck
        State Blue"``), while existing ``teams`` rows use 4-digit years and often
        a club abbreviation prefix (e.g. ``"CISC 2015 PRE MLS Academy North
        Tan"``). Without normalization, token-overlap scoring penalizes the same
        team for cosmetic differences. This helper:
          * Slash-token birth-year pairs (``07/08``, ``09/10/11/12``) anywhere
            in the name → 4-digit year for the *oldest* cohort (smaller digit).
            Confirmed pattern in PlayMetrics: every slash-token observed maps
            to a division whose U-cohort matches the older year (e.g. ``07/08``
            → U19, ``10/11`` → U16). U-age slash tokens (``U10/U11``) are NOT
            used by PlayMetrics — only birth-year pairs.
          * Leading single 2-digit cohort token (``00``-``19``) → 4-digit
            (``2000``-``2019``) so birth-year matches become token-aligned.
          * Strips separator characters (``|``, en/em dashes) that fragment tokens.

        Applied only on the tournament path (``default_state_code=None``); the
        SECL flow keeps its original league-format names untouched.
        """
        if not name:
            return name
        s = re.sub(r"\b(\d{2})(?:/\d{2})+\b", r"20\1", name)
        s = re.sub(r"^([01]\d)\b", lambda m: f"20{m.group(1)}", s)
        s = re.sub(r"[|–—]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """State-scoped fuzzy matching with Python-side club gate.

        SQL narrows candidates by ``age_group/gender`` and (when set) by
        ``state_code``. With ``default_state_code=None`` the state filter is
        dropped — the candidate pool grows to all states, the team_name is
        normalized via ``_normalize_pm_tournament_team_name`` (2-digit-year →
        4-digit, separator strip) so PM tournament naming aligns with DB
        format, and the candidate's ``state_code`` is copied onto the provider
        for scoring (otherwise the location component drags every score down
        by 0.10 since PM doesn't expose team state). The ``are_same_club`` gate
        becomes the load-bearing identity check.

        No SQL ``.ilike("club_name", ...)`` prefix filter because that drops
        legitimate candidates whose club_name differs by prefix (e.g.
        ``"Bavarian United"`` vs ``"Bavarian Soccer Club"`` normalize to the
        same canonical club). Within the candidate set, ``are_same_club``
        enforces the club gate, then distinction-based rejection prevents
        within-club variant collisions (Red ≠ Blue, ECNL ≠ ECRL), and finally
        base ``_calculate_match_score`` assigns the weighted score.
        """
        try:
            age_group_normalized = age_group.lower() if age_group else age_group
            gender_normalized = self._normalize_gender(gender)
            club_threshold = MATCHING_CONFIG.get("affinity_club_similarity_threshold", 0.9)

            candidates = self._get_candidates(self.default_state_code, age_group_normalized, gender_normalized)
            if not candidates:
                return None

            tournament_path = self.default_state_code is None
            scoring_team_name = (
                self._normalize_pm_tournament_team_name(team_name) if tournament_path else team_name
            )
            provider_distinctions = extract_distinctions(scoring_team_name)
            provider_team = {
                "team_name": scoring_team_name,
                "club_name": club_name,
                "age_group": age_group,
                "state_code": self.default_state_code,
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
                cand_state = team.get("state_code")
                # Tournament path: copy candidate's state_code so the location
                # component (0.10 weight) doesn't penalize for PM's missing state.
                # SECL path: provider already has its own state_code.
                provider_for_scoring = provider_team
                if tournament_path and cand_state:
                    provider_for_scoring = {**provider_team, "state_code": cand_state}
                candidate = {
                    "team_name": cand_name,
                    "club_name": candidate_club,
                    "age_group": team.get("age_group"),
                    "state_code": cand_state,
                }
                score = self._calculate_match_score(provider_for_scoring, candidate)

                if score >= self.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_match = {
                        "team_id": team["team_id_master"],
                        "team_name": cand_name,
                        "confidence": round(score, 3),
                    }

            return best_match
        except Exception as e:
            logger.error(f"[PlayMetrics] Fuzzy match error: {e}")
            return None

    def _get_candidates(
        self,
        state_code: Optional[str],
        age_group_normalized: Optional[str],
        gender_normalized: Optional[str],
    ) -> list:
        """Return the candidate set for (state, age_group, gender), fetching on first miss.

        ``state_code=None`` skips the state filter entirely (tournament path).
        """
        key = (state_code, age_group_normalized, gender_normalized)
        cached = self._candidate_cache.get(key)
        if cached is not None:
            return cached
        query = (
            self.db.table("teams")
            .select("team_id_master, team_name, club_name, age_group, gender, state_code")
            .eq("age_group", age_group_normalized)
            .eq("gender", gender_normalized)
        )
        if state_code is not None:
            query = query.eq("state_code", state_code)
        result = query.execute()
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
            logger.info(f"[PlayMetrics] No match for '{team_name}' ({age_group}, {gender}), creating new team")
            try:
                new_team_id = self._create_new_playmetrics_team(
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
                logger.info(f"[PlayMetrics] Created: {team_name} ({age_group}, {gender}) -> {new_team_id}")
                return {
                    "matched": True,
                    "team_id": new_team_id,
                    "method": match_method,
                    "confidence": 1.0,
                    "created": True,
                }
            except Exception as e:
                logger.error(f"[PlayMetrics] Error creating team for {team_name}: {e}")

        return base_result

    def _resolve_state_from_club(self, club_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Look up ``(state_code, state)`` for a brand-new team in the multi-state path.

        Returns the unique non-null ``(state_code, state)`` pair if every existing
        ``teams`` row for this ``club_name`` agrees on it. Returns ``(None, None)``
        when the club spans multiple states, has no rows, or has rows but all have
        NULL state — those cases defer state assignment to the review queue or a
        later import that *does* know the state.
        """
        if not club_name:
            return (None, None)
        cached = self._club_state_cache.get(club_name)
        if cached is not None:
            return cached
        try:
            result = (
                self.db.table("teams")
                .select("state_code, state")
                .eq("club_name", club_name)
                .not_.is_("state_code", "null")
                .limit(500)
                .execute()
            )
            rows = list(result.data) if result and result.data else []
        except Exception as e:
            logger.debug(f"[PlayMetrics] club→state lookup failed for '{club_name}': {e}")
            rows = []
        distinct_codes = {row.get("state_code") for row in rows if row.get("state_code")}
        if len(distinct_codes) == 1:
            code = next(iter(distinct_codes))
            # Take the canonical full-name `state` from the first row that has it.
            full = next((row.get("state") for row in rows if row.get("state")), None)
            resolved = (code, full)
        else:
            resolved = (None, None)
        self._club_state_cache[club_name] = resolved
        return resolved

    def _create_new_playmetrics_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
    ) -> str:
        """Create a new row in ``teams`` for a PlayMetrics team.

        State assignment:
          * ``default_state_code`` set (SECL) → use it directly with
            ``STATE_CODE_TO_NAME`` for the ``state`` column.
          * ``default_state_code`` is ``None`` (tournament) → resolve from the
            club's existing rows in ``teams`` (unique non-null state); leave
            both ``state_code`` and ``state`` NULL if the club spans multiple
            states or has no DB signal.

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

        age_group_normalized = age_group.lower() if age_group else age_group
        gender_normalized = self._normalize_gender(gender)

        if self.default_state_code is not None:
            new_state_code = self.default_state_code
            new_state = STATE_CODE_TO_NAME.get(self.default_state_code)
        else:
            new_state_code, new_state = self._resolve_state_from_club(club_name)

        # Deterministic stub UUID for dry-runs — same inputs always yield the
        # same ID so home + away perspectives within a batch resolve to one
        # "team", and repeated dry-runs are idempotent. Real team_id_master
        # uses uuid4 (random) per insert.
        if self.dry_run:
            team_id_master = str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"playmetrics_dry_run|{provider_id}|{provider_team_id}|{team_name}|{age_group_normalized}|{gender_normalized}",
                )
            )
        else:
            team_id_master = str(uuid.uuid4())

        # PlayMetrics: pass raw `team_name` — no clean_team_name intermediate exists.
        # state_code lets resolve_distinction strip state-name tokens
        # (e.g., 'New Hampshire' for clubs whose name doesn't include the state).
        distinction = resolve_distinction(team_name, club_name, new_state_code)

        team_data = {
            "team_id_master": team_id_master,
            "team_name": team_name,
            "club_name": club_name or team_name,
            "age_group": age_group_normalized,
            "gender": gender_normalized,
            "state_code": new_state_code,
            "state": new_state,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": distinction,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if not self.dry_run:
                self.db.table("teams").insert(team_data).execute()
            # Keep the fuzzy-match candidate cache fresh so later rows in the same
            # batch can match against the team we just created. Cache key uses
            # ``self.default_state_code`` so the no-state cache (None, age, gender)
            # gets the new row in tournament mode and the state-scoped cache
            # ("WI", age, gender) gets it in SECL mode. Cached during dry-runs
            # too so the in-batch dedup works the same way.
            key = (self.default_state_code, age_group_normalized, gender_normalized)
            if key in self._candidate_cache:
                self._candidate_cache[key].append({**team_data, "_distinctions": None})
            return team_id_master
        except Exception as e:
            err = str(e).lower()
            if "duplicate key" in err or "23505" in err:
                logger.debug(f"[PlayMetrics] Duplicate key on insert, looking up existing team: {e}")
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
            logger.error(f"[PlayMetrics] Error creating new team: {e}")
            raise
