"""
PlayMetrics-specific game matcher.

Hybrid design:
- Structure mirrors ``TGSGameMatcher`` — JSON-API, integer provider_team_id
  unique per team, so ``_match_by_provider_id`` skips the age-group gate.
- State scoping follows the CSV row: ``scrape_playmetrics_league.py`` writes
  ``state_code`` on every row from the league's governing body, and each game
  is matched and autocreated in that state. A row with no ``state_code``
  falls back to the per-instance ``default_state_code``:
    * ``"WI"`` (default) — state-scoped flow: WI-scoped fuzzy candidates, WI autocreate.
    * ``None`` — tournament flow: no state filter on fuzzy candidates,
      autocreate resolves ``state_code`` from the club's existing rows in
      ``teams`` (unique non-null state) or leaves it NULL when the club spans
      states or is unknown to the DB.
  A row whose ``state_code`` is not a US state is matched the tournament way
  rather than filed under the default.
- Inline autocreate: after base ``_match_team`` exhausts alias / direct_id /
  fuzzy paths without matching, a fresh team row is created so no game is
  dropped.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional

from config.settings import MATCHING_CONFIG
from scripts.scrape_playmetrics_league import _TEAM_U_AGE_RE, derive_team_age_group
from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_normalizer import are_same_club
from src.utils.team_name_utils import (
    DIRECTION_CANONICAL,
    _club_acronym,
    _club_tokens,
    extract_distinctions,
    resolve_distinction,
)
from src.utils.us_states import STATE_CODE_TO_NAME

logger = logging.getLogger(__name__)

DEFAULT_STATE_CODE = "WI"


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
        # State scope of the row being matched. ``match_game_history`` sets it
        # from the row and restores the default afterwards: the base class calls
        # ``_match_team`` without a state, so the scope has to travel on the instance.
        self._row_state_code: Optional[str] = default_state_code

    def match_game_history(self, game_data: Dict) -> Dict:
        self._row_state_code = self._row_state_scope(game_data.get("state_code"))
        try:
            return super().match_game_history(game_data)
        finally:
            self._row_state_code = self.default_state_code

    def _row_state_scope(self, raw) -> Optional[str]:
        """State a row is matched in: its code, the default when blank, unscoped when unknown.

        An unrecognized code is matched unscoped rather than defaulted: the default
        would file the row under the wrong state, which is what this column exists to prevent.
        """
        code = str(raw or "").strip().upper()
        if not code:
            return self.default_state_code
        if code in STATE_CODE_TO_NAME:
            return code
        logger.warning(f"[PlayMetrics] Unrecognized state_code {raw!r} on row; matching unscoped")
        return None

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
            U-age slash tokens (``U10/U11``) are NOT used by PlayMetrics — only
            birth-year pairs.

            NOTE: the older year is what this produces, and it is not the year
            that names the band. A band is U_N = {SEASON+1-N, SEASON-N}, named by
            its YOUNGER year, so ``10/11`` is U16 from 2011 while 2010 alone is
            U17. The comment this replaces cited ``10/11`` → U16 as evidence for
            the older-year rule, which its own arithmetic contradicts; ``07/08``
            → U19 holds under either rule only because 2007 folds back into U19.

            Left as the older year deliberately. This is token normalization for
            fuzzy matching, not cohort derivation — it only has to agree with how
            the DB names the same team, and changing it moves every PlayMetrics
            tournament match. Whether it should switch wants measuring against
            the alias table first, not a comment fix.
          * Leading single 2-digit cohort token (``00``-``19``) → 4-digit
            (``2000``-``2019``) so birth-year matches become token-aligned.
          * Strips separator characters (``|``, en/em dashes) that fragment tokens.

        Applied only when matching unscoped (``state_code=None``: the tournament
        flow, or a row with an unrecognized state); the league flow keeps its
        original league-format names untouched.
        """
        if not name:
            return name
        s = re.sub(r"\b(\d{2})(?:/\d{2})+\b", r"20\1", name)
        s = re.sub(r"^([01]\d)\b", lambda m: f"20{m.group(1)}", s)
        s = re.sub(r"[|–—]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _club_words(*club_names: Optional[str]) -> frozenset:
        """Words and acronyms that name the club rather than the squad."""
        words = set()
        for club in club_names:
            words |= _club_tokens(club)
            acronym = _club_acronym(club)
            if acronym:
                words.add(acronym)
        # A name's directions are read canonically ("NE Surf" -> northeast), so the
        # club's must be too or they never cancel.
        words |= {DIRECTION_CANONICAL[w] for w in words if w in DIRECTION_CANONICAL}
        return frozenset(words)

    @staticmethod
    def _u_age(name: str) -> Optional[int]:
        """The U-age a name writes ("U18G", "BU12", "11uB"), or None."""
        m = _TEAM_U_AGE_RE.search(name or "")
        return int(m.group(1) or m.group(2)) if m else None

    @staticmethod
    def _u_age_cohort(u_age: int) -> str:
        return "u19" if u_age in (18, 19) else f"u{u_age}"

    @staticmethod
    def _without_club_words(name: str, club_words: frozenset) -> str:
        """``name`` minus its club words with the rest sorted, or ``name`` itself when nothing else is left.

        League names usually leave the club out ("U12 Boys National") while
        stored names often lead with it ("Real Colorado National U12B"), and
        the words that remain come in either order ("U16G United" against
        "United U16G"). Sorting them lets the order-sensitive difflib scorer
        see what rapidfuzz's token sort would.
        """
        words = re.split(r"[\s\-_./]+", name)
        kept = [w for w in words if w and w.lower().strip("()[]'*.,") not in club_words]
        return " ".join(sorted(kept, key=str.lower)) or name

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        """State-scoped fuzzy matching with Python-side club gate.

        SQL narrows candidates by ``age_group/gender`` and (when set) by
        ``state_code``. With ``state_code=None`` the state filter is
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

            candidates = self._get_candidates(state_code, age_group_normalized, gender_normalized)
            if not candidates:
                return None

            unscoped = state_code is None
            scoring_team_name = self._normalize_pm_tournament_team_name(team_name) if unscoped else team_name
            provider_distinctions = extract_distinctions(scoring_team_name)
            provider_team = {
                "team_name": scoring_team_name,
                "club_name": club_name,
                "age_group": age_group,
                "state_code": state_code,
            }

            best_match = None
            best_rank = (0.0, 0.0)

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
                # Tier words are never ignored, even inside a club name ("GA Rush"):
                # a tier mismatch refuses the match rather than merging across tiers.
                if provider_distinctions["programs"] != cand_distinctions["programs"]:
                    continue
                if provider_distinctions["team_number"] != cand_distinctions["team_number"]:
                    continue
                club_words = self._club_words(club_name, candidate_club)
                # The team's own state ("CO Rush") and a club's initials read as a
                # state ("LA Surf") are expected in a name; any other state marks a
                # branch ("CSA NH King G" is not "CSA Charlotte King G").
                own_states = {s.lower() for s in (state_code, team.get("state_code")) if s}
                if any(
                    provider_distinctions[key] - ignored != cand_distinctions[key] - ignored
                    for key, ignored in (
                        ("colors", club_words),
                        ("directions", club_words),
                        ("location_codes", club_words),
                        ("squad_words", club_words),
                        ("state_codes", club_words | own_states),
                    )
                ):
                    continue
                # The coach detector can pick a club word ("NE" of "NE Surf"), which
                # names the club, not a coach.
                provider_coach = provider_distinctions.get("coach_name")
                cand_coach = cand_distinctions.get("coach_name")
                if (
                    provider_coach
                    and cand_coach
                    and provider_coach != cand_coach
                    and provider_coach.lower() not in club_words
                    and cand_coach.lower() not in club_words
                ):
                    continue
                # "U18G Black" and "U19G Black" share the u19 board but are two
                # squads. A stored U-age from last season ("BU11" filed under u12)
                # is a stale name, not a different squad, so it does not refuse.
                provider_u_age = self._u_age(team_name)
                cand_u_age = self._u_age(team.get("team_name", ""))
                if (
                    provider_u_age
                    and cand_u_age
                    and provider_u_age != cand_u_age
                    and self._u_age_cohort(cand_u_age) == team.get("age_group")
                ):
                    continue

                cand_name = team.get("team_name", "")
                cand_state = team.get("state_code")
                # Copy the candidate's state_code so the location component
                # (0.10 weight) doesn't penalize for PM's missing state.
                provider_for_scoring = provider_team
                if unscoped and cand_state:
                    provider_for_scoring = {**provider_team, "state_code": cand_state}
                candidate = {
                    "team_name": cand_name,
                    "club_name": candidate_club,
                    "age_group": team.get("age_group"),
                    "state_code": cand_state,
                }
                raw_score = self._calculate_match_score(provider_for_scoring, candidate)
                stripped_score = self._calculate_match_score(
                    {**provider_for_scoring, "team_name": self._without_club_words(scoring_team_name, club_words)},
                    {**candidate, "team_name": self._without_club_words(cand_name, club_words)},
                )
                score = max(raw_score, stripped_score)
                # Stripping can tie a club's duplicate rows ("Polonia U16 Girls Red"
                # and "U16 Girls Red"); the name as written breaks the tie.
                rank = (score, raw_score)

                if score >= self.fuzzy_threshold and rank > best_rank:
                    best_rank = rank
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
        state_code: Optional[str] = None,
    ) -> Dict:
        """Try base matching (alias / direct_id / fuzzy). On miss, autocreate a new team.

        ``state_code`` scopes the fuzzy candidates and the autocreated team; it
        defaults to the row being matched (see ``match_game_history``).

        A row carries one age group, the row team's, and the base class applies
        it to the opponent too. So each team's age is read from its own name the
        way the scraper reads it, and the row's age is only the fallback.
        """
        if state_code is None:
            state_code = self._row_state_code
        age_group = derive_team_age_group(team_name, age_group)
        base_result = super()._match_team(
            provider_id, provider_team_id, team_name, age_group, gender, club_name, state_code=state_code
        )

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
                    state_code=state_code,
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

    def _create_new_playmetrics_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> str:
        """Create a new row in ``teams`` for a PlayMetrics team.

        State assignment writes ``state_code`` only, never the full-name
        ``state`` column: ``assign_team_states`` treats a filled one as
        provider-reported and queues corrections instead of applying them, and
        a league's governing body is per-league evidence, not per-team.

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

        if state_code is not None:
            new_state_code: Optional[str] = state_code
        else:
            new_state_code, _ = self._resolve_state_from_club(club_name)

        team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)

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
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": distinction,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if not self.dry_run:
                self.db.table("teams").insert(team_data).execute()
            # Keep the candidate cache fresh so later rows in the same batch match
            # the team just created -- keyed by the row's state scope, not the
            # resolved state, so it lands in the bucket the next lookup reads.
            # Cached during dry-runs too so in-batch dedup behaves the same.
            key = (state_code, age_group_normalized, gender_normalized)
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
