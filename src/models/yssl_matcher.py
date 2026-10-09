"""
YSSL game matcher (yssl.org, Chicago-area boys league).

YSSL teams are registered by a roster pass in ``scripts/import_yssl.py``, as
Athletes2Events teams are, and need the same matching: the club gate (the driver
passes PitchRank's club name from ``config/yssl_club_map.csv`` as ``club_name``
and YSSL's own spelling as ``written_club``), the squad and tier gates, state
scoping, and review for ties. So this reuses that matcher whole.

Two things differ.

YSSL names a squad by words the shared gates do not read: a branch (``RUSH -
WILMETTE WINGS``, ``RUSH OSWEGO``), a location (``DARIEN``, ``NAPERVILLE``) or a
squad name (``SOLAR``, ``LUNAR``). Without them, ``RUSH - WILMETTE WINGS 15/16B
BLUE`` scored 0.99 against ``SC 2016 Oswego Blue``. So a candidate qualifies only
when every such word of the YSSL name appears in its team name, a stored word
being allowed to abbreviate it (``Prem`` for ``PREMIER``). A twin written another
way becomes a duplicate to merge, which is recoverable; a wrong link is not.

YSSL also writes the club inside every team name under its own spelling, so the
Athletes2Events habit of cutting the club off the front of a created team's name
would store ``CHICAGO 14/15 GOLD`` for ``AAC EAGLES CHICAGO 14/15 GOLD`` whenever
the two spellings share a prefix. A created YSSL team keeps its full name.
"""

import re
from typing import Dict, FrozenSet, Optional, Tuple

from src.models.athletes2events_matcher import Athletes2EventsGameMatcher
from src.models.tournament_name_gates import canonical_team_name, is_boys, without_club
from src.utils.team_name_utils import resolve_distinction
from src.utils.us_states import STATE_CODE_TO_NAME

_WORDS = re.compile(r"[a-z]+")
_NOT_DISTINGUISHING = frozenset({"fc", "sc", "soccer", "club", "the", "boys", "boy", "girls", "girl", "u"})
_SHORTEST_ABBREVIATION = 4
# YSSL's own shorthand, spelled out before matching so "UTD" and "SEL" meet PitchRank's
# "United" and "Select". "SEL" matters beyond the word rule: unexpanded, the candidate's
# "Select" is a tier the YSSL name lacks, and a one-sided tier blocks the link.
_YSSL_SHORTHAND = {"UTD": "UNITED", "SEL": "SELECT", "PREM": "PREMIER", "ACAD": "ACADEMY"}
_SHORTHAND = re.compile(r"\b(" + "|".join(_YSSL_SHORTHAND) + r")\b", re.IGNORECASE)


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_ROMAN_SQUAD = re.compile(r"\b(IV|I{1,3})\b", re.IGNORECASE)


def roman_to_digits(team_name: str) -> str:
    """Write "PREMIER II" as "PREMIER 2": the shared gates compare squad numbers as text."""
    return _ROMAN_SQUAD.sub(lambda m: str(_ROMAN[m.group(1).lower()]), team_name)


def expand_shorthand(team_name: str) -> str:
    return roman_to_digits(_SHORTHAND.sub(lambda m: _YSSL_SHORTHAND[m.group(1).upper()], team_name))


_SQUAD_NUMBER = re.compile(r"(?<![\d/])\b(?:([1-9])|(iv|i{1,3})|([1-9])(?:st|nd|rd|th))\b(?![\d/])", re.IGNORECASE)
_BAND = re.compile(r"(?<!\d)(?:20)?\d{2}\s*/\s*(?:20)?\d{2}(?!\d)[bg]?", re.IGNORECASE)


def squad_numbers(text: str) -> FrozenSet[int]:
    """Standalone squad numbers: 2, II and 2ND alike. Ages, years and bands are not squad numbers."""
    return frozenset(
        int(digit or ordinal) if (digit or ordinal) else _ROMAN[roman.lower()]
        for digit, roman, ordinal in _SQUAD_NUMBER.findall(_BAND.sub(" ", text))
    )


def yssl_squad_number(team_name: str) -> Optional[int]:
    """The squad number YSSL writes ("WHITE 2", "- 3RD TEAM"); None when it writes none.

    Read after the band when there is one, so a number in the club's name ("FC-1") is not taken for one.
    """
    parts = _BAND.split(team_name, maxsplit=1)
    numbers = squad_numbers(parts[1] if len(parts) == 2 else team_name)
    return min(numbers) if numbers else None


def _fits_squad_number(number: Optional[int], candidate: Dict) -> bool:
    """An unnumbered or first squad fits a stored name with no number or a 1; a later squad needs its own number."""
    stored = squad_numbers(candidate.get("team_name") or "")
    return number in stored if number and number >= 2 else not stored or 1 in stored


def _initials(name: str) -> str:
    return "".join(word[0] for word in _WORDS.findall(name.lower()))


def distinguishing_words(team_name: str, written_club: Optional[str], club_name: Optional[str]) -> FrozenSet[str]:
    """The words of a YSSL name that name its squad: not the club or its initials, an age, a year or a gender.

    Takes the name after ``expand_shorthand``, so a roman squad number is already a digit.
    """
    name = without_club(canonical_team_name(team_name), written_club).lower()
    club_words = set(_WORDS.findall(f"{written_club or ''} {club_name or ''}".lower()))
    club_words |= {_initials(club) for club in (written_club, club_name) if club}
    return frozenset(
        word
        for word in _WORDS.findall(re.sub(r"\w*\d\w*", " ", name))
        if len(word) > 1 and word not in _NOT_DISTINGUISHING and word not in club_words
    )


def _carries(words: FrozenSet[str], candidate: Dict) -> bool:
    stored = set(_WORDS.findall((candidate.get("team_name") or "").lower()))
    return all(
        word in stored or any(len(s) >= _SHORTEST_ABBREVIATION and word.startswith(s) for s in stored) for word in words
    )


class YSSLGameMatcher(Athletes2EventsGameMatcher):
    """Athletes2Events matching, narrowed to candidates carrying the YSSL name's own words."""

    _required_words: FrozenSet[str] = frozenset()
    _squad_number: Optional[int] = None
    _yssl_name: Optional[str] = None

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
        expanded = expand_shorthand(team_name or "")
        self._required_words = distinguishing_words(expanded, written_club, club_name)
        self._squad_number = yssl_squad_number(team_name or "")
        self._yssl_name = team_name
        try:
            return super()._match_team(
                provider_id,
                provider_team_id,
                expanded,
                age_group,
                gender,
                club_name,
                state_code=state_code,
                written_club=written_club,
            )
        finally:
            self._required_words = frozenset()
            self._squad_number = None
            self._yssl_name = None

    def _fetch_candidates(self, age_group: str, gender: str, state_code: str) -> list:
        return [
            {**team, "team_name": roman_to_digits(team.get("team_name") or "")}
            for team in super()._fetch_candidates(age_group, gender, state_code)
            if _carries(self._required_words, team) and _fits_squad_number(self._squad_number, team)
        ]

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
        """A team already carrying this YSSL code is returned with ``was_created`` False."""
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
        clean_team_name = " ".join((self._yssl_name or team_name).replace("\xa0", " ").split())
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
