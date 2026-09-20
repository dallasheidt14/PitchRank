"""
Athletes2Events game matcher (athletes2events.com, one subdomain per host club).

Every team on the platform carries a numeric team id and a state, printed on its
team page, so teams are linked once per event by a roster pass rather than
discovered game by game.  That pass is the only thing that creates teams: the game
import resolves Athletes2Events ids through the aliases it wrote, and a team still
waiting in the review queue has no alias, so its games are held back upstream.

The platform glues its squad marks onto the age, the birth year and the league
tag, which the shared gates would otherwise read as part of one token:

- ``ECNL2`` is ECNL squad 2, and ``ENCL`` is a misspelling of the same league.
- ``RCL 1``, ``RCL-1`` and ``RCL1`` are one squad label.  RCL is a team-name
  distinction here rather than a league, so it is read as a squad code.
- A squad letter runs into the age (``B-U10B``, ``GU10A``) or the birth year
  (``B15C``).  A standalone A-F letter is a squad mark too.

``_presplit`` is handed to the shared gates rather than applied once, because the
provider name, each database candidate name and the club split are canonicalised
separately and all three must read the marks the same way.
"""

import logging
import re
from typing import Dict, Optional, Set, Tuple

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher
from src.models.squad_name_gates import is_same_club
from src.models.tournament_name_gates import (
    TOURNAMENT_TIER_TOKENS,
    canonical_team_name,
    club_from_team_name,
    is_boys,
    squad_marks,
    squads_conflict,
    without_club,
)
from src.tournaments.alias_writer import REVIEW_QUEUE_CLAMP
from src.utils.team_name_utils import resolve_distinction
from src.utils.us_states import STATE_CODE_TO_NAME
from supabase import Client

logger = logging.getLogger(__name__)

_ENCL = re.compile(r"\bENCL\b", re.IGNORECASE)
# ECNL and its squad number: "ECNL2", "ECNL-2" -> "ECNL 2".
_ECNL_SQUAD = re.compile(r"\b(ECNL)[-\s]?(\d)\b", re.IGNORECASE)
# RCL is a squad label, not a league: "RCL 1", "RCL-1", "RCL1" -> one token "RCL1".
_RCL_SQUAD = re.compile(r"\bRCL[-\s]?(\d{1,2})\b", re.IGNORECASE)
# A squad letter glued to the age (B-U10B, GU10A, BU9C) or to the birth year (B15C, G14B).
_LETTER_ON_AGE = re.compile(r"\b[BG]?-?U-?(\d{1,2})([A-F])\b")
_LETTER_ON_YEAR = re.compile(r"\b([BG]?(?:20)?\d{2})([A-F])\b")
# The kit's split: a hyphen is left alone, since _presplit has already collapsed
# the hyphenated squad labels this platform writes.
_MARK_TOKENS = re.compile(r"[\s,()]+")
_SQUAD_LETTER = re.compile(r"[A-F]")
_RCL_LABEL = re.compile(r"RCL\d{1,2}", re.IGNORECASE)

_REVIEW_SUPPRESSED_METHODS = frozenset({"fuzzy_low_confidence", "no_match"})


def _presplit(name: str) -> str:
    """Split what this platform glues together, before anything is read from the name."""
    text = _ENCL.sub("ECNL", name or "")
    text = _ECNL_SQUAD.sub(r"\1 \2", text)
    text = _RCL_SQUAD.sub(r"RCL\1", text)
    text = _LETTER_ON_AGE.sub(r"U\1 \2", text)
    return _LETTER_ON_YEAR.sub(r"\1 \2", text)


def _squad_marks(name: str, boys: bool = False) -> Dict:
    """The shared squad marks plus this platform's own squad codes.

    A standalone A-F letter and an ``RCL<n>`` label each name a squad, and neither
    is a shape :func:`squad_marks` reads.
    """
    marks = squad_marks(name, boys, tier_extra=TOURNAMENT_TIER_TOKENS, pre=_presplit)
    tokens = _MARK_TOKENS.split(_presplit(name or ""))
    labels = {f"squad-{token.lower()}" for token in tokens if _SQUAD_LETTER.fullmatch(token)}
    labels |= {token.lower() for token in tokens if _RCL_LABEL.fullmatch(token)}
    return {**marks, "squad_codes": marks["squad_codes"] | frozenset(labels)}


class Athletes2EventsGameMatcher(GameHistoryMatcher):
    """Gated fuzzy matching scoped to the team page's state; creates teams only when registering.

    In ``registration_mode`` a team with no candidate is created under its
    Athletes2Events id, while a 0.75-0.90 candidate (or a birth-year conflict)
    keeps its review row and creates nothing.
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
        # The club as the team page wrote it, for the team being matched. ``_match_team``
        # sets it and restores None afterwards: the base class calls ``_fuzzy_match_team``
        # with the canonical club only, so the written form has to travel on the instance.
        self._written_club: Optional[str] = None

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
        return super()._normalize_team_name(canonical_team_name(name, _presplit))

    def _match_by_provider_id(
        self,
        provider_id: str,
        provider_team_id: str,
        age_group: Optional[str] = None,
        gender: Optional[str] = None,
    ) -> Optional[Dict]:
        """Resolve an alias without re-checking the age, as TGS and SincSports do.

        An Athletes2Events team id names one team across the whole platform, so an
        approved alias on it is unambiguous and the age adds nothing. Keeping the
        base check costs real games: a team playing up carries its opponent's age on
        the importer's row, the older side fails the check, and the game inserts with
        that side NULL -- which the ranking engine then drops entirely, because it
        selects only games with both master ids set. Modular11 keeps the check for
        the opposite reason: its provider id is a club id reused across age groups.
        """
        return super()._match_by_provider_id(provider_id, provider_team_id, None, None)

    def _without_club(self, name: str, club: Optional[str]) -> str:
        """Drop the club from a name, as the team page writes it and as PitchRank stores it.

        Both spellings have to go, and from both sides of the comparison. This host
        writes "Crossfire Select", which PitchRank stores as "Crossfire Select Soccer
        Club"; the stored form does not occur in either name, so stripping it alone
        leaves "Select" behind — and "select" is a tier token. A stored row whose own
        name omits the word then reads as a different tier and the right candidate is
        rejected, while stripping only the written form inverts that onto the rows
        whose names carry it.
        """
        return without_club(without_club(name, self._written_club), club)

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
        supplies one, and a game import resolves Athletes2Events ids through aliases
        alone. A failed query raises rather than reading as "no candidate", which
        would create a duplicate.
        """
        if not state_code:
            return None
        provider_team_name = canonical_team_name(team_name, _presplit)
        provider_club_name = club_name or club_from_team_name(team_name, _presplit)
        boys = is_boys(gender)
        provider_marks = _squad_marks(self._without_club(provider_team_name, provider_club_name), boys)
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
            candidate_name = canonical_team_name(candidate_name_raw, _presplit)
            name_club = club_from_team_name(candidate_name_raw, _presplit)

            # A stored club_name is often the long form ("Crossfire Select Soccer
            # Club") while the row's own team name says "XF", so either may vouch
            # for the club. A provider club neither agrees with declines: a
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

            candidate_marks = _squad_marks(self._without_club(candidate_name, club_in_name), boys)
            if squads_conflict(provider_marks, candidate_marks):
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
        written_club: Optional[str] = None,
    ) -> Dict:
        """Adds ``created`` to every result, ``review`` to one left in the review queue, and
        ``relinked`` to one whose team row already carried this Athletes2Events id.

        ``written_club`` is the club as the team page spells it, where that differs
        from the name PitchRank stores; the squad gates need both (see
        :meth:`_without_club`). ``club_name`` stays the stored form, so it is what a
        created team is filed under.
        """
        self._written_club = written_club
        try:
            base_result = super()._match_team(
                provider_id, provider_team_id, team_name, age_group, gender, club_name, state_code=state_code
            )
        finally:
            self._written_club = None
        if base_result.get("matched"):
            return {**base_result, "created": False}
        if base_result.get("method") == "fuzzy_review":
            return {**base_result, "created": False, "review": True}
        if not (self.registration_mode and state_code and team_name and age_group and gender):
            return {**base_result, "created": False}

        new_team_id, was_created = self._create_new_athletes2events_team(
            team_name=team_name,
            club_name=club_name or club_from_team_name(team_name, _presplit),
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
        logger.info(f"[A2E] Created: {team_name} ({age_group}, {gender}, {state_code}) -> {new_team_id}")
        return {
            "matched": True,
            "team_id": new_team_id,
            "method": "direct_id",
            "confidence": 1.0,
            "created": was_created,
            "relinked": not was_created,
        }

    def _create_new_athletes2events_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """A team already carrying this Athletes2Events id is returned with ``was_created`` False."""
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
                # PostgREST raises PGRST116 on a zero-row .single(), which is the
                # normal path for a team this run has never seen.
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
            "gender": "Male" if is_boys(gender) else "Female",
            "state_code": state_code,
            "state": STATE_CODE_TO_NAME.get(state_code) if state_code else None,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": resolve_distinction(clean_team_name, club_name, state_code),
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master, True
