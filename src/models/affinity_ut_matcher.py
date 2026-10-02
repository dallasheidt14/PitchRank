"""
Affinity Sports UT game matcher - Utah Youth Soccer (uysa.sportsaffinity.com).

UYSA's pages follow the Oregon conventions, so the OR matcher applies with Utah's
default state and these changes for how Utah writes team names:

- Bands, glued U-ages and league tags ('13/14B', 'U12B', '(SFC)') are rewritten
  before the OR normalizer reads a name.
- The club is the words before the first age mark, less trailing coach initials
  ('Avalanche U13B Black DW' is 'Avalanche').
- Squads of one club are told apart by coach initials anywhere after the club ('MH Black'
  against 'ZZ Black', 'White JN' against 'White MC') and by a squad number, even one
  present on one side only. When two stored squads tie for best, neither is taken.
- A stored team is first looked for by squad key (the name less its club, cohort,
  gender and league words), the rule the squad-key duplicate finder pairs rows by. Only
  a single live stored team that also passes the cohort, league, tier, gender and squad
  checks is taken; otherwise the OR fuzzy match runs. The duplicate finder's game
  screens cannot apply: a team being matched has no stored games yet.
- A club is asked for its state only within Utah and its neighbours. A generic club
  word can name a club elsewhere ('Avalanche' also names a Virginia club).
"""

import logging
import re
from collections import Counter
from typing import Dict, Optional, Tuple

from scripts.find_cross_provider_duplicates import stated_gender
from scripts.find_squad_key_duplicates import (
    LEAGUE_WORDS,
    cohorts_compatible,
    is_protected_division,
    leagues_conflict,
    squad_key,
)
from src.models.affinity_or_matcher import (
    AffinityORGameMatcher,
    _normalize_club_for_affinity,
    _normalize_for_affinity_or,
)
from src.models.squad_name_gates import extract_lane_number, extract_tier_tokens, is_same_club, tiers_conflict
from src.utils.placeholder_clubs import is_placeholder_club
from src.utils.us_states import STATE_CODE_TO_NAME

logger = logging.getLogger(__name__)

_REGION = ("UT", "ID", "WY", "NV", "CO", "AZ")

_BAND = re.compile(r"\b[BG]?(?:20)?(\d{2})[/-](?:20)?(\d{2})[BG]?\b", re.IGNORECASE)
_GLUED_BAND = re.compile(r"\b[BG](\d{2})(\d{2})\b", re.IGNORECASE)
# Registration tags UYSA appends after the squad: the Salt Lake league and an independent team.
_LEAGUE_TAG = re.compile(r"\(\s*(?:SFC|SLFC|IND\.?)\s*\)|\bIND\b", re.IGNORECASE)
_UT_GLUED_U_AGE = re.compile(r"\b[BG]?U\d{1,2}(?:/U?\d{1,2})?[BG]?\b", re.IGNORECASE)
_AGE_MARK = re.compile(
    r"(?:\b|(?<=-))(?:[BG]?U-?\d{1,2}[BG]?|[BG]?(?:20)?\d{2}(?:[/-]\d{2,4})?[BG]?|[BG]\d{4})(?=\b|-|$)",
    re.IGNORECASE,
)
# Wildcards to PostgREST's ilike; a club carrying one cannot be looked up as itself.
_LIKE_WILDCARDS = re.compile(r"[%_*\\]")
_INITIALS = re.compile(r"^[A-Z]{2,4}$")
# Region state codes stay readable as initials (a coach 'NV' or 'CO' is common); only UT, which
# Utah club names carry ('City SC UT'), is excluded.
_NOT_INITIALS = (
    frozenset(w.upper() for w in LEAGUE_WORDS)
    | frozenset(
        {
            "UT", "FC", "SC", "AC", "USA", "AD", "HD", "EA", "ECNL", "PRE", "ASPIRE", "HSP", "IND", "SFC", "SLFC",
            "BOYS", "RED", "BLUE", "GOLD", "GREY", "GRAY", "PINK", "TEAL", "NAVY", "BLK", "WHT", "II", "III", "IV",
        }
    )
)  # fmt: skip


def _one_year_band(match: re.Match) -> bool:
    return abs(int(match.group(1)) - int(match.group(2))) == 1


def _younger_year(match: re.Match) -> str:
    return f"20{max(int(match.group(1)), int(match.group(2))):02d}"


def _without_tags_respelling_glued(name: str, respell) -> str:
    """League tags dropped, and each one-year glued band ('B1314') passed through ``respell``."""
    n = _LEAGUE_TAG.sub(" ", name or "")
    return _GLUED_BAND.sub(lambda m: respell(m) if _one_year_band(m) else m.group(0), n)


def _rewrite_bands(name: str) -> str:
    """Every one-year band as its younger year ('13/14B' and 'B1314' are both '2014'), league tags dropped."""
    n = _without_tags_respelling_glued(name, _younger_year)
    return _BAND.sub(lambda m: _younger_year(m) if _one_year_band(m) else m.group(0), n)


def _squad_key_text(name: str) -> str:
    """A name as the squad-key reader takes it: league tags dropped and 'B1314' spelled as the band '13/14'.

    Other bands stay as written, because the reader treats a band as one exact cohort
    and a bare year as two.
    """
    return _without_tags_respelling_glued(name, lambda m: f"{m.group(1)}/{m.group(2)}")


def _normalize_for_affinity_ut(name: str) -> str:
    """Rewrite Utah's spellings into the forms the OR normalizer reads.

    A band becomes its younger year, the year it is named by; left alone, the OR
    rewrite of '14B' to '2014' turns '13/14B' into '13/2014'. A glued U-age ('U12B',
    'BU18/19') is dropped as OR drops a bare 'U12'.
    """
    return _normalize_for_affinity_or(_UT_GLUED_U_AGE.sub(" ", _rewrite_bands(name)))


def _is_coach_initials(token: str) -> bool:
    """Two to four capitals that are not a league, tier, colour or club word: 'JN', 'MH', 'WSL'."""
    return bool(_INITIALS.match(token)) and token not in _NOT_INITIALS


def _name_tokens(name: str) -> list:
    return [t.strip("()[].,*'") for t in _squad_key_text(name).replace("-", " ").split()]


def _club_before_age(team_name: str) -> Optional[str]:
    """The words before a name's first age mark, less trailing coach initials; None when it carries no age."""
    mark = _AGE_MARK.search(team_name or "")
    if not mark:
        return None
    return _without_coach_initials(team_name[: mark.start()]) or None


def _without_coach_initials(text: str) -> str:
    """'Impact PT' -> 'Impact', 'Strikers BB 14' -> 'Strikers'; a lone token such as 'NUU' is kept."""
    words = text.strip(" -–—").split()
    while len(words) > 1 and (words[-1].isdigit() or _is_coach_initials(words[-1].strip("()[].,*'"))):
        words.pop()
    return " ".join(words).strip(" -–—")


class AffinityUTGameMatcher(AffinityORGameMatcher):
    """Affinity UT matcher: the OR matcher with Utah's default state and name conventions."""

    state_code = "UT"
    state_name = "Utah"
    refuse_tied_best = True

    def __init__(self, supabase, provider_id=None, alias_cache=None, dry_run=False):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self._ut_club_states: Dict[str, Counter] = {}

    def _club_states(self, club_name: Optional[str]) -> Counter:
        """How many of the club's stored teams sit in each state of the region."""
        if not club_name or is_placeholder_club(club_name) or _LIKE_WILDCARDS.search(club_name):
            return Counter()
        if club_name not in self._ut_club_states:
            counts: Counter = Counter()
            try:
                rows = (
                    self.db.table("teams")
                    .select("state_code")
                    .ilike("club_name", club_name)
                    .in_("state_code", list(_REGION))
                    .limit(1000)
                    .execute()
                )
                counts = Counter(r["state_code"] for r in rows.data or [] if r.get("state_code"))
            except Exception as e:  # a read failure must not block matching
                logger.debug(f"[AffinityUT] Club state lookup failed for {club_name!r}: {e}")
            self._ut_club_states[club_name] = counts
        return self._ut_club_states[club_name]

    def _club_state_plurality(self, club_name: Optional[str]) -> Optional[str]:
        counts = self._club_states(club_name)
        return counts.most_common(1)[0][0] if counts else None

    def _state_for_new_team(self, club_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """The region state every stored team of the club agrees on; NULL when they disagree; else Utah."""
        counts = self._club_states(club_name)
        if len(counts) == 1:
            code = next(iter(counts))
            return code, STATE_CODE_TO_NAME.get(code)
        if counts:
            return None, None
        return self.state_code, self.state_name

    def _normalize_provider_name(self, name: str) -> str:
        return _normalize_for_affinity_ut(name)

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        stored = self._squad_key_match(team_name, age_group, gender, club_name)
        if stored:
            return {"team_id": stored["team_id_master"], "team_name": stored["team_name"], "confidence": 0.95}
        return super()._fuzzy_match_team(team_name, age_group, gender, club_name)

    def _squad_key_match(self, team_name: str, age_group: str, gender: str, club_name: Optional[str]) -> Optional[Dict]:
        """The one live stored team of this club whose squad key, cohort, league, tier, gender and squad agree.

        A competitive tier named on one side only is a difference, as in the OR gates: the key drops league
        words, so 'C Santos ECNL RL' and 'C Santos' would otherwise share one.
        """
        club = _normalize_club_for_affinity(self._club_for(team_name, club_name))
        if not club or is_protected_division(team_name):
            return None
        search_state = self._state_for_club(club)
        provider_text = _squad_key_text(team_name)
        key = squad_key(provider_text, club, search_state)
        if not key:
            return None
        try:
            rows = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name")
                .eq("age_group", age_group.lower())
                .eq("gender", gender)
                .eq("state_code", search_state)
                .eq("is_deprecated", False)
                .execute()
            ).data or []
        except Exception as e:  # a read failure falls back to the fuzzy match
            logger.debug(f"[AffinityUT] Squad-key lookup failed for {team_name!r}: {e}")
            return None
        hits = []
        for row in rows:
            stored_name = row.get("team_name") or ""
            stored_text = _squad_key_text(stored_name)
            stated = stated_gender(stored_name)
            if (
                self._same_club_as_candidate(club, row.get("club_name") or "", stored_name)
                and squad_key(stored_text, row.get("club_name") or self._club_for(stored_name, None), search_state)
                == key
                and cohorts_compatible(provider_text, stored_text)
                and not leagues_conflict(team_name, stored_name)
                and not tiers_conflict(extract_tier_tokens(team_name), extract_tier_tokens(stored_name))
                and not is_protected_division(stored_name)
                and stated in (None, gender)
                and not self._squads_conflict(team_name, stored_name)
            ):
                hits.append(row)
        return hits[0] if len(hits) == 1 else None

    def _club_for(self, team_name: Optional[str], club_name: Optional[str]) -> Optional[str]:
        if club_name:
            return club_name
        if not team_name:
            return None
        return _club_before_age(team_name) or _without_coach_initials(_LEAGUE_TAG.sub(" ", team_name)) or None

    def _same_club_as_candidate(self, provider_club: str, candidate_club: str, candidate_name: str) -> bool:
        """Also accept the club a stored name starts with: 'Avalanche U13B' is stored under 'Utah Avalanche'."""
        if super()._same_club_as_candidate(provider_club, candidate_club, candidate_name):
            return True
        named_club = self._club_for(candidate_name, None)
        return bool(named_club) and is_same_club(provider_club, named_club, self._affinity_club_similarity_threshold)

    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Score a stored team under the club its name starts with, not its stored club field.

        The candidate name arrives normalized, its U-age gone, so the club-before-age rule
        cannot read it; a prefix test can ('Avalanche Black DW' under 'Utah Avalanche').
        """
        provider_club = provider_team.get("club_name")
        if provider_club and (candidate.get("team_name") or "").lower().startswith(provider_club.lower()):
            candidate = {**candidate, "club_name": provider_club}
        return super()._calculate_match_score(provider_team, candidate)

    def _squad_marks(self, team_name: str) -> Tuple[frozenset, Optional[str]]:
        """(coach initials anywhere after the club, squad number read with the initials removed)."""
        club_words = {w.upper() for w in (self._club_for(team_name, None) or "").split()}
        tokens = _name_tokens(team_name)
        initials = frozenset(t for t in tokens if t.upper() not in club_words and _is_coach_initials(t))
        rest = " ".join(t for t in tokens if t not in initials)
        return initials, extract_lane_number(_normalize_for_affinity_ut(rest))

    def _squads_conflict(self, provider_name: str, candidate_name: str) -> bool:
        """Different coach initials, or different squad numbers, one-sided included ('Black SL' vs 'Black SL 2')."""
        provider_initials, provider_lane = self._squad_marks(provider_name)
        candidate_initials, candidate_lane = self._squad_marks(candidate_name)
        if provider_initials and candidate_initials and provider_initials != candidate_initials:
            return True
        return provider_lane != candidate_lane
