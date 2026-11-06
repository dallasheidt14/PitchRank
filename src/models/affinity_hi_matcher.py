"""
Affinity Sports HI game matcher - Hawaii Youth Soccer's Oahu League (hysa.sportsaffinity.com).

HYSA's pages follow the Oregon conventions and its names the state league ones, so that
matcher applies, with Hawaii's state and these changes for how HYSA writes team names:

- Every name starts with the team's own age and gender ('13UB - HSC Bulls 13/14B - II').
  The label sets the team's age and is dropped before a name's words are compared.
- Clubs are written in a short form the stored rows spell out ('HSC Bulls' is stored as
  'Honolulu Bulls Soccer Club'), sometimes after a band ('13/14G Surf Hawaii Academy I').
- Squads of one club are numbered in Roman numerals ('- I', '- II', 'Academy I'), which are
  read as squad numbers, and named by words no gate reads ('RUSH Azul', 'Leahi Maile', Albion's
  'HNL' and 'WND').
"""

import re
from typing import Optional

from src.models.affinity_state_league_matcher import AffinityStateLeagueMatcher
from src.models.yssl_matcher import roman_to_digits
from src.scrapers._age_normalization import normalize_age

_AGE_LABEL = re.compile(r"^\s*(\d{1,2})U[BG]\s*-\s*", re.IGNORECASE)

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


class AffinityHIGameMatcher(AffinityStateLeagueMatcher):
    """Affinity HI matcher: the state league matcher with Hawaii's state and HYSA's name conventions."""

    state_code = "HI"
    state_name = "Hawaii"
    clubs = _HI_CLUBS
    not_squad_words = frozenset({"HI", "HAWAII"})

    def _prepared(self, name: Optional[str]) -> str:
        return _AGE_LABEL.sub("", name or "")

    def _own_board(self, team_name: Optional[str]) -> Optional[str]:
        label = _AGE_LABEL.match(team_name or "")
        return normalize_age(int(label.group(1))) if label else None

    def _normalize_provider_name(self, name: str) -> str:
        """Roman squad numbers written as digits, which the club reading leaves alone: 'Hawai'i' keeps its 'i'."""
        return super()._normalize_provider_name(roman_to_digits(name or ""))
