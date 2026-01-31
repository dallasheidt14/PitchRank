#!/usr/bin/env python3
"""
Team Name Normalizer v2 - Clean structured format

Output format: [Club] [Age] [Division] [Squad]

Examples:
- Phoenix FC 2014 ECNL Black
- Surf SC 2011 MLS NEXT I
- Rapids 2013 Premier Blue
"""

import re
from typing import Optional, Dict, List, Tuple

# Division tiers (order matters - check longer patterns first)
DIVISIONS = [
    'mls next', 'mls-next', 'mlsnext',
    'ecnl-rl', 'ecnl rl', 'ecrl',
    'pre-ecnl', 'pre ecnl',
    'ecnl',
    'ga', 'girls academy',
    'npl', 'dpl', 'dplo',
    'premier', 'elite', 'academy', 'select', 'classic',
    'competitive', 'development', 'recreational',
    'showcase', 'challenge',
]

# Squad identifiers
COLORS = ['black', 'blue', 'red', 'white', 'navy', 'gold', 'orange', 'green',
          'silver', 'gray', 'grey', 'purple', 'yellow', 'pink', 'maroon', 'teal']

NUMERALS = ['i', 'ii', 'iii', 'iv', 'v', 'vi', '1', '2', '3', '4', '5']

REGIONS = ['north', 'south', 'east', 'west', 'central', 'sw', 'ne', 'nw', 'se']

# Age patterns
AGE_PATTERNS = [
    (r'\b[BbGg]?20(\d{2})[BbGg]?\b', lambda m: f'20{m.group(1)}'),  # B2014, 2014G, 2014
    (r'\b[BbGg](\d{2})[BbGg]?\b', lambda m: f'20{m.group(1)}' if int(m.group(1)) <= 20 else None),  # B14, 14G
    (r'\b(\d{2})[BbGg]\b', lambda m: f'20{m.group(1)}' if int(m.group(1)) <= 20 else None),  # 14B
    (r'\b[Uu]-?(\d{1,2})[BbGg]?\b', lambda m: f'U{m.group(1)}'),  # U14, U-14, U14B
    (r'\b[BbGg][Uu]-?(\d{1,2})\b', lambda m: f'U{m.group(1)}'),  # BU14, GU14
]

# Combined age patterns to skip (take oldest)
COMBINED_AGE = re.compile(r'\b(\d{2})/(\d{2})[BbGg]?\b|\b20(\d{2})/20(\d{2})[BbGg]?\b')


def extract_age(text: str) -> Tuple[Optional[str], str]:
    """Extract and normalize age from text. Returns (age, remaining_text)."""
    
    # Check for combined ages first (11/12B -> take oldest)
    combined = COMBINED_AGE.search(text)
    if combined:
        if combined.group(1) and combined.group(2):
            y1, y2 = int(combined.group(1)), int(combined.group(2))
        else:
            y1, y2 = int(combined.group(3)), int(combined.group(4))
        oldest = min(y1, y2)
        age = f'20{oldest:02d}' if oldest < 100 else str(oldest)
        remaining = text[:combined.start()] + text[combined.end():]
        return age, remaining.strip()
    
    # Try each age pattern
    for pattern, formatter in AGE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            age = formatter(match)
            if age:
                remaining = text[:match.start()] + text[match.end():]
                return age, remaining.strip()
    
    return None, text


def extract_divisions(text: str) -> Tuple[List[str], str]:
    """Extract division tiers from text. Returns (divisions, remaining_text)."""
    found = []
    remaining = text
    
    for div in DIVISIONS:
        pattern = r'\b' + re.escape(div) + r'\b'
        if re.search(pattern, remaining, re.IGNORECASE):
            # Normalize the division name
            normalized = div.upper().replace('-', ' ').replace('  ', ' ')
            if normalized == 'MLS NEXT' or normalized == 'MLSNEXT':
                normalized = 'MLS NEXT'
            elif normalized == 'ECNL RL' or normalized == 'ECRL':
                normalized = 'ECNL RL'
            elif normalized == 'PRE ECNL':
                normalized = 'Pre-ECNL'
            elif normalized == 'GIRLS ACADEMY':
                normalized = 'GA'
            else:
                normalized = normalized.title()
            
            if normalized not in found:
                found.append(normalized)
            remaining = re.sub(pattern, '', remaining, flags=re.IGNORECASE)
    
    return found, remaining.strip()


def extract_squad(text: str) -> Tuple[List[str], str]:
    """Extract squad identifiers (colors, numerals, regions, coach names)."""
    found = []
    remaining = text
    
    # Colors
    for color in COLORS:
        pattern = r'\b' + color + r'\b'
        if re.search(pattern, remaining, re.IGNORECASE):
            found.append(color.title())
            remaining = re.sub(pattern, '', remaining, flags=re.IGNORECASE)
    
    # Roman numerals (standalone)
    for num in NUMERALS:
        pattern = r'\b' + num + r'\b'
        if re.search(pattern, remaining, re.IGNORECASE):
            found.append(num.upper())
            remaining = re.sub(pattern, '', remaining, flags=re.IGNORECASE)
    
    # Regions
    for region in REGIONS:
        pattern = r'\b' + region + r'\b'
        if re.search(pattern, remaining, re.IGNORECASE):
            found.append(region.upper() if len(region) <= 2 else region.title())
            remaining = re.sub(pattern, '', remaining, flags=re.IGNORECASE)
    
    # Coach names (pattern: "- Name" or "(Name)" at end)
    coach_match = re.search(r'[-–]\s*([A-Z][a-z]+)$', remaining)
    if coach_match:
        found.append(coach_match.group(1))
        remaining = remaining[:coach_match.start()]
    
    return found, remaining.strip()


def normalize_team_name(team_name: str, club_name: str) -> Dict:
    """
    Normalize a team name to structured format.
    
    Returns dict with:
    - original: original team_name
    - club: club name
    - age: normalized age (2014 or U14)
    - divisions: list of division tiers
    - squad: list of squad identifiers
    - normalized: clean formatted string
    """
    result = {
        'original': team_name,
        'club': club_name,
        'age': None,
        'divisions': [],
        'squad': [],
        'normalized': None
    }
    
    if not team_name:
        return result
    
    # Start with team_name, remove club prefix if present
    working = team_name.strip()
    if club_name:
        # Remove club name from start (case insensitive)
        pattern = r'^' + re.escape(club_name) + r'\s*[-–]?\s*'
        working = re.sub(pattern, '', working, flags=re.IGNORECASE).strip()
    
    # Extract components
    age, working = extract_age(working)
    divisions, working = extract_divisions(working)
    squad, working = extract_squad(working)
    
    # Anything left might be additional identifiers
    leftover = re.sub(r'[-–()\[\]]+', ' ', working)
    leftover = ' '.join(leftover.split()).strip()
    if leftover and len(leftover) > 1:
        # Add non-empty leftovers to squad
        squad.append(leftover)
    
    result['age'] = age
    result['divisions'] = divisions
    result['squad'] = squad
    
    # Build normalized string: Club Age Division(s) Squad
    parts = []
    if club_name:
        parts.append(club_name)
    if age:
        parts.append(age)
    if divisions:
        parts.extend(divisions)
    if squad:
        parts.extend(squad)
    
    result['normalized'] = ' '.join(parts) if parts else team_name
    
    return result


if __name__ == '__main__':
    # Test cases
    test_cases = [
        ("Phoenix Premier FC 14B Black", "Phoenix Premier FC"),
        ("PHOENIX PREMIER FC B2014 BLACK", "Phoenix Premier FC"),
        ("Phoenix Premier FC B14 SW Black", "Phoenix Premier FC"),
        ("Surf SC ECNL 14B", "Surf SC"),
        ("Surf SC ECNL-RL B2014", "Surf SC"),
        ("XF Academy 2012 ECNL", "XF Academy"),
        ("Rapids 13/14B Premier Blue", "Rapids"),
        ("FC Dallas U15 MLS NEXT", "FC Dallas"),
        ("Arizona Arsenal 2011B Academy I", "Arizona Arsenal"),
        ("Club XYZ 2014G Elite - Coach Smith", "Club XYZ"),
        ("ECNL RL B11", "Tennessee SC"),  # Short name, club not in team_name
        ("2011 Boys Red", "Some Club"),  # Age at start
    ]
    
    print("=" * 80)
    print("TEAM NAME NORMALIZER v2 TEST")
    print("=" * 80)
    
    for team, club in test_cases:
        result = normalize_team_name(team, club)
        print(f"\nOriginal:   {team}")
        print(f"Club:       {club}")
        print(f"→ Age:      {result['age']}")
        print(f"→ Division: {result['divisions']}")
        print(f"→ Squad:    {result['squad']}")
        print(f"→ OUTPUT:   {result['normalized']}")
