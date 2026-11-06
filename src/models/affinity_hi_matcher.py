"""
Affinity Sports HI game matcher - Hawaii Youth Soccer's Oahu League (hysa.sportsaffinity.com).

HYSA's pages follow the Oregon conventions and its names the Utah ones closely
enough that the UT matcher applies, with Hawaii's state and these changes for how
HYSA writes team names:

- Every name starts with the team's own age and gender ('13UB - HSC Bulls 13/14B - II').
  The label is dropped before a name's words are compared; only the age checks read it.
- Clubs are written in a short form the stored rows spell out ('HSC Bulls' is stored as
  'Honolulu Bulls Soccer Club'), sometimes after a band ('13/14G Surf Hawaii Academy I').
- Squads of one club are numbered in Roman numerals ('- I', '- II', 'Academy I'), which are
  read as squad numbers, and named by words no gate reads ('RUSH Azul', 'Leahi Maile', Albion's
  'HNL' and 'WND'), so any difference in a squad's own words is a different squad. That rule
  replaces Utah's coach initials and squad numbers, which those words already include.
- U18 and U19 teams share the u19 board, so two names stating different U-ages are different
  squads there even when their words agree.
- A club is asked for its state only in Hawaii.
"""

import re
from typing import Optional

from scripts.decide_team_merges import label_numbers
from src.models.affinity_ut_matcher import AffinityUTGameMatcher, _normalize_for_affinity_ut
from src.models.yssl_matcher import roman_to_digits
from src.utils.team_name_utils import NOISE_WORDS

_AGE_LABEL = re.compile(r"^\s*\d{1,2}U[BG]\s*-\s*", re.IGNORECASE)

# How HYSA writes a club, against the name PitchRank stores it under; each pairing is
# read from stored Hawaii rows, which include teams carrying HYSA's own names.
_HI_CLUBS = {
    "HSC Bulls": "Honolulu Bulls Soccer Club",
    "BI Rush": "BI Rush",
    "RUSH": "Hawaii Rush",
    "Surf Hawaii": "Hawaii Surf Soccer Club",
    "Leahi Na Koa": "Leahi Soccer Club",
    "Leahi": "Leahi Soccer Club",
    "BVB IA Hawaii": "BVB International Academy Hawaii",
    "808 FC": "808 Futbol Club",
    "808FC": "808 Futbol Club",
    "Universal SC": "Universal Soccer League",
    "ALBION SC Hawaii": "ALBION SC Hawaii",
    "FC Hawaii": "FC Hawaii",
    "Inter Ohana CF": "Inter Ohana CF",
    "Hawaii United FC": "Hawaii United FC",
    "Ballistic": "Ballistic Soccer Hawaii",
    "Hoomau": "Ho'omau FC",
    "Arsenal FC": "Arsenal FC Hawaii",
}
_STORED_CLUB = {written.lower(): stored for written, stored in _HI_CLUBS.items()}
_CLUB_SPELLING = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(w) for w in sorted(_HI_CLUBS, key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NOT_SQUAD_WORDS = frozenset(w.upper() for w in NOISE_WORDS) | {"HI", "HAWAII"}
_AGE_TOKEN = re.compile(r"[BG]?U?\d{2}U?[BG]?|[BG]?(?:19|20)\d{2}[BG]?", re.IGNORECASE)


def _without_age_label(name: str) -> str:
    return _AGE_LABEL.sub("", name or "")


def _normalize_for_affinity_hi(name: str) -> str:
    """The age label dropped and Roman squad numbers written as digits, then read as Utah's names are."""
    return _normalize_for_affinity_ut(roman_to_digits(_without_age_label(name)))


class AffinityHIGameMatcher(AffinityUTGameMatcher):
    """Affinity HI matcher: the UT matcher with Hawaii's state and HYSA's name conventions."""

    state_code = "HI"
    state_name = "Hawaii"
    region = ("HI",)

    def _normalize_provider_name(self, name: str) -> str:
        return _normalize_for_affinity_hi(name)

    def _club_for(self, team_name: Optional[str], club_name: Optional[str]) -> Optional[str]:
        if club_name or not team_name:
            return super()._club_for(team_name, club_name)
        name = _without_age_label(team_name)
        written = _CLUB_SPELLING.search(name)
        if written:
            return _STORED_CLUB[written.group(1).lower()]
        return super()._club_for(name, None)

    def _club_words(self, team_name: str) -> set:
        """The stored club's words and the words HYSA wrote it with, so neither reads as a squad's own."""
        written = _CLUB_SPELLING.search(_without_age_label(team_name))
        spelled = written.group(1) if written else ""
        return {w.upper() for w in re.findall(r"[A-Za-z0-9]+", f"{self._club_for(team_name, None) or ''} {spelled}")}

    def _squad_words(self, team_name: str, club_words: set) -> frozenset:
        """The words of a name once its club, ages and generic club words are gone: 'Azul', 'HNL Academy 1'."""
        tokens = re.findall(r"[A-Za-z0-9]+", self._normalize_provider_name(team_name))
        return frozenset(
            t.upper()
            for t in tokens
            if t.upper() not in club_words and t.upper() not in _NOT_SQUAD_WORDS and not _AGE_TOKEN.fullmatch(t)
        )

    def _squads_conflict(self, provider_name: str, candidate_name: str) -> bool:
        """Different stated U-ages, or any difference in the squad's own words, one-sided included.

        A stored name that names no squad ('Hawaii Rush 2016') cannot choose between 'RUSH Azul'
        and 'RUSH Lightning Salt Lake'. The provider's club words are struck from both names
        because a stored row such as 'WND BU12 Academy' carries no club to read. U-ages are
        compared first because ages leave the words and '18UB' and '19UB' teams share a board; a
        band is not compared, since HYSA labels an '08/09' squad either 18UB or 19UB.
        """
        provider_ages, candidate_ages = label_numbers(provider_name), label_numbers(candidate_name)
        if provider_ages and candidate_ages and not provider_ages & candidate_ages:
            return True
        club_words = self._club_words(provider_name)
        return self._squad_words(provider_name, club_words) != self._squad_words(candidate_name, club_words)
