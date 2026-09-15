"""
Soccer Events Group game matcher (soccereventsgroup.com, on the 3 Step Sports platform).

SEG registers every tournament team with a numeric team id, a home town and a state,
so teams are linked once per event by a roster pass rather than discovered game by
game.  That pass is the only thing that creates teams: the game import resolves SEG
ids through the aliases it wrote, and a team still waiting in the review queue has
no alias, so its games are held back upstream rather than matched here.

- Candidates are scoped to the state SEG registered the team in, or to no state.
- Names glue the gender letter onto the age ("U15G", "BU08", "14uG") and put the
  age first ("U12G FC LAKE COUNTY 14/15 SELECT"); the shared club extractor reads
  either as part of the club, so names are canonicalised before anything is read
  from them.
- Squads of one club are told apart by colour, direction, squad number, squad
  code (N1, S2) and tier, read from the name with its club removed where the
  name carries it.
  ``extract_team_variant`` is not used: its coach-name fallback reads "ECNL-RL"
  and the "/13" of "G2012/13" as coach names.
"""

import logging
import re
from typing import Dict, Optional, Set, Tuple

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher, extract_club_from_team_name
from src.models.squad_name_gates import extract_tier_tokens, is_same_club, tiers_conflict
from src.tournaments.alias_writer import REVIEW_QUEUE_CLAMP
from src.utils.team_name_utils import extract_distinctions, resolve_distinction
from src.utils.us_states import STATE_CODE_TO_NAME
from supabase import Client

logger = logging.getLogger(__name__)

# A U-age written with the gender letter glued to either side (GU14, U14G, BU08),
# the number-first form (14U, 14uG), or run into the next token (U15N1).
_GLUED_U_AGE = re.compile(r"\b[BG]?U0?(\d{1,2})(?:[BG]\b|\b|(?=[A-Z]))|\b0?(\d{1,2})U[BG]?\b", re.IGNORECASE)
# Dotted initials ("S.C.", "F.C."): a lone "S" is read as the direction South.
_DOTTED_INITIALS = re.compile(r"\b([A-Z])\.([A-Z])\.?", re.IGNORECASE)
# One tier, several spellings. Left apart, the tier gate reads them as different
# tiers and the squad is created again beside its existing row.
_TIER_SPELLINGS = (
    (re.compile(r"\bgirls\s+academy\b", re.IGNORECASE), "GA"),
    (re.compile(r"\becnl\s*/\s*rl\b", re.IGNORECASE), "ECNL RL"),
    (re.compile(r"\bpre\s*[-/]?\s*(ecnl|ga|mls)\b", re.IGNORECASE), r"Pre-\1"),
)
_LEADING_U_AGE = re.compile(r"^U\d{1,2}\s+", re.IGNORECASE)
# No trailing \b: the gender letter is often glued on ("15/16B").
_TWO_DIGIT_BAND = re.compile(r"\b\d{2}/\d{2}(?!\d)")
_GENDER_WORD = re.compile(r"\b(?:boys?|girls?)\b", re.IGNORECASE)
_NAME_TOKENS = re.compile(r"[\s/\-(),.]+")
# A squad code such as N1 or S2. U, B and G are left out: U14, B14 and G15 are ages.
_SQUAD_CODE = re.compile(r"^[ac-fh-tv-z]\d{1,2}$")

# Tiers the shared tier set does not carry. "Pre-ECNL" and "Pre-GA" are a club's
# development squads, "GA Aspire" is Girls Academy's second tier, and EA, AD and
# HD are separate MLS NEXT tiers.
_SEG_TIER_TOKENS = frozenset({"pre", "aspire", "ea", "ad", "hd"})

_REVIEW_SUPPRESSED_METHODS = frozenset({"fuzzy_low_confidence", "no_match"})


def canonical_team_name(name: Optional[str]) -> str:
    """Collapse NBSP, whitespace, dotted initials and tier spellings; write every U-age as ``U<n>``.

    'AFC Union U15G N1' and 'AFC Union U15N1' both become 'AFC Union U15 N1'.
    """
    if not name:
        return ""
    text = _DOTTED_INITIALS.sub(r"\1\2", " ".join(name.replace("\xa0", " ").split()))
    for pattern, replacement in _TIER_SPELLINGS:
        text = pattern.sub(replacement, text)
    text = _GLUED_U_AGE.sub(lambda m: f" U{int(m.group(1) or m.group(2))} ", text)
    return " ".join(text.split())


def club_from_team_name(name: Optional[str]) -> Optional[str]:
    """The club a SEG team name names, e.g. 'U12G FC LAKE COUNTY 14/15 SELECT' -> 'FC LAKE COUNTY'."""
    canonical = _LEADING_U_AGE.sub("", canonical_team_name(name))
    stop = len(canonical)
    for pattern in (_TWO_DIGIT_BAND, _GENDER_WORD):
        match = pattern.search(canonical)
        if match:
            stop = min(stop, match.start())
    return extract_club_from_team_name(canonical[:stop].strip() or canonical)


def without_club(name: str, club: Optional[str]) -> str:
    """So a club's own words ("Blue Fire") are not read as squad marks."""
    if not club:
        return name
    return " ".join(re.sub(re.escape(club), " ", name, count=1, flags=re.IGNORECASE).split())


def seg_tier_tokens(name: str) -> frozenset:
    """Shared tier tokens plus the SEG-only ones.

    "MLS NEXT AD" names the AD tier, so an explicit AD or HD absorbs the "mls"
    beside it; a bare "MLS NEXT" keeps it and stays apart from either.
    """
    words = {w.lower() for w in _NAME_TOKENS.split(name or "") if w}
    tiers = extract_tier_tokens(name) | (words & _SEG_TIER_TOKENS)
    return tiers - {"mls"} if tiers & {"ad", "hd"} else tiers


def squad_marks(name: str) -> Dict:
    """The parts of a canonical, club-free name that tell two squads of one club apart."""
    distinctions = extract_distinctions(name)
    return {
        "colors": distinctions["colors"],
        "directions": distinctions["directions"],
        "team_number": distinctions["team_number"],
        "squad_codes": frozenset(t for t in (w.lower() for w in _NAME_TOKENS.split(name)) if _SQUAD_CODE.match(t)),
        "tiers": seg_tier_tokens(name),
    }


def squads_conflict(provider: Dict, candidate: Dict) -> bool:
    """True when the marks say two different squads.

    A squad number or squad code counts only when both names carry one: "FC Pride
    Pre-ECNL" beside "FC Pride Pre-ECNL 2" is not evidence either way.
    """
    if provider["colors"] != candidate["colors"] or provider["directions"] != candidate["directions"]:
        return True
    if provider["team_number"] and candidate["team_number"] and provider["team_number"] != candidate["team_number"]:
        return True
    if provider["squad_codes"] and candidate["squad_codes"] and provider["squad_codes"] != candidate["squad_codes"]:
        return True
    return tiers_conflict(provider["tiers"], candidate["tiers"])


class SoccerEventsGroupGameMatcher(GameHistoryMatcher):
    """Gated fuzzy matching scoped to SEG's registered state; creates teams only when registering.

    In ``registration_mode`` a team with no candidate is created under its SEG id,
    while a 0.75-0.90 candidate (or a birth-year conflict) keeps its review row and
    creates nothing.
    """

    def __init__(
        self,
        supabase: Client,
        provider_id: Optional[str] = None,
        alias_cache: Optional[Dict] = None,
        registration_mode: bool = False,
        dry_run: bool = False,
    ):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self.registration_mode = registration_mode
        self._club_similarity_threshold = MATCHING_CONFIG.get("affinity_club_similarity_threshold", 0.9)
        # A later team of the event is never matched onto a team created this run: the
        # dry-run preview that decided what to create could not see it.
        self._created_this_run: Set[str] = set()

    def _create_review_queue_entry(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        provider_team_name: str,
        suggested_master_team_id: Optional[str],
        confidence_score: float,
        match_details: Dict,
    ):
        """Skip the review row for a team the roster pass is about to create, and clamp the rest.

        The queue's CHECK refuses a confidence of 0.90 or more, and a birth-year
        conflict is queued at whatever the match scored.
        """
        if self.registration_mode and match_details.get("match_method") in _REVIEW_SUPPRESSED_METHODS:
            return None
        return super()._create_review_queue_entry(
            provider_id=provider_id,
            provider_team_id=provider_team_id,
            provider_team_name=provider_team_name,
            suggested_master_team_id=suggested_master_team_id,
            confidence_score=min(confidence_score, float(REVIEW_QUEUE_CLAMP)),
            match_details=match_details,
        )

    def _normalize_team_name(self, name: str) -> str:
        return super()._normalize_team_name(canonical_team_name(name))

    def _fetch_candidates(self, age_group: str, gender: str, state_code: str) -> list:
        rows: list = []
        page_size = 1000
        offset = 0
        while True:
            page = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name, age_group, gender, state_code")
                .eq("age_group", age_group)
                .eq("gender", gender)
                .eq("is_deprecated", False)
                .or_(f"state_code.eq.{state_code},state_code.is.null")
                .order("team_id_master")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            data = page.data or []
            rows.extend(data)
            if len(data) < page_size:
                return rows
            offset += page_size

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        """Club and squad gates, then score.

        Returns None without querying when no state is given: only the roster pass
        supplies one, and a game import resolves SEG ids through aliases alone. A
        failed query raises rather than reading as "no candidate", which would
        create a duplicate.
        """
        if not state_code:
            return None
        provider_team_name = canonical_team_name(team_name)
        provider_club_name = club_name or club_from_team_name(team_name)
        provider_marks = squad_marks(without_club(provider_team_name, provider_club_name))
        provider_team = {
            "team_name": provider_team_name,
            "club_name": provider_club_name,
            "age_group": age_group,
            "state_code": state_code,
        }
        ecnl_boost = 0.05 if provider_marks["tiers"] & {"ecnl", "rl"} else 0.0

        scored = []
        for team in self._fetch_candidates(age_group.lower(), gender, state_code):
            if team["team_id_master"] in self._created_this_run:
                continue
            candidate_name_raw = team.get("team_name") or ""
            candidate_name = canonical_team_name(candidate_name_raw)
            name_club = club_from_team_name(candidate_name_raw)

            # A stored club_name is often the long form ("Chicago Fire Youth SC
            # (CFYSC)") while the row's own team name says "CFYSC", so either may
            # vouch for the club. A provider club neither agrees with declines: a
            # duplicate is recoverable by merge, a wrong match is not.
            matched_club = None
            club_in_name = None
            if provider_club_name:
                if name_club and is_same_club(provider_club_name, name_club, self._club_similarity_threshold):
                    matched_club = club_in_name = name_club
                elif team.get("club_name") and is_same_club(
                    provider_club_name, team["club_name"], self._club_similarity_threshold
                ):
                    matched_club = team["club_name"]
                else:
                    continue

            if squads_conflict(provider_marks, squad_marks(without_club(candidate_name, club_in_name))):
                continue

            candidate = {
                "team_name": candidate_name,
                "club_name": matched_club or team.get("club_name"),
                "age_group": team.get("age_group"),
                "state_code": team.get("state_code"),
            }
            score = min(1.0, self._calculate_match_score(provider_team, candidate) + ecnl_boost)
            tiebreak = (
                1 if provider_team_name.lower() == candidate_name.lower() else 0,
                1 if team.get("state_code") == state_code else 0,
            )
            if score >= self.fuzzy_threshold:
                scored.append(((score, tiebreak), team["team_id_master"], candidate_name_raw))
        if not scored:
            return None
        scored.sort(key=lambda entry: entry[0], reverse=True)
        (best_rank, team_id, name), *rest = scored
        confidence = round(best_rank[0], 3)
        if rest and rest[0][0] == best_rank:
            # Two different teams are equally good; which one wins would be the
            # candidate order's call, so the choice goes to review instead.
            confidence = min(confidence, float(REVIEW_QUEUE_CLAMP))
        return {"team_id": team_id, "team_name": name, "confidence": confidence}

    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Add the club boost; the caller only scores a candidate whose club it has matched."""
        score = super()._calculate_match_score(provider_team, candidate)
        if provider_team.get("club_name") and candidate.get("club_name"):
            score = min(1.0, score + MATCHING_CONFIG.get("club_variant_match_boost", 0.35))
        return score

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
        """Adds ``created`` to every result, ``review`` to one left in the review queue, and
        ``relinked`` to one whose team row already carried this SEG id and got its alias rewritten."""
        base_result = super()._match_team(
            provider_id, provider_team_id, team_name, age_group, gender, club_name, state_code=state_code
        )
        if base_result.get("matched"):
            return {**base_result, "created": False}
        if base_result.get("method") == "fuzzy_review":
            return {**base_result, "created": False, "review": True}
        if not (self.registration_mode and state_code and team_name and age_group and gender):
            return {**base_result, "created": False}

        new_team_id, was_created = self._create_new_soccereventsgroup_team(
            team_name=team_name,
            club_name=club_name or club_from_team_name(team_name),
            age_group=age_group,
            gender=gender,
            provider_id=provider_id,
            provider_team_id=provider_team_id,
            state_code=state_code,
        )
        self._created_this_run.add(new_team_id)
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
        logger.info(f"[SEG] Created: {team_name} ({age_group}, {gender}, {state_code}) -> {new_team_id}")
        return {
            "matched": True,
            "team_id": new_team_id,
            "method": "direct_id",
            "confidence": 1.0,
            "created": was_created,
            "relinked": not was_created,
        }

    def queue_for_review(
        self,
        provider_id: str,
        provider_team_id: str,
        team_name: str,
        age_group: str,
        gender: str,
        state_code: str,
        reason: str,
    ) -> Dict:
        """Queue a registration for review with its best candidate, linking and creating nothing."""
        suggestion = self._fuzzy_match_team(team_name, age_group, gender, state_code=state_code)
        confidence = suggestion["confidence"] if suggestion else self.review_threshold
        self._create_review_queue_entry(
            provider_id=provider_id,
            provider_team_id=provider_team_id,
            provider_team_name=team_name,
            suggested_master_team_id=suggestion["team_id"] if suggestion else None,
            confidence_score=confidence,
            match_details={
                "age_group": age_group,
                "gender": gender,
                "club_name": None,
                "match_method": "name_age_review",
                "reason": reason,
            },
        )
        return {
            "matched": False,
            "team_id": None,
            "method": "name_age_review",
            "confidence": confidence,
            "review": True,
        }

    def _create_new_soccereventsgroup_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """A team already carrying this SEG id is returned with ``was_created`` False, not inserted again."""
        if provider_id and provider_team_id:
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
                    return existing.data["team_id_master"], False
            except Exception:
                pass

        team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)
        clean_team_name = " ".join(team_name.replace("\xa0", " ").split())
        if club_name and clean_team_name.lower().startswith(club_name.lower()):
            clean_team_name = clean_team_name[len(club_name) :].strip(" -–—") or clean_team_name

        team_data = {
            "team_id_master": team_id_master,
            "team_name": clean_team_name,
            "club_name": club_name or clean_team_name,
            "age_group": age_group.lower(),
            "gender": "Male" if gender.upper() in ("M", "MALE", "BOYS", "B") else "Female",
            "state_code": state_code,
            "state": STATE_CODE_TO_NAME.get(state_code) if state_code else None,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": resolve_distinction(clean_team_name, club_name, state_code),
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master, True
