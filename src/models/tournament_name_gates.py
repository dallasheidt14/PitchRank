"""
Name gates shared by the per-event tournament providers (Soccer Events Group,
Athletes2Events).

Both platforms write the age before the club, glue the gender letter onto the age,
and tell squads of one club apart by colour, direction, squad number, squad code
and tier.  What differs is what each glues together and which tiers it names, so
those are hooks rather than copies: ``pre`` splits a platform's own spellings
before anything is read from a name, and ``extra`` / ``tier_extra`` add the tiers
the shared tier set does not carry.

``extract_team_variant`` is not used here: its coach-name fallback reads "ECNL-RL"
and the "/13" of "G2012/13" as coach names.
"""

import re
from typing import Callable, Dict, Optional

from src.models.game_matcher import extract_club_from_team_name
from src.models.squad_name_gates import extract_tier_tokens, tiers_conflict
from src.utils.team_name_utils import extract_distinctions

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

# Tiers the shared tier set does not carry, named by both platforms. "Pre-ECNL"
# and "Pre-GA" are a club's development squads, "GA Aspire" is Girls Academy's
# second tier, and EA, AD and HD are separate MLS NEXT tiers. Passed explicitly
# rather than defaulted: a tier set that applied itself would widen the gate for
# every provider reading ``squad_name_gates``, not only these two.
TOURNAMENT_TIER_TOKENS = frozenset({"pre", "aspire", "ea", "ad", "hd"})


def canonical_team_name(name: Optional[str], pre: Optional[Callable[[str], str]] = None) -> str:
    """Collapse NBSP, whitespace, dotted initials and tier spellings; write every U-age as ``U<n>``.

    'AFC Union U15G N1' and 'AFC Union U15N1' both become 'AFC Union U15 N1'.
    ``pre`` runs first, for a platform that glues its own marks on ("ECNL2").
    """
    if not name:
        return ""
    text = pre(name) if pre else name
    text = _DOTTED_INITIALS.sub(r"\1\2", " ".join(text.replace("\xa0", " ").split()))
    for pattern, replacement in _TIER_SPELLINGS:
        text = pattern.sub(replacement, text)
    text = _GLUED_U_AGE.sub(lambda m: f" U{int(m.group(1) or m.group(2))} ", text)
    return " ".join(text.split())


def club_from_team_name(name: Optional[str], pre: Optional[Callable[[str], str]] = None) -> Optional[str]:
    """The club a team name names, e.g. 'U12G FC LAKE COUNTY 14/15 SELECT' -> 'FC LAKE COUNTY'."""
    canonical = _LEADING_U_AGE.sub("", canonical_team_name(name, pre))
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


def tier_tokens(name: str, extra: frozenset = frozenset()) -> frozenset:
    """Shared tier tokens plus the provider's own.

    "MLS NEXT AD" names the AD tier, so an explicit AD or HD absorbs the "mls"
    beside it; a bare "MLS NEXT" keeps it and stays apart from either.
    """
    words = {w.lower() for w in _NAME_TOKENS.split(name or "") if w}
    tiers = extract_tier_tokens(name) | (words & extra)
    return tiers - {"mls"} if tiers & {"ad", "hd"} else tiers


def is_boys(gender: Optional[str]) -> bool:
    return (gender or "").upper() in ("M", "MALE", "BOYS", "B")


def squad_marks(
    name: str,
    boys: bool = False,
    tier_extra: frozenset = frozenset(),
    pre: Optional[Callable[[str], str]] = None,
) -> Dict:
    """The parts of a canonical, club-free name that tell two squads of one club apart.

    Girls Academy is a girls league, so on a boys team "GA" is the state of Georgia.
    """
    text = pre(name) if pre else name
    distinctions = extract_distinctions(text)
    tiers = tier_tokens(text, tier_extra)
    return {
        "colors": distinctions["colors"],
        "directions": distinctions["directions"],
        "team_number": distinctions["team_number"],
        "squad_codes": frozenset(t for t in (w.lower() for w in _NAME_TOKENS.split(text)) if _SQUAD_CODE.match(t)),
        "tiers": tiers - {"ga"} if boys else tiers,
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
