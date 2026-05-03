#!/usr/bin/env python3
"""
Team Name Normalizer for PitchRank

Parses team names into structured components:
- Club name
- Age (normalized to U-age format)
- Gender (Male/Female)
- Squad identifier (color, Roman numeral, coach, division, etc.)

Key rules:
- B/G = gender (Boys/Girls), NOT part of age
- No "U" prefix = birth year (14B = 2014 Boys = U12 Male)
- "U" prefix = age group (U14B = U14 Boys = U14 Male)
- ECNL ≠ ECNL-RL (different tiers)
"""

import re
from typing import Dict, Optional, Tuple

# Known squad identifiers (things that distinguish teams within same club/age)
COLORS = {
    "black",
    "blue",
    "red",
    "white",
    "navy",
    "gold",
    "orange",
    "green",
    "silver",
    "gray",
    "grey",
    "purple",
    "yellow",
    "pink",
    "maroon",
    "teal",
}

DIVISIONS = {
    "premier",
    "elite",
    "academy",
    "select",
    "classic",
    "competitive",
    "ecnl",
    "ecnl rl",
    "ecnl-rl",
    "ecrl",
    "rl",
    "dpl",
    "dplo",
    "npl",
    "ga",
    "mls next",
    "mls-next",
    "pre-ecnl",
    "pre-academy",
    "development",
    "showcase",
    "challenge",
    "recreational",
    "pre ecnl",
}

# Normalize division name variations to standard form
DIVISION_ALIASES = {
    "ecnl-rl": "ECNL RL",
    "ecnl rl": "ECNL RL",
    "ecrl": "ECNL RL",  # Common abbreviation
    "rl": "ECNL RL",  # Standalone RL = ECNL Regional League
    "mls-next": "MLS NEXT",
    "mls next": "MLS NEXT",
    "pre-ecnl": "Pre-ECNL",
    "pre ecnl": "Pre-ECNL",
}

# Provider alias suffixes that indicate different divisions (DO NOT auto-merge)
ALIAS_DIVISION_SUFFIXES = {"_ad", "_hd", "_ea", "_mlsnext", "_mls"}

ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

REGIONS = {"north", "south", "east", "west", "central", "sw", "ne", "nw", "se"}


def normalize_gender(text: str) -> Optional[str]:
    """Convert gender indicators to Male/Female."""
    text = text.lower().strip()
    if text in ("b", "boys", "boy", "male", "m"):
        return "Male"
    elif text in ("g", "girls", "girl", "female", "f"):
        return "Female"
    return None


def parse_age_gender(
    token: str,
    club_skip_tokens: Optional[set] = None,
    season_year_max: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse an age/gender token.

    Returns: (normalized_age, gender) tuple

    NEW NORMALIZATION RULES (Jan 2026):
    - Birth year formats → 4-digit year: '12B' -> '2012', 'B2012' -> '2012'
    - Age group formats → U##: 'U14B' -> 'U14', 'U-14' -> 'U14', 'BU14' -> 'U14',
      '14U' -> 'U14', '14UB' -> ('U14', 'Male')
    - Gender is extracted separately, stripped from age token

    club_skip_tokens:
        When provided and ``token`` is in this set, the bare-2-digit branch
        (`Pattern: ## alone`) returns ``(None, None)`` instead of converting
        to a birth year. Prevents club names like "Union 10 FC" from
        rewriting "10" to "2010" during normalization.

    season_year_max:
        Cutoff above which 4-digit years are treated as season labels rather
        than birth years (e.g., "Spring 2025" or a "2020" founding year for
        a team whose actual birth-year cohort is something else). When ``None``
        (default), derived at runtime from
        ``CURRENT_YEAR - 7`` so the cutoff tracks the season:
        in 2025-26 → 2018, dropping 2020+ as season labels but preserving
        u7 = 2019-born.

    Examples:
        '14B' -> ('2012', 'Male')  # 14 = 2014 birth year, B = Boys
        'B14' -> ('2012', 'Male')  # B = Boys, 14 = 2014 birth year
        '2014B' -> ('2014', 'Male')  # 4-digit birth year + gender
        'B2014' -> ('2014', 'Male')  # gender + 4-digit birth year
        'U14B' -> ('U14', 'Male')  # U14 = age group, B = Boys
        'U-14' -> ('U14', None)  # age group with hyphen
        'BU14' -> ('U14', 'Male')  # gender prefix on age group
        '14U' -> ('U14', None)  # digit-then-U age group form
        '14UB' -> ('U14', 'Male')  # digit-then-U with gender suffix
        '14uG' -> ('U14', 'Female')  # lowercase u with gender suffix
        '2014' -> ('2014', None)  # birth year only
        'U14' -> ('U14', None)  # age only
    """
    token = token.strip()
    if season_year_max is None:
        # Lazy import to avoid bootstrap cycles when this module is imported
        # by other scripts that don't need src.utils.team_utils.
        # Ensure repo root is on path so `src.*` imports work in standalone runs.
        try:
            from src.utils.team_utils import CURRENT_YEAR
        except ModuleNotFoundError:
            import os as _os
            import sys as _sys
            _repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if _repo_root not in _sys.path:
                _sys.path.insert(0, _repo_root)
            from src.utils.team_utils import CURRENT_YEAR
        season_year_max = CURRENT_YEAR - 7

    # Pattern: U-## with optional gender suffix (U14, U14B, U-14, U14M)
    match = re.match(r"^[Uu]-?(\d{1,2})([BbGgMmFf]?)$", token)
    if match:
        age_num = int(match.group(1))
        gender_char = match.group(2)
        gender = normalize_gender(gender_char) if gender_char else None
        return (f"U{age_num}", gender)

    # Pattern: BU## or GU## or MU## (gender prefix on age group)
    match = re.match(r"^([BbGgMmFf])[Uu]-?(\d{1,2})$", token)
    if match:
        gender_char = match.group(1)
        age_num = int(match.group(2))
        gender = normalize_gender(gender_char)
        return (f"U{age_num}", gender)

    # Pattern: ##U with optional gender suffix (14U, 14UB, 14uG, 14UM) -> U-age
    # Semantically an age-group token (not a birth-year shorthand), mirrors
    # scrape_playmetrics_league._TEAM_U_AGE_RE which handles both U14 and 14U orderings.
    match = re.match(r"^(\d{1,2})[Uu]([BbGgMmFf]?)$", token)
    if match:
        age_num = int(match.group(1))
        # Guard U6-U19 (full youth cohort range); rejects tokens like '20U' or '5U'
        if 6 <= age_num <= 19:
            gender_char = match.group(2)
            gender = normalize_gender(gender_char) if gender_char else None
            return (f"U{age_num}", gender)

    # Pattern: ##B/G/M/F with optional trailing 's' (14B, 15M, b15s) -> 4-digit year
    match = re.match(r"^(\d{2})([BbGgMmFf])[Ss]?$", token)
    if match:
        year_short = int(match.group(1))
        gender_char = match.group(2)
        # Assume 20XX for years < 30, 19XX otherwise
        birth_year = 2000 + year_short if year_short < 30 else 1900 + year_short
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)

    # Pattern: B/G/M/F## with optional trailing 's' (B14, M15, b15s) -> 4-digit year
    match = re.match(r"^([BbGgMmFf])(\d{2})[Ss]?$", token)
    if match:
        gender_char = match.group(1)
        year_short = int(match.group(2))
        birth_year = 2000 + year_short if year_short < 30 else 1900 + year_short
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)

    # Pattern: ####B/G/M/F (4-digit birth year + gender) -> 4-digit year
    match = re.match(r"^(\d{4})([BbGgMmFf])$", token)
    if match:
        birth_year = int(match.group(1))
        if birth_year > season_year_max + 1:
            return (None, None)  # season label, not birth year
        gender_char = match.group(2)
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)

    # Pattern: B/G/M/F#### (gender + 4-digit birth year) -> 4-digit year
    match = re.match(r"^([BbGgMmFf])(\d{4})$", token)
    if match:
        gender_char = match.group(1)
        birth_year = int(match.group(2))
        if birth_year > season_year_max + 1:
            return (None, None)  # season label, not birth year
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)

    # Pattern: #### alone (4-digit birth year) -> keep as-is
    match = re.match(r"^(\d{4})$", token)
    if match:
        if int(token) > season_year_max + 1:
            return (None, None)  # season label, not birth year
        return (token, None)

    # Pattern: ## alone (2-digit, could be age or year - ambiguous)
    # Assume birth year if 08-18 (valid birth years), convert to 4-digit
    match = re.match(r"^(\d{2})$", token)
    if match:
        num = int(match.group(1))
        # Skip if this 2-digit token is a club-name fragment — prevents
        # "Union 10 FC 2008" → "Union 2010 FC 2008" pollution.
        if club_skip_tokens and token in club_skip_tokens:
            return (None, None)
        if 6 <= num <= 18:  # Valid birth years 2006-2018
            birth_year = 2000 + num
            return (str(birth_year), None)
        # Outside birth year range - treat as age group
        return (f"U{num}", None)

    # Pattern: ## Boys or ## Girls (with word gender)
    match = re.match(r"^(\d{2,4})\s*(boys?|girls?|male|female)$", token, re.IGNORECASE)
    if match:
        year_str = match.group(1)
        gender_word = match.group(2)
        gender = normalize_gender(gender_word)
        if len(year_str) == 2:
            num = int(year_str)
            birth_year = 2000 + num if num < 30 else 1900 + num
            return (str(birth_year), gender)
        return (year_str, gender)

    return (None, None)


def extract_squad_identifier(tokens: list) -> str:
    """Extract squad identifiers from remaining tokens."""
    squad_parts = []

    # First pass: join tokens that form multi-word divisions (e.g., "ECNL" + "RL" -> "ECNL RL")
    i = 0
    merged_tokens = []
    while i < len(tokens):
        token = tokens[i]
        t_lower = token.lower().strip()

        # Check for ECNL + RL pattern
        if t_lower == "ecnl" and i + 1 < len(tokens) and tokens[i + 1].lower() == "rl":
            merged_tokens.append("ECNL RL")
            i += 2
            continue
        # Check for MLS + NEXT pattern
        elif t_lower == "mls" and i + 1 < len(tokens) and tokens[i + 1].lower() == "next":
            merged_tokens.append("MLS NEXT")
            i += 2
            continue
        # Check for Pre + ECNL pattern
        elif t_lower == "pre" and i + 1 < len(tokens) and tokens[i + 1].lower() == "ecnl":
            merged_tokens.append("Pre-ECNL")
            i += 2
            continue
        else:
            merged_tokens.append(token)
            i += 1

    for token in merged_tokens:
        t_lower = token.lower().strip()

        # Check for division aliases first (normalize variations)
        if t_lower in DIVISION_ALIASES:
            squad_parts.append(DIVISION_ALIASES[t_lower])
        # Check if it's a known squad identifier
        elif t_lower in COLORS:
            squad_parts.append(token.title())
        elif t_lower in DIVISIONS:
            squad_parts.append(token.upper() if len(token) <= 4 else token.title())
        elif t_lower in ROMAN_NUMERALS:
            squad_parts.append(token.upper())
        elif t_lower in REGIONS:
            squad_parts.append(token.upper() if len(token) <= 2 else token.title())
        else:
            # Could be coach name or other identifier
            squad_parts.append(token)

    return " ".join(squad_parts).strip()


# Common suffixes/prefixes to strip when matching club names to team names
_CLUB_SUFFIXES = [
    " soccer club",
    " football club",
    " futbol club",
    " youth soccer",
    " soccer association",
    " youth academy",
    " soccer",
    " futbol",
    " fc",
    " sc",
    " sa",
    " ac",
    " cf",
    " cd",
]
_CLUB_PREFIXES = ["fc ", "sc "]


def _strip_club_from_name(team_name: str, club_name: str) -> str:
    """
    Remove club name from team name, trying multiple strategies.
    Returns the remaining text (age, gender, squad, division, etc.)
    """
    if not club_name or not team_name:
        return team_name

    name_lower = team_name.lower()
    club_lower = club_name.lower()

    # Strategy 1: Exact substring match (handles club anywhere in name)
    if club_lower in name_lower:
        idx = name_lower.find(club_lower)
        before = team_name[:idx]
        after = team_name[idx + len(club_name) :]
        remaining = (before + " " + after).strip()
        return remaining.strip("- ")

    # Strategy 2: Strip common suffixes/prefixes from club and try again
    # e.g. club="Solar SC" → core="Solar", team="Solar PRE-ECNL 2015"
    club_core = club_lower
    for suffix in _CLUB_SUFFIXES:
        if club_core.endswith(suffix):
            club_core = club_core[: -len(suffix)].strip()
            break
    for prefix in _CLUB_PREFIXES:
        if club_core.startswith(prefix):
            club_core = club_core[len(prefix) :].strip()
            break

    # Also strip parenthetical qualifiers like "(Ca)", "(OR)"
    club_core = re.sub(r"\s*\(.*?\)\s*$", "", club_core).strip()
    # Strip slashes like "LouCity / Racing Youth Academy" → try first part
    club_parts = [p.strip() for p in club_core.split("/") if p.strip()]

    # Try each candidate core (full core + slash parts)
    candidates = [club_core] + club_parts if len(club_parts) > 1 else [club_core]
    for core in candidates:
        if not core or len(core) < 3:
            continue
        # Use word boundary match to avoid partial word matches
        pattern = re.compile(r"\b" + re.escape(core) + r"\b", re.IGNORECASE)
        match = pattern.search(team_name)
        if match:
            before = team_name[: match.start()]
            after = team_name[match.end() :]
            remaining = (before + " " + after).strip()
            return remaining.strip("- ")

    # Strategy 3: No match found — return full team name as-is
    return team_name.strip("- ")


def parse_team_name(team_name: str, club_name: str = None) -> Dict:
    """
    Parse a team name into structured components.

    Args:
        team_name: Full team name (e.g., "Phoenix Premier FC 14B Black")
        club_name: Optional club name to help with parsing

    Returns:
        {
            'original': original team name,
            'club': extracted club name,
            'age': normalized age (e.g., 'U12'),
            'gender': 'Male' or 'Female' or None,
            'squad': squad identifier (color, division, etc.),
            'normalized': normalized full identifier
        }
    """
    result = {"original": team_name, "club": club_name, "age": None, "gender": None, "squad": None, "normalized": None}

    if not team_name:
        return result

    # Clean up the team name
    name = team_name.strip()

    # If club name is provided, try to extract everything except the club name
    remaining = name
    if club_name:
        remaining = _strip_club_from_name(name, club_name)

    # Tokenize remaining part
    # Split on spaces, hyphens (but keep hyphenated terms together for things like ECNL-RL)
    tokens = re.split(r"[\s]+", remaining)
    tokens = [t.strip("()[]") for t in tokens if t.strip("()[]")]

    # Find age/gender token
    age = None
    gender = None
    remaining_tokens = []

    for token in tokens:
        if age is None:
            parsed_age, parsed_gender = parse_age_gender(token)
            if parsed_age:
                age = parsed_age
                if parsed_gender:
                    gender = parsed_gender
                continue

        # Check for standalone gender
        if gender is None:
            g = normalize_gender(token)
            if g:
                gender = g
                continue

        remaining_tokens.append(token)

    # Extract squad identifier from remaining tokens
    squad = extract_squad_identifier(remaining_tokens)

    result["age"] = age
    result["gender"] = gender
    result["squad"] = squad if squad else None

    # Build normalized identifier
    parts = []
    if club_name:
        parts.append(club_name)
    if age:
        parts.append(age)
    if gender:
        parts.append(gender[0])  # M or F
    if squad:
        parts.append(squad)

    result["normalized"] = " | ".join(parts) if parts else None

    return result


def teams_match(parsed_a: Dict, parsed_b: Dict) -> Tuple[bool, str]:
    """
    Determine if two parsed teams represent the same team.

    Returns: (match: bool, reason: str)
    """
    # Must have same club (if known)
    if parsed_a.get("club") and parsed_b.get("club"):
        if parsed_a["club"].lower() != parsed_b["club"].lower():
            return (False, "Different clubs")

    # Must have same age
    if parsed_a.get("age") != parsed_b.get("age"):
        # Check if both are None (couldn't parse)
        if parsed_a.get("age") is None or parsed_b.get("age") is None:
            return (False, "Could not parse age")
        return (False, f"Different ages: {parsed_a.get('age')} vs {parsed_b.get('age')}")

    # Must have same gender (if known)
    if parsed_a.get("gender") and parsed_b.get("gender"):
        if parsed_a["gender"] != parsed_b["gender"]:
            return (False, f"Different genders: {parsed_a.get('gender')} vs {parsed_b.get('gender')}")

    # Squad identifier comparison (case-insensitive)
    squad_a = (parsed_a.get("squad") or "").lower().strip()
    squad_b = (parsed_b.get("squad") or "").lower().strip()

    # Normalize squad for comparison
    squad_a_norm = re.sub(r"[^a-z0-9]", "", squad_a)
    squad_b_norm = re.sub(r"[^a-z0-9]", "", squad_b)

    if squad_a_norm != squad_b_norm:
        # Check if one is subset of other (e.g., "Black" vs "SW Black")
        if squad_a_norm and squad_b_norm:
            if squad_a_norm not in squad_b_norm and squad_b_norm not in squad_a_norm:
                return (False, f"Different squads: '{parsed_a.get('squad')}' vs '{parsed_b.get('squad')}'")
            else:
                return (True, f"Squad variation: '{parsed_a.get('squad')}' ~ '{parsed_b.get('squad')}'")

    return (True, "Match")


# Test cases
if __name__ == "__main__":
    # First, test the parse_age_gender function directly
    print("=== AGE NORMALIZATION (Jan 2026 Rules) ===\n")
    print("Birth year formats → 4-digit year:")
    age_tests = [
        ("12B", "2012"),
        ("B12", "2012"),
        ("2012B", "2012"),
        ("B2012", "2012"),
        ("G2016", "2016"),
        ("2016G", "2016"),
        ("2014", "2014"),
    ]
    for token, expected in age_tests:
        age, _ = parse_age_gender(token)
        status = "✅" if age == expected else "❌"
        print(f"  {status} {token:10} → {age} (expected: {expected})")

    print("\nAge group formats → U##:")
    age_tests2 = [
        ("U14B", "U14"),
        ("U14", "U14"),
        ("U-14", "U14"),
        ("BU14", "U14"),
        ("GU12", "U12"),
        ("14U", "U14"),
        ("14u", "U14"),
        ("15U", "U15"),
        ("10U", "U10"),
        ("19U", "U19"),
    ]
    for token, expected in age_tests2:
        age, _ = parse_age_gender(token)
        status = "✅" if age == expected else "❌"
        print(f"  {status} {token:10} → {age} (expected: {expected})")

    print("\nDigit-then-U with gender suffix → (U##, gender):")
    digit_u_gender_tests = [
        ("14UB", ("U14", "Male")),
        ("14UG", ("U14", "Female")),
        ("14UM", ("U14", "Male")),
        ("14UF", ("U14", "Female")),
        ("14uG", ("U14", "Female")),
        ("20U", (None, None)),
        ("5U", (None, None)),
        ("14UZ", (None, None)),
    ]
    for token, expected in digit_u_gender_tests:
        result = parse_age_gender(token)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {token:10} → {result} (expected: {expected})")

    # ── CLUB-TOKEN SKIP ──
    # When club_skip_tokens contains a 2-digit number, the bare-2-digit
    # branch must return (None, None) instead of converting to a birth year.
    # Prevents "Union 10 FC 2008" → "Union 2010 FC 2008" pollution.
    print("\nCLUB-TOKEN SKIP (bare-2-digit branch returns None when in skip set):")
    club_skip_tests = [
        # (token, club_skip_tokens, expected_age)
        ("10", {"union", "10", "fc"}, None),  # club fragment, skip
        ("10", set(), "2010"),                 # no skip, parse as birth year
        ("12", {"union", "10", "fc"}, "2012"), # different number, parse
        ("08", {"team", "08"}, None),          # club fragment, skip
        ("08", set(), "2008"),                 # no skip, parse
        ("14", None, "2014"),                  # None skip set → no skip
    ]
    for token, skip, expected in club_skip_tests:
        age, _ = parse_age_gender(token, club_skip_tokens=skip)
        status = "✅" if age == expected else "❌"
        skip_repr = "None" if skip is None else f"len={len(skip)}"
        print(f"  {status} parse_age_gender({token!r}, skip={skip_repr}) → {age!r} (expected: {expected!r})")

    # ── SEASON-YEAR FILTER ──
    # 4-digit years above CURRENT_YEAR-7+1 are season labels, not birth years.
    # In 2025-26: season_year_max=2018, so 2019 IS preserved (u7 cohort) but
    # 2020, 2025 are dropped.
    print("\nSEASON-YEAR FILTER (default season_year_max from CURRENT_YEAR):")
    season_tests = [
        ("2014", "2014"),  # within range
        ("2018", "2018"),  # at max
        ("2019", "2019"),  # max+1, still allowed (u7 cohort)
        ("2020", None),    # season label, dropped
        ("2025", None),    # season label, dropped
        ("B2025", None),   # gender + season label
        ("2025B", None),   # season label + gender
    ]
    for token, expected in season_tests:
        age, _ = parse_age_gender(token)
        status = "✅" if age == expected else "❌"
        print(f"  {status} parse_age_gender({token!r}) → {age!r} (expected: {expected!r})")

    # ── normalize_team_name CLUB-TOKEN preservation ──
    # End-to-end check that the Union 10 FC pollution path is fixed.
    try:
        from normalize_team_names import normalize_team_name as _normalize
    except ImportError:
        _normalize = None
    if _normalize:
        print("\nnormalize_team_name preserves club-name numbers:")
        norm_tests = [
            ("Union 10 FC 2008 Boys", "Union 10 FC", "Union 10 FC 2008"),
            ("Union 10 FC 2009 Boys", "Union 10 FC", "Union 10 FC 2009"),
        ]
        for name, club, expected in norm_tests:
            got = _normalize(name, club)
            status = "✅" if got == expected else "❌"
            print(f"  {status} normalize({name!r}, {club!r}) → {got!r} (expected {expected!r})")

    print("\n=== TEAM NAME PARSER TEST ===\n")
    test_cases = [
        ("Phoenix Premier FC 14B Black", "Phoenix Premier FC"),
        ("Phoenix Premier FC B2014 Black", "Phoenix Premier FC"),
        ("Phoenix Premier FC U12B Black", "Phoenix Premier FC"),
        ("SS Academy 2014G Select", "SS Academy"),
        ("East Coast Surf G2016", "East Coast Surf"),
        ("East Coast Surf 2016G", "East Coast Surf"),
        ("Rebels SC B2010 Premier", "Rebels SC"),
        ("Utah Royals FC-AZ ECNL G12", "Utah Royals FC - AZ"),
        ("Utah Royals FC-AZ RL G12", "Utah Royals FC - AZ"),
        ("Napa United 14B Development", "Napa United"),
    ]

    for team_name, club in test_cases:
        result = parse_team_name(team_name, club)
        print(f"Input: {team_name}")
        print(f"  Club: {result['club']}")
        print(f"  Age: {result['age']}")
        print(f"  Gender: {result['gender']}")
        print(f"  Squad: {result['squad']}")
        print(f"  Normalized: {result['normalized']}")
        print()

    # Test matching
    print("=== MATCH TESTS ===\n")

    match_tests = [
        (
            ("Phoenix Premier FC 14B Black", "Phoenix Premier FC"),
            ("Phoenix Premier FC B2014 Black", "Phoenix Premier FC"),
        ),
        (("East Coast Surf G2016", "East Coast Surf"), ("East Coast Surf 2016G", "East Coast Surf")),
        (("Phoenix Premier FC 14B Black", "Phoenix Premier FC"), ("Phoenix Premier FC 14B Blue", "Phoenix Premier FC")),
        (("Utah Royals FC-AZ ECNL G12", "Utah Royals FC - AZ"), ("Utah Royals FC-AZ RL G12", "Utah Royals FC - AZ")),
    ]

    for (name_a, club_a), (name_b, club_b) in match_tests:
        parsed_a = parse_team_name(name_a, club_a)
        parsed_b = parse_team_name(name_b, club_b)
        match, reason = teams_match(parsed_a, parsed_b)

        symbol = "✅" if match else "❌"
        print(f"{symbol} {name_a}")
        print(f"   vs {name_b}")
        print(f"   → {reason}")
        print()
