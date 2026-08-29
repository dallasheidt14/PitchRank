"""Clubs whose state a count of their own teams cannot settle.

Tier B reads a club's state from its teams: a state is *meaningful* when it holds at
least two of them and at least 5% of the club's known-state teams, and the tier fires
only when exactly one state qualifies. For most clubs that works. For the clubs in this
module it cannot, because two or more states qualify, and no amount of counting says
which one the club is actually based in.

Every club here has at least 100 teams and at least two meaningful states, so each one
it gets wrong gets a lot of teams wrong at once.

Two fields decide what happens, and they are independent:

``home``    the club's real state. Where it is set it simply *is* the club's state, for
            every team in the club, replacing the computed test (R11).
``curate``  True where the answer needs a person. Tiers B, C and D queue rather than
            auto-apply for these clubs, both for fills and for corrections (R6). Tier A
            is exempt: it reads a per-team provider record, and the reason a club is
            curated -- that club-level inference cannot pick a home -- does not apply to
            it.

The ``txt`` figure in each state tuple is the discriminator that separates the two
groups. It counts teams in that bucket whose full-name ``state`` column is set, which
only four writers ever do. A minority bucket at ``txt0`` was therefore derived or
guessed by a heuristic, not reported by a provider -- contamination inside one club,
not evidence of a second location. Those clubs get a ``home`` and auto-apply normally.
A minority bucket with real provider-set values is a genuine question -- a national
brand, a league bucket, two different clubs sharing a name -- and gets ``curate: True``
instead.

The operator confirmed four homes by hand on 2026-08-28, blind to the analysis, and
agreed with it four times out of four: arizona arsenal soccer club AZ, city sc CA,
soccer chance academy OR, steel city fc PA. That is the only external ground truth this
problem has. Treat it as weak positive evidence, not measured precision.

**The key is the raw club name, lowercased and stripped -- never ``normalize_club_name``
output.** That function collapses 9,852 club keys to 8,642 and fails in both directions:
it deletes parentheticals, which are often the only state disambiguator, merging
``fc stars`` (MA) with ``fc stars (il)``, a different club; and it leaves branch
suffixes intact, splitting ``ayso united - las vegas`` off from its own brand.

Counts were measured on 2026-08-29 and are a snapshot for the reader, not a live
figure. They drift as teams are added and states are filled; the R36 checker reports
that drift rather than failing on it.
"""

from typing import Optional

# label values:
#   CONTAMINATION      one club, minority states written onto its own teams by a heuristic
#   MULTI_STATE_BRAND  one brand operating in several states
#   NAME_COLLISION     two or more unrelated clubs sharing a name
#   LEAGUE_BUCKET      a league or association in the club_name column
#   PLACEHOLDER        not a club at all
CLUBS = {
    "alliance youth soccer league": {
        "teams": 134,
        "known": 134,
        "states": {"NV": (113, 84.3, 0), "TX": (21, 15.7, 0)},
        "label": "LEAGUE_BUCKET",
        "home": None,
        "curate": True,
    },
    "arizona arsenal soccer club": {
        "teams": 156,
        "known": 156,
        "states": {"AZ": (145, 92.9, 124), "TX": (10, 6.4, 0)},
        "label": "CONTAMINATION",
        "home": "AZ",
        "curate": False,
    },
    "arkansas comets fc": {
        "teams": 100,
        "known": 94,
        "states": {"AR": (79, 84.0, 72), "OK": (6, 6.4, 0), "TX": (5, 5.3, 0)},
        "label": "CONTAMINATION",
        "home": "AR",
        "curate": False,
    },
    "ayso united": {
        "teams": 208,
        "known": 200,
        "states": {"CA": (127, 63.5, 96), "MI": (36, 18.0, 29), "UT": (34, 17.0, 22)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "beadling sc": {
        "teams": 149,
        "known": 149,
        "states": {"PA": (123, 82.6, 97), "OH": (15, 10.1, 0)},
        "label": "CONTAMINATION",
        "home": "PA",
        "curate": False,
    },
    "carolina core fc youth": {
        "teams": 119,
        "known": 119,
        "states": {"NC": (100, 84.0, 72), "VA": (7, 5.9, 0)},
        "label": "CONTAMINATION",
        "home": "NC",
        "curate": False,
    },
    "carolina elite soccer academy": {
        "teams": 150,
        "known": 144,
        "states": {"SC": (118, 81.9, 109), "NC": (22, 15.3, 18)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "carolina velocity fc": {
        "teams": 111,
        "known": 111,
        "states": {"NC": (105, 94.6, 87), "VA": (6, 5.4, 0)},
        "label": "CONTAMINATION",
        "home": "NC",
        "curate": False,
    },
    "carshield fc": {
        "teams": 106,
        "known": 106,
        "states": {"MO": (92, 86.8, 46), "IL": (8, 7.5, 0)},
        "label": "CONTAMINATION",
        "home": "MO",
        "curate": False,
    },
    "ccv stars": {
        "teams": 161,
        "known": 161,
        "states": {"AZ": (144, 89.4, 104), "TX": (14, 8.7, 0)},
        "label": "CONTAMINATION",
        "home": "AZ",
        "curate": False,
    },
    "central illinois united": {
        "teams": 100,
        "known": 100,
        "states": {"IL": (86, 86.0, 81), "MO": (9, 9.0, 0)},
        "label": "CONTAMINATION",
        "home": "IL",
        "curate": False,
    },
    "cincinnati united soccer club": {
        "teams": 180,
        "known": 180,
        "states": {"OH": (140, 77.8, 28), "KY": (20, 11.1, 0), "IN": (14, 7.8, 0)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "city sc": {
        "teams": 259,
        "known": 259,
        "states": {"CA": (237, 91.5, 108), "AZ": (15, 5.8, 0)},
        "label": "CONTAMINATION",
        "home": "CA",
        "curate": False,
    },
    "coastal rush": {
        "teams": 117,
        "known": 99,
        "states": {"FL": (84, 84.8, 64), "AL": (11, 11.1, 3)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "columbia premier soccer club": {
        "teams": 156,
        "known": 153,
        "states": {"WA": (83, 54.2, 51), "OR": (63, 41.2, 32)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "connecticut fc": {
        "teams": 108,
        "known": 108,
        "states": {"CT": (79, 73.1, 69), "NY": (12, 11.1, 0), "VT": (7, 6.5, 0), "NJ": (6, 5.6, 0)},
        "label": "CONTAMINATION",
        "home": "CT",
        "curate": False,
    },
    "coppermine soccer club": {
        "teams": 115,
        "known": 115,
        "states": {"MD": (103, 89.6, 69), "NY": (7, 6.1, 0)},
        "label": "CONTAMINATION",
        "home": "MD",
        "curate": False,
    },
    "ct rush": {
        "teams": 118,
        "known": 118,
        "states": {"CT": (103, 87.3, 98), "VT": (8, 6.8, 0)},
        "label": "CONTAMINATION",
        "home": "CT",
        "curate": False,
    },
    "dasc": {
        "teams": 109,
        "known": 109,
        "states": {"SD": (85, 78.0, 64), "NE": (9, 8.3, 8), "MN": (7, 6.4, 0)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "delaware football club": {
        "teams": 164,
        "known": 161,
        "states": {"DE": (109, 67.7, 83), "PA": (29, 18.0, 0), "NJ": (11, 6.8, 0)},
        "label": "CONTAMINATION",
        "home": "DE",
        "curate": False,
    },
    "eastside fc": {
        "teams": 247,
        "known": 183,
        "states": {"WA": (156, 85.2, 139), "MI": (22, 12.0, 10)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "edmond sc": {
        "teams": 127,
        "known": 127,
        "states": {"OK": (118, 92.9, 56), "TX": (9, 7.1, 0)},
        "label": "CONTAMINATION",
        "home": "OK",
        "curate": False,
    },
    "elite fc": {
        "teams": 153,
        "known": 142,
        "states": {"OH": (98, 69.0, 54), "UT": (33, 23.2, 33)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "elmbrook united": {
        "teams": 149,
        "known": 149,
        "states": {"WI": (139, 93.3, 130), "IL": (8, 5.4, 0)},
        "label": "CONTAMINATION",
        "home": "WI",
        "curate": False,
    },
    "fc delco": {
        "teams": 316,
        "known": 316,
        "states": {"PA": (236, 74.7, 156), "NY": (34, 10.8, 0), "NJ": (31, 9.8, 0)},
        "label": "CONTAMINATION",
        "home": "PA",
        "curate": False,
    },
    "fc pride": {
        "teams": 141,
        "known": 140,
        "states": {"IN": (121, 86.4, 110), "KY": (9, 6.4, 0)},
        "label": "CONTAMINATION",
        "home": "IN",
        "curate": False,
    },
    "fc stars": {
        "teams": 343,
        "known": 343,
        "states": {"MA": (284, 82.8, 180), "NH": (27, 7.9, 22)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "fusion soccer club": {
        "teams": 110,
        "known": 110,
        "states": {"MN": (94, 85.5, 56), "IL": (10, 9.1, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "ginga fc": {
        "teams": 102,
        "known": 102,
        "states": {"CT": (85, 83.3, 55), "VT": (7, 6.9, 0), "NJ": (6, 5.9, 0)},
        "label": "CONTAMINATION",
        "home": "CT",
        "curate": False,
    },
    "kc legends": {
        "teams": 148,
        "known": 148,
        "states": {"KS": (113, 76.4, 89), "MO": (24, 16.2, 15)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "kings hammer soccer club": {
        "teams": 339,
        "known": 337,
        "states": {"OH": (131, 38.9, 108), "KY": (130, 38.6, 102), "TN": (74, 22.0, 54)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "lakeville soccer club": {
        "teams": 113,
        "known": 113,
        "states": {"MN": (98, 86.7, 56), "IL": (9, 8.0, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "lobos rush": {
        "teams": 152,
        "known": 138,
        "states": {"TN": (80, 58.0, 58), "MS": (28, 20.3, 28), "NM": (17, 12.3, 17), "MO": (8, 5.8, 0)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "metro alliance fc": {
        "teams": 102,
        "known": 102,
        "states": {"IL": (87, 85.3, 73), "MO": (12, 11.8, 0)},
        "label": "CONTAMINATION",
        "home": "IL",
        "curate": False,
    },
    "michigan stars elite sc": {
        "teams": 131,
        "known": 131,
        "states": {"MI": (121, 92.4, 64), "IN": (9, 6.9, 0)},
        "label": "CONTAMINATION",
        "home": "MI",
        "curate": False,
    },
    "minnesota rush": {
        "teams": 102,
        "known": 102,
        "states": {"MN": (94, 92.2, 82), "IL": (6, 5.9, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "missouri rush": {
        "teams": 257,
        "known": 255,
        "states": {"MO": (222, 87.1, 162), "IL": (15, 5.9, 0)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "mockingbird valley premier": {
        "teams": 100,
        "known": 100,
        "states": {"KY": (78, 78.0, 51), "OH": (18, 18.0, 0)},
        "label": "CONTAMINATION",
        "home": "KY",
        "curate": False,
    },
    "mysa independent teams": {
        "teams": 124,
        "known": 124,
        "states": {"MO": (106, 85.5, 43), "IL": (9, 7.3, 0)},
        "label": "LEAGUE_BUCKET",
        "home": None,
        "curate": True,
    },
    "new england force": {
        "teams": 130,
        "known": 130,
        "states": {"MA": (113, 86.9, 53), "VT": (9, 6.9, 0)},
        "label": "CONTAMINATION",
        "home": "MA",
        "curate": False,
    },
    "nm rapids sc": {
        "teams": 149,
        "known": 149,
        "states": {"NM": (136, 91.3, 116), "AZ": (8, 5.4, 0)},
        "label": "CONTAMINATION",
        "home": "NM",
        "curate": False,
    },
    "no club selection": {
        "teams": 1589,
        "known": 210,
        "states": {"CA": (78, 37.1, 47), "WA": (46, 21.9, 13), "TX": (22, 10.5, 15), "NJ": (12, 5.7, 12)},
        "label": "PLACEHOLDER",
        "home": None,
        "curate": True,
    },
    "penn fusion soccer academy": {
        "teams": 136,
        "known": 130,
        "states": {"PA": (115, 88.5, 106), "NY": (7, 5.4, 0), "NJ": (7, 5.4, 0)},
        "label": "CONTAMINATION",
        "home": "PA",
        "curate": False,
    },
    "philadelphia ukrainian nationals": {
        "teams": 125,
        "known": 116,
        "states": {"PA": (103, 88.8, 62), "NY": (6, 5.2, 0)},
        "label": "CONTAMINATION",
        "home": "PA",
        "curate": False,
    },
    "philadelphia union": {
        "teams": 155,
        "known": 155,
        "states": {"PA": (94, 60.6, 63), "NJ": (48, 31.0, 0), "NY": (10, 6.5, 0)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "phoenix rising fc": {
        "teams": 186,
        "known": 186,
        "states": {"AZ": (168, 90.3, 133), "TX": (16, 8.6, 0)},
        "label": "CONTAMINATION",
        "home": "AZ",
        "curate": False,
    },
    "prince william soccer inc": {
        "teams": 130,
        "known": 130,
        "states": {"VA": (114, 87.7, 82), "MD": (9, 6.9, 0)},
        "label": "CONTAMINATION",
        "home": "VA",
        "curate": False,
    },
    "sac/ba": {
        "teams": 106,
        "known": 106,
        "states": {"MD": (93, 87.7, 67), "NY": (6, 5.7, 0)},
        "label": "CONTAMINATION",
        "home": "MD",
        "curate": False,
    },
    "salvo sc": {
        "teams": 147,
        "known": 147,
        "states": {"MN": (122, 83.0, 56), "IL": (10, 6.8, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "scorpions sc": {
        "teams": 164,
        "known": 164,
        "states": {"MA": (142, 86.6, 97), "VT": (11, 6.7, 0)},
        "label": "CONTAMINATION",
        "home": "MA",
        "curate": False,
    },
    "seacoast united": {
        "teams": 107,
        "known": 107,
        "states": {"NH": (94, 87.9, 73)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "soccer chance academy": {
        "teams": 136,
        "known": 136,
        "states": {"OR": (127, 93.4, 66), "WA": (7, 5.1, 0)},
        "label": "CONTAMINATION",
        "home": "OR",
        "curate": False,
    },
    "sporting athletic club": {
        "teams": 101,
        "known": 101,
        "states": {"DE": (73, 72.3, 54), "PA": (9, 8.9, 0), "NY": (7, 6.9, 0), "NJ": (7, 6.9, 0)},
        "label": "CONTAMINATION",
        "home": "DE",
        "curate": False,
    },
    # The one entry where a minority bucket carries provider-set states and the club is
    # still homed rather than curated. Blue Valley is Overland Park KS, and Kansas City
    # straddles the line, so a couple of its teams registering with Missouri Youth is
    # ordinary. Registration is not the question R2 asks -- a team's state is where its
    # club is based -- so KS is right for all 177 of them.
    "sporting blue valley": {
        "teams": 177,
        "known": 171,
        "states": {"KS": (146, 85.4, 130), "MO": (13, 7.6, 2)},
        "label": "CONTAMINATION",
        "home": "KS",
        "curate": False,
    },
    "sporting city soccer club": {
        "teams": 112,
        "known": 112,
        "states": {"MO": (85, 75.9, 61), "IL": (12, 10.7, 0), "KS": (9, 8.0, 5)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "sporting springfield": {
        "teams": 100,
        "known": 100,
        "states": {"MO": (93, 93.0, 54), "IL": (6, 6.0, 0)},
        "label": "CONTAMINATION",
        "home": "MO",
        "curate": False,
    },
    "st. croix": {
        "teams": 107,
        "known": 107,
        "states": {"MN": (95, 88.8, 59), "IL": (8, 7.5, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "st. louis development academy": {
        "teams": 131,
        "known": 131,
        "states": {"MO": (117, 89.3, 78), "IL": (8, 6.1, 0)},
        "label": "CONTAMINATION",
        "home": "MO",
        "curate": False,
    },
    "st. louis scott gallagher": {
        "teams": 508,
        "known": 500,
        "states": {"MO": (394, 78.8, 237), "IL": (70, 14.0, 56)},
        "label": "MULTI_STATE_BRAND",
        "home": None,
        "curate": True,
    },
    "st. louis stars sc": {
        "teams": 114,
        "known": 111,
        "states": {"MO": (92, 82.9, 64), "IA": (11, 9.9, 0)},
        "label": "CONTAMINATION",
        "home": "MO",
        "curate": False,
    },
    "st. paul blackhawks": {
        "teams": 101,
        "known": 101,
        "states": {"MN": (70, 69.3, 32), "IL": (18, 17.8, 0)},
        "label": "CONTAMINATION",
        "home": "MN",
        "curate": False,
    },
    "steel city fc": {
        "teams": 154,
        "known": 154,
        "states": {"PA": (139, 90.3, 133), "OH": (9, 5.8, 0)},
        "label": "CONTAMINATION",
        "home": "PA",
        "curate": False,
    },
    "strikers fc": {
        "teams": 178,
        "known": 177,
        "states": {"CA": (96, 54.2, 46), "MT": (60, 33.9, 41), "UT": (16, 9.0, 16)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "tri-city united": {
        "teams": 128,
        "known": 128,
        "states": {"ND": (59, 46.1, 38), "MN": (54, 42.2, 0)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
    "vale sc": {
        "teams": 103,
        "known": 103,
        "states": {"CT": (78, 75.7, 48), "VT": (9, 8.7, 0), "MA": (7, 6.8, 0)},
        "label": "CONTAMINATION",
        "home": "CT",
        "curate": False,
    },
    "wasatch sc": {
        "teams": 114,
        "known": 114,
        "states": {"UT": (95, 83.3, 65), "CA": (11, 9.6, 0)},
        "label": "CONTAMINATION",
        "home": "UT",
        "curate": False,
    },
    "westside metros fc": {
        "teams": 111,
        "known": 111,
        "states": {"OR": (103, 92.8, 85), "WA": (7, 6.3, 0)},
        "label": "CONTAMINATION",
        "home": "OR",
        "curate": False,
    },
    "wichita regional soccer association": {
        "teams": 104,
        "known": 104,
        "states": {"KS": (97, 93.3, 47), "NE": (6, 5.8, 6)},
        "label": "LEAGUE_BUCKET",
        "home": None,
        "curate": True,
    },
    "wsa": {
        "teams": 101,
        "known": 101,
        "states": {"NJ": (68, 67.3, 44), "MD": (26, 25.7, 18), "NY": (6, 5.9, 0)},
        "label": "NAME_COLLISION",
        "home": None,
        "curate": True,
    },
}


def _key(club_name: Optional[str]) -> str:
    return (club_name or "").strip().lower()


def entry(club_name: Optional[str]) -> Optional[dict]:
    """The registry entry for a club, or None when it has none."""
    return CLUBS.get(_key(club_name))


def home_state(club_name: Optional[str]) -> Optional[str]:
    """The club's own state, or None.

    None means "this module cannot tell you" -- either the club has no entry, in which
    case the computed test applies, or it has one awaiting a person. Callers must not
    read it as "no state".
    """
    record = CLUBS.get(_key(club_name))
    return record["home"] if record else None


def requires_review(club_name: Optional[str]) -> bool:
    """Whether club-level evidence must queue rather than auto-apply for this club."""
    record = CLUBS.get(_key(club_name))
    return bool(record and record["curate"])
