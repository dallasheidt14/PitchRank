"""GotSport ``team_association`` → US state postal code.

The GotSport team_details payload carries a ``team_association`` field naming the
US Youth Soccer state association a team registers with. It is per-team and it
is authoritative about location in a way the surrounding heuristics are not: over
231 live probes it agreed with the stored ``teams.state_code`` on 91.3% of teams,
and adjudicating the disagreements against independent evidence put its real
accuracy between 96.2% and 98.4%. Nine of the sixteen disagreements were the
stored value being wrong, not this field.

**It is an association code, not a postal code**, which is the whole reason this
module exists rather than a bare ``.upper()``:

    CAN  is California North.  Not Canada.  Canada is CND.

Four states never emit their postal code at all, splitting instead by region, so
a lookup that only handled the identity cases would silently drop California,
New York, Pennsylvania and Texas -- four of the five largest cohorts in the
database.

The map is deliberately closed. ``to_state_code`` returns None for anything it
has not seen, because the alternative -- treating any two-letter value as a
postal code -- is what sends a Canadian or Brazilian team to a US state board.
Every US state is now present. Montana was the last one held out, on the rule
that a state is added when a real payload shows it rather than by inference;
the probe ledger recorded fifteen ``MT`` payloads on 2026-09-01, which is that
evidence. A national body still maps to nothing on purpose: ``USA`` names no
state, and the ledger holds one of those too.
"""

from typing import Optional

# Associations whose code is the postal code. Verified against live payloads;
# CA, NY, PA and TX are absent because they only ever emit a SPLIT code.
IDENTITY = frozenset(
    {
        "AK", "AL", "AR", "AZ", "CO", "CT", "DE", "FL", "GA", "HI",
        "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME",
        "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ",
        "NM",
        "NV", "OH", "OK", "OR", "RI", "SC", "SD", "TN", "UT", "VA",
        "VT", "WA", "WI", "WV", "WY",
    }
)

# Regional associations. The split is geographic and was clean in all 37
# observations, so both halves resolve to the one state.
SPLIT = {
    "CAN": "CA",  # California North -- NOT Canada
    "CAS": "CA",  # California South
    "NYE": "NY",
    "NYW": "NY",
    "PAE": "PA",
    "PAW": "PA",
    "TXN": "TX",
    "TXS": "TX",
}

# Recorded so a reader can tell "known, deliberately unmapped" from "unknown".
# Canadian teams are legitimate data here and simply have no US state; the
# national bodies and the OTH catch-all likewise. Nothing consults these sets --
# they exist so the next person does not read the omission as an oversight.
CANADIAN_PROVINCES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK", "CND"})
NON_US_BODIES = frozenset({"BRA", "CRC", "GER", "NED", "POL", "RSA", "OTH"})

# GBR plus every English county FA the probe ledger has recorded. Unlike the two sets
# above, this one is consulted. Held upper-cased because the county names arrive in
# mixed case.
ENGLISH_ASSOCIATIONS = frozenset(
    code.upper()
    for code in {
        "GBR",
        "Berks & Bucks",
        "Birmingham",
        "Cheshire",
        "Cumberland",
        "Dorset",
        "Durham",
        "East Riding",
        "English Schools",
        "Essex",
        "Gloucestershire",
        "Hampshire",
        "Kent",
        "Lancashire",
        "Liverpool",
        "London",
        "Manchester",
        "Middlesex",
        "Norfolk",
        "Northamptonshire",
        "Sheffield and Hallamshire",
        "Somerset",
        "Suffolk",
        "Surrey",
        "West Riding",
        "Wiltshire",
    }
)

# The outcomes scripts/assign_team_states.py writes to team_state_probe_log for an
# answered probe.
MAPPED_OUTCOME = "mapped"
NO_ASSOCIATION_OUTCOME = "no association in payload"
UNMAPPED_OUTCOME_PREFIX = "unmapped code "


def is_answer(outcome: str) -> bool:
    """A request failure, a 404 or a missing alias says nothing about the team, so it must
    not displace an earlier answer."""
    return outcome in (MAPPED_OUTCOME, NO_ASSOCIATION_OUTCOME) or outcome.startswith(UNMAPPED_OUTCOME_PREFIX)


def is_english_association(association: Optional[str]) -> bool:
    return (association or "").strip().upper() in ENGLISH_ASSOCIATIONS


def to_state_code(association: Optional[str]) -> Optional[str]:
    """The US state a ``team_association`` names, or None.

    None means "this field cannot tell you the state" -- an unmapped code, a
    Canadian province, a national body, or nothing at all. Callers treat that as
    no signal rather than as a state.
    """
    code = (association or "").strip().upper()
    if not code:
        return None
    if code in IDENTITY:
        return code
    return SPLIT.get(code)
