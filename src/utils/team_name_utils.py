"""
Shared team name parsing and matching utilities.

Consolidates structured name decomposition, distinction extraction, and
normalization logic used by both the import pipeline (game_matcher.py)
and the offline duplicate-detection scripts.

Key concepts:
 - **Distinctions**: Structural features (color, direction, program, team
   number, location code, squad word) that differentiate squads *within*
   the same club.  If ANY distinction differs, two names cannot be the
   same team.
 - **Normalized base**: The club + age portion of the name, stripped of
   noise words and common suffixes, used for fuzzy scoring.
 - **Club normalization**: Canonicalizes suffix variations so
   "Pride SC" == "Pride Soccer Club".
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

TEAM_COLORS = frozenset({
    "red", "blue", "white", "black", "gold", "grey", "gray", "green",
    "orange", "purple", "yellow", "navy", "maroon", "silver", "pink",
    "sky", "royal", "crimson", "teal",
})

DIRECTION_CANONICAL = {
    "north": "north", "south": "south", "east": "east", "west": "west",
    "central": "central",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "nw": "northwest", "ne": "northeast", "sw": "southwest", "se": "southeast",
    "nth": "north", "sth": "south",
}

PROGRAM_WORDS = frozenset({
    "academy", "premier", "select", "elite", "ecnl", "ecrl", "npl",
    "ga", "rl", "comp", "recreational", "tal", "stxcl", "dpl", "scdsl",
    "next", "copa", "nal", "reserve", "classic", "division", "fdl",
    "showcase", "challenge", "development", "competitive",
})

LOCATION_CODES = frozenset({
    # Texas
    "ctx", "ntx", "stx", "etx", "wtx",
    # Arizona
    "phx", "sev", "wv", "ev",
    # California
    "sm", "av", "mv", "le", "hb", "nb", "lb", "oc", "ie", "sfv",
    # General
    "cp", "wc", "up", "rc", "go", "sl", "tw", "tt", "cy",
})

NOISE_WORDS = frozenset({
    "fc", "sc", "sa", "ac", "cf", "fcs", "ysa",
    "soccer", "club", "futbol", "football", "youth",
    "boys", "girls", "the", "of", "and",
    "b", "g", "m", "f",
})

US_STATES = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
})

# Age/year regex applied to the raw name string
AGE_PATTERN = re.compile(
    r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b"
)

# Club-suffix canonicalization (from full_club_analysis.py)
_CLUB_SUFFIX_RE = [
    (re.compile(r'\s+soccer\s+club\s*$', re.I), ' sc'),
    (re.compile(r'\s+s\.c\.\s*$', re.I), ' sc'),
    (re.compile(r'\s+football\s+club\s*$', re.I), ' fc'),
    (re.compile(r'\s+futbol\s+club\s*$', re.I), ' fc'),
    (re.compile(r'\s+f\.c\.\s*$', re.I), ' fc'),
    (re.compile(r'\s+soccer\s+academy\s*$', re.I), ' sa'),
    (re.compile(r'\s+youth\s+soccer\s*$', re.I), ''),
    (re.compile(r'\s+soccer\s+association\s*$', re.I), ''),
    (re.compile(r'\s+soccer\s*$', re.I), ''),
]


# ═══════════════════════════════════════════════════════════════
# Tokenization
# ═══════════════════════════════════════════════════════════════

def _tokenize(name: str) -> List[str]:
    """Lowercase tokens, splitting on spaces / hyphens / underscores / dots."""
    if not name:
        return []
    normalized = re.sub(r"[-_./]", " ", name.lower())
    return [w.strip("()[]'*") for w in normalized.split() if w.strip("()[]'*")]


# ═══════════════════════════════════════════════════════════════
# Distinction Extraction  (from find_fuzzy_duplicate_teams.py)
# ═══════════════════════════════════════════════════════════════

def extract_distinctions(name: str) -> Dict:
    """
    Decompose a team name into every distinguishing feature.

    Returns dict with frozenset / str / tuple values for:
        colors, directions, programs, team_number, location_codes,
        state_codes, squad_words, age_tokens, secondary_nums.

    Two names from the same club are duplicates **only** when every
    extracted distinction matches.
    """
    empty: Dict = {
        "colors": frozenset(), "directions": frozenset(),
        "programs": frozenset(), "team_number": None,
        "location_codes": frozenset(), "state_codes": frozenset(),
        "squad_words": frozenset(), "age_tokens": (),
        "secondary_nums": (),
    }
    if not name:
        return empty

    tokens = _tokenize(name)
    colors: set = set()
    directions: set = set()
    programs: set = set()
    location_codes: set = set()
    state_codes: set = set()
    team_number: Optional[str] = None
    classified: set = set()

    # Pass 1: classify known token types
    for idx, tok in enumerate(tokens):
        if tok in TEAM_COLORS:
            colors.add(tok); classified.add(idx)
        elif tok in DIRECTION_CANONICAL:
            directions.add(DIRECTION_CANONICAL[tok]); classified.add(idx)
        elif tok in PROGRAM_WORDS:
            programs.add(tok); classified.add(idx)
        elif tok in LOCATION_CODES:
            location_codes.add(tok); classified.add(idx)
        elif tok in NOISE_WORDS:
            classified.add(idx)
        elif tok in US_STATES:
            state_codes.add(tok); classified.add(idx)
        elif re.fullmatch(r"(i{1,3}|iv|v|vi{0,3})", tok):
            team_number = tok; classified.add(idx)
        elif re.fullmatch(r"[1-9]|10", tok):
            team_number = tok; classified.add(idx)

    # Pass 2: extract age tokens and secondary numbers
    age_tokens: list = []
    for m in AGE_PATTERN.finditer(name):
        age_tokens.append(m.group(0).lower().strip("'"))

    secondary_nums: list = []
    first_age = AGE_PATTERN.search(name)
    if first_age:
        after = name[first_age.end():]
        secondary_nums = re.findall(r"\d+", after)

    # Pass 3: classify age/gender combo indices
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        age_gender = re.fullmatch(
            r"(\d{1,4})u?[bgmf]|[bgmf](\d{1,4})u?|u(\d{1,2})[bgmf]", tok
        )
        if age_gender:
            age_num = age_gender.group(1) or age_gender.group(2) or age_gender.group(3)
            if age_num:
                age_tokens.append(age_num)
            classified.add(idx)
        elif re.fullmatch(r"20\d{2}", tok) or re.fullmatch(r"\d{2}/\d{2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"u-?\d{1,2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"\d+m?", tok):
            classified.add(idx)

    # Pass 4: remaining unclassified → squad words or location codes
    squad_words: set = set()
    for idx, tok in enumerate(tokens):
        if idx in classified or not tok:
            continue
        if not tok.isalpha() and not tok.isdigit() and len(tok) >= 2:
            squad_words.add(tok); continue
        if not tok.isalpha():
            continue
        if len(tok) == 1:
            squad_words.add(tok)
        elif 2 <= len(tok) <= 3:
            location_codes.add(tok)
        elif len(tok) >= 4:
            squad_words.add(tok)

    # Normalize: RL alone implies ECNL RL
    if "rl" in programs:
        programs.add("ecnl")

    return {
        "colors": frozenset(colors),
        "directions": frozenset(directions),
        "programs": frozenset(programs),
        "team_number": team_number,
        "location_codes": frozenset(location_codes),
        "state_codes": frozenset(state_codes),
        "squad_words": frozenset(squad_words),
        "age_tokens": tuple(sorted(set(age_tokens))),
        "secondary_nums": tuple(secondary_nums),
    }


def should_skip_pair(name_a: str, name_b: str) -> bool:
    """
    Return True if ANY structural distinction differs — the two names
    represent different squads within the same club and must NOT be merged.
    """
    da = extract_distinctions(name_a)
    db = extract_distinctions(name_b)

    if da["colors"] != db["colors"]:
        return True
    if da["directions"] != db["directions"]:
        return True
    if da["programs"] != db["programs"]:
        return True
    if da["team_number"] != db["team_number"]:
        return True
    if da["location_codes"] != db["location_codes"]:
        return True
    if da["squad_words"] != db["squad_words"]:
        return True
    if da["age_tokens"] != db["age_tokens"]:
        return True
    if da["secondary_nums"] != db["secondary_nums"]:
        return True
    # State codes: skip only if BOTH names contain them and they differ
    if da["state_codes"] and db["state_codes"] and da["state_codes"] != db["state_codes"]:
        return True

    return False


# ═══════════════════════════════════════════════════════════════
# Club name normalization  (from full_club_analysis.py)
# ═══════════════════════════════════════════════════════════════

def normalize_club_for_comparison(club: str) -> str:
    """
    Normalize club name for grouping/comparison.

    Canonicalizes suffix variations so
    "Pride Soccer Club" → "pride sc", "Florida West F.C." → "florida west fc".
    Keeps prefixes like "FC" intact to avoid false matches
    ("FC Arkansas" ≠ "Arkansas SC").
    """
    if not club:
        return ""
    n = club.lower().strip()
    for pattern, replacement in _CLUB_SUFFIX_RE:
        n = pattern.sub(replacement, n)
    return n.strip()


# ═══════════════════════════════════════════════════════════════
# Normalized base name  (for fuzzy scoring)
# ═══════════════════════════════════════════════════════════════

def normalize_name_for_matching(name: str) -> str:
    """
    Strip league markers, gender chars, and normalize age formats for
    SequenceMatcher comparison.  Produces a lowercase string with noise
    removed but club identity preserved.
    """
    if not name:
        return ""
    n = name.lower().strip()

    # Strip league/tier markers
    n = re.sub(
        r'\b(ecnl-rl|ecnl rl|ecrl|ecnl|pre-ecnl|pre ecnl|mls next|'
        r'mls-next|mlsnext|ga|rl|npl|dpl|dplo|scdsl|copa|nal)\b',
        ' ', n
    )
    # Replace dashes with spaces
    n = re.sub(r'\s*-\s*', ' ', n)

    # Normalize age formats — strip gender char, keep number
    n = re.sub(r'\b[bg]\s*(\d{2,4})\b', r'\1', n)
    n = re.sub(r'\b(\d{2,4})\s*[bg]\b', r'\1', n)
    n = re.sub(r'\bu\s*(\d+)\b', r'u\1', n)

    # Remove punctuation (except apostrophes in names like O'Brien)
    n = re.sub(r"[^\w\s']", '', n)

    # Remove standalone gender words
    n = re.sub(r'\b(boys?|girls?|male|female)\b', '', n)

    # Compress whitespace
    n = ' '.join(n.split())
    return n


# ═══════════════════════════════════════════════════════════════
# Club extraction from team name
# ═══════════════════════════════════════════════════════════════

# Age/year patterns for splitting club from the rest
_AGE_SPLIT_PATTERNS = [
    r'\bU-?\d{1,2}\b',
    r'\b[BG]?\d{4}[BG]?\b',
    r'\b[BG]\d{2}(?!\d)\b',
    r'\b\d{2}[BG](?!\d)\b',
]

_TRAILING_SUFFIXES = [
    re.compile(s, re.I) for s in [
        r'\s+(ECNL-RL|ECNL RL|ECRL)\s*$',
        r'\s+ECNL\s*$', r'\s+RL\s*$', r'\s+PRE-ECNL\s*$',
        r'\s+PRE\s*$', r'\s+COMP\s*$', r'\s+GA\s*$',
        r'\s+MLS NEXT\s*$', r'\s+ACADEMY\s*$',
        r'\s+SELECT\s*$', r'\s+PREMIER\s*$', r'\s+ELITE\s*$',
    ]
]


def extract_club_from_team_name(team_name: str) -> Optional[str]:
    """
    Extract club name from a provider team name by splitting on the
    first age/year token and stripping trailing league suffixes.
    """
    if not team_name:
        return None

    name = team_name.strip()
    earliest_pos = len(name)
    for pattern in _AGE_SPLIT_PATTERNS:
        match = re.search(pattern, name, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()

    club = name[:earliest_pos].strip() if earliest_pos < len(name) else name

    for pat in _TRAILING_SUFFIXES:
        club = pat.sub('', club)
    club = club.strip(' -.')

    # Dedup repeated halves ("Kingman SC Kingman SC" → "Kingman SC")
    words = club.split()
    if len(words) >= 4:
        mid = len(words) // 2
        if ' '.join(words[:mid]).lower() == ' '.join(words[mid:mid * 2]).lower():
            club = ' '.join(words[:mid])

    club = ' '.join(club.split())
    return club if club and len(club) >= 3 else None


# ═══════════════════════════════════════════════════════════════
# League marker helpers
# ═══════════════════════════════════════════════════════════════

def has_ecnl_rl(name: str) -> bool:
    n = name.lower()
    return ' rl' in n or '-rl' in n or 'ecnl rl' in n or 'ecnl-rl' in n

def has_ecnl_only(name: str) -> bool:
    return 'ecnl' in name.lower() and not has_ecnl_rl(name)

def has_protected_division(name: str) -> bool:
    """Names with league-specific division markers should NOT be auto-merged
    across divisions (ECNL ≠ ECNL-RL ≠ MLS NEXT)."""
    n = name.lower()
    return any(kw in n for kw in ('ecnl', 'mls next', 'mls-next', 'ga '))
