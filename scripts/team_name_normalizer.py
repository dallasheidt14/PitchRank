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
from typing import Optional, Dict, Tuple

# Birth year to U-age mapping (as of 2026 season)
BIRTH_YEAR_TO_AGE = {
    2016: 'U10', 2015: 'U11', 2014: 'U12', 2013: 'U13',
    2012: 'U14', 2011: 'U15', 2010: 'U16', 2009: 'U17', 2008: 'U18',
    2017: 'U9', 2018: 'U8', 2007: 'U19', 2006: 'U20'
}

# Known squad identifiers (things that distinguish teams within same club/age)
COLORS = {'black', 'blue', 'red', 'white', 'navy', 'gold', 'orange', 'green', 
          'silver', 'gray', 'grey', 'purple', 'yellow', 'pink', 'maroon', 'teal'}

DIVISIONS = {'premier', 'elite', 'academy', 'select', 'classic', 'competitive',
             'ecnl', 'ecnl rl', 'ecnl-rl', 'ecrl', 'rl', 'dpl', 'dplo', 'npl', 'ga',
             'mls next', 'mls-next', 'pre-ecnl', 'pre-academy', 'development',
             'showcase', 'challenge', 'recreational', 'pre ecnl'}

# Normalize division name variations to standard form
DIVISION_ALIASES = {
    'ecnl-rl': 'ECNL RL',
    'ecnl rl': 'ECNL RL',
    'ecrl': 'ECNL RL',  # Common abbreviation
    'rl': 'ECNL RL',  # Standalone RL = ECNL Regional League
    'mls-next': 'MLS NEXT',
    'mls next': 'MLS NEXT',
    'pre-ecnl': 'Pre-ECNL',
    'pre ecnl': 'Pre-ECNL',
}

# Provider alias suffixes that indicate different divisions (DO NOT auto-merge)
ALIAS_DIVISION_SUFFIXES = {'_ad', '_hd', '_ea', '_mlsnext', '_mls'}

ROMAN_NUMERALS = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}

REGIONS = {'north', 'south', 'east', 'west', 'central', 'sw', 'ne', 'nw', 'se'}


def normalize_gender(text: str) -> Optional[str]:
    """Convert gender indicators to Male/Female."""
    text = text.lower().strip()
    if text in ('b', 'boys', 'boy', 'male', 'm'):
        return 'Male'
    elif text in ('g', 'girls', 'girl', 'female', 'f'):
        return 'Female'
    return None


def parse_age_gender(token: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse an age/gender token.
    
    Returns: (normalized_age, gender) tuple
    
    NEW NORMALIZATION RULES (Jan 2026):
    - Birth year formats → 4-digit year: '12B' -> '2012', 'B2012' -> '2012'
    - Age group formats → U##: 'U14B' -> 'U14', 'U-14' -> 'U14', 'BU14' -> 'U14'
    - Gender is extracted separately, stripped from age token
    
    Examples:
        '14B' -> ('2012', 'Male')  # 14 = 2014 birth year, B = Boys
        'B14' -> ('2012', 'Male')  # B = Boys, 14 = 2014 birth year
        '2014B' -> ('2014', 'Male')  # 4-digit birth year + gender
        'B2014' -> ('2014', 'Male')  # gender + 4-digit birth year
        'U14B' -> ('U14', 'Male')  # U14 = age group, B = Boys
        'U-14' -> ('U14', None)  # age group with hyphen
        'BU14' -> ('U14', 'Male')  # gender prefix on age group
        '2014' -> ('2014', None)  # birth year only
        'U14' -> ('U14', None)  # age only
    """
    token = token.strip()
    
    # Pattern: U-## with optional gender suffix (U14, U14B, U-14, U14M)
    match = re.match(r'^[Uu]-?(\d{1,2})([BbGgMmFf]?)$', token)
    if match:
        age_num = int(match.group(1))
        gender_char = match.group(2)
        gender = normalize_gender(gender_char) if gender_char else None
        return (f'U{age_num}', gender)
    
    # Pattern: BU## or GU## or MU## (gender prefix on age group)
    match = re.match(r'^([BbGgMmFf])[Uu]-?(\d{1,2})$', token)
    if match:
        gender_char = match.group(1)
        age_num = int(match.group(2))
        gender = normalize_gender(gender_char)
        return (f'U{age_num}', gender)
    
    # Pattern: ##B/G/M/F with optional trailing 's' (14B, 15M, b15s) -> 4-digit year
    match = re.match(r'^(\d{2})([BbGgMmFf])[Ss]?$', token)
    if match:
        year_short = int(match.group(1))
        gender_char = match.group(2)
        # Assume 20XX for years < 30, 19XX otherwise
        birth_year = 2000 + year_short if year_short < 30 else 1900 + year_short
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)
    
    # Pattern: B/G/M/F## with optional trailing 's' (B14, M15, b15s) -> 4-digit year
    match = re.match(r'^([BbGgMmFf])(\d{2})[Ss]?$', token)
    if match:
        gender_char = match.group(1)
        year_short = int(match.group(2))
        birth_year = 2000 + year_short if year_short < 30 else 1900 + year_short
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)
    
    # Pattern: ####B/G/M/F (4-digit birth year + gender) -> 4-digit year
    match = re.match(r'^(\d{4})([BbGgMmFf])$', token)
    if match:
        birth_year = int(match.group(1))
        gender_char = match.group(2)
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)
    
    # Pattern: B/G/M/F#### (gender + 4-digit birth year) -> 4-digit year
    match = re.match(r'^([BbGgMmFf])(\d{4})$', token)
    if match:
        gender_char = match.group(1)
        birth_year = int(match.group(2))
        gender = normalize_gender(gender_char)
        return (str(birth_year), gender)
    
    # Pattern: #### alone (4-digit birth year) -> keep as-is
    match = re.match(r'^(\d{4})$', token)
    if match:
        return (token, None)
    
    # Pattern: ## alone (2-digit, could be age or year - ambiguous)
    # Assume birth year if 08-18 (valid birth years), convert to 4-digit
    match = re.match(r'^(\d{2})$', token)
    if match:
        num = int(match.group(1))
        if 6 <= num <= 18:  # Valid birth years 2006-2018
            birth_year = 2000 + num
            return (str(birth_year), None)
        # Outside birth year range - treat as age group
        return (f'U{num}', None)
    
    # Pattern: ## Boys or ## Girls (with word gender)
    match = re.match(r'^(\d{2,4})\s*(boys?|girls?|male|female)$', token, re.IGNORECASE)
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
        if t_lower == 'ecnl' and i + 1 < len(tokens) and tokens[i + 1].lower() == 'rl':
            merged_tokens.append('ECNL RL')
            i += 2
            continue
        # Check for MLS + NEXT pattern
        elif t_lower == 'mls' and i + 1 < len(tokens) and tokens[i + 1].lower() == 'next':
            merged_tokens.append('MLS NEXT')
            i += 2
            continue
        # Check for Pre + ECNL pattern
        elif t_lower == 'pre' and i + 1 < len(tokens) and tokens[i + 1].lower() == 'ecnl':
            merged_tokens.append('Pre-ECNL')
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
    
    return ' '.join(squad_parts).strip()


# Common suffixes/prefixes to strip when matching club names to team names
_CLUB_SUFFIXES = [
    ' soccer club', ' football club', ' futbol club',
    ' youth soccer', ' soccer association', ' youth academy',
    ' soccer', ' futbol',
    ' fc', ' sc', ' sa', ' ac', ' cf', ' cd',
]
_CLUB_PREFIXES = ['fc ', 'sc ']


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
        after = team_name[idx + len(club_name):]
        remaining = (before + ' ' + after).strip()
        return remaining.strip('- ')

    # Strategy 2: Strip common suffixes/prefixes from club and try again
    # e.g. club="Solar SC" → core="Solar", team="Solar PRE-ECNL 2015"
    club_core = club_lower
    for suffix in _CLUB_SUFFIXES:
        if club_core.endswith(suffix):
            club_core = club_core[:-len(suffix)].strip()
            break
    for prefix in _CLUB_PREFIXES:
        if club_core.startswith(prefix):
            club_core = club_core[len(prefix):].strip()
            break

    # Also strip parenthetical qualifiers like "(Ca)", "(OR)"
    club_core = re.sub(r'\s*\(.*?\)\s*$', '', club_core).strip()
    # Strip slashes like "LouCity / Racing Youth Academy" → try first part
    club_parts = [p.strip() for p in club_core.split('/') if p.strip()]

    # Try each candidate core (full core + slash parts)
    candidates = [club_core] + club_parts if len(club_parts) > 1 else [club_core]
    for core in candidates:
        if not core or len(core) < 3:
            continue
        # Use word boundary match to avoid partial word matches
        pattern = re.compile(r'\b' + re.escape(core) + r'\b', re.IGNORECASE)
        match = pattern.search(team_name)
        if match:
            before = team_name[:match.start()]
            after = team_name[match.end():]
            remaining = (before + ' ' + after).strip()
            return remaining.strip('- ')

    # Strategy 3: No match found — return full team name as-is
    return team_name.strip('- ')


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
    result = {
        'original': team_name,
        'club': club_name,
        'age': None,
        'gender': None,
        'squad': None,
        'normalized': None
    }
    
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
    tokens = re.split(r'[\s]+', remaining)
    tokens = [t.strip('()[]') for t in tokens if t.strip('()[]')]
    
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
    
    result['age'] = age
    result['gender'] = gender
    result['squad'] = squad if squad else None
    
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
    
    result['normalized'] = ' | '.join(parts) if parts else None
    
    return result


def teams_match(parsed_a: Dict, parsed_b: Dict) -> Tuple[bool, str]:
    """
    Determine if two parsed teams represent the same team.
    
    Returns: (match: bool, reason: str)
    """
    # Must have same club (if known)
    if parsed_a.get('club') and parsed_b.get('club'):
        if parsed_a['club'].lower() != parsed_b['club'].lower():
            return (False, 'Different clubs')
    
    # Must have same age
    if parsed_a.get('age') != parsed_b.get('age'):
        # Check if both are None (couldn't parse)
        if parsed_a.get('age') is None or parsed_b.get('age') is None:
            return (False, 'Could not parse age')
        return (False, f"Different ages: {parsed_a.get('age')} vs {parsed_b.get('age')}")
    
    # Must have same gender (if known)
    if parsed_a.get('gender') and parsed_b.get('gender'):
        if parsed_a['gender'] != parsed_b['gender']:
            return (False, f"Different genders: {parsed_a.get('gender')} vs {parsed_b.get('gender')}")
    
    # Squad identifier comparison (case-insensitive)
    squad_a = (parsed_a.get('squad') or '').lower().strip()
    squad_b = (parsed_b.get('squad') or '').lower().strip()
    
    # Normalize squad for comparison
    squad_a_norm = re.sub(r'[^a-z0-9]', '', squad_a)
    squad_b_norm = re.sub(r'[^a-z0-9]', '', squad_b)
    
    if squad_a_norm != squad_b_norm:
        # Check if one is subset of other (e.g., "Black" vs "SW Black")
        if squad_a_norm and squad_b_norm:
            if squad_a_norm not in squad_b_norm and squad_b_norm not in squad_a_norm:
                return (False, f"Different squads: '{parsed_a.get('squad')}' vs '{parsed_b.get('squad')}'")
            else:
                return (True, f"Squad variation: '{parsed_a.get('squad')}' ~ '{parsed_b.get('squad')}'")
    
    return (True, 'Match')


# Test cases
if __name__ == '__main__':
    # First, test the parse_age_gender function directly
    print("=== AGE NORMALIZATION (Jan 2026 Rules) ===\n")
    print("Birth year formats → 4-digit year:")
    age_tests = [
        ('12B', '2012'),
        ('B12', '2012'),
        ('2012B', '2012'),
        ('B2012', '2012'),
        ('G2016', '2016'),
        ('2016G', '2016'),
        ('2014', '2014'),
    ]
    for token, expected in age_tests:
        age, _ = parse_age_gender(token)
        status = '✅' if age == expected else '❌'
        print(f"  {status} {token:10} → {age} (expected: {expected})")
    
    print("\nAge group formats → U##:")
    age_tests2 = [
        ('U14B', 'U14'),
        ('U14', 'U14'),
        ('U-14', 'U14'),
        ('BU14', 'U14'),
        ('GU12', 'U12'),
    ]
    for token, expected in age_tests2:
        age, _ = parse_age_gender(token)
        status = '✅' if age == expected else '❌'
        print(f"  {status} {token:10} → {age} (expected: {expected})")
    
    print("\n=== TEAM NAME PARSER TEST ===\n")
    test_cases = [
        ('Phoenix Premier FC 14B Black', 'Phoenix Premier FC'),
        ('Phoenix Premier FC B2014 Black', 'Phoenix Premier FC'),
        ('Phoenix Premier FC U12B Black', 'Phoenix Premier FC'),
        ('SS Academy 2014G Select', 'SS Academy'),
        ('East Coast Surf G2016', 'East Coast Surf'),
        ('East Coast Surf 2016G', 'East Coast Surf'),
        ('Rebels SC B2010 Premier', 'Rebels SC'),
        ('Utah Royals FC-AZ ECNL G12', 'Utah Royals FC - AZ'),
        ('Utah Royals FC-AZ RL G12', 'Utah Royals FC - AZ'),
        ('Napa United 14B Development', 'Napa United'),
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
        (('Phoenix Premier FC 14B Black', 'Phoenix Premier FC'), 
         ('Phoenix Premier FC B2014 Black', 'Phoenix Premier FC')),
        (('East Coast Surf G2016', 'East Coast Surf'), 
         ('East Coast Surf 2016G', 'East Coast Surf')),
        (('Phoenix Premier FC 14B Black', 'Phoenix Premier FC'), 
         ('Phoenix Premier FC 14B Blue', 'Phoenix Premier FC')),
        (('Utah Royals FC-AZ ECNL G12', 'Utah Royals FC - AZ'), 
         ('Utah Royals FC-AZ RL G12', 'Utah Royals FC - AZ')),
    ]
    
    for (name_a, club_a), (name_b, club_b) in match_tests:
        parsed_a = parse_team_name(name_a, club_a)
        parsed_b = parse_team_name(name_b, club_b)
        match, reason = teams_match(parsed_a, parsed_b)
        
        symbol = '✅' if match else '❌'
        print(f"{symbol} {name_a}")
        print(f"   vs {name_b}")
        print(f"   → {reason}")
        print()
