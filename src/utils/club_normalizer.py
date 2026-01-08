"""
Club Name Normalization Module

Provides reliable mapping of messy club name strings to canonical club_id / club_norm.

Examples:
    - Phoenix Rising
    - Phoenix Rising FC
    - PHX Rising
    - Phoenix Rising Soccer Club
    - Phoenix Rising - AZ
    → club_norm: "PHOENIX RISING", club_id: "phoenix_rising"
"""

import hashlib
import re
import string
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

# Try to import rapidfuzz, fall back to difflib-based implementation
try:
    from rapidfuzz import fuzz, process
    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False

    # Fallback implementation using difflib
    class _FuzzFallback:
        @staticmethod
        def ratio(s1: str, s2: str) -> float:
            """Simple ratio using SequenceMatcher"""
            return SequenceMatcher(None, s1.lower(), s2.lower()).ratio() * 100

        @staticmethod
        def partial_ratio(s1: str, s2: str) -> float:
            """Partial ratio - check if shorter string is in longer"""
            s1, s2 = s1.lower(), s2.lower()
            if len(s1) > len(s2):
                s1, s2 = s2, s1
            # Slide shorter string along longer and find best match
            best = 0
            len_s1 = len(s1)
            for i in range(len(s2) - len_s1 + 1):
                score = SequenceMatcher(None, s1, s2[i:i + len_s1]).ratio()
                best = max(best, score)
            return best * 100

        @staticmethod
        def token_set_ratio(s1: str, s2: str) -> float:
            """Token set ratio - compare sets of tokens"""
            tokens1 = set(s1.lower().split())
            tokens2 = set(s2.lower().split())
            intersection = tokens1 & tokens2
            union = tokens1 | tokens2
            if not union:
                return 0.0
            # Jaccard-like similarity with some adjustment
            sorted_intersection = ' '.join(sorted(intersection))
            sorted_s1 = ' '.join(sorted(tokens1))
            sorted_s2 = ' '.join(sorted(tokens2))
            return max(
                SequenceMatcher(None, sorted_s1, sorted_s2).ratio(),
                len(intersection) / len(union)
            ) * 100

    class _ProcessFallback:
        @staticmethod
        def extractOne(query: str, choices: List[str], scorer=None, score_cutoff: float = 0):
            """Find best match from choices"""
            if not choices:
                return None
            scorer = scorer or _FuzzFallback.ratio
            best_match = None
            best_score = 0
            best_idx = 0
            for idx, choice in enumerate(choices):
                score = scorer(query, choice)
                if score > best_score:
                    best_score = score
                    best_match = choice
                    best_idx = idx
            if best_score >= score_cutoff:
                return (best_match, best_score, best_idx)
            return None

    fuzz = _FuzzFallback()
    process = _ProcessFallback()


@dataclass
class ClubNormResult:
    """Result of club name normalization"""
    club_id: str          # Stable identifier (slug form): "phoenix_rising"
    club_norm: str        # Canonical display name: "PHOENIX RISING"
    original: str         # Original input string
    confidence: float     # 0.0-1.0, how confident we are in the match
    matched_canonical: bool  # True if matched to a known canonical club

    @property
    def needs_review(self) -> bool:
        """True if this match should be manually reviewed (not 100% confident)"""
        return not self.matched_canonical or self.confidence < 1.0


# =============================================================================
# ABBREVIATION MAPPINGS
# =============================================================================

# City/Location abbreviations
CITY_ABBREVIATIONS = {
    'phx': 'phoenix',
    'la': 'los angeles',
    'nyc': 'new york city',
    'ny': 'new york',
    'sf': 'san francisco',
    'sd': 'san diego',
    'dc': 'washington dc',
    'stl': 'st louis',
    'kc': 'kansas city',
    'atl': 'atlanta',
    'chi': 'chicago',
    'det': 'detroit',
    'dal': 'dallas',
    'hou': 'houston',
    'mia': 'miami',
    'sea': 'seattle',
    'den': 'denver',
    'min': 'minnesota',
    'cin': 'cincinnati',
    'cle': 'cleveland',
    'pit': 'pittsburgh',
    'bal': 'baltimore',
    'phi': 'philadelphia',
    'bos': 'boston',
    'lv': 'las vegas',
    'orl': 'orlando',
    'tb': 'tampa bay',
    'sac': 'sacramento',
    'slc': 'salt lake city',
    'okc': 'oklahoma city',
    'indy': 'indianapolis',
    'jax': 'jacksonville',
    'char': 'charlotte',
    'nash': 'nashville',
    'mem': 'memphis',
    'nola': 'new orleans',
    'pdx': 'portland',
    'philly': 'philadelphia',
    'cbus': 'columbus',
    'rdu': 'raleigh',
    'rva': 'richmond',
    'dfw': 'dallas fort worth',
}

# Common soccer abbreviations
SOCCER_ABBREVIATIONS = {
    'fc': 'football club',
    'sc': 'soccer club',
    'sa': 'soccer academy',
    'ac': 'athletic club',
    'afc': 'association football club',
    'cf': 'club de futbol',
    'ys': 'youth soccer',
    'ysc': 'youth soccer club',
    'utd': 'united',
    'u': 'united',  # Only when standalone
    'fca': 'football club academy',
    'sfc': 'soccer football club',
}

# State abbreviations (for removal from club names)
STATE_ABBREVIATIONS = {
    'al': 'alabama', 'ak': 'alaska', 'az': 'arizona', 'ar': 'arkansas',
    'ca': 'california', 'co': 'colorado', 'ct': 'connecticut', 'de': 'delaware',
    'fl': 'florida', 'ga': 'georgia', 'hi': 'hawaii', 'id': 'idaho',
    'il': 'illinois', 'in': 'indiana', 'ia': 'iowa', 'ks': 'kansas',
    'ky': 'kentucky', 'la': 'louisiana', 'me': 'maine', 'md': 'maryland',
    'ma': 'massachusetts', 'mi': 'michigan', 'mn': 'minnesota', 'ms': 'mississippi',
    'mo': 'missouri', 'mt': 'montana', 'ne': 'nebraska', 'nv': 'nevada',
    'nh': 'new hampshire', 'nj': 'new jersey', 'nm': 'new mexico', 'ny': 'new york',
    'nc': 'north carolina', 'nd': 'north dakota', 'oh': 'ohio', 'ok': 'oklahoma',
    'or': 'oregon', 'pa': 'pennsylvania', 'ri': 'rhode island', 'sc': 'south carolina',
    'sd': 'south dakota', 'tn': 'tennessee', 'tx': 'texas', 'ut': 'utah',
    'vt': 'vermont', 'va': 'virginia', 'wa': 'washington', 'wv': 'west virginia',
    'wi': 'wisconsin', 'wy': 'wyoming',
}

# =============================================================================
# SUFFIXES AND PREFIXES TO REMOVE
# =============================================================================

# Common suffixes to strip (order by length, longest first applied)
# NOTE: "united" is NOT stripped - it's part of the club name (Sacramento United, Atlanta United)
SUFFIXES_TO_STRIP = [
    # Long forms first
    ' soccer club',
    ' football club',
    ' soccer academy',
    ' futbol club',
    ' athletic club',
    ' youth soccer',
    ' youth soccer club',
    ' academy',
    ' soccer',
    # Short forms
    ' fc',
    ' sc',
    ' sa',
    ' ac',
    ' cf',
    ' afc',
    ' ys',
    ' ysc',
]

# Prefixes to strip
PREFIXES_TO_STRIP = [
    'fc ',
    'sc ',
    'cf ',
    'ac ',
    'afc ',
]

# Location suffixes pattern (e.g., "- AZ", "- Arizona", "- CA")
LOCATION_SUFFIX_PATTERN = re.compile(
    r'\s*[-–—]\s*('
    r'[A-Z]{2}|'  # State codes: AZ, CA, TX
    r'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|'
    r'Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|'
    r'Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|'
    r'Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|'
    r'New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|'
    r'Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|'
    r'Virginia|Washington|West Virginia|Wisconsin|Wyoming'
    r')\s*$',
    re.IGNORECASE
)

# Age group pattern (e.g., "U13", "U-14", "U15 Boys", "2012")
AGE_GROUP_PATTERN = re.compile(
    r'\s*(?:'
    r'U[-]?\d{1,2}(?:\s*(?:Boys?|Girls?|[BG]|HD|AD))?|'  # U13, U-14, U13 Boys, U13B, U13 HD
    r'\d{4}(?:\s*(?:Boys?|Girls?|[BG]))?|'  # 2012, 2012 Boys
    r'(?:Boys?|Girls?)\s*U[-]?\d{1,2}'  # Boys U13
    r')\s*$',
    re.IGNORECASE
)


# =============================================================================
# CANONICAL CLUB REGISTRY
# =============================================================================

# Known canonical clubs with their variations (including common abbreviations)
# Format: 'canonical_name': ['variation1', 'variation2', ...]
# IMPORTANT: Include common abbreviations like PRFC, LAFC, ATLUTD, etc.
CANONICAL_CLUBS: Dict[str, List[str]] = {
    # MLS Clubs
    'PHOENIX RISING': [
        'phoenix rising', 'phx rising', 'phoenix rising fc',
        'phoenix rising soccer club', 'pr fc', 'prfc', 'phxrfc',
        'phoenix rising sc', 'prsc'
    ],
    'LA GALAXY': [
        'la galaxy', 'los angeles galaxy', 'galaxy', 'lag', 'lagalaxy',
        'la galaxy fc', 'galaxy fc', 'galaxy sc'
    ],
    'FC DALLAS': [
        'fc dallas', 'dallas fc', 'fcd', 'dallas', 'fcdallas',
        'dallas sc', 'dal fc'
    ],
    'SPORTING KC': [
        'sporting kc', 'sporting kansas city', 'skc', 'kansas city',
        'sporting', 'kc sporting', 'sportingkc'
    ],
    'REAL SALT LAKE': [
        'real salt lake', 'rsl', 'salt lake', 'real sl',
        'rsl fc', 'salt lake fc', 'slc fc'
    ],
    'SEATTLE SOUNDERS': [
        'seattle sounders', 'sounders fc', 'sounders', 'seattle sounders fc',
        'ssfc', 'sea sounders', 'seattle fc'
    ],
    'PORTLAND TIMBERS': [
        'portland timbers', 'timbers', 'timbers fc', 'ptfc',
        'portland fc', 'pdx timbers'
    ],
    'COLORADO RAPIDS': [
        'colorado rapids', 'rapids', 'rapids fc', 'col rapids',
        'colorado fc', 'corap'
    ],
    'AUSTIN FC': [
        'austin fc', 'austin', 'afc austin', 'atxfc', 'atx fc',
        'austin football club', 'austinfc'
    ],
    'HOUSTON DYNAMO': [
        'houston dynamo', 'dynamo', 'houston dynamo fc', 'hdfc',
        'hou dynamo', 'dynamo fc', 'houston fc'
    ],
    'MINNESOTA UNITED': [
        'minnesota united', 'mn united', 'mnufc', 'loons',
        'minnesota utd', 'minn united', 'minnesota fc'
    ],
    'ATLANTA UNITED': [
        'atlanta united', 'atl united', 'atlutd', 'atlanta utd',
        'atl utd', 'aufc', 'atlanta united fc', 'atlunitedfc'
    ],
    'INTER MIAMI': [
        'inter miami', 'inter miami cf', 'miami', 'imcf',
        'miami fc', 'inter miami fc', 'mia inter'
    ],
    'ORLANDO CITY': [
        'orlando city', 'orlando city sc', 'ocsc', 'orlando',
        'orl city', 'orlando sc', 'orlandocity'
    ],
    'NASHVILLE SC': [
        'nashville sc', 'nashville', 'nsc', 'nashvillesc',
        'nash sc', 'nashville fc'
    ],
    'CHARLOTTE FC': [
        'charlotte fc', 'charlotte', 'cltfc', 'cfc',
        'charlotte football club', 'charlottefc', 'clt fc'
    ],
    'DC UNITED': [
        'dc united', 'd.c. united', 'dcu', 'washington dc united',
        'dcunited', 'dc utd', 'dcfc', 'washington united'
    ],
    'NEW YORK RED BULLS': [
        'new york red bulls', 'ny red bulls', 'red bulls', 'nyrb', 'rbny',
        'nyredbulls', 'new york rb', 'nyrb fc'
    ],
    'NYCFC': [
        'nycfc', 'new york city fc', 'nyc fc', 'new york city',
        'ny city fc', 'newyorkcityfc', 'nyfc'
    ],
    'NEW ENGLAND REVOLUTION': [
        'new england revolution', 'revolution', 'revs', 'ne revolution',
        'nerevs', 'new england revs', 'ner', 'ne revs'
    ],
    'PHILADELPHIA UNION': [
        'philadelphia union', 'philly union', 'union', 'phl union',
        'phila union', 'phi union', 'philaunion', 'doop'
    ],
    'CHICAGO FIRE': [
        'chicago fire', 'fire fc', 'chicago fire fc', 'cf97',
        'cffc', 'chi fire', 'chifire'
    ],
    'COLUMBUS CREW': [
        'columbus crew', 'crew', 'crew sc', 'the crew',
        'colcrew', 'cbus crew', 'columbus sc'
    ],
    'CINCINNATI FC': [
        'fc cincinnati', 'cincinnati fc', 'fcc', 'cincy',
        'cincinatti fc', 'cinci fc', 'fccincy'
    ],
    'TORONTO FC': [
        'toronto fc', 'tfc', 'toronto', 'tor fc',
        'torontofc', 'toronto football club'
    ],
    'CF MONTREAL': [
        'cf montreal', 'montreal', 'cfm', 'montreal impact', 'impact',
        'cfmontreal', 'mtl fc', 'montreal fc'
    ],
    'VANCOUVER WHITECAPS': [
        'vancouver whitecaps', 'whitecaps', 'whitecaps fc', 'vwfc',
        'van whitecaps', 'vancouver fc', 'vanwfc'
    ],
    'SAN JOSE EARTHQUAKES': [
        'san jose earthquakes', 'earthquakes', 'quakes', 'sj earthquakes',
        'sjeq', 'san jose fc', 'sjquakes'
    ],
    'LAFC': [
        'lafc', 'los angeles fc', 'la fc', 'los angeles football club',
        'losangelesfc', 'la football club'
    ],
    'ST LOUIS CITY': [
        'st louis city', 'stl city', 'st louis city sc', 'stl city sc',
        'stlcity', 'st louis sc', 'stl sc', 'stlouiscity'
    ],

    # Major Youth Clubs / Academies
    'ALBION SC': [
        'albion sc', 'albion', 'albion soccer club'
    ],
    'SOLAR SC': [
        'solar sc', 'solar soccer club', 'solar', 'dallas solar'
    ],
    'SURF': [
        'surf', 'surf sc', 'surf soccer club', 'sd surf', 'san diego surf'
    ],
    'BARCELONA': [
        'barcelona', 'barca', 'barcelona usa', 'barca academy', 'barca residency'
    ],
    'IMG ACADEMY': [
        'img academy', 'img', 'img soccer'
    ],
    'REAL SO CAL': [
        'real so cal', 'real socal', 'rsc', 'real southern california'
    ],
    'CROSSFIRE': [
        'crossfire', 'crossfire premier', 'crossfire united'
    ],
    'CONCORDE FIRE': [
        'concorde fire', 'concorde', 'cfire'
    ],
    'FC UNITED': [
        'fc united', 'fcu'
    ],
    'BALTIMORE ARMOUR': [
        'baltimore armour', 'armour', 'balt armour'
    ],
    'PA CLASSICS': [
        'pa classics', 'pennsylvania classics', 'pa classic'
    ],
    'MICHIGAN JAGUARS': [
        'michigan jaguars', 'jaguars', 'mi jaguars'
    ],
    'SOCKERS FC': [
        'sockers fc', 'sockers', 'chicago sockers'
    ],
    'LONESTAR': [
        'lonestar', 'lonestar sc', 'lone star', 'lonestar soccer'
    ],
    'TOPHAT': [
        'tophat', 'tophat sc', 'top hat', 'atlanta tophat'
    ],
    'BEADLING SC': [
        'beadling sc', 'beadling', 'beadling soccer club'
    ],
    'LAMORINDA': [
        'lamorinda', 'lamorinda sc', 'lamorinda soccer club', 'lamorinda united'
    ],
    'SACRAMENTO UNITED': [
        'sacramento united', 'sac united', 'sacramento utd'
    ],
    'SC WAVE': [
        'sc wave', 'wave sc', 'wave'
    ],
    'NEFC': [
        'nefc', 'new england fc', 'new england football club'
    ],
    'GFI ACADEMY': [
        'gfi academy', 'global football innovation academy', 'gfi', 'gfia'
    ],
    'KINGS HAMMER': [
        'kings hammer', 'kings hammer fc', 'kings hammer academy'
    ],
    'HOUSTON RANGERS': [
        'houston rangers', 'rangers houston', 'h rangers'
    ],
    'INTER ATLANTA': [
        'inter atlanta', 'inter atlanta fc', 'inter atl'
    ],
    'IRONBOUND SC': [
        'ironbound sc', 'ironbound', 'ironbound soccer club'
    ],
    'BAVARIAN UNITED': [
        'bavarian united', 'bavarian united sc', 'bavarian'
    ],
    'CLUB OHIO': [
        'club ohio', 'ohio soccer', 'ohio'
    ],
    'CITY SC': [
        'city sc', 'city soccer club'
    ],
    'VENTURA COUNTY FUSION': [
        'ventura county fusion', 'vc fusion', 'fusion', 'ventura fusion'
    ],
    'BALLISTIC UNITED': [
        'ballistic united', 'ballistic', 'ballistic sc'
    ],
    'ACHILLES FC': [
        'achilles fc', 'achilles', 'achilles football club'
    ],
    'ATHLETUM FC': [
        'athletum fc', 'athletum', 'athletum fc academy'
    ],
    'ONE FC': [
        'one fc', 'one football club', '1fc'
    ],
    'HOOSIER PREMIER': [
        'hoosier premier', 'hoosier', 'hoosier fc'
    ],
    'NORTHERN VIRGINIA ALLIANCE': [
        'northern virginia alliance', 'nova alliance', 'nva', 'nova'
    ],
    'OAKWOOD SC': [
        'oakwood sc', 'oakwood', 'oakwood soccer club'
    ],
    'IDEASPORT SA': [
        'ideasport sa', 'ideasport', 'idea sport'
    ],
    'GINGA FC': [
        'ginga fc', 'ginga', 'ginga football club'
    ],
    'FC BAY AREA': [
        'fc bay area', 'bay area fc', 'bay area surf', 'fc bay area surf'
    ],
    'ALEXANDRIA SA': [
        'alexandria sa', 'alexandria', 'alexandria soccer'
    ],
}

# Build reverse lookup: variation -> canonical
_VARIATION_TO_CANONICAL: Dict[str, str] = {}
for canonical, variations in CANONICAL_CLUBS.items():
    for var in variations:
        _VARIATION_TO_CANONICAL[var.lower()] = canonical


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================

def _clean_basic(name: str) -> str:
    """Basic cleaning: lowercase, strip, normalize whitespace"""
    if not name:
        return ''
    # Lowercase and strip
    name = name.lower().strip()
    # Replace multiple spaces with single space
    name = ' '.join(name.split())
    return name


def _remove_age_group(name: str) -> str:
    """Remove age group suffixes (U13, 2012 Boys, etc.)"""
    return AGE_GROUP_PATTERN.sub('', name).strip()


def _remove_location_suffix(name: str) -> str:
    """Remove location suffixes like '- AZ', '- California'"""
    return LOCATION_SUFFIX_PATTERN.sub('', name).strip()


def _remove_punctuation(name: str, keep_hyphens: bool = False) -> str:
    """Remove punctuation, optionally keeping hyphens"""
    if keep_hyphens:
        # Keep hyphens but remove other punctuation
        chars_to_remove = string.punctuation.replace('-', '')
    else:
        chars_to_remove = string.punctuation
    return name.translate(str.maketrans('', '', chars_to_remove))


def _expand_city_abbreviations(name: str) -> str:
    """Expand city abbreviations (PHX -> Phoenix, etc.)"""
    words = name.split()
    expanded = []
    for word in words:
        # Only expand if it's likely a city abbreviation (2-4 chars, all letters)
        if word in CITY_ABBREVIATIONS and len(word) <= 4:
            expanded.append(CITY_ABBREVIATIONS[word])
        else:
            expanded.append(word)
    return ' '.join(expanded)


def _strip_suffixes(name: str) -> str:
    """Strip common suffixes (FC, SC, Soccer Club, etc.)"""
    # Sort by length (longest first) to avoid partial matches
    for suffix in sorted(SUFFIXES_TO_STRIP, key=len, reverse=True):
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    return name


def _strip_prefixes(name: str) -> str:
    """Strip common prefixes (FC, SC, etc.)"""
    for prefix in PREFIXES_TO_STRIP:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
            break
    return name


def _generate_club_id(normalized_name: str) -> str:
    """Generate a stable club_id from normalized name (slug form)"""
    # Convert to slug: lowercase, replace spaces with underscores
    club_id = normalized_name.lower().strip()
    club_id = re.sub(r'[^a-z0-9]+', '_', club_id)
    club_id = club_id.strip('_')
    return club_id


def normalize_club_name(
    name: str,
    remove_age_group: bool = True,
    remove_location: bool = False,
    strip_suffixes: bool = False,
    strip_prefixes: bool = False,
) -> str:
    """
    Normalize a club name to a canonical form.

    Pipeline:
    1. Basic cleaning (lowercase, strip, normalize whitespace)
    2. Remove age group suffixes (U13, 2012 Boys, etc.)
    3. Remove location suffixes (- AZ, - California, etc.) - DISABLED by default
    4. Remove punctuation
    5. Expand city abbreviations (PHX -> Phoenix)
    6. Strip common suffixes (FC, SC, Soccer Club, etc.) - DISABLED by default
    7. Strip common prefixes (FC, SC, etc.) - DISABLED by default
    8. Final whitespace normalization

    Returns the normalized name in lowercase.
    """
    if not name:
        return ''

    # Step 1: Basic cleaning
    result = _clean_basic(name)

    # Step 2: Remove age group
    if remove_age_group:
        result = _remove_age_group(result)

    # Step 3: Remove location suffix (before removing punctuation)
    if remove_location:
        result = _remove_location_suffix(result)

    # Step 4: Remove punctuation (but preserve word boundaries)
    result = _remove_punctuation(result)

    # Step 5: Expand city abbreviations
    result = _expand_city_abbreviations(result)

    # Step 6: Strip suffixes (disabled by default)
    if strip_suffixes:
        result = _strip_suffixes(result)

    # Step 7: Strip prefixes (disabled by default)
    if strip_prefixes:
        result = _strip_prefixes(result)

    # Step 8: Final whitespace normalization
    result = ' '.join(result.split())

    return result


def lookup_canonical(normalized_name: str) -> Optional[str]:
    """
    Look up the canonical club name from the registry.

    Returns the canonical name if found, None otherwise.
    """
    return _VARIATION_TO_CANONICAL.get(normalized_name.lower())


def fuzzy_match_canonical(
    normalized_name: str,
    threshold: float = 0.85
) -> Optional[Tuple[str, float]]:
    """
    Fuzzy match against canonical club registry.

    Returns (canonical_name, score) if a match is found above threshold,
    None otherwise.
    """
    if not normalized_name:
        return None

    # Get all variations for fuzzy matching
    all_variations = list(_VARIATION_TO_CANONICAL.keys())

    if not all_variations:
        return None

    # Find best match using token_set_ratio (handles word reordering)
    result = process.extractOne(
        normalized_name.lower(),
        all_variations,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold * 100
    )

    if result:
        matched_variation, score, _ = result
        canonical = _VARIATION_TO_CANONICAL[matched_variation]
        return (canonical, score / 100.0)

    return None


def normalize_to_club(
    name: str,
    fuzzy_threshold: float = 0.85
) -> ClubNormResult:
    """
    Main entry point: Normalize a club name and return full result.

    This function:
    1. Normalizes the input name
    2. Looks up exact match in canonical registry
    3. If no exact match, tries fuzzy matching
    4. Returns a ClubNormResult with club_id, club_norm, confidence

    Args:
        name: Raw club name string
        fuzzy_threshold: Minimum similarity score for fuzzy matching (0.0-1.0)

    Returns:
        ClubNormResult with:
        - club_id: Stable identifier (slug form)
        - club_norm: Canonical display name (UPPERCASE)
        - original: Original input string
        - confidence: Match confidence (1.0 for exact, lower for fuzzy)
        - matched_canonical: Whether matched to a known club
    """
    if not name or not name.strip():
        return ClubNormResult(
            club_id='',
            club_norm='',
            original=name or '',
            confidence=0.0,
            matched_canonical=False
        )

    original = name

    # Step 1: Normalize the name
    normalized = normalize_club_name(name)

    if not normalized:
        return ClubNormResult(
            club_id='',
            club_norm='',
            original=original,
            confidence=0.0,
            matched_canonical=False
        )

    # Step 2: Try exact lookup
    canonical = lookup_canonical(normalized)
    if canonical:
        return ClubNormResult(
            club_id=_generate_club_id(canonical),
            club_norm=canonical,
            original=original,
            confidence=1.0,
            matched_canonical=True
        )

    # Step 3: Try fuzzy matching
    fuzzy_result = fuzzy_match_canonical(normalized, fuzzy_threshold)
    if fuzzy_result:
        canonical, score = fuzzy_result
        return ClubNormResult(
            club_id=_generate_club_id(canonical),
            club_norm=canonical,
            original=original,
            confidence=score,
            matched_canonical=True
        )

    # Step 4: No match - use normalized form
    # Convert to uppercase for display
    club_norm = normalized.upper()
    club_id = _generate_club_id(normalized)

    return ClubNormResult(
        club_id=club_id,
        club_norm=club_norm,
        original=original,
        confidence=0.8,  # Decent confidence in normalization, just not canonical
        matched_canonical=False
    )


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def normalize_club_names_batch(
    names: List[str],
    fuzzy_threshold: float = 0.85
) -> List[ClubNormResult]:
    """
    Normalize a batch of club names.

    Args:
        names: List of raw club name strings
        fuzzy_threshold: Minimum similarity for fuzzy matching

    Returns:
        List of ClubNormResult objects in the same order as input
    """
    return [normalize_to_club(name, fuzzy_threshold) for name in names]


def build_club_mapping(
    names: List[str],
    fuzzy_threshold: float = 0.85
) -> Dict[str, ClubNormResult]:
    """
    Build a mapping from original names to normalized results.

    Useful for deduplication: find all unique clubs from a list of names.

    Args:
        names: List of raw club name strings
        fuzzy_threshold: Minimum similarity for fuzzy matching

    Returns:
        Dict mapping original name -> ClubNormResult
    """
    return {name: normalize_to_club(name, fuzzy_threshold) for name in names}


def group_by_club(
    names: List[str],
    fuzzy_threshold: float = 0.85
) -> Dict[str, List[str]]:
    """
    Group raw club names by their normalized club_id.

    Useful for seeing all variations that map to the same club.

    Args:
        names: List of raw club name strings
        fuzzy_threshold: Minimum similarity for fuzzy matching

    Returns:
        Dict mapping club_id -> list of original names
    """
    groups: Dict[str, List[str]] = {}
    for name in names:
        result = normalize_to_club(name, fuzzy_threshold)
        if result.club_id:
            if result.club_id not in groups:
                groups[result.club_id] = []
            groups[result.club_id].append(name)
    return groups


def get_matches_needing_review(
    names: List[str],
    fuzzy_threshold: float = 0.85
) -> List[ClubNormResult]:
    """
    Get all matches that need manual review (not 100% confident).

    A match needs review if:
    - It didn't match a known canonical club, OR
    - The confidence score is less than 1.0 (fuzzy match)

    Args:
        names: List of raw club name strings
        fuzzy_threshold: Minimum similarity for fuzzy matching

    Returns:
        List of ClubNormResult objects that need review
    """
    results = normalize_club_names_batch(names, fuzzy_threshold)
    return [r for r in results if r.needs_review]


def get_confident_matches(
    names: List[str],
    fuzzy_threshold: float = 0.85
) -> List[ClubNormResult]:
    """
    Get all matches that are 100% confident (exact canonical matches).

    Args:
        names: List of raw club name strings
        fuzzy_threshold: Minimum similarity for fuzzy matching

    Returns:
        List of ClubNormResult objects that are confident
    """
    results = normalize_club_names_batch(names, fuzzy_threshold)
    return [r for r in results if not r.needs_review]


# =============================================================================
# REGISTRY MANAGEMENT
# =============================================================================

def add_canonical_club(canonical: str, variations: List[str]) -> None:
    """
    Add a new canonical club to the registry at runtime.

    Args:
        canonical: The canonical club name (will be uppercased)
        variations: List of known variations (will be lowercased)
    """
    canonical_upper = canonical.upper()
    variations_lower = [v.lower() for v in variations]

    # Add to main registry
    if canonical_upper not in CANONICAL_CLUBS:
        CANONICAL_CLUBS[canonical_upper] = []
    CANONICAL_CLUBS[canonical_upper].extend(variations_lower)

    # Update reverse lookup
    for var in variations_lower:
        _VARIATION_TO_CANONICAL[var] = canonical_upper


def get_all_canonical_clubs() -> List[str]:
    """Return list of all canonical club names"""
    return list(CANONICAL_CLUBS.keys())


def get_variations_for_club(canonical: str) -> List[str]:
    """Return all known variations for a canonical club name"""
    return CANONICAL_CLUBS.get(canonical.upper(), [])


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def similarity_score(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two club names.

    Returns a score from 0.0 to 1.0.
    """
    norm1 = normalize_club_name(name1)
    norm2 = normalize_club_name(name2)

    if not norm1 or not norm2:
        return 0.0

    if norm1 == norm2:
        return 1.0

    # Use token_set_ratio for best results with reordered words
    return fuzz.token_set_ratio(norm1, norm2) / 100.0


def are_same_club(
    name1: str,
    name2: str,
    threshold: float = 0.85
) -> bool:
    """
    Check if two club names refer to the same club.

    Args:
        name1: First club name
        name2: Second club name
        threshold: Minimum similarity score to consider same club

    Returns:
        True if the names refer to the same club
    """
    result1 = normalize_to_club(name1)
    result2 = normalize_to_club(name2)

    # If both matched to canonical, compare canonical names
    if result1.matched_canonical and result2.matched_canonical:
        return result1.club_id == result2.club_id

    # Otherwise, compare similarity
    return similarity_score(name1, name2) >= threshold
