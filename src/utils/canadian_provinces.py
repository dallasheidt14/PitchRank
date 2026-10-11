"""Canadian province and territory codes as stored in ``teams.state_code``.

A team stored with one of these has a legitimate state, not a malformed one, and no state tier
corrects it.
"""

CANADIAN_PROVINCES = frozenset({"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"})
