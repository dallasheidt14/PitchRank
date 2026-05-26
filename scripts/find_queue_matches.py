#!/usr/bin/env python3
"""
Find matches for team_match_review_queue entries against current teams.

This script:
1. Pulls pending queue entries
2. Searches for matches in the teams table using fuzzy matching
3. Categorizes by match quality
4. Can auto-approve high-confidence matches

Usage:
    python3 scripts/find_queue_matches.py [--dry-run] [--limit 100] [--execute]
"""

import argparse
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client

# Shared structured-distinction logic (also used by find_fuzzy_duplicate_teams.py).
# Path setup mirrors find_fuzzy_duplicate_teams.py — parent for siblings,
# grandparent for src.utils.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _team_distinction import should_skip_pair  # noqa: E402

# Load .env.local if it exists, otherwise fall back to .env
env_path = Path(__file__).parent.parent / ".env.local"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()


def get_supabase():
    """Create Supabase client - same pattern as all other scripts."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

    return create_client(supabase_url, supabase_key)


def normalize_filter_age_group(age_group):
    """Normalize an age group value without merging U18/U19."""
    if not age_group:
        return None
    digits = re.sub(r"[^0-9]", "", str(age_group))
    if not digits:
        return None
    return f"u{int(digits)}"


def build_age_group_filter_clause(age_group):
    """Build a Supabase OR clause for exact age-group matches."""
    normalized = normalize_filter_age_group(age_group)
    if not normalized:
        return None
    values = (normalized, normalized.upper())
    return ",".join(f"age_group.eq.{value}" for value in values)


def normalize_team_name(name):
    """Normalize team name for matching."""
    if not name:
        return ""

    # Lowercase
    n = name.lower().strip()

    # Handle gender tokens. GotSport puts "Boys"/"Girls" as a literal word in
    # team names ("Alaska Rush 2010 Boys White"); masters almost never do.
    # Order matters: catch year-shorthand combos first so "12 Boys" → "2012",
    # then strip standalone "Boys"/"Girls".
    def _expand_2digit(s):
        n_int = int(s)
        return str(2000 + n_int if n_int < 30 else 1900 + n_int)

    n = re.sub(r"\b(\d{2})\s+(boys|girls)\b", lambda m: _expand_2digit(m.group(1)), n)
    n = re.sub(r"\b(boys|girls)\s+(\d{2})\b", lambda m: _expand_2digit(m.group(2)), n)
    n = re.sub(r"\b(boys|girls)\b", " ", n)

    # Remove common suffixes/prefixes
    n = re.sub(r"\s*(ecnl|ecnl-rl|rl|pre-ecnl|mls next|ga|academy)\s*", " ", n)
    n = re.sub(r"\s*-\s*", " ", n)  # Replace dashes with spaces

    # Normalize age formats — expand 2-digit shorthand to full birth year
    # (GotSport: "14B"/"B14" → "2014") so "11G Aspire" can match "2011 Aspire".
    def _expand_year(match_obj):
        digits = next(g for g in match_obj.groups() if g and g.isdigit())
        n_int = int(digits)
        # 00-29 → 20xx, 30-99 → 19xx (covers all realistic youth-soccer birth years)
        full = 2000 + n_int if n_int < 30 else 1900 + n_int
        return str(full)

    n = re.sub(r"\b([bg])\s*(\d{2})\b(?!\d)", _expand_year, n)  # B14 -> 2014
    n = re.sub(r"\b(\d{2})\s*([bg])\b(?!\d)", _expand_year, n)  # 14B -> 2014
    n = re.sub(r"\b([bg])\s*(\d{4})\b", r"\2", n)  # B2014 -> 2014
    n = re.sub(r"\b(\d{4})\s*([bg])\b", r"\1", n)  # 2014B -> 2014
    n = re.sub(r"\bu\s*(\d+)\b", r"u\1", n)  # U 14 -> u14
    n = re.sub(r"\b(\d{1,2})u\b", r"u\1", n)  # 14u -> u14 (digit-then-U form)

    # Remove extra whitespace
    n = " ".join(n.split())

    return n


def extract_club_from_name(provider_team_name):
    """Extract club name from provider team name.

    Logic:
    1. Split on age/year patterns (2014, U14, B2014, etc.)
    2. Take the first part as club name
    3. Remove duplicate words (e.g., "Kingman SC Kingman SC" → "Kingman SC")
    4. Strip common suffixes (ECNL, RL, PRE, COMP)

    Examples:
        "FC Tampa Rangers FCTS 2015 Falcons" → "FC Tampa Rangers FCTS"
        "Phoenix Rising FC B2014 Black" → "Phoenix Rising FC"
        "Kingman SC Kingman SC U14" → "Kingman SC"
        "Real Salt Lake AZ ECNL 2014 Red" → "Real Salt Lake AZ"
    """
    if not provider_team_name:
        return None

    name = provider_team_name.strip()

    # Age/year patterns to split on (from team_name_normalizer.py).
    # Match: U14, U-14, 2014, B2014, 2014B, G2015, 15B, B15, 14U, etc.
    # NOTE: Duplicated inside extract_team_variant and extract_program_tier below;
    # keep in sync until consolidated into src/utils/team_name_utils.py.
    age_patterns = [
        r"\bU-?\d{1,2}\b",  # U14, U-14
        r"\b[BG]?\d{4}[BG]?\b",  # 2014, B2014, 2014B, G2015, 2015G
        r"\b[BG]\d{2}(?!\d)\b",  # B14, G15 (not followed by more digits)
        r"\b\d{2}[BG](?!\d)\b",  # 14B, 15G (not followed by more digits)
        r"\b\d{1,2}[Uu]\b",  # 14U, 14u (digit-then-U age form)
    ]

    # Find the earliest age pattern match
    earliest_pos = len(name)
    for pattern in age_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()

    # Extract club name before the age pattern
    if earliest_pos < len(name):
        club_name = name[:earliest_pos].strip()
    else:
        # No age pattern found, use whole name
        club_name = name

    # Remove common suffixes (case insensitive)
    suffixes = [
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

    for suffix_pattern in suffixes:
        club_name = re.sub(suffix_pattern, "", club_name, flags=re.IGNORECASE)

    # Remove trailing hyphens, dots, and extra whitespace
    club_name = club_name.strip(" -.")

    # Remove duplicate words (e.g., "Kingman SC Kingman SC" → "Kingman SC")
    words = club_name.split()
    if len(words) >= 4:  # Only check if at least 4 words
        # Check if first half == second half
        mid = len(words) // 2
        first_half = " ".join(words[:mid])
        second_half = " ".join(words[mid : mid * 2])
        if first_half.lower() == second_half.lower():
            club_name = first_half

    # Final cleanup
    club_name = " ".join(club_name.split())

    # Don't return empty or too-short club names
    if not club_name or len(club_name) < 3:
        return None

    return club_name


# Common team colors and variants that indicate DIFFERENT teams
TEAM_COLORS = {
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
}

# Direction/location variants that indicate different teams
TEAM_DIRECTIONS = {"north", "south", "east", "west", "central"}

# Trailing-marker punctuation stripped from each token before matching against
# variant/coach/program tables. Must include `'*` so markers like "Blue*" /
# "Bolts'" don't leak into the variant and cause a phantom mismatch against an
# otherwise-identical sibling, and `.,` so coach names like "Riedell," parse
# correctly. Mirrors `_tokenize` in find_fuzzy_duplicate_teams.py and the
# matching constants in src/utils/team_name_utils.py and
# src/models/game_matcher.py — keep all four in sync.
_VARIANT_STRIP_CHARS = "-()[]'*.,"


def extract_team_variant(name, club_name: str = ""):
    """Extract team variant (color, direction, coach name, roman numeral) from team name.

    Teams like 'FC Dallas 2014 Blue' and 'FC Dallas 2014 Gold' are DIFFERENT teams.
    Also 'Select North' and 'Select South' are DIFFERENT teams.
    Coach names like 'Atletico Dallas 15G Riedell' and 'Atletico Dallas 15G Davis' are DIFFERENT teams.

    When ``club_name`` is provided, its words are added to the skip set so that
    club tokens (e.g. 'Union' in 'Rush Union Wisconsin') don't get returned as
    a phantom coach/squad variant when the duplicate side omits the club prefix.
    """
    if not name:
        return None

    name_lower = name.lower()
    words = name_lower.split()

    # Check for color ANYWHERE in name (not just at end)
    for word in words:
        word_clean = word.strip(_VARIANT_STRIP_CHARS)
        if word_clean in TEAM_COLORS:
            return word_clean

    # Check for direction variants (North, South, East, West, Central)
    for word in words:
        word_clean = word.strip(_VARIANT_STRIP_CHARS)
        if word_clean in TEAM_DIRECTIONS:
            return word_clean

    # Check for roman numerals or letter variants (I, II, III, A, B)
    roman_match = re.search(r"\b(i{1,3}|iv|v|vi{0,3})\b", name_lower)
    if roman_match:
        return roman_match.group(1)

    # === ENHANCED COACH NAME DETECTION ===
    # Coach names typically appear AFTER age/year but BEFORE regions/programs
    # Pattern: "Club [Age] [CoachName] (Region)" or "Club [Age] [CoachName] Region"
    # Examples: "15G Riedell (CTX)", "2015 Davis CTX", "2014 Thompson", "U14 Blanton"

    # Known non-coach words to filter out
    common_words = {
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
        "united",
    }

    # Known region codes (3-letter abbreviations, typically in parens or at end)
    region_codes = {
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
        "nj",
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
        "la",
        "ar",
        "mo",
        "ia",
        "ecnl",
        "rl",
        "ga",
        "ea",
        "npl",
        "usys",
        "ayso",
        "scdsl",
        "dpl",
        "mls",
        "ussda",
        "pre",
    }

    # Program/league names that aren't coach names
    program_names = {
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
        # League/program abbreviations (synced from find_fuzzy_duplicate_teams.PROGRAM_WORDS)
        "stxcl",
        "scdsl",
        "dpl",
        "dplo",
        "npl",
        "tal",
        "fdl",
        "copa",
        "nal",
        "comp",
        "recreational",
        "reserve",
        "classic",
        "division",
        "ecrl",
        "regional",
        "showcase",
        "challenge",
        "development",
        "competitive",
        # Common squad/mascot names that appear in team names
        "royal",
        "cosmos",
        "celtic",
        "rovers",
        "arsenal",
        "mustangs",
        "wolves",
        "coyotes",
        "cobras",
        "vipers",
        "hurricanes",
        "cyclones",
        "rebels",
        "chargers",
        "bulldogs",
        "wildcats",
        "jaguars",
        "panthers",
        "mustang",
    }

    # All non-variant words (union of all exclusion sets)
    _skip_words = common_words | region_codes | program_names | TEAM_COLORS | TEAM_DIRECTIONS

    # Club tokens are never variants — strip them so duplicates whose stored
    # name omits the club prefix don't produce a phantom variant from a club word.
    if club_name:
        club_tokens = {w.strip(_VARIANT_STRIP_CHARS).lower() for w in club_name.replace("-", " ").split()}
        _skip_words = _skip_words | (club_tokens - {""})

    def _extract_candidate(text):
        """Find the first unknown word in *text* that looks like a coach/squad name."""
        # Normalize hyphens to spaces so "PRE-ECNL" → "PRE ECNL"
        # (each part checked individually against _skip_words)
        text = text.replace("-", " ")
        for word in text.split():
            w = word.strip(_VARIANT_STRIP_CHARS).lower()
            if not w or len(w) < 3:
                continue
            if w in _skip_words:
                continue
            if w.isdigit() or re.match(r"^[bug]?\d+", w):
                continue
            return w
        return None

    # Find age/year position in the team name — search ALL occurrences and
    # look for a candidate word on EITHER side so word-order doesn't matter.
    # NOTE: Duplicated with extract_club_from_name (above) and extract_program_tier (below).
    age_patterns = [
        r"\bU-?\d{1,2}\b",  # U14, U-14
        r"\b[BG]?\d{4}[BG]?\b",  # 2014, B2014, 2014B, G2015, 2015G
        r"\b[BG]\d{2}(?!\d)\b",  # B14, G15
        r"\b\d{2}[BG](?!\d)\b",  # 14B, 15G
        r"\b\d{1,2}[Uu]\b",  # 14U, 14u (digit-then-U age form)
    ]

    age_match = None
    for pattern in age_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            age_match = match
            break

    if age_match:
        # Look AFTER the age token first (most common position for coach/squad)
        after_age = name[age_match.end() :].strip()
        after_age_clean = re.sub(r"\s*\([^)]+\)\s*$", "", after_age).strip()
        candidate = _extract_candidate(after_age_clean)
        if candidate:
            return candidate

        # Look BEFORE the age token (handles "Arsenal 2014" word order)
        before_age = name[: age_match.start()].strip()
        # Strip known club-name words that appear before the age
        # Only consider the last 1-2 words before the age (coach/squad names
        # sit adjacent to the age, not at the start of the name)
        before_words = before_age.split()
        if before_words:
            tail = " ".join(before_words[-2:])  # last 2 words before age
            candidate = _extract_candidate(tail)
            if candidate:
                return candidate

    # Check for coach names in parentheses: "2014 (Holohan)" but NOT regions like "(CTX)"
    coach_match = re.search(r"\(([a-z]+)\)\s*$", name_lower)
    if coach_match:
        word = coach_match.group(1)
        # Only return if it's not a region code
        if word not in region_codes:
            return word

    return None


def _current_season_year():
    """Return the current season year for birth-year-to-age conversion.

    Youth soccer seasons typically start in August/September, so we use the
    calendar year directly (players born in 2014 are U12 in 2026).
    """
    from datetime import date

    return date.today().year


def extract_age_group(name, details):
    """Extract age group from name - ALWAYS parse from name first, metadata is unreliable."""
    name_lower = name.lower() if name else ""
    season_year = _current_season_year()

    # Priority 1: U-age format (U13, U14, etc)
    match = re.search(r"\bu(\d+)\b", name_lower)
    if match:
        return normalize_filter_age_group(match.group(1))

    # Priority 1b: digit-then-U form (14U, 14u) — route through the same
    # normalizer as Priority 1 so "18U" and "U18" don't produce different cohorts.
    # _canonicalize_age_token is not used here because it remaps U18 -> U19, which
    # would diverge from Priority 1's normalize_filter_age_group (preserves U18).
    match = re.search(r"\b(\d{1,2})u\b", name_lower)
    if match:
        return normalize_filter_age_group(match.group(1))

    # Priority 2: Birth year with gender prefix (G13, B2014, 2013G, etc)
    # G13/B13 = 2013 birth year, G2014/B2014 = 2014 birth year
    match = re.search(r"[bg](\d{2})(?!\d)", name_lower)  # G13, B14 (2-digit)
    if match:
        short_year = int(match.group(1))
        year = 2000 + short_year if short_year < 50 else 1900 + short_year
        age = season_year - year
        return normalize_filter_age_group(age)

    match = re.search(r"[bg](20\d{2})", name_lower)  # G2013, B2014 (4-digit)
    if match:
        year = int(match.group(1))
        age = season_year - year
        return normalize_filter_age_group(age)

    # Priority 3: Standalone 4-digit birth year
    match = re.search(r"\b(20\d{2})\b", name)
    if match:
        year = int(match.group(1))
        age = season_year - year
        return normalize_filter_age_group(age)

    # Fallback: use metadata only if nothing found in name
    if details and details.get("age_group"):
        return normalize_filter_age_group(details["age_group"])

    return None


def extract_gender(name, details):
    """Extract gender from name or details."""
    if details and details.get("gender"):
        return details["gender"].lower()

    name_lower = name.lower()
    if " g20" in name_lower or " g1" in name_lower or "girls" in name_lower:
        return "female"
    if " b20" in name_lower or " b1" in name_lower or "boys" in name_lower:
        return "male"

    return None


# League / program / tier tokens that distinguish teams within the same club.
# Order matters: longer tokens must come first so "pre-ecnl" is matched before "ecnl".
PROGRAM_TIERS = [
    "ecnl-rl",
    "ecnl rl",
    "ecrl",
    "pre-ecnl",
    "pre ecnl",
    "ecnl",
    "mls next",
    "mlsnext",
    "ga",
    "pre-dplo",
    "dplo",
    "dpl",
    "npl",
    "rl",
    "elite",
    "premier",
    "select",
    "academy",
    "classic",
    "comp",
    "recreational",
    "reserve",
    "showcase",
    "challenge",
    "competitive",
    "development",
]

# Short tokens (2 chars) that appear after age group and distinguish teams
# e.g. "Chelsea SC - B2014 OG" vs "Chelsea SC DC 2014"
SHORT_BRANCH_TOKENS = {"og", "dc", "ac", "sc", "fc", "sa", "sb"}


def extract_program_tier(name):
    """Extract league/program/tier from a team name.

    Returns the first matching program token found in the name, or None.
    This is used to prevent merging teams from the same club but different
    programs (e.g. GA vs PRE-ECNL, Elite vs Pre-DPLO).
    """
    if not name:
        return None
    name_lower = name.lower()

    for token in PROGRAM_TIERS:
        # Use word-boundary matching to avoid partial matches
        pattern = r"\b" + re.escape(token).replace(r"\ ", r"[\s-]") + r"\b"
        if re.search(pattern, name_lower):
            return token

    # Check for short branch tokens that appear AFTER an age/year pattern.
    # NOTE: Duplicated with extract_club_from_name and extract_team_variant above.
    age_patterns = [
        r"\bU-?\d{1,2}\b",
        r"\b[BG]?\d{4}[BG]?\b",
        r"\b[BG]\d{2}(?!\d)\b",
        r"\b\d{2}[BG](?!\d)\b",
        r"\b\d{1,2}[Uu]\b",
    ]
    age_end = 0
    for pattern in age_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match and match.end() > age_end:
            age_end = match.end()

    if age_end > 0:
        after_age = name[age_end:].strip(" -")
        after_words = after_age.lower().split()
        if after_words:
            first_word = after_words[0].strip(_VARIANT_STRIP_CHARS)
            if first_word in SHORT_BRANCH_TOKENS:
                return first_word

    return None


def has_protected_division(name):
    """Check if team name contains AD, HD, or MLS NEXT - needs manual review."""
    if not name:
        return False
    name_upper = name.upper()
    # Check for division markers
    if " AD" in name_upper or "_AD" in name_upper or "-AD" in name_upper:
        return True
    if " HD" in name_upper or "_HD" in name_upper or "-HD" in name_upper:
        return True
    if "MLS NEXT" in name_upper or "MLSNEXT" in name_upper:
        return True
    if " EA" in name_upper or "_EA" in name_upper:  # Elite Academy
        return True
    return False


# Tier tokens to look for in the provider team name. If the provider name
# contains one of these and exactly one near-tied candidate has the matching
# program_tier, that candidate wins the tiebreak.
PROGRAM_TIER_TOKENS = {
    "pre-academy": "pre-academy",
    "pre academy": "pre-academy",
    "academy": "academy",
    "pre-dpl": "pre-dpl",
    "pre dpl": "pre-dpl",
    "dpl": "dpl",
    "ecnl-rl": "ecnl-rl",
    "ecnl rl": "ecnl-rl",
    "pre-ecnl": "pre-ecnl",
    "pre ecnl": "pre-ecnl",
    "ecnl": "ecnl",
    "mls next": "mls-next",
    "mlsnext": "mls-next",
    "elite": "elite",
    "premier": "premier",
    "select": "select",
    "ga": "ga",
}


def _provider_tier_token(provider_team_name):
    """Return the canonical program_tier string a provider name carries, or None.

    Longest-match first so 'pre-academy' wins over 'academy', etc. Word-boundary
    matching so 'ga' doesn't match inside 'yoga' and 'elite' doesn't match
    inside a longer word — false-positive tier detection would feed the
    auto-resolve tiebreak path and could pick the wrong master.
    """
    if not provider_team_name:
        return None
    # Replace non-word non-space chars with spaces so hyphens act as boundaries
    # ("pre-academy" → "pre academy"), then pad the whole string with spaces so
    # each token check can require leading and trailing space alignment.
    normalized = re.sub(r"[^\w\s]+", " ", provider_team_name.lower())
    padded = f" {' '.join(normalized.split())} "
    # Longest token first so 'pre-academy' / 'pre academy' wins over 'academy'.
    for token, canonical in sorted(PROGRAM_TIER_TOKENS.items(), key=lambda kv: -len(kv[0])):
        # Normalize the token the same way the input was normalized so the
        # space-padded boundary check works consistently.
        norm_token = re.sub(r"[^\w\s]+", " ", token)
        norm_token = " ".join(norm_token.split())
        if f" {norm_token} " in padded:
            return canonical
    return None


def _extract_birth_year_token(name):
    """Extract the birth year a team name encodes, as a 4-digit string.

    Recognized forms (in priority order):
      - 4-digit year: '2013', 'B2009', 'G2010'
      - 2-digit token with B/G affix: '13B', '14G', 'B14', 'G09', '09G'

    Returns None when no year-like token is present (e.g. 'Palatine Celtic U19 Black').
    Caller uses None as "year unknown — don't apply year guard".

    Note: PitchRank's convention is BIRTH YEAR, not USYS cohort. '14B' means born
    2014 (U12 in 2025-26 season), NOT U14. See age_token_birth_year_convention memory.
    """
    if not name:
        return None
    # 4-digit year first — most reliable. Covers '2013', '2014B' (right-side
    # letter), 'B2009' and 'G2010' (left-side letter). `\b` would not match
    # between B and 2 (both word chars), so use explicit non-digit lookarounds.
    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", name)
    if m:
        return m.group(1)
    # 2-digit age token, must be flanked by B or G to distinguish from jersey numbers, etc.
    m = re.search(r"(?:^|[\s\-/])(?:[BG](\d{2})|(\d{2})[BG])(?=[\s\-/]|$)", name)
    if m:
        token = m.group(1) or m.group(2)
        n = int(token)
        if 7 <= n <= 19:  # plausible birth-year range: 2007-2019
            return f"20{token}"
    return None


def _has_club_anchor(name):
    """Heuristic gate against bare-name matches like 'Warriors', 'Inter', '12G GA'.

    Stored-tiebreak resolution operates without DB-side club_name validation, so
    when the provider name is just an age/program token (no proper noun anchor)
    the resolver can confidently merge two unrelated 'Warriors' teams. Require
    at least 3 whitespace-separated tokens — every legitimate match in the
    2026-05-25 failure sample has ≥3 tokens, every bad one has ≤2.
    """
    if not name:
        return False
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    return len(tokens) >= 3


def resolve_via_stored_candidates(queue_entry):
    """Resolve a queue row using the candidates JSON stored at scrape time.

    Returns ``(match_dict, score, method)`` when stored candidates yield an
    unambiguous winner via one of the tiebreak rules. Returns ``(None, 0, None)``
    when no clear winner emerges and the caller should fall through to the
    fuzzy matcher.

    Tiebreaks (applied to candidates within 0.015 of the top score):
    1. **Unique normalized_name_exact** — only one candidate normalizes to an
       exact name match.
    2. **Unique search_age_exact** — only one candidate is the exact age;
       others are play-up/down neighbors.
    3. **Unique state_code** matching the candidate's own state_code — when
       multiple legitimate teams share a normalized name across states, pick
       the one whose state matches the suggested master's state context.
    4. **Unique program_tier** matching a tier token in the provider name —
       e.g., provider has 'DPL' and only one candidate has program_tier='dpl'.

    Pure resolution from already-stored data — no DB queries, no
    normalization, no scoring. Safe to run on the full backlog.
    """
    details = queue_entry.get("match_details") or {}
    candidates = details.get("candidates") or []
    if not candidates:
        return None, 0.0, None

    # Guard: stored tiebreaks bypass DB-side club_name validation. Refuse to
    # resolve provider names without a club anchor (bare 'Warriors', '12G GA').
    provider_name = queue_entry.get("provider_team_name") or ""
    if not _has_club_anchor(provider_name):
        return None, 0.0, None

    # Drop deprecated masters and anything below 0.90 raw score
    candidates = [c for c in candidates if not c.get("is_deprecated") and (c.get("score") or 0) >= 0.90]
    if not candidates:
        return None, 0.0, None

    best = candidates[0]
    best_score = best.get("score") or 0.0
    near_tied = [c for c in candidates[1:] if (best_score - (c.get("score") or 0.0)) <= 0.015]

    # Guard: when both names carry a birth-year token, require agreement.
    # Catches off-by-year drift (e.g. 'Dynamos SC 14B SC' → 'Dynamos SC 2013 SC')
    # where the resolver picked a sibling-year team in the same club.
    provider_year = _extract_birth_year_token(provider_name)
    best_year = _extract_birth_year_token(best.get("team_name"))
    if provider_year and best_year and provider_year != best_year:
        return None, 0.0, None

    def _winner(rule):
        return (
            {
                "team_id_master": best.get("team_id_master"),
                "team_name": best.get("team_name"),
                "club_name": best.get("club_name"),
                "age_group": best.get("age_group"),
                "gender": best.get("gender"),
                "state_code": best.get("state_code"),
            },
            best_score,
            f"stored_tiebreak:{rule}",
        )

    # Sole candidate above the floor → not a tiebreak case, just a strong match
    if not near_tied:
        if best_score >= 0.93 and best.get("age_match_kind") == "search_age_exact":
            return _winner("sole_strong_candidate")
        return None, 0.0, None

    # Rule 1: unique normalized_name_exact
    if best.get("normalized_name_exact") and not any(c.get("normalized_name_exact") for c in near_tied):
        return _winner("normalized_name_exact")

    # Rule 2: unique search_age_exact (vs play_up_or_neighbor)
    if best.get("age_match_kind") == "search_age_exact" and not any(
        c.get("age_match_kind") == "search_age_exact" for c in near_tied
    ):
        return _winner("search_age_exact")

    # Rule 3: unique program_tier matching a tier token in the provider name
    provider_tier = _provider_tier_token(queue_entry.get("provider_team_name"))
    if provider_tier:
        best_tier = (best.get("program_tier") or "").lower() or None
        if best_tier == provider_tier and not any(
            (c.get("program_tier") or "").lower() == provider_tier for c in near_tied
        ):
            return _winner("program_tier")

    return None, 0.0, None


def _cohort_fallback_candidates(supabase, gender, age_group, state_code, limit=200):
    """Broad candidate fetch when club_name lookups have all failed.

    Pulls up to ``limit`` teams matching gender + age_group (+ state_code
    when available). Caller is expected to filter the result via
    should_skip_pair to drop obvious mismatches before scoring. Returns
    [] when gender or age_group is missing (cohort too broad to be useful).
    """
    if not gender or not age_group:
        return []

    query = supabase.table("teams").select(
        "id, team_id_master, team_name, club_name, gender, age_group, state_code"
    )
    query = query.ilike("gender", gender)
    age_clause = build_age_group_filter_clause(age_group)
    if age_clause:
        query = query.or_(age_clause)
    if state_code:
        query = query.eq("state_code", state_code)
    query = query.limit(limit)
    result = query.execute()
    return result.data or []


def _stored_club_looks_wrong(stored_club, provider_team_name):
    """Heuristic: does match_details.club_name appear to disagree with provider_team_name?

    Returns True when stored_club has at least one >=4-char token AND none of
    those long tokens appear (case-insensitive substring) in provider_team_name.
    Catches scraper bugs that wrote the wrong club_name (e.g. La Roca FC
    tagged as "LOS ANGELES SC"). Short tokens are ignored — acronyms like
    "EBU" can legitimately map to a full club name like "Elmbrook United"
    and we don't want to misclassify those, but if we do, the calling code
    will fall back to the stored value anyway, so a false positive just
    costs one extra DB query.
    """
    if not stored_club or not provider_team_name:
        return False
    long_tokens = [t for t in stored_club.lower().split() if len(t) >= 4]
    if not long_tokens:
        return False
    provider_lower = provider_team_name.lower()
    return not any(tok in provider_lower for tok in long_tokens)


def find_best_match(queue_entry, supabase, teams_cache):
    """Find the best matching team for a queue entry using Supabase client."""
    name = queue_entry["provider_team_name"]
    details = queue_entry["match_details"] or {}
    club_name = details.get("club_name", "")

    # Skip protected divisions - need manual review
    if has_protected_division(name):
        return None, 0.0, "protected_division"

    # Try stored-candidates tiebreaks first — much cheaper than the DB
    # fuzzy path and handles the cases the scrape-time matcher punted on
    # because raw scores tied (Alaska Rush / Arizona SC DPL / Dynamos SC).
    if not getattr(find_best_match, "_disable_tiebreaks", False):
        tb_match, tb_score, tb_method = resolve_via_stored_candidates(queue_entry)
        if tb_match is not None:
            return tb_match, tb_score, tb_method

    # Capture both club_name sources up front so we can try each independently.
    extracted_club = extract_club_from_name(name)
    stored_club = club_name  # may be ""

    norm_name = normalize_team_name(name)
    age_group = extract_age_group(name, details)
    gender = extract_gender(name, details)
    queue_variant = extract_team_variant(name)
    queue_program = extract_program_tier(name)

    # Build the per-attempt query factory so each lookup attempt gets a clean
    # query (Supabase query builders are mutable and chained calls aren't safe to reuse).
    def _build_base_query():
        q = supabase.table("teams").select(
            "id, team_id_master, team_name, club_name, gender, age_group, state_code"
        )
        if gender:
            q = q.ilike("gender", gender)
        if age_group:
            age_clause = build_age_group_filter_clause(age_group)
            if age_clause:
                q = q.or_(age_clause)
        return q

    def _lookup_state(club):
        if not club:
            return None
        r = (
            supabase.table("teams")
            .select("state_code")
            .ilike("club_name", f"%{club}%")
            .not_.is_("state_code", "null")
            .limit(1)
            .execute()
        )
        return r.data[0]["state_code"] if r.data else None

    def _fetch_with_club(club, state):
        if not club:
            return []
        q = _build_base_query().ilike("club_name", f"%{club}%")
        if state:
            q = q.eq("state_code", state)
        return q.limit(50).execute().data or []

    # Decide which club to try first. When the stored value looks wrong, prefer
    # the extracted one — but always pull candidates from BOTH and merge them,
    # so the scorer can pick the best across the union (avoids false-negative
    # cases where the heuristic mis-flags stored data and the primary lookup
    # produces only low-scoring candidates — Codex P1 on PR #829).
    if stored_club and _stored_club_looks_wrong(stored_club, name) and extracted_club:
        primary_club, secondary_club = extracted_club, stored_club
        primary_method, secondary_method = "fuzzy_re_derived_club", "fuzzy"
    else:
        primary_club = stored_club or extracted_club
        secondary_club = extracted_club if (stored_club and extracted_club and stored_club != extracted_club) else None
        primary_method = "fuzzy"
        secondary_method = "fuzzy_re_derived_club"

    # Use the chosen primary_club for downstream should_skip_pair / exact-club
    # boost when stored_club was empty (Codex P2 on PR #829: club_name was
    # never updated to reflect what extract_club_from_name found, so the
    # exact-club boost and structured-distinction gate lost signal).
    if not club_name and primary_club:
        club_name = primary_club

    primary_state = _lookup_state(primary_club)
    primary_candidates = _fetch_with_club(primary_club, primary_state)
    secondary_state = None
    secondary_candidates = []
    if secondary_club:
        secondary_state = _lookup_state(secondary_club)
        secondary_candidates = _fetch_with_club(secondary_club, secondary_state)

    # Merge with provenance so the scorer's winner can be attributed back to
    # the primary or secondary path.
    candidates = []
    seen_ids = set()
    for c in primary_candidates:
        tid = c.get("team_id_master")
        if tid and tid not in seen_ids:
            c["_source"] = "primary"
            candidates.append(c)
            seen_ids.add(tid)
    for c in secondary_candidates:
        tid = c.get("team_id_master")
        if tid and tid not in seen_ids:
            c["_source"] = "secondary"
            candidates.append(c)
            seen_ids.add(tid)

    state_code = primary_state or secondary_state

    # Cohort fallback — broad search filtered by should_skip_pair.
    if not candidates:
        cohort = _cohort_fallback_candidates(supabase, gender, age_group, state_code)
        for c in cohort:
            if not should_skip_pair(name, c["team_name"], club_name=club_name or "", require_age_token_match=False):
                c["_source"] = "cohort"
                candidates.append(c)

    if not candidates:
        return None, 0.0, "no_candidates"

    # Score each candidate
    best_match = None
    best_score = 0.0
    best_source = None

    # Check for league markers in queue name
    name_lower = name.lower()
    has_rl = " rl" in name_lower or "-rl" in name_lower or "ecnl rl" in name_lower or "ecnl-rl" in name_lower
    has_ecnl = "ecnl" in name_lower and not has_rl

    for team in candidates:
        team_norm = normalize_team_name(team["team_name"])
        team_lower = team["team_name"].lower()
        team_variant = extract_team_variant(team["team_name"])
        team_program = extract_program_tier(team["team_name"])

        # CRITICAL: Variants must match EXACTLY
        if queue_variant != team_variant:
            continue

        # CRITICAL: Program/tier must match if either side has one
        # e.g. "GA" != "PRE-ECNL", "Elite" != "Pre-DPLO"
        if queue_program != team_program:
            continue

        # Structured-distinction gate (shared with find_fuzzy_duplicate_teams.py):
        # skip candidates whose colors, directions, programs, etc. differ from
        # the provider name. require_age_token_match=False because the Supabase
        # query above already filtered by age_group — if the provider name
        # itself omits an age token, valid masters with "2012" in their names
        # shouldn't be rejected (Codex P1 on PR #827).
        if should_skip_pair(name, team["team_name"], club_name=club_name or "", require_age_token_match=False):
            continue

        # Calculate similarity
        score = SequenceMatcher(None, norm_name, team_norm).ratio()

        # Boost if club name matches exactly
        if club_name and team["club_name"] and club_name.lower() == team["club_name"].lower():
            score = min(1.0, score + 0.15)

        # League matching: penalize mismatches, boost matches
        team_has_rl = " rl" in team_lower or "-rl" in team_lower or "ecnl rl" in team_lower
        team_has_ecnl = "ecnl" in team_lower and not team_has_rl

        if has_rl and team_has_rl:
            score = min(1.0, score + 0.05)
        elif has_ecnl and team_has_ecnl and not team_has_rl:
            score = min(1.0, score + 0.05)
        elif has_rl != team_has_rl:
            score = max(0.0, score - 0.08)

        if score > best_score:
            best_score = score
            best_source = team.get("_source")
            best_match = {
                "id": team["id"],
                "team_id_master": team["team_id_master"],
                "team_name": team["team_name"],
                "club_name": team["club_name"],
                "gender": team["gender"],
                "age_group": team["age_group"],
            }

    if best_score >= 0.7:
        if best_source == "cohort":
            chosen_method = "fuzzy_cohort_fallback"
        elif best_source == "secondary":
            chosen_method = secondary_method
        else:
            chosen_method = primary_method
        return best_match, best_score, chosen_method

    return None, 0.0, "low_confidence"


def analyze_queue(limit=100, min_confidence=0.90, force=False):
    """Analyze queue entries and find matches using Supabase client.

    Args:
        limit: Max number of entries to analyze. 0 means no cap — process every pending entry.
        min_confidence: Minimum confidence score (unused, kept for compatibility)
        force: If True, ignore last_analyzed_at filter and reprocess all pending entries
    """
    supabase = get_supabase()

    # Fetch pending queue entries with pagination (Supabase caps at 1000 per request)
    all_entries = []
    page_size = 1000
    offset = 0
    unlimited = not limit  # limit=0 (or None) → drain entire queue

    while unlimited or len(all_entries) < limit:
        fetch_size = page_size if unlimited else min(page_size, limit - len(all_entries))

        query = (
            supabase.table("team_match_review_queue")
            .select("id, provider_id, provider_team_id, provider_team_name, match_details, confidence_score")
            .eq("status", "pending")
            .order("created_at")
            .order("id")  # stable secondary key for offset pagination
        )

        if not force:
            # Skip recently analyzed entries (use or_ for NULL check)
            query = query.or_("last_analyzed_at.is.null,last_analyzed_at.lt.now()-7d")

        result = query.range(offset, offset + fetch_size - 1).execute()

        if not result.data:
            break

        all_entries.extend(result.data)

        if len(result.data) < fetch_size:
            break

        offset += fetch_size
        print(f"  Fetched {len(all_entries)} entries so far...")

    entries = all_entries if unlimited else all_entries[:limit]

    results = {
        "exact": [],  # 95%+ match
        "high": [],  # 90-94% match
        "medium": [],  # 80-89% match
        "low": [],  # 70-79% match
        "no_match": [],  # < 70% or no candidates
    }

    print(f"Analyzing {len(entries)} queue entries...")
    print()

    for i, entry in enumerate(entries):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(entries)}...")

        # Refresh Supabase client every 1000 entries to avoid HTTP/2 connection timeout
        if i > 0 and i % 1000 == 0:
            supabase = get_supabase()
            print(f"  🔄 Refreshed Supabase connection at entry {i}")

        # Retry logic for transient connection errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                match, score, method = find_best_match(entry, supabase, None)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    import time

                    print(f"  ⚠️  Connection error at entry {i}, retrying ({attempt + 1}/{max_retries})...")
                    supabase = get_supabase()  # Fresh connection
                    time.sleep(2)
                else:
                    print(f"  ❌ Failed after {max_retries} retries at entry {i}: {e}")
                    match, score, method = None, 0.0, "error"

        result = {"queue_entry": entry, "match": match, "score": score, "method": method}

        if score >= 0.95:
            results["exact"].append(result)
        elif score >= 0.90:
            results["high"].append(result)
        elif score >= 0.80:
            results["medium"].append(result)
        elif score >= 0.70:
            results["low"].append(result)
        else:
            results["no_match"].append(result)

    # Mark ALL analyzed entries with timestamp so we skip them next run
    analyzed_ids = [e["id"] for e in entries]
    if analyzed_ids:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        # Update in batches (Supabase has limits on IN clauses)
        batch_size = 100
        for i in range(0, len(analyzed_ids), batch_size):
            batch = analyzed_ids[i : i + batch_size]
            supabase.table("team_match_review_queue").update({"last_analyzed_at": now_iso}).in_("id", batch).eq(
                "status", "pending"
            ).execute()
        print(f"  Marked {len(analyzed_ids)} entries as analyzed")

    return results


def display_results(results, verbose=False):
    """Display analysis results."""
    print("=" * 70)
    print("MATCH ANALYSIS RESULTS")
    print("=" * 70)
    print(f"✅ EXACT (95%+):    {len(results['exact']):>5} - Safe to auto-merge")
    print(f"🟢 HIGH (90-94%):   {len(results['high']):>5} - Likely safe")
    print(f"🟡 MEDIUM (80-89%): {len(results['medium']):>5} - Review recommended")
    print(f"🟠 LOW (70-79%):    {len(results['low']):>5} - Manual review needed")
    print(f"❌ NO MATCH:        {len(results['no_match']):>5} - Need to create new team")
    print()

    # Breakdown by resolution method — surfaces how many rows landed via the
    # cheap stored-candidate tiebreaks vs the DB fuzzy-search fallback.
    method_counts = {}
    for bucket in ("exact", "high", "medium", "low", "no_match"):
        for r in results.get(bucket, []):
            method_counts[r.get("method") or "unknown"] = method_counts.get(r.get("method") or "unknown", 0) + 1
    if method_counts:
        print("Resolution method breakdown:")
        for method, n in sorted(method_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {method:<40} {n:>6}")
        print()

    # Show exact matches
    if results["exact"]:
        print("=" * 70)
        print("✅ EXACT MATCHES (Safe to auto-merge)")
        print("=" * 70)
        for r in results["exact"][:15]:
            q = r["queue_entry"]
            m = r["match"]
            print(f"  [{q['id']}] {q['provider_team_name']}")
            print(f"       → {m['team_name']} ({m['club_name']})")
            print(f"       Score: {r['score']:.1%} | {q['provider_id']}")
            print()

        if len(results["exact"]) > 15:
            print(f"  ... and {len(results['exact']) - 15} more")
        print()

    # Show high matches
    if results["high"] and verbose:
        print("=" * 70)
        print("🟢 HIGH CONFIDENCE MATCHES")
        print("=" * 70)
        for r in results["high"][:10]:
            q = r["queue_entry"]
            m = r["match"]
            print(f"  [{q['id']}] {q['provider_team_name']}")
            print(f"       → {m['team_name']} ({m['club_name']})")
            print(f"       Score: {r['score']:.1%}")
            print()


def execute_merges(results, dry_run=True, min_confidence=0.95):
    """Execute auto-merges for high-confidence matches using Supabase client."""
    candidates = results["exact"]
    if min_confidence < 0.95:
        candidates = candidates + results["high"]

    if not candidates:
        print("No candidates to merge.")
        return 0, 0

    if dry_run:
        print(f"\n🔍 DRY RUN - Would merge {len(candidates)} entries\n")
    else:
        print(f"\n⚡ EXECUTING {len(candidates)} merges\n")

    supabase = get_supabase()

    # Cache provider lookups
    provider_cache = {}

    approved = 0
    failed = 0

    for r in candidates:
        q = r["queue_entry"]
        m = r["match"]

        try:
            if not dry_run:
                # Get provider UUID (cached)
                provider_code = q["provider_id"]
                if provider_code not in provider_cache:
                    provider_result = (
                        supabase.table("providers").select("id").eq("code", provider_code).limit(1).execute()
                    )
                    if not provider_result.data:
                        raise ValueError(f"Provider not found: {provider_code}")
                    provider_cache[provider_code] = provider_result.data[0]["id"]
                provider_uuid = provider_cache[provider_code]

                # Cap score at 0.99 for alias table
                db_score = min(0.99, r["score"])

                # Create alias - use team_id_master (FK target), NOT id
                supabase.table("team_alias_map").upsert(
                    {
                        "team_id_master": m["team_id_master"],
                        "provider_id": provider_uuid,
                        "provider_team_id": q["provider_team_id"],
                        "match_confidence": db_score,
                        "match_method": "fuzzy_auto",
                        "review_status": "approved",
                    },
                    on_conflict="provider_id,provider_team_id",
                    ignore_duplicates=True,
                ).execute()

                # Update queue. suggested_master_team_id holds team_id_master,
                # not teams.id — the review view joins ON teams.team_id_master =
                # q.suggested_master_team_id (see 20240201000003_add_match_review_queue.sql).
                from datetime import datetime, timezone

                supabase.table("team_match_review_queue").update(
                    {
                        "status": "approved",
                        "suggested_master_team_id": m["team_id_master"],
                        "reviewed_by": "auto-merge-script",
                        "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", q["id"]).execute()

            approved += 1
            action = "Would merge" if dry_run else "Merged"
            print(f"  ✅ {action}: {q['provider_team_name']} → {m['team_name']} ({r['score']:.1%})")

        except Exception as e:
            failed += 1
            print(f"  ❌ Failed [{q['id']}]: {e}")

    return approved, failed


def main():
    parser = argparse.ArgumentParser(description="Find matches for queue entries")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max entries to analyze (default: 200; 0 = no cap, drain all pending)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show more details")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Show what would be merged (default)")
    parser.add_argument("--execute", action="store_true", help="Actually execute merges")
    parser.add_argument(
        "--include-high", action="store_true", help="Include 90%+ matches in auto-merge (not just 95%+)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt (for CI/automation)")
    parser.add_argument(
        "--force", action="store_true", help="Reprocess all pending entries (ignore last_analyzed_at filter)"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("🔍 QUEUE MATCH FINDER")
    print("=" * 70)
    print(f"Analyzing up to {args.limit} queue entries...")
    if args.force:
        print("⚡ FORCE mode: Reprocessing all pending entries")
    print()

    results = analyze_queue(limit=args.limit, force=args.force)
    display_results(results, verbose=args.verbose)

    # Execute if requested
    min_conf = 0.90 if args.include_high else 0.95

    if args.execute:
        total = len(results["exact"])
        if args.include_high:
            total += len(results["high"])

        if args.yes:
            print(f"\n⚠️  Auto-confirming merge of {total} entries (--yes flag)")
            approved, failed = execute_merges(results, dry_run=False, min_confidence=min_conf)
            print(f"\n✅ Approved: {approved}, ❌ Failed: {failed}")
        else:
            confirm = input(f"\n⚠️  Merge {total} entries? Type 'yes' to confirm: ")
            if confirm.lower() == "yes":
                approved, failed = execute_merges(results, dry_run=False, min_confidence=min_conf)
                print(f"\n✅ Approved: {approved}, ❌ Failed: {failed}")
            else:
                print("Cancelled.")
    else:
        approved, _ = execute_merges(results, dry_run=True, min_confidence=min_conf)
        print(f"\n📊 DRY RUN: {approved} would be merged")
        print("\nTo execute, run with --execute")


def _run_inline_tests() -> int:
    """Exercise the 14U canonicalization path. Returns non-zero on failure."""
    passed = failed = 0

    def check(desc: str, cond: bool) -> None:
        nonlocal passed, failed
        status = "✅" if cond else "❌"
        print(f"  {status} {desc}")
        if cond:
            passed += 1
        else:
            failed += 1

    # normalize_team_name rewrites digit-then-U form
    got = normalize_team_name("Team 14U Blue")
    check(f"normalize_team_name('Team 14U Blue') == 'team u14 blue' (got {got!r})", got == "team u14 blue")
    got = normalize_team_name("Team U14 Blue")
    check(f"normalize_team_name('Team U14 Blue') == 'team u14 blue' (got {got!r})", got == "team u14 blue")

    # extract_age_group returns same cohort for both 14U and U14 orderings
    a = extract_age_group("FC Example 14U", {})
    b = extract_age_group("FC Example U14", {})
    check(f"extract_age_group '14U' == 'U14' (got {a!r} vs {b!r})", a == b and a is not None)

    # Birth year and digit-U form resolve to the same cohort
    a = extract_age_group("FC Example 2012", {})
    b = extract_age_group("FC Example 14U", {})
    check(f"extract_age_group '2012' == '14U' (got {a!r} vs {b!r})", a == b and a is not None)

    # U18/U19 parity: Priority 1 and 1b must agree on the same cohort.
    # Previously Priority 1b routed through _canonicalize_age_token which remaps
    # U18 -> U19, diverging from Priority 1's normalize_filter_age_group.
    a = extract_age_group("FC Example U18", {})
    b = extract_age_group("FC Example 18U", {})
    check(f"extract_age_group 'U18' == '18U' (got {a!r} vs {b!r})", a == b and a is not None)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_run_inline_tests())
    main()
