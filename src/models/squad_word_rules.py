"""
Squad-word rules for hosts whose clubs name squads by words no shared gate reads.

Heartland Soccer's clubs name the squads of one age by such words: KC Athletics enters Borussia,
Genoa and Monaco, Toca Fusion a Premier and a Championship squad. The club read from a stored name
swallows that word ("KC Athletics Genoa u11B" reads as the club "KC Athletics Genoa"), so the
squad gates find nothing to compare. Two names of one club that each carry such a word the other
lacks are two squads and never link, and a team naming a squad goes to review rather than linking
to a stored row of its club that names none.
"""

import re
import unicodedata
from typing import Dict, List, Optional, Set, Tuple

from src.models.athletes2events_matcher import _presplit
from src.models.squad_name_gates import TIER_ALIASES
from src.models.tournament_name_gates import AGE_WORD, begins, canonical_team_name, initials
from src.tournaments.alias_writer import REVIEW_QUEUE_CLAMP
from src.utils.team_name_utils import NOISE_WORDS

_WORD = re.compile(r"[a-z0-9]+")
# A U-age run into the club before it, or a number into the word after it: "SportingSpringfieldU12Atletico".
# Splitting at every capital would part a club's "McCarthy" from the "MCCARTHY" a stored name writes:
# adjacent words are rejoined only between two names, never against a club's words.
_GLUED = re.compile(r"(?<=[a-z])(?=[BG]?U\d)|(?<=\d)(?=[A-Z][a-z])")
_NOT_SQUAD = frozenset(NOISE_WORDS) | {"u", "under", "boy", "girl", "male", "female"}
# BSSA writes a squad as a four-letter code keeping its name's letters in order: CHTA for Cheetahs.
_CODE_LENGTH = 4
# Club spellings are read raw, and stored names keep both forms: "Steamer's Crew", "K.C.L.".
_INSIDE_A_WORD = re.compile(r"(?<=[A-Za-z0-9])['’.](?=[A-Za-z0-9])")


def _words(text: Optional[str]) -> List[str]:
    """Lowercase words with accents, and apostrophes and dots inside a word, dropped.

    Any other character outside a-z and 0-9 parts two words, and so does a U-age or number run into a word.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WORD.findall(_GLUED.sub(" ", _INSIDE_A_WORD.sub("", unaccented)).lower())


def _runs(words: List[str]) -> List[Tuple[int, int]]:
    """``(start, end)`` of every run of two or more adjacent words."""
    return [(start, end) for start in range(len(words)) for end in range(start + 2, len(words) + 1)]


def club_words(words: List[str]) -> Set[str]:
    """A club's words, and the initials of every run of two or more: 'sbv' and 'bv' of Sporting Blue Valley."""
    return set(words) | {initials(words[start:end]) for start, end in _runs(words)}


def _vouched_for(words: List[str], other: Set[str], outside: Set[str]) -> Set[str]:
    """The words to strike from a club spelling read from the team's own name.

    They run from its first word through its first run of vouched-for words, a word being vouched for when
    the other name carries it or a whole-struck spelling has it, so a code ahead of a shared word goes too
    ('SWMO' of 'SWMO Rush') while the words after an unvouched one stay ('Manchester City' of 'KC Athletics
    Manchester City'). Every run whose initials the other name carries goes as well ('LA' for 'Lawrence Arsenal').
    """
    struck: Set[str] = set()
    vouched = [word in other or word in outside for word in words]
    if True in vouched:
        end = vouched.index(True)
        while end < len(words) and vouched[end]:
            end += 1
        struck.update(words[:end])
    for start, end in _runs(words):
        if initials(words[start:end]) in other:
            struck.update(words[start:end])
            struck.add(initials(words[start:end]))
    return struck


def _club_spellings(team_name: str, other_name: str, club: Optional[str], written: Optional[str]) -> Set[str]:
    """The club words to strike from both names, given the club the team is filed under and its written club.

    A spelling is struck whole, with the initials of every run of its words, when it is one word (a club
    code: KCL, TFAC), when the two spellings are the same (a club table's entry, or a club cell opening the
    name), or when the name does not contain it (a cell spelling the club another way: 'Kansas City
    Athletics' for 'KC Athletics Borussia'). Any other spelling was read from the team's own name, the
    written club guessed from the words before the age or a club cut from the name at a squad mark ('OPSC
    Premier' beside 'OPSC'), and can carry the squad word, so only what ``_vouched_for`` returns is struck.
    A guess its written club repeats (a blank club cell) is struck whole, squad word included, and the club
    gate, which gates on that guess, is then what keeps the team off its club's other squads.
    """
    team = set(_words(team_name))
    spellings = [words for words in (_words(club), _words(written)) if words]
    differ = len(spellings) == 2 and spellings[0] != spellings[1]
    from_name = [words for words in spellings if differ and len(words) > 1 and set(words) <= team]
    struck: Set[str] = set()
    for words in spellings:
        if words not in from_name:
            struck |= club_words(words)
    other = set(_words(other_name))
    outside = set(struck)
    for words in from_name:
        struck |= _vouched_for(words, other, outside)
    return struck


def squad_words(name: str, club: Set[str]) -> List[str]:
    """A name's words, in order, once its club, ages, gender and generic club words are gone: 'Pre ECNL Navy'.

    A league spelled as one word reads as the league's words ("ECRL" as "ECNL RL"), as the tier gate reads it.
    """
    dropped = club | _NOT_SQUAD
    found: List[str] = []
    for word in _words(name):
        if word not in dropped and not AGE_WORD.fullmatch(word):
            found.extend(sorted(TIER_ALIASES.get(word, (word,))))
    return found


def _abbreviates(short: str, long: str) -> bool:
    """``short``, four letters or more, begins ``long``; or is a four-letter code starting with ``long``'s first letter
    and keeping the rest of its letters in order."""
    if begins(short, long):
        return True
    letters = iter(long)
    return len(short) == _CODE_LENGTH and short[0] == long[0] and all(c in letters for c in short)


def _unmatched(words: List[str], other: List[str]) -> Set[str]:
    """The words with no counterpart on the other side.

    A word may stand for a longer one it abbreviates, and adjacent words for the one word they spell run
    together ('Mc Nutt' for 'McNutt', 'De La Salle' for 'DeLaSalle'), on either side.
    """
    other_words = set(other)
    other_runs = {"".join(other[start:end]) for start, end in _runs(other)}
    in_a_run = {w for start, end in _runs(words) if "".join(words[start:end]) in other_words for w in words[start:end]}
    return {
        word
        for word in set(words) - other_words
        if word not in in_a_run
        and word not in other_runs
        and not any(_abbreviates(word, o) or _abbreviates(o, word) for o in other_words)
    }


class SquadWordRules:
    """Mixed in ahead of an Athletes2Events-family matcher, whose candidate loop calls ``_names_another_squad``.

    ``_filed_club`` holds the club the team is filed under while it is matched. Tourney Central's second
    pass hands the candidate loop the written club instead, which may carry the squad word, and the club
    gate lets a near spelling of it through ('KC Athletics Courage' beside 'KC Athletics Coraggio').
    """

    _filed_club: Optional[str] = None

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        self._filed_club = club_name
        try:
            match = super()._fuzzy_match_team(team_name, age_group, gender, club_name, state_code)
        finally:
            self._filed_club = None
        if match is None:
            return None
        confidence = match["confidence"]
        if self._names_no_squad(team_name, match["team_name"], club_name):
            confidence = min(confidence, float(REVIEW_QUEUE_CLAMP))
        return {"team_id": match["team_id"], "team_name": match["team_name"], "confidence": confidence}

    def _squad_words_of(
        self, provider_name: str, candidate_name: str, club: Optional[str]
    ) -> Tuple[List[str], List[str]]:
        """Both names' squad words, read from the canonical names, once the team's own club spellings are struck.

        ``club`` is the club the team is filed under, or the gated club when none is filed. Never the
        candidate's club: the club read from a stored name swallows its squad word, and a near spelling the
        club gate let through ('KC Atletico' for 'KC Athletics') carries the words that tell it apart.
        """
        provider = canonical_team_name(provider_name, _presplit)
        candidate = canonical_team_name(candidate_name, _presplit)
        struck = _club_spellings(provider, candidate, club, self._written_club)
        return squad_words(provider, struck), squad_words(candidate, struck)

    def _names_no_squad(self, provider_name: str, candidate_name: str, club: Optional[str]) -> bool:
        """A stored row naming no squad, for a team that names one: 'SPORTING BV U12G' for 'SPORTING BV Inter 14/15'.

        Such a row is one of the club's squads at that age, which one unknown, and it is left as
        the only candidate once its named siblings are refused, so it goes to review.
        """
        provider, candidate = self._squad_words_of(provider_name, candidate_name, club)
        return bool(provider) and not candidate

    def _names_another_squad(self, provider_name: str, candidate_name: str, club: Optional[str]) -> bool:
        """Each name carries a squad word the other lacks: 'Borussia' against 'Genoa', 'Premier' against 'Championship'.

        A name lacking a word the other carries, such as a stored row that names no squad, is no
        evidence either way. ``club`` is the club the candidate was gated on; the filed club stands in
        for it while one is set.
        """
        filed = self._filed_club if self._filed_club is not None else club
        provider, candidate = self._squad_words_of(provider_name, candidate_name, filed)
        return bool(_unmatched(provider, candidate)) and bool(_unmatched(candidate, provider))
