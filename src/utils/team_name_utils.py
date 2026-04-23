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
from typing import Dict, List, Optional

from src.utils.team_utils import CURRENT_YEAR, calculate_age_group_from_birth_year

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

TEAM_COLORS = frozenset(
    {
        "red",
        "blue",
        "white",
        "black",
        "gold",
        "grey",
        "gray",
        "green",
        "orange",
        "purple",
        "yellow",
        "navy",
        "maroon",
        "silver",
        "pink",
        "sky",
        "royal",
        "crimson",
        "teal",
    }
)

DIRECTION_CANONICAL = {
    "north": "north",
    "south": "south",
    "east": "east",
    "west": "west",
    "central": "central",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "nw": "northwest",
    "ne": "northeast",
    "sw": "southwest",
    "se": "southeast",
    "nth": "north",
    "sth": "south",
}

PROGRAM_WORDS = frozenset(
    {
        "academy",
        "premier",
        "select",
        "elite",
        "ecnl",
        "ecrl",
        "npl",
        "ga",
        "rl",
        "comp",
        "recreational",
        "tal",
        "stxcl",
        "dpl",
        "scdsl",
        "next",
        "copa",
        "nal",
        "reserve",
        "classic",
        "division",
        "fdl",
        "showcase",
        "challenge",
        "development",
        "competitive",
    }
)

LOCATION_CODES = frozenset(
    {
        # Texas
        "ctx",
        "ntx",
        "stx",
        "etx",
        "wtx",
        # Arizona
        "phx",
        "sev",
        "wv",
        "ev",
        # California
        "sm",
        "av",
        "mv",
        "le",
        "hb",
        "nb",
        "lb",
        "oc",
        "ie",
        "sfv",
        # General
        "cp",
        "wc",
        "up",
        "rc",
        "go",
        "sl",
        "tw",
        "tt",
        "cy",
    }
)

NOISE_WORDS = frozenset(
    {
        "fc",
        "sc",
        "sa",
        "ac",
        "cf",
        "fcs",
        "ysa",
        "soccer",
        "club",
        "futbol",
        "football",
        "youth",
        "boys",
        "girls",
        "the",
        "of",
        "and",
        "b",
        "g",
        "m",
        "f",
    }
)

US_STATES = frozenset(
    {
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "de",
        "fl",
        "ga",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
        "dc",
    }
)

# ── Coach name detection exclusion sets ──
# Words that appear AFTER the age token but are NOT coach names.
# Ported from find_queue_matches.py and game_matcher.py.

NON_COACH_WORDS = frozenset(
    {
        "ecnl",
        "boys",
        "girls",
        "academy",
        "united",
        "elite",
        "club",
        "futbol",
        "soccer",
        "youth",
        "rush",
        "surf",
        "select",
        "premier",
        "gold",
        "blue",
        "white",
        "black",
        "grey",
        "gray",
        "green",
        "maroon",
        "navy",
        "lafc",
        "futeca",
        "selection",
        "fire",
        "storm",
        "fusion",
        "athletico",
        "atletico",
        "fc",
        "sc",
        "real",
        "inter",
        "sporting",
        "copa",
        "classic",
        "challenge",
        "showcase",
        "competitive",
        "development",
        "recreational",
        "reserve",
        "division",
        "national",
        "regional",
        "league",
        "cup",
        "premier",
    }
)

REGION_CODES_COACH = frozenset(
    {
        "ctx",
        "phx",
        "atx",
        "dal",
        "hou",
        "san",
        "sdg",
        "sfv",
        "oc",
        "ie",
        "la",
        "bay",
        "nyc",
        "nj",
        "dmv",
        "pnw",
        "sea",
        "pdx",
        "slc",
        "den",
        "chi",
        "stl",
        "kc",
        "min",
        "det",
        "cle",
        "pit",
        "atl",
        "mia",
        "orl",
        "tam",
        "ral",
        "cha",
        "dc",
        "md",
        "va",
        "pa",
        "ma",
        "ct",
        "ri",
        "vt",
        "nh",
        "me",
        "az",
        "ca",
        "tx",
        "fl",
        "ny",
        "ga",
        "nc",
        "sc",
        "co",
        "ut",
        "nv",
        "wa",
        "or",
        "id",
        "mt",
        "wy",
        "nm",
        "ok",
        "ks",
        "ne",
        "sd",
        "nd",
        "mn",
        "wi",
        "mi",
        "il",
        "in",
        "oh",
        "ky",
        "tn",
        "al",
        "ms",
        "ar",
        "mo",
        "ia",
        "ecnl",
        "rl",
        "ea",
        "npl",
        "usys",
        "ayso",
        "scdsl",
        "dpl",
        "mls",
        "ussda",
        "pre",
        # Small 2-letter codes that match US states
        *US_STATES,
    }
)

VARIANT_PROGRAM_NAMES = frozenset(
    {
        "aspire",
        "rise",
        "revolution",
        "evolution",
        "dynasty",
        "legacy",
        "impact",
        "force",
        "thunder",
        "lightning",
        "blaze",
        "inferno",
        "phoenix",
        "predators",
        "raptors",
        "lions",
        "tigers",
        "bears",
        "eagles",
        "hawks",
        "falcons",
        "united",
        "strikers",
        "raiders",
        "warriors",
        "knights",
        "spartans",
        "titans",
        "trojans",
    }
)

# Age/year patterns used for club extraction and variant detection
_VARIANT_AGE_PATTERNS = [
    r"\bU-?\d{1,2}\b",
    r"\b[BG]?\d{4}[BG]?\b",
    r"\b[BG]\d{2}(?!\d)\b",
    r"\b\d{2}[BG](?!\d)\b",
    r"\b\d{1,2}[Uu]\b",
]

# Age/year regex applied to the raw name string
AGE_PATTERN = re.compile(r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b|\b(\d{1,2})[Uu]\b")

# Pre-compiled patterns for _canonicalize_age_token — this helper runs per token
# during fuzzy duplicate scanning (O(n²) teams-per-cohort) so pattern compilation
# on every call is measurable. See `architecture_age_pattern_drift.md`.
_RE_BIRTH_YEAR_4 = re.compile(r"[bgmf]?(\d{4})[bgmf]?")
_RE_DIGIT_U = re.compile(r"(\d{1,2})u[bgmf]?")
_RE_U_PREFIX = re.compile(r"[bgmf]?u-?(\d{1,2})[bgmf]?")
_RE_2DIGIT_GENDER = re.compile(r"(\d{2})[bgmf]|[bgmf](\d{2})")
_RE_SLASH_DUAL = re.compile(r"(\d{2})/(\d{2})")
_RE_2DIGIT_BARE = re.compile(r"\d{2}")


def _canonicalize_age_token(tok: str) -> str | None:
    """Map any age token to a canonical cohort key like 'u14'.

    Accepts (case-insensitive; caller may pass lowercased and apostrophe-stripped):
      4-digit birth year:   '2012' -> 'u14'
      2-digit shorthand:    '12' via birth-year rule -> 'u14' (apostrophe-strip context)
      U-age form:           'U14', 'u-14' -> 'u14'
      Digit-then-U form:    '14U', '14u' -> 'u14'
      With gender suffix:   '14ub', 'u14b', '14b', 'b14', 'b2012', '2012b' -> canonical + drop gender
      Slash dual-age:       '10/11' -> 'u15' (take LARGER 2-digit year = younger cohort)

    Returns None for:
      - Out-of-range ages (outside U6-U19 after canonicalization)
      - Unrecognized tokens (do NOT fall back to raw — silent drift masks bugs)

    U18 remap:
      U18 is merged into the U19 cohort everywhere else in PitchRank (see AGE_GROUPS,
      scrape_playmetrics_league.derive_team_age_group).

    Slash-form rationale:
      Dual-age divisions are "play-up gates, not cohort labels" — the team is primarily
      the younger cohort (larger 2-digit year). So '10/11 -> 2011 -> U15. A single '10
      resolves to 2010 -> U16, so slash teams remain distinct from single-cohort teams.

    Bare 2-digit rationale:
      In the extract_distinctions path, bare 2-digit strings arrive only from the
      apostrophe-stripped AGE_PATTERN branch ('10, '10/11), where the semantic is
      always birth-year shorthand. Pass-3 callers wrap their emissions with 'u' prefix
      before calling this helper, so U-age inputs never arrive as bare digits here.
    """
    if not tok:
        return None
    t = tok.lower().strip().strip("'")
    if not t:
        return None

    age: int | None = None

    # 4-digit birth year (optionally gender-wrapped): '2012', 'b2012', '2012b'
    m = _RE_BIRTH_YEAR_4.fullmatch(t)
    if m:
        birth_year = int(m.group(1))
        if 1990 <= birth_year <= 2030:
            ag = calculate_age_group_from_birth_year(birth_year)
            if ag:
                age = int(ag[1:])

    # Digit-then-U form with optional gender: '14u', '14ub', '14um'
    if age is None:
        m = _RE_DIGIT_U.fullmatch(t)
        if m:
            age = int(m.group(1))

    # U-prefix form with optional gender prefix/suffix: 'u14', 'u-14', 'u14b', 'bu14'
    if age is None:
        m = _RE_U_PREFIX.fullmatch(t)
        if m:
            age = int(m.group(1))

    # 2-digit shorthand with gender: '14b', 'b14' → birth-year shorthand
    if age is None:
        m = _RE_2DIGIT_GENDER.fullmatch(t)
        if m:
            short = int(m.group(1) or m.group(2))
            birth_year = 2000 + short if short < 30 else 1900 + short
            ag = calculate_age_group_from_birth_year(birth_year)
            if ag:
                age = int(ag[1:])

    # Slash dual-age: '10/11' → take larger 2-digit year (younger cohort)
    if age is None:
        m = _RE_SLASH_DUAL.fullmatch(t)
        if m:
            y1, y2 = int(m.group(1)), int(m.group(2))
            short = max(y1, y2)
            birth_year = 2000 + short if short < 30 else 1900 + short
            ag = calculate_age_group_from_birth_year(birth_year)
            if ag:
                age = int(ag[1:])

    # Bare 2-digit: birth-year shorthand (apostrophe-strip context)
    if age is None:
        m = _RE_2DIGIT_BARE.fullmatch(t)
        if m:
            short = int(t)
            birth_year = 2000 + short if short < 30 else 1900 + short
            ag = calculate_age_group_from_birth_year(birth_year)
            if ag:
                age = int(ag[1:])

    if age is None:
        return None

    if not (6 <= age <= 19):
        return None

    if age == 18:
        age = 19

    return f"u{age}"


# Club-suffix canonicalization (from full_club_analysis.py)
_CLUB_SUFFIX_RE = [
    (re.compile(r"\s+soccer\s+club\s*$", re.I), " sc"),
    (re.compile(r"\s+s\.c\.\s*$", re.I), " sc"),
    (re.compile(r"\s+football\s+club\s*$", re.I), " fc"),
    (re.compile(r"\s+futbol\s+club\s*$", re.I), " fc"),
    (re.compile(r"\s+f\.c\.\s*$", re.I), " fc"),
    (re.compile(r"\s+soccer\s+academy\s*$", re.I), " sa"),
    (re.compile(r"\s+youth\s+soccer\s*$", re.I), ""),
    (re.compile(r"\s+soccer\s+association\s*$", re.I), ""),
    (re.compile(r"\s+soccer\s*$", re.I), ""),
]


# ═══════════════════════════════════════════════════════════════
# Team variant extraction  (color / direction / coach / numeral)
# ═══════════════════════════════════════════════════════════════


def extract_team_variant(name: str) -> Optional[str]:
    """Extract the variant that distinguishes squads within the same club.

    Returns a lowercase string identifying the variant, or None.
    Recognised variant types (checked in priority order):
      1. Color      — "blue", "gold", "navy"
      2. Direction   — "north", "south"
      3. Roman/digit — "ii", "3"
      4. Coach name  — "riedell", "davis" (last-name after age token)
    """
    if not name:
        return None

    name_lower = name.lower()
    words = name_lower.split()

    # 1. Color anywhere in name
    for w in words:
        w_clean = w.strip("-()[]")
        if w_clean in TEAM_COLORS:
            return w_clean

    # 2. Direction
    for w in words:
        w_clean = w.strip("-()[]")
        if w_clean in DIRECTION_CANONICAL:
            return DIRECTION_CANONICAL[w_clean]

    # 3. Roman numerals or single digits (I, II, III, IV, V, 1-10)
    roman_match = re.search(r"\b(i{1,3}|iv|v|vi{0,3})\b", name_lower)
    if roman_match:
        return roman_match.group(1)

    # 4. Coach name detection — look for names AFTER the first age/year token
    age_end_pos = -1
    for pattern in _VARIANT_AGE_PATTERNS:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            age_end_pos = match.end()
            break

    if age_end_pos > 0:
        after_age = name[age_end_pos:].strip()
        # Strip trailing region markers in parens: "(CTX)" → ""
        after_age_clean = re.sub(r"\s*\([^)]+\)\s*$", "", after_age).strip()
        for word in after_age_clean.split():
            wc = word.strip("-()[].,").lower()
            if not wc or len(wc) < 3:
                continue
            if wc in NON_COACH_WORDS:
                continue
            if wc in REGION_CODES_COACH:
                continue
            if wc in VARIANT_PROGRAM_NAMES:
                continue
            if wc in TEAM_COLORS:
                continue
            if wc in DIRECTION_CANONICAL:
                continue
            if wc.isdigit() or re.match(r"^[bug]?\d+", wc):
                continue
            # Looks like a coach name
            return wc

    # 5. Coach name in parentheses: "2014 (Holohan)" (not region codes)
    coach_match = re.search(r"\(([a-z]+)\)\s*$", name_lower)
    if coach_match:
        w = coach_match.group(1)
        if w not in REGION_CODES_COACH and len(w) >= 3:
            return w

    # 6. ALL-CAPS word after year: "2014 THOMPSON"
    caps_match = re.search(r"20\d{2}\s+([A-Z]{4,})\b", name)
    if caps_match:
        w = caps_match.group(1).lower()
        if w not in NON_COACH_WORDS and w not in REGION_CODES_COACH and w not in VARIANT_PROGRAM_NAMES:
            return w

    # 7. Capitalized last word after age portion
    name_parts = name.split()
    if len(name_parts) >= 2:
        last = name_parts[-1]
        lc = last.strip("()[]").lower()
        if (
            last[0].isupper()
            and lc not in TEAM_COLORS
            and lc not in NON_COACH_WORDS
            and lc not in REGION_CODES_COACH
            and lc not in VARIANT_PROGRAM_NAMES
            and lc not in DIRECTION_CANONICAL
            and len(lc) >= 3
            and not re.match(r"^[BG]?\d+", last)
        ):
            return lc

    return None


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
        "colors": frozenset(),
        "directions": frozenset(),
        "programs": frozenset(),
        "team_number": None,
        "location_codes": frozenset(),
        "state_codes": frozenset(),
        "squad_words": frozenset(),
        "age_tokens": (),
        "secondary_nums": (),
        "coach_name": None,
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
            colors.add(tok)
            classified.add(idx)
        elif tok in DIRECTION_CANONICAL:
            directions.add(DIRECTION_CANONICAL[tok])
            classified.add(idx)
        elif tok in PROGRAM_WORDS:
            programs.add(tok)
            classified.add(idx)
        elif tok in LOCATION_CODES:
            location_codes.add(tok)
            classified.add(idx)
        elif tok in NOISE_WORDS:
            classified.add(idx)
        elif tok in US_STATES:
            state_codes.add(tok)
            classified.add(idx)
        elif re.fullmatch(r"(i{1,3}|iv|v|vi{0,3})", tok):
            team_number = tok
            classified.add(idx)
        elif re.fullmatch(r"[1-9]|10", tok):
            team_number = tok
            classified.add(idx)

    # Pass 2: extract canonical age tokens; mask age spans for secondary_nums.
    # Same shape as scripts/find_fuzzy_duplicate_teams.py.extract_distinctions — both
    # must canonicalize so '14U', 'U14', '2012', "'12" all collapse to the same key.
    age_tokens: list = []
    age_spans: list = []
    for m in AGE_PATTERN.finditer(name):
        canonical = _canonicalize_age_token(m.group(0).lower().strip("'"))
        if canonical is not None:
            age_tokens.append(canonical)
        age_spans.append((m.start(), m.end()))

    # Mask all matched age spans before scanning for secondary numbers — otherwise
    # "14U 2012 Rush Union" would emit '2012' as a spurious secondary_num after
    # matching the first age at position 0.
    secondary_nums: list = []
    if age_spans:
        masked_chars = list(name)
        for start, end in age_spans:
            for i in range(start, min(end, len(masked_chars))):
                masked_chars[i] = " "
        masked = "".join(masked_chars)
        first_end = age_spans[0][1]
        secondary_nums = re.findall(r"\d+", masked[first_end:])

    # Pass 3: classify age/gender combo indices; canonicalize emissions.
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        age_gender = re.fullmatch(r"(\d{1,4})u?[bgmf]|[bgmf](\d{1,4})u?|u(\d{1,2})[bgmf]", tok)
        if age_gender:
            # Pass the original token — the helper distinguishes 4-digit birth year,
            # 2-digit shorthand ('14b' -> U12), and U-forms ('u14b' -> U14).
            canonical = _canonicalize_age_token(tok)
            if canonical is not None:
                age_tokens.append(canonical)
            classified.add(idx)
        elif re.fullmatch(r"20\d{2}", tok) or re.fullmatch(r"\d{2}/\d{2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"u-?\d{1,2}|\d{1,2}u", tok) and _canonicalize_age_token(tok) is not None:
            classified.add(idx)
        elif re.fullmatch(r"\d+m?", tok):
            classified.add(idx)

    # Pass 4: remaining unclassified → squad words or location codes
    squad_words: set = set()
    for idx, tok in enumerate(tokens):
        if idx in classified or not tok:
            continue
        if not tok.isalpha() and not tok.isdigit() and len(tok) >= 2:
            squad_words.add(tok)
            continue
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

    # Extract coach name via the variant detector
    coach = extract_team_variant(name)
    # Only keep if the variant is a coach name (not a color/direction/numeral
    # already captured above)
    if coach and (
        coach in colors
        or coach in {DIRECTION_CANONICAL.get(coach, "")}
        or re.fullmatch(r"(i{1,3}|iv|v|vi{0,3}|\d{1,2})", coach)
    ):
        coach = None

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
        "coach_name": coach,
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
    # Coach names: if both present and different → different squads
    if da["coach_name"] and db["coach_name"] and da["coach_name"] != db["coach_name"]:
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
    fuzzy comparison.  Produces a lowercase string with noise removed but
    club identity preserved.
    """
    if not name:
        return ""
    n = name.lower().strip()

    # Join multi-word compound tokens BEFORE stripping league markers
    # so that "ECNL RL" is recognised as a single unit.
    n = re.sub(r"\becnl[\s-]+rl\b", "ecnl-rl", n)
    n = re.sub(r"\bmls[\s-]+next\b", "mls-next", n)
    n = re.sub(r"\bpre[\s-]+ecnl\b", "pre-ecnl", n)

    # Strip league/tier markers (now includes the joined forms)
    n = re.sub(
        r"\b(ecnl-rl|ecnl rl|ecrl|ecnl|pre-ecnl|pre ecnl|mls-next|mls next|"
        r"mlsnext|ga|rl|npl|dpl|dplo|scdsl|copa|nal)\b",
        " ",
        n,
    )
    # Replace dashes with spaces
    n = re.sub(r"\s*-\s*", " ", n)

    # Normalize age formats — strip gender char, keep number
    n = re.sub(r"\b[bg]\s*(\d{2,4})\b", r"\1", n)
    n = re.sub(r"\b(\d{2,4})\s*[bg]\b", r"\1", n)
    n = re.sub(r"\bu\s*(\d+)\b", r"u\1", n)

    # Remove punctuation (except apostrophes in names like O'Brien)
    n = re.sub(r"[^\w\s']", "", n)

    # Remove standalone gender words
    n = re.sub(r"\b(boys?|girls?|male|female)\b", "", n)

    # Compress whitespace
    n = " ".join(n.split())
    return n


# ═══════════════════════════════════════════════════════════════
# Club extraction from team name
# ═══════════════════════════════════════════════════════════════

# Age/year patterns for splitting club from the rest
_AGE_SPLIT_PATTERNS = [
    r"\bU-?\d{1,2}\b",
    r"\b[BG]?\d{4}[BG]?\b",
    r"\b[BG]\d{2}(?!\d)\b",
    r"\b\d{2}[BG](?!\d)\b",
    r"\b\d{1,2}[Uu]\b",
]

_TRAILING_SUFFIXES = [
    re.compile(s, re.I)
    for s in [
        r"\s+(ECNL-RL|ECNL RL|ECRL)\s*$",
        r"\s+ECNL\s*$",
        r"\s+RL\s*$",
        r"\s+PRE-ECNL\s*$",
        r"\s+PRE\s*$",
        r"\s+COMP\s*$",
        r"\s+GA\s*$",
        r"\s+MLS NEXT\s*$",
        r"\s+ACADEMY\s*$",
        r"\s+SELECT\s*$",
        r"\s+PREMIER\s*$",
        r"\s+ELITE\s*$",
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
        club = pat.sub("", club)
    club = club.strip(" -.")

    # Dedup repeated halves ("Kingman SC Kingman SC" → "Kingman SC")
    words = club.split()
    if len(words) >= 4:
        mid = len(words) // 2
        if " ".join(words[:mid]).lower() == " ".join(words[mid : mid * 2]).lower():
            club = " ".join(words[:mid])

    club = " ".join(club.split())
    return club if club and len(club) >= 3 else None


# ═══════════════════════════════════════════════════════════════
# League marker helpers
# ═══════════════════════════════════════════════════════════════


def has_ecnl_rl(name: str) -> bool:
    n = name.lower()
    return " rl" in n or "-rl" in n or "ecnl rl" in n or "ecnl-rl" in n


def has_ecnl_only(name: str) -> bool:
    return "ecnl" in name.lower() and not has_ecnl_rl(name)


def has_protected_division(name: str) -> bool:
    """Names with league-specific division markers should NOT be auto-merged
    across divisions (ECNL ≠ ECNL-RL ≠ MLS NEXT)."""
    n = name.lower()
    return any(kw in n for kw in ("ecnl", "mls next", "mls-next", "ga "))


# ═══════════════════════════════════════════════════════════════
# Inline tests (run via `python -m src.utils.team_name_utils`)
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    import sys

    print(f"=== _canonicalize_age_token (season CURRENT_YEAR={CURRENT_YEAR}) ===")
    # Season-dependent assertions assume CURRENT_YEAR==2025 (2025-26 soccer season).
    # If run off-season these expectations shift with the helper's birth-year math.
    u14_forms = [
        "2012",
        "'12",
        "12",
        "U14",
        "u-14",
        "14U",
        "14u",
        "14ub",
        "u14b",
        "b2012",
        "2012b",
        "12b",
        "b12",
    ]
    passed = failed = 0
    for tok in u14_forms:
        got = _canonicalize_age_token(tok)
        ok = got == "u14"
        status = "✅" if ok else "❌"
        print(f"  {status} _canonicalize_age_token({tok!r:10}) → {got!r} (expected 'u14')")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    # U18 remap: U18 and 2007 birth year both merge into U19
    for tok, expected in [("U18", "u19"), ("2007", "u19")]:
        got = _canonicalize_age_token(tok)
        ok = got == expected
        status = "✅" if ok else "❌"
        print(f"  {status} _canonicalize_age_token({tok!r:10}) → {got!r} (expected {expected!r})")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    # Slash-form: larger 2-digit year (younger cohort) wins, so '10/11 → u15
    for tok, expected in [("10/11", "u15"), ("10", "u16")]:
        got = _canonicalize_age_token(tok)
        ok = got == expected
        status = "✅" if ok else "❌"
        print(f"  {status} _canonicalize_age_token({tok!r:10}) → {got!r} (expected {expected!r})")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    # Out of range / unrecognized → None
    for tok in ["20U", "5U", "2003", "random", ""]:
        got = _canonicalize_age_token(tok)
        ok = got is None
        status = "✅" if ok else "❌"
        print(f"  {status} _canonicalize_age_token({tok!r:10}) → {got!r} (expected None)")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    # AGE_PATTERN recognizes both orderings
    checks = [
        ("Phoenix FC 14U Black", "14U"),
        ("Phoenix FC U14 Black", "U14"),
    ]
    for text, expected in checks:
        m = AGE_PATTERN.search(text)
        got = m.group(0) if m else None
        ok = got == expected
        status = "✅" if ok else "❌"
        print(f"  {status} AGE_PATTERN.search({text!r}).group(0) → {got!r} (expected {expected!r})")
        passed += 1 if ok else 0
        failed += 0 if ok else 1

    # extract_team_variant detects coach name after 14U (uses _VARIANT_AGE_PATTERNS)
    got = extract_team_variant("FC Example 14U Riedell")
    ok = got == "riedell"
    status = "✅" if ok else "❌"
    print(f"  {status} extract_team_variant('FC Example 14U Riedell') → {got!r} (expected 'riedell')")
    passed += 1 if ok else 0
    failed += 0 if ok else 1

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
