"""US state postal-code ↔ full-name mapping.

Source-of-truth lookup for the 50 US states + DC, used by the SincSports
discovery scraper (`src/scrapers/sincsports_clubs.py`) to convert between
the full state names rendered in the SincSports filter UI and the postal
codes stored on `teams.state_code`.

Not yet adopted by the pre-existing scripts that duplicate this dict
(`scripts/backfill_state_from_state_code.py`, `backfill_missing_state_codes.py`,
`match_state_from_club.py`, `update_single_team_state.py`); migrating those
callers is out of scope for the SincSports discovery plan.
"""

from typing import Optional

STATE_CODE_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}

STATE_NAME_TO_CODE = {name: code for code, name in STATE_CODE_TO_NAME.items()}

# Common variants mapped to canonical forms.
_NAME_VARIANTS = {
    "district of columbia": "DC",
    "d.c.": "DC",
    "d.c": "DC",
    "dc": "DC",
    "washington d.c.": "DC",
    "washington dc": "DC",
}


def state_name_to_code(name: str) -> Optional[str]:
    """Return postal code for a state name, case-insensitive, handling common variants.

    >>> state_name_to_code("Arizona")
    'AZ'
    >>> state_name_to_code("arizona")
    'AZ'
    >>> state_name_to_code("D.C.")
    'DC'
    """
    if not name:
        return None

    trimmed = name.strip()

    # Exact match against canonical names
    if trimmed in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[trimmed]

    # Case-insensitive exact match
    lower = trimmed.lower()
    for canonical, code in STATE_NAME_TO_CODE.items():
        if canonical.lower() == lower:
            return code

    # Known variants (D.C. etc.)
    if lower in _NAME_VARIANTS:
        return _NAME_VARIANTS[lower]

    return None
