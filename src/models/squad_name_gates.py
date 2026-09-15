"""
Name gates applied before similarity scoring, which alone merges distinct clubs that
share a word and squads of one club that differ only by tier or lane.
"""

import re
from difflib import SequenceMatcher
from typing import Optional

from src.utils.club_normalizer import are_same_club, normalize_club_name


def token_sort_ratio(a: str, b: str) -> float:
    """Order-insensitive similarity on two names, 0.0-1.0, stdlib only.

    Deliberately not ``rapidfuzz``. It is in neither requirements file, so
    ``club_normalizer`` carries a difflib fallback and CI and the scheduled
    workflows all run on it — and that fallback defines no ``token_sort_ratio``
    at all. Importing rapidfuzz made every threshold measured against it
    measured against a library production does not have, and would have raised
    ``AttributeError`` into a caller's broad ``except``, matching nothing and
    autocreating every team.
    """
    sorted_a = " ".join(sorted(a.split()))
    sorted_b = " ".join(sorted(b.split()))
    return SequenceMatcher(None, sorted_a, sorted_b).ratio()


def is_same_club(provider_club: str, candidate_club: str, threshold: float) -> bool:
    """Same club by canonical id AND by order-insensitive name similarity.

    Two shared shortcuts each merge distinct Oregon clubs on their own, so
    this requires both to agree:

    - ``are_same_club`` returns on canonical id alone when both names resolve,
      and the canonical map folds every Oregon "Timbers" affiliate into
      ``portland_timbers``. Eastside, Eugene, Rogue Valley and Portland
      Timbers are four clubs, and Cascade Surf and Oregon Surf two more.
    - ``similarity_score`` is ``token_set_ratio``, which scores containment:
      "portland" sits inside "portland city united", so FC Portland and
      Portland City United SC score a perfect 1.0.

    :func:`token_sort_ratio` is the one that reads both names whole.
    Measured 2026-09-12 over the 106 distinct OR club names, genuinely-
    different pairs top out at 0.67 while same-club pairs reach 0.74-1.00,
    so the configured threshold clears every different-club pair. It also declines two true
    same-club pairs that differ by a trailing "and Thorns"; that costs a
    duplicate row, which ``merging-duplicate-teams`` reverses, where the other
    direction fuses two squads into one and does not reverse.

    The ``are_same_club`` half is redundant on every Oregon pair measured, and
    a mutation run confirms no test pins it: ``token_set_ratio`` never
    scores below a token-sort score, so a name pair clearing the sort check
    clears it too. It is kept because the one case that *can* separate two
    near-identical names is a hand-curated canonical id, which lives there and
    nowhere else.
    """
    if not are_same_club(provider_club, candidate_club, threshold=threshold):
        return False
    return (
        token_sort_ratio(
            normalize_club_name(provider_club),
            normalize_club_name(candidate_club),
        )
        >= threshold
    )


TIER_TOKENS = frozenset(
    {"ecnl", "rl", "npl", "dpl", "ga", "mls", "premier", "elite", "select", "classic", "academy"}
)

# One tier, three spellings in this data — game_matcher.extract_club_from_team_name
# strips all of ``ECNL-RL|ECNL RL|ECRL``. Splitting on the hyphen makes the first
# two agree; the contraction has to be expanded explicitly or it reads as no tier
# at all and an ECNL-RL squad merges onto its club's ECNL squad.
TIER_ALIASES = {"ecrl": frozenset({"ecnl", "rl"})}

# "Academy" and "Premier" are frequently part of a club's actual name — 14 and 5
# of the 106 distinct OR club names respectively, e.g. "Coast to Coast Futbol
# Academy", "Oregon Premier FC" — so a side naming one has not necessarily named
# a tier, and a one-sided difference there is not evidence of anything. Every
# other token in TIER_TOKENS was measured absent from OR club names on
# 2026-09-12, so one side naming ECNL while the other does not is a real tier
# difference and must reject.
CLUB_AMBIGUOUS_TIERS = frozenset({"academy", "premier"})


def extract_tier_tokens(name: str) -> frozenset:
    """Competitive tiers named in a team name, e.g. 'United PDX ECNL 2013' -> {'ecnl'}.

    Returned as a set so every spelling of ECNL-RL ({'ecnl', 'rl'}) stays
    distinct from plain 'ECNL' ({'ecnl'}), the pair CLAUDE.md singles out as
    never mergeable.
    """
    if not name:
        return frozenset()
    words = {w.lower() for w in re.split(r"[\s/\-]+", name) if w}
    tiers = set(words & TIER_TOKENS)
    for word in words:
        tiers |= TIER_ALIASES.get(word, frozenset())
    return frozenset(tiers)


def tiers_conflict(provider_tiers: frozenset, candidate_tiers: frozenset) -> bool:
    """True when two names name different tiers and so cannot be one team.

    A one-sided *competitive* tier counts: requiring both sides to name one let
    a plain squad match its club's ECNL squad, with the club and variant boosts
    carrying it past auto-approve. "Academy" and "Premier" are the exception —
    often just part of a club's name — so they only count when both sides say
    one, which still separates a club's Academy squad from its Premier squad.
    """
    provider_strong = provider_tiers - CLUB_AMBIGUOUS_TIERS
    candidate_strong = candidate_tiers - CLUB_AMBIGUOUS_TIERS
    if provider_strong != candidate_strong:
        return True
    return bool(provider_tiers and candidate_tiers and provider_tiers != candidate_tiers)


def extract_lane_number(name: str) -> Optional[str]:
    """Trailing squad number, e.g. 'Columbia Premier SC 2013 Black 1' -> '1'.

    Oregon separates same-colour squads of one club by a trailing number, the
    role WA fills with an RCL number.  ``extract_team_variant`` cannot see it —
    'Black 1' and 'Black 2' both reduce to 'black' — so without this the two
    squads match each other at full confidence.  A four-digit birth year is not
    a lane: the lookbehind keeps '... 2013' from reading as lane 3.

    A trailing parenthetical hides the lane, and DB rows carry one far more
    often than provider rows do — 'Columbia Premier SC ... Black 1 (OR)'
    against provider 'Columbia Premier SC 2013 Black 2' left the gate with
    only one lane number and so no opinion, which is the shape that let the
    two squads match. Any parenthetical is stripped, not just a state code.

    A lane is one digit. Measured over the 2,861 OR team names on 2026-09-12:
    every trailing single digit is a lane ('Comp 1', 'Prem 2', 'East 3', 152
    rows) and every trailing two-digit token is the tail of a birth-year band
    ('ECNL RL B2013/14', 'B06/07', 93 rows), so reading two digits would make
    the gate reject correct candidates over a year.
    """
    if not name:
        return None
    trimmed = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    m = re.search(r"(?<![\d/])(\d)\s*$", trimmed)
    return m.group(1) if m else None
