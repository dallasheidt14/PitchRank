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
