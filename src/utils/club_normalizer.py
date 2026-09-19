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

import re
import string
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, FrozenSet, List, Optional, Tuple

from src.utils.us_states import STATE_CODE_TO_NAME


@dataclass
class ClubNormResult:
    """Result of club name normalization"""

    club_id: str  # Stable identifier (slug form): "phoenix_rising"
    club_norm: str  # Canonical display name: "PHOENIX RISING"
    original: str  # Original input string
    confidence: float  # 0.0-1.0, how confident we are in the match
    matched_canonical: bool  # True if matched to a known canonical club

    @property
    def needs_review(self) -> bool:
        """True if this match should be manually reviewed (not a registered club)"""
        return not self.matched_canonical


# =============================================================================
# ABBREVIATION MAPPINGS
# =============================================================================

# City/Location abbreviations
CITY_ABBREVIATIONS = {
    "phx": "phoenix",
    "la": "los angeles",
    "nyc": "new york city",
    "ny": "new york",
    "sf": "san francisco",
    "sd": "san diego",
    "dc": "washington dc",
    "stl": "st louis",
    "kc": "kansas city",
    "atl": "atlanta",
    "chi": "chicago",
    "det": "detroit",
    "dal": "dallas",
    "hou": "houston",
    "mia": "miami",
    "sea": "seattle",
    "den": "denver",
    "min": "minnesota",
    "cin": "cincinnati",
    "cle": "cleveland",
    "pit": "pittsburgh",
    "bal": "baltimore",
    "phi": "philadelphia",
    "bos": "boston",
    "lv": "las vegas",
    "orl": "orlando",
    "tb": "tampa bay",
    "sac": "sacramento",
    "slc": "salt lake city",
    "okc": "oklahoma city",
    "indy": "indianapolis",
    "jax": "jacksonville",
    "char": "charlotte",
    "nash": "nashville",
    "mem": "memphis",
    "nola": "new orleans",
    "pdx": "portland",
    "philly": "philadelphia",
    "cbus": "columbus",
    "rdu": "raleigh",
    "rva": "richmond",
    "dfw": "dallas fort worth",
}

# =============================================================================
# SUFFIXES AND PREFIXES TO REMOVE
# =============================================================================

# Common suffixes to strip (order by length, longest first applied)
# NOTE: "united" is NOT stripped - it's part of the club name (Sacramento United, Atlanta United)
SUFFIXES_TO_STRIP = [
    # Long forms first
    " soccer club",
    " football club",
    " soccer academy",
    " futbol club",
    " athletic club",
    " youth soccer",
    " youth soccer club",
    " academy",
    " soccer",
    # Short forms
    " fc",
    " sc",
    " sa",
    " ac",
    " cf",
    " afc",
    " ys",
    " ysc",
]

# Prefixes to strip
PREFIXES_TO_STRIP = [
    "fc ",
    "sc ",
    "cf ",
    "ac ",
    "afc ",
]

# Location suffixes pattern (e.g., "- AZ", "- Arizona", "- CA")
LOCATION_SUFFIX_PATTERN = re.compile(
    r"\s*[-–—]\s*("
    r"[A-Z]{2}|"  # State codes: AZ, CA, TX
    r"Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|"
    r"Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
    r"Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|"
    r"New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
    r"Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|"
    r"Virginia|Washington|West Virginia|Wisconsin|Wyoming"
    r")\s*$",
    re.IGNORECASE,
)

# Age group pattern (e.g., "U13", "U-14", "U15 Boys", "2012")
AGE_GROUP_PATTERN = re.compile(
    r"\s*(?:"
    r"U[-]?\d{1,2}(?:\s*(?:Boys?|Girls?|[BG]|HD|AD))?|"  # U13, U-14, U13 Boys, U13B, U13 HD
    r"\d{4}(?:\s*(?:Boys?|Girls?|[BG]))?|"  # 2012, 2012 Boys
    r"(?:Boys?|Girls?)\s*U[-]?\d{1,2}"  # Boys U13
    r")\s*$",
    re.IGNORECASE,
)

# Club suffix phrases shortened to their codes in a name's light form, applied in order
# so the longer phrase wins ("youth soccer club" before "soccer club").
SUFFIX_PHRASE_CODES = [
    (re.compile(r"\byouth soccer club\b", re.ASCII), "ysc"),
    (re.compile(r"\byouth soccer\b", re.ASCII), "ys"),
    (re.compile(r"\bsoccer club\b", re.ASCII), "sc"),
    (re.compile(r"\bfutbol club\b", re.ASCII), "fc"),
    (re.compile(r"\bfootball club\b", re.ASCII), "fc"),
    (re.compile(r"\bsoccer academy\b", re.ASCII), "sa"),
    (re.compile(r"\bfutbol academy\b", re.ASCII), "fa"),
    (re.compile(r"\bfootball academy\b", re.ASCII), "fa"),
    (re.compile(r"\bsoccer association\b", re.ASCII), "sa"),
    (re.compile(r"\bsoccer assn\b", re.ASCII), "sa"),
    (re.compile(r"\bathletic club\b", re.ASCII), "ac"),
]

# Club codes by the kind of organisation they name. Equal cores that both carry codes but
# share no family are different clubs ("Tyler FC", "Tyler SA"); in that test alone
# similarity_score counts a youth code as a club code.
CODE_FAMILIES = {
    "sc": "club",
    "fc": "club",
    "cf": "club",
    "afc": "club",
    "ysc": "club",
    "cd": "club",
    "sa": "academy",
    "fa": "academy",
    "ac": "athletic",
    "ys": "youth",
}
CLUB_CODES = frozenset(CODE_FAMILIES)
NEUTRAL_WORDS = frozenset({"soccer", "academy", "club", "futbol", "football"})

# A core made only of these words names a place, which many unrelated clubs share.
PLACE_WORDS = frozenset(
    {word for state in STATE_CODE_TO_NAME.values() for word in state.lower().split()}
    | {word for city in CITY_ABBREVIATIONS.values() for word in city.split()}
    | set(
        "los angeles san diego jose francisco new york england jersey st saint louis salt lake bay area "
        "north south east west central southern northern so cal socal city tampa fort worth vegas las "
        "silicon valley county".split()
    )
)


# =============================================================================
# CANONICAL CLUB REGISTRY
# =============================================================================

# Known canonical clubs with their variations (including common abbreviations)
# Format: 'canonical_name': ['variation1', 'variation2', ...]
# Include a club's abbreviations (PRFC, LAFC, ATLUTD) unless another club could share them;
# SHARED_CLUB_NAMES drops those keys.
CANONICAL_CLUBS: Dict[str, List[str]] = {
    # MLS Clubs
    "PHOENIX RISING": [
        "phoenix rising",
        "phx rising",
        "phoenix rising fc",
        "phoenix rising soccer club",
        "pr fc",
        "prfc",
        "phxrfc",
        "phoenix rising sc",
        "prsc",
    ],
    "LA GALAXY": [
        "la galaxy",
        "los angeles galaxy",
        "lagalaxy",
        "la galaxy fc",
    ],
    "FC DALLAS": ["fc dallas", "fcdallas", "dal fc"],
    "SPORTING KC": [
        "sporting kc",
        "sporting kansas city",
        "skc",
        "kc sporting",
        "sportingkc",
    ],
    "REAL SALT LAKE": ["real salt lake", "rsl", "salt lake", "real sl", "rsl fc"],
    "SEATTLE SOUNDERS": [
        "seattle sounders",
        "sounders",
        "seattle sounders fc",
        "ssfc",
        "sea sounders",
    ],
    "PORTLAND TIMBERS": ["portland timbers", "timbers", "ptfc", "pdx timbers"],
    "COLORADO RAPIDS": ["colorado rapids", "col rapids", "corap"],
    "AUSTIN FC": ["austin fc", "afc austin", "atxfc", "atx fc", "austin football club", "austinfc"],
    "HOUSTON DYNAMO": [
        "houston dynamo",
        "houston dynamo fc",
        "hdfc",
        "hou dynamo",
    ],
    "MINNESOTA UNITED": [
        "minnesota united",
        "mn united",
        "mnufc",
        "loons",
        "minnesota utd",
        "minn united",
        "minnesota fc",
    ],
    "ATLANTA UNITED": [
        "atlanta united",
        "atl united",
        "atlutd",
        "atlanta utd",
        "atl utd",
        "aufc",
        "atlanta united fc",
        "atlunitedfc",
    ],
    "INTER MIAMI": ["inter miami", "inter miami cf", "imcf", "inter miami fc", "mia inter"],
    "ORLANDO CITY": ["orlando city", "orlando city sc", "ocsc", "orl city", "orlandocity"],
    "NASHVILLE SC": ["nashville sc", "nashvillesc", "nash sc"],
    "CHARLOTTE FC": ["charlotte fc", "cltfc", "charlotte football club", "charlottefc", "clt fc"],
    "DC UNITED": [
        "dc united",
        "d.c. united",
        "dcu",
        "washington dc united",
        "dcunited",
        "dc utd",
        "dcfc",
        "washington united",
    ],
    "NEW YORK RED BULLS": [
        "new york red bulls",
        "ny red bulls",
        "red bulls",
        "nyrb",
        "rbny",
        "nyredbulls",
        "new york rb",
        "nyrb fc",
    ],
    "NYCFC": ["nycfc", "new york city fc", "nyc fc", "new york city", "ny city fc", "newyorkcityfc", "nyfc"],
    "NEW ENGLAND REVOLUTION": [
        "new england revolution",
        "revs",
        "ne revolution",
        "nerevs",
        "new england revs",
        "ne revs",
    ],
    "PHILADELPHIA UNION": [
        "philadelphia union",
        "philly union",
        "phl union",
        "phila union",
        "phi union",
        "philaunion",
        "doop",
    ],
    "CHICAGO FIRE": ["chicago fire", "chicago fire fc", "cf97", "cffc", "chi fire", "chifire"],
    "COLUMBUS CREW": ["columbus crew", "the crew", "colcrew", "cbus crew"],
    "CINCINNATI FC": ["fc cincinnati", "cincinnati fc", "cincy", "cincinatti fc", "cinci fc", "fccincy"],
    "TORONTO FC": ["toronto fc", "tor fc", "torontofc", "toronto football club"],
    "CF MONTREAL": [
        "cf montreal",
        "montreal impact",
        "cfmontreal",
        "mtl fc",
        "montreal fc",
    ],
    "VANCOUVER WHITECAPS": [
        "vancouver whitecaps",
        "whitecaps",
        "vwfc",
        "van whitecaps",
        "vancouver fc",
        "vanwfc",
    ],
    "SAN JOSE EARTHQUAKES": [
        "san jose earthquakes",
        "sj earthquakes",
        "san jose fc",
        "sjquakes",
    ],
    "LAFC": ["lafc", "los angeles fc", "la fc", "los angeles football club", "losangelesfc", "la football club"],
    "ST LOUIS CITY": [
        "st louis city",
        "stl city",
        "st louis city sc",
        "stl city sc",
        "stlcity",
        "st louis sc",
        "stl sc",
        "stlouiscity",
    ],
    # Major Youth Clubs / Academies
    "ALBION SC": ["albion sc", "albion soccer club"],
    "SOLAR SC": ["solar sc", "solar soccer club", "solar", "dallas solar"],
    "SURF": ["surf sc", "surf soccer club", "sd surf", "san diego surf"],
    "BARCELONA": ["barcelona usa", "barca academy"],
    "IMG ACADEMY": ["img academy", "img", "img soccer"],
    "REAL SO CAL": ["real so cal", "real socal", "real southern california"],
    "CROSSFIRE": ["crossfire premier", "crossfire united"],
    "CONCORDE FIRE": ["concorde fire", "cfire"],
    "FC UNITED": ["fc united"],
    "BALTIMORE ARMOUR": ["baltimore armour", "balt armour"],
    "PA CLASSICS": ["pa classics", "pennsylvania classics", "pa classic"],
    "MICHIGAN JAGUARS": ["michigan jaguars", "mi jaguars"],
    "SOCKERS FC": ["sockers fc", "chicago sockers"],
    "LONESTAR": ["lonestar", "lonestar sc", "lone star", "lonestar soccer"],
    "TOPHAT": ["tophat", "tophat sc", "top hat", "atlanta tophat"],
    "BEADLING SC": ["beadling sc", "beadling", "beadling soccer club"],
    "LAMORINDA": ["lamorinda sc", "lamorinda soccer club", "lamorinda united"],
    "SACRAMENTO UNITED": ["sacramento united", "sac united", "sacramento utd"],
    "SC WAVE": ["sc wave"],
    "NEFC": ["nefc", "new england football club"],
    "GFI ACADEMY": ["gfi academy", "global football innovation academy", "gfi", "gfia"],
    "KINGS HAMMER": ["kings hammer", "kings hammer fc", "kings hammer academy"],
    "HOUSTON RANGERS": ["houston rangers", "rangers houston", "h rangers"],
    "INTER ATLANTA": ["inter atlanta", "inter atlanta fc", "inter atl"],
    "IRONBOUND SC": ["ironbound sc", "ironbound", "ironbound soccer club"],
    "BAVARIAN UNITED": ["bavarian united", "bavarian united sc", "bavarian", "bavarian sc"],
    "CLUB OHIO": ["club ohio", "ohio soccer"],
    "CITY SC": ["city sc", "city soccer club"],
    "VENTURA COUNTY FUSION": ["ventura county fusion", "vc fusion", "ventura fusion"],
    "BALLISTIC UNITED": ["ballistic united", "ballistic", "ballistic sc"],
    "ACHILLES FC": ["achilles fc", "achilles", "achilles football club"],
    "ATHLETUM FC": ["athletum fc", "athletum", "athletum fc academy"],
    "ONE FC": ["one fc", "one football club", "1fc"],
    "HOOSIER PREMIER": ["hoosier premier"],
    "NORTHERN VIRGINIA ALLIANCE": ["northern virginia alliance", "nova alliance", "nva", "nova"],
    "OAKWOOD SC": ["oakwood sc", "oakwood soccer club"],
    "IDEASPORT SA": ["ideasport sa", "ideasport", "idea sport"],
    "GINGA FC": ["ginga fc", "ginga", "ginga football club"],
    "FC BAY AREA": ["fc bay area", "bay area fc", "bay area surf", "fc bay area surf"],
    "ALEXANDRIA SA": ["alexandria sa", "alexandria soccer"],
    # =========================================================================
    # CLUBS FROM MERGE HISTORY (acronym → full name mappings)
    # =========================================================================
    "LOS ANGELES SC": ["los angeles sc", "lasc", "la sc", "los angeles soccer club"],
    "JACKSONVILLE FC": ["jacksonville fc", "jax fc"],
    "FL PREMIER FC": ["fl premier fc", "fpfc", "florida premier fc", "florida premier"],
    "WOODSIDE SOCCER CLUB": ["woodside soccer club", "woodside sc"],
    "SILICON VALLEY SA": [
        "silicon valley soccer academy",
        "svsa",
        "silicon valley sa",
        "sv soccer academy",
        "silicon valley",
    ],
    "THE TOWN FC": ["the town fc", "ttfc", "town fc", "the town fc academy"],
    "TOTAL FUTBOL ACADEMY": ["total futbol academy", "tfa", "tfa-pro", "tfapro", "total futbol"],
    "WESTERN IOWA SURF": ["western iowa surf", "wi surf", "iowa surf"],
    "RSL ARIZONA": ["rsl arizona", "rsl az", "real salt lake arizona"],
    "CEDAR STARS ACADEMY": ["cedar stars academy", "cedar stars"],
    "ST LOUIS SCOTT GALLAGHER": ["st louis scott gallagher", "slsg", "scott gallagher"],
    "LOU FUSZ ATHLETIC": ["lou fusz athletic", "lou fusz", "lou fusz athletic 2"],
    "PDA": ["players development academy", "pda"],
    "FC DELCO": ["fc delco", "delco", "delco fc"],
    "BETHESDA SC": ["bethesda sc", "bethesda soccer club"],
    "MCLEAN YOUTH SOCCER": ["mclean youth soccer"],
    "CHARLOTTE INDEPENDENCE": [
        "charlotte independence",
        "charlotte independence soccer club",
        "clt independence",
    ],
    "CHICAGO FC UNITED": ["chicago fc united", "cfcu", "chicago fcu"],
    "SPORTING BLUE VALLEY": ["sporting blue valley", "blue valley"],
    "SPORTING OKLAHOMA": ["sporting oklahoma", "sporting ok"],
    "MICHIGAN WOLVES": ["michigan wolves", "mi wolves"],
    "VARDAR SOCCER CLUB": ["vardar soccer club", "vardar", "vardar sc"],
    "DE ANZA FORCE": ["de anza force", "deanza force", "de anza"],
    "STRIKERS FC": ["strikers fc", "irvine strikers"],
    "WESTON FC": ["weston fc", "weston football club"],
    "TAMPA BAY UNITED": ["tampa bay united", "tb united", "tampa united"],
    "FC GOLDEN STATE": ["fc golden state", "fcgs", "golden state fc", "fc golden state force"],
    "SEACOAST UNITED": ["seacoast united", "seacoast utd"],
    "COPPERMINE SC": ["coppermine sc", "coppermine soccer club"],
    "TSF ACADEMY": ["tsf academy", "the soccer factory"],
    "INDY ELEVEN": ["indy eleven", "indianapolis eleven", "indy 11"],
    "FORWARD MADISON FC": ["forward madison fc", "forward madison", "fmfc"],
    "SACRAMENTO REPUBLIC": ["sacramento republic fc", "sacramento republic", "sac republic", "srfc"],
    "SAN DIEGO FC": ["san diego fc", "sdfc", "sd fc"],
    "BARCA RESIDENCY ACADEMY": [
        "barca residency academy",
        "barca residency",
        "barcelona residency",
        "barca academy usa",
    ],
    "DALLAS HORNETS": ["dallas hornets"],
}

# Names other clubs share: places, generic soccer words, short acronyms and multi-word
# forms that name a different club. Nothing whose light form is one of these becomes a
# lookup key, so SURF, BARCELONA, CROSSFIRE and LAMORINDA do not claim their bare word,
# and an alias cannot rebuild a removed key through CITY_ABBREVIATIONS ("dal fc" is
# "dallas fc").
SHARED_CLUB_NAMES = frozenset(
    "austin charlotte dallas miami orlando nashville toronto montreal jacksonville alexandria ohio weston "
    "woodside bethesda oakwood mclean seacoast coppermine lamorinda hoosier albion fusion surf wave union "
    "impact independence revolution crew rapids galaxy dynamo hornets strikers sporting sockers jaguars "
    "armour quakes earthquakes barca barcelona concorde crossfire csa cfc nsc rsc wsc fcc fcu jfc lfa mys "
    "sbv sok tbu tfc tsf fcd lag ner sjeq cfm".split()
    + [
        "columbus sc", "houston fc", "wolves fc", "fire fc", "dallas fc", "dallas sc", "miami fc", "orlando sc",
        "nashville fc", "colorado fc", "portland fc", "salt lake fc", "slc fc", "seattle fc", "new england fc",
        "galaxy sc", "galaxy fc", "dynamo fc", "rapids fc", "wave sc", "crew sc", "hoosier fc", "timbers fc",
        "sounders fc", "whitecaps fc", "kansas city",
    ]
)


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================


def _clean_basic(name: str) -> str:
    """Basic cleaning: lowercase, strip, normalize whitespace, remove artifacts"""
    if not name:
        return ""

    # Lowercase and strip
    name = name.lower().strip()

    # Remove trailing "..." or "…" (truncation artifacts)
    name = re.sub(r"\.{2,}$", "", name)
    name = re.sub(r"…$", "", name)

    # Remove content in parentheses/brackets (often meta info like "(HFA)")
    # But keep the rest of the name
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    name = re.sub(r"\s*\[[^\]]*\]\s*", " ", name)

    # Normalize separators: replace /, \, _ with space
    name = re.sub(r"[/_\\]", " ", name)

    # Replace multiple spaces with single space
    name = " ".join(name.split())

    return name.strip()


def _remove_age_group(name: str) -> str:
    """Remove age group suffixes (U13, 2012 Boys, etc.)"""
    return AGE_GROUP_PATTERN.sub("", name).strip()


def _remove_location_suffix(name: str) -> str:
    """Remove location suffixes like '- AZ', '- California'"""
    return LOCATION_SUFFIX_PATTERN.sub("", name).strip()


def _remove_punctuation(name: str, keep_hyphens: bool = False) -> str:
    """Remove punctuation, optionally keeping hyphens"""
    if keep_hyphens:
        # Keep hyphens but remove other punctuation
        chars_to_remove = string.punctuation.replace("-", "")
    else:
        chars_to_remove = string.punctuation
    return name.translate(str.maketrans("", "", chars_to_remove))


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
    return " ".join(expanded)


def _strip_suffixes(name: str) -> str:
    """Strip common suffixes (FC, SC, Soccer Club, etc.)"""
    # Sort by length (longest first) to avoid partial matches
    for suffix in sorted(SUFFIXES_TO_STRIP, key=len, reverse=True):
        if name.endswith(suffix):
            stripped = name[: -len(suffix)].strip()
            # Don't strip if the remaining name is a single short word (<=3 chars)
            # e.g., "one fc" should stay as "one fc", not become "one"
            if len(stripped.split()) >= 2 or len(stripped) > 3:
                name = stripped
            break
    return name


def _strip_prefixes(name: str) -> str:
    """Strip common prefixes (FC, SC, etc.)"""
    for prefix in PREFIXES_TO_STRIP:
        if name.startswith(prefix):
            name = name[len(prefix) :].strip()
            break
    return name


def _generate_club_id(normalized_name: str) -> str:
    """Generate a stable club_id from normalized name (slug form)"""
    # Convert to slug: lowercase, replace spaces with underscores
    club_id = normalized_name.lower().strip()
    club_id = re.sub(r"[^a-z0-9]+", "_", club_id)
    club_id = club_id.strip("_")
    return club_id


def normalize_club_name(
    name: str,
    remove_age_group: bool = True,
    remove_location: bool = True,
    strip_suffixes: bool = True,
    strip_prefixes: bool = True,
) -> str:
    """
    Normalize a club name to a canonical form.

    Pipeline:
    1. Basic cleaning (lowercase, strip, normalize whitespace)
    2. Remove age group suffixes (U13, 2012 Boys, etc.)
    3. Remove location suffixes (- AZ, - California, etc.)
    4. Remove punctuation
    5. Expand city abbreviations (PHX -> Phoenix)
    6. Strip common suffixes (FC, SC, Soccer Club, etc.)
    7. Strip common prefixes (FC, SC, etc.)
    8. Final whitespace normalization

    Returns the normalized name in lowercase.
    """
    if not name:
        return ""

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

    # Step 6: Strip suffixes
    if strip_suffixes:
        result = _strip_suffixes(result)

    # Step 7: Strip prefixes
    if strip_prefixes:
        result = _strip_prefixes(result)

    # Step 8: Final whitespace normalization
    result = " ".join(result.split())

    return result


def _light_form(name: str) -> str:
    """A club name normalized with its club suffix kept, suffix phrases shortened to codes.

    "Charlotte Soccer Academy" -> "charlotte sa" and "Charlotte FC" -> "charlotte fc",
    two clubs that ``normalize_club_name`` reduces to one "charlotte".
    """
    result = normalize_club_name(name, strip_suffixes=False, strip_prefixes=False)
    for pattern, code in SUFFIX_PHRASE_CODES:
        result = pattern.sub(code, result)
    return " ".join(result.split())


_SHARED_KEYS = frozenset(_light_form(shared) for shared in SHARED_CLUB_NAMES)

# Reverse lookup: light form -> canonical. Never keyed on the suffix-stripped form,
# which collides clubs that differ only by their suffix. A key two clubs would claim
# is a registry error; a test forbids it.
_VARIATION_TO_CANONICAL: Dict[str, str] = {}
for canonical, variations in CANONICAL_CLUBS.items():
    for var in [canonical.lower(), *variations]:
        key = _light_form(var)
        if key not in _SHARED_KEYS:
            _VARIATION_TO_CANONICAL.setdefault(key, canonical)


def lookup_canonical(name: str) -> Optional[str]:
    """
    Look up the canonical club name from the registry.

    Matches the name's light form exactly.
    """
    return _VARIATION_TO_CANONICAL.get(_light_form(name))


def normalize_to_club(name: str) -> ClubNormResult:
    """
    Main entry point: Normalize a club name and return full result.

    Only an exact match of the name's light form is canonical. Character similarity
    against the registry's short names pairs unrelated clubs (NC Fusion with VENTURA
    COUNTY FUSION, NCFC with NYCFC), and a name that only begins with a registered one
    may be a branch fielding its own squads ("Albion SC San Diego"). A misspelling is
    left to ``similarity_score``.

    Args:
        name: Raw club name string

    Returns:
        ClubNormResult with:
        - club_id: Stable identifier (slug form)
        - club_norm: Canonical display name (UPPERCASE)
        - original: Original input string
        - confidence: Match confidence (1.0 for a registered club)
        - matched_canonical: Whether matched to a known club
    """
    if not name or not name.strip():
        return ClubNormResult(club_id="", club_norm="", original=name or "", confidence=0.0, matched_canonical=False)

    original = name

    normalized = normalize_club_name(name)

    if not normalized:
        return ClubNormResult(club_id="", club_norm="", original=original, confidence=0.0, matched_canonical=False)

    canonical = lookup_canonical(name)
    if canonical:
        return ClubNormResult(
            club_id=_generate_club_id(canonical),
            club_norm=canonical,
            original=original,
            confidence=1.0,
            matched_canonical=True,
        )

    club_norm = normalized.upper()
    club_id = _generate_club_id(normalized)

    return ClubNormResult(
        club_id=club_id,
        club_norm=club_norm,
        original=original,
        confidence=0.8,  # Decent confidence in normalization, just not canonical
        matched_canonical=False,
    )


# =============================================================================
# BATCH PROCESSING
# =============================================================================


def normalize_club_names_batch(names: List[str]) -> List[ClubNormResult]:
    """
    Normalize a batch of club names.

    Args:
        names: List of raw club name strings

    Returns:
        List of ClubNormResult objects in the same order as input
    """
    return [normalize_to_club(name) for name in names]


def group_by_club(names: List[str]) -> Dict[str, List[str]]:
    """
    Group raw club names by their normalized club_id.

    Useful for seeing all variations that map to the same club.

    Args:
        names: List of raw club name strings

    Returns:
        Dict mapping club_id -> list of original names
    """
    groups: Dict[str, List[str]] = {}
    for name in names:
        result = normalize_to_club(name)
        if result.club_id:
            if result.club_id not in groups:
                groups[result.club_id] = []
            groups[result.club_id].append(name)
    return groups


def get_matches_needing_review(names: List[str]) -> List[ClubNormResult]:
    """
    Get all matches that need manual review.

    A match needs review if it didn't match a known canonical club.

    Args:
        names: List of raw club name strings

    Returns:
        List of ClubNormResult objects that need review
    """
    results = normalize_club_names_batch(names)
    return [r for r in results if r.needs_review]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def _core_and_codes(name: str) -> Tuple[str, FrozenSet[str]]:
    """The words that tell a club apart, and the club codes peeled off to reach them.

    Code and neutral words are peeled from either end of the light form while more than
    one word is left: "Charlotte Soccer Academy" -> ("charlotte", {"sa"}), "FC Dallas" ->
    ("dallas", {"fc"}), "Club Ohio Soccer" -> ("ohio", set()).
    """
    words = _light_form(name).split()
    codes = set()
    peeled = True
    while peeled:
        peeled = False
        for end in (0, -1):
            if len(words) > 1 and (words[end] in CLUB_CODES or words[end] in NEUTRAL_WORDS):
                word = words.pop(end)
                if word in CLUB_CODES:
                    codes.add(word)
                peeled = True
    return " ".join(words), frozenset(codes)


def _signature(name: str) -> str:
    """The light form without neutral words, each code replaced by its family, order kept.

    "FC Arkansas" -> "club arkansas", "Arkansas Soccer Club" -> "arkansas club".
    """
    return " ".join(CODE_FAMILIES.get(word, word) for word in _light_form(name).split() if word not in NEUTRAL_WORDS)


def _families(codes: FrozenSet[str]) -> FrozenSet[str]:
    """The families of a name's club codes, a youth code counting as a club."""
    return frozenset("club" if CODE_FAMILIES[code] == "youth" else CODE_FAMILIES[code] for code in codes)


# difflib only: rapidfuzz is in neither requirements file, so CI and every workflow
# run without it.
def _word_set_similarity(s1: str, s2: str) -> float:
    """Word-set similarity of two names, 0.0-1.0.

    The higher of the sorted words' character similarity and the share of words the
    two have in common.
    """
    tokens1 = set(s1.lower().split())
    tokens2 = set(s2.lower().split())
    union = tokens1 | tokens2
    if not union:
        return 0.0
    sorted_s1 = " ".join(sorted(tokens1))
    sorted_s2 = " ".join(sorted(tokens2))
    return max(SequenceMatcher(None, sorted_s1, sorted_s2).ratio(), len(tokens1 & tokens2) / len(union))


def similarity_score(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two club names.

    Returns a score from 0.0 to 1.0. Compares the names' cores (``_core_and_codes``);
    the first rule that applies decides:

    1. A core made only of place words is shared by many clubs, so it scores 1.0 only
       when the two signatures are equal ("FC Arkansas" is not "Arkansas Soccer Club").
    2. Two different one-word cores, either of five letters or fewer, score 0.0: short
       names sit close in characters without being one club ("NCFC", "NYCFC").
    3. Equal cores score 1.0, unless both carry codes and no family is shared, youth
       counting as club ("Tyler FC" is not "Tyler SA").
    4. Otherwise the word-set similarity of the two cores.
    """
    core1, codes1 = _core_and_codes(name1)
    core2, codes2 = _core_and_codes(name2)

    if not core1 or not core2:
        return 0.0

    if set(core1.split()) <= PLACE_WORDS or set(core2.split()) <= PLACE_WORDS:
        return 1.0 if _signature(name1) == _signature(name2) else 0.0

    if " " not in core1 and " " not in core2 and min(len(core1), len(core2)) <= 5 and core1 != core2:
        return 0.0

    if core1 == core2:
        families1 = _families(codes1)
        families2 = _families(codes2)
        return 0.0 if families1 and families2 and not families1 & families2 else 1.0

    return _word_set_similarity(core1, core2)


def are_same_club(name1: str, name2: str, threshold: float = 0.85) -> bool:
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
