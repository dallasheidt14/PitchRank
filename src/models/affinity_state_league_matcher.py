"""
Affinity state league matcher - the Utah matcher narrowed to one state's league.

Hawaii's Oahu League and Georgia's fall league differ from Utah in the same ways:

- Clubs are written in short forms the stored rows spell out, so a league maps each spelling
  to the stored club, and neither is read as a squad's own words.
- Squads of one club are named by words no gate reads, so any difference in a squad's own
  words is a different squad. That rule replaces Utah's coach initials and squad numbers,
  which those words already include.
- U18 and U19 teams share the u19 board, so two names stating different U-ages are different
  squads there even when their words agree.
- A club is asked for its state only in the league's own state.
- A team can play up and a division can mix ages, so each team is matched at the age its own
  name states. The age on the importer's row, which is one age for both teams, only stands in
  for a name stating no board's age.
"""

import re
from typing import Dict, Optional

from config.settings import AGE_GROUPS
from scripts.decide_team_merges import label_numbers
from src.models.affinity_ut_matcher import AffinityUTGameMatcher, _normalize_for_affinity_ut
from src.utils.team_name_utils import NOISE_WORDS

_GENERIC_WORDS = frozenset(w.upper() for w in NOISE_WORDS)
_AGE_TOKEN = re.compile(r"[BG]?U?\d{2}U?[BG]?|[BG]?(?:19|20)\d{2}[BG]?", re.IGNORECASE)


class AffinityStateLeagueMatcher(AffinityUTGameMatcher):
    """The UT matcher for one state's league.

    A subclass sets its state, ``clubs`` and ``not_squad_words``, and writes ``_prepared``, what a
    name becomes before its words are read, and ``_own_board``, the age its own name states.
    """

    clubs: Dict[str, str] = {}
    not_squad_words: frozenset = frozenset()

    def __init__(self, supabase, provider_id=None, alias_cache=None, dry_run=False):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self.region = (self.state_code,)
        self._stored_club = {written.lower(): stored for written, stored in self.clubs.items()}
        self._club_spelling = re.compile(
            r"(?<![A-Za-z0-9])("
            + "|".join(re.escape(w) for w in sorted(self.clubs, key=len, reverse=True))
            + r")(?![A-Za-z0-9])",
            re.IGNORECASE | re.ASCII,
        )

    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
    ) -> Dict:
        stated = self._own_board(team_name)
        own_age = stated if stated in AGE_GROUPS else age_group
        return super()._match_team(provider_id, provider_team_id, team_name, own_age, gender, club_name)

    def _normalize_provider_name(self, name: str) -> str:
        return _normalize_for_affinity_ut(self._prepared(name))

    def _club_for(self, team_name: Optional[str], club_name: Optional[str]) -> Optional[str]:
        if club_name or not team_name:
            return super()._club_for(team_name, club_name)
        name = self._prepared(team_name)
        written = self._club_spelling.search(name)
        if written:
            return self._stored_club[written.group(1).lower()]
        return super()._club_for(name, None)

    def _club_words(self, team_name: str) -> set:
        """The stored club's words and the words the league wrote it with, so neither reads as a squad's own."""
        written = self._club_spelling.search(self._prepared(team_name))
        spelled = written.group(1) if written else ""
        return {w.upper() for w in re.findall(r"[A-Za-z0-9]+", f"{self._club_for(team_name, None) or ''} {spelled}")}

    def _squad_words(self, team_name: str, club_words: set) -> frozenset:
        """The words of a name once its club, ages and generic club words are gone: 'Azul', 'HNL Academy 1'."""
        tokens = re.findall(r"[A-Za-z0-9]+", self._normalize_provider_name(team_name))
        not_squad = club_words | _GENERIC_WORDS | self.not_squad_words
        return frozenset(t.upper() for t in tokens if t.upper() not in not_squad and not _AGE_TOKEN.fullmatch(t))

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
