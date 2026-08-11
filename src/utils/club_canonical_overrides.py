"""Per-state canonical club-name overrides — shared registry.

Single source of truth for the hand-curated ``(state, match_type, pattern,
canonical)`` overrides used by two flows:

1. **Monday batch standardization** —
   ``scripts/full_club_analysis.py`` rewrites ``teams.club_name`` in the DB
   so every canonical row uses a consistent club name. Runs via
   ``update-missing-club-and-state.yml`` at 4am MT Mondays.

2. **Provider import-time gated funnel** — provider matchers (e.g.
   ``SomSportsGameMatcher``) canonicalize the incoming club name before
   issuing the ``teams.club_name ilike <X>`` query. Without this, a SOM
   Sports row whose club extracts to ``"Beach FC"`` would never gate-match
   the canonical ``"Beach Futbol Club"`` rows that the Monday job
   produced, even though they are the same club.

Match semantics (preserved verbatim from the original ``_matches_override``
in ``full_club_analysis.py``):

- ``exact``  — case-insensitive equality after ``.strip()``
- ``prefix`` — case-insensitive ``startswith`` after ``.strip()``
- ``regex``  — ``re.search(pattern, club, re.IGNORECASE)`` after ``.strip()``

Ordering: overrides are evaluated in declared order and the **first match
wins**. The Monday script enforces this with ``processed.add(club)``; the
runtime helper here returns on first hit.

State-aware vs. no-state lookups:

- ``canonicalize_club_name(state_code, name)`` — when ``state_code`` is
  provided, only overrides for that state are tried (the Monday script's
  ``analyze_state`` path).
- ``canonicalize_club_name(None, name)`` — when ``state_code`` is
  unknown, only the **cross-state-safe subset** is tried: overrides whose
  ``(match_type, pattern)`` resolves to exactly one canonical across all
  states (the Monday script's ``analyze_no_state_teams`` path). This
  prevents e.g. an IL ``"FC Stars"`` row from being silently rewritten to
  the TX ``"FC Stars (il)"`` canonical.

To add or edit an override, append to ``CLUB_CANONICAL_OVERRIDES`` below.
Tests in ``tests/unit/test_club_canonical_overrides.py`` enforce that the
shared module produces the same standardization decisions as the legacy
inline list did.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# (state_code, match_type, pattern, canonical_name)
# match_type ∈ {"exact", "prefix", "regex"}
Override = Tuple[str, str, str, str]


CLUB_CANONICAL_OVERRIDES: List[Override] = [
    # ── Washington ────────────────────────────────────────────────────────
    ("WA", "exact", "XF", "Crossfire Premier"),
    ("WA", "exact", "XL", "Crossfire Select Soccer Club"),
    ("WA", "exact", "HPFC Heat", "Highline Premier FC"),
    ("WA", "exact", "Kitsap Alliance FC B", "Kitsap Alliance FC"),
    ("WA", "exact", "PacNW", "Pacific Northwest SC"),
    ("WA", "exact", "Pacific FC Washington", "Pacific FC"),
    ("WA", "exact", "Washington Premier", "Washington Premier FC"),
    ("WA", "exact", "Wenatchee FC Youth", "Wenatchee FC"),
    ("WA", "regex", r"Eastside FC\s*\(wa\)\s*$", "Eastside FC"),
    ("WA", "regex", r"Atletico\s*\(wa\)\s*$", "Atletico FC"),
    ("WA", "prefix", "NW United", "Northwest United FC"),
    ("WA", "exact", "Eastside F.C", "Eastside FC"),
    ("WA", "exact", "Mount Rainier FC", "Mt. Rainier Futbol Club"),
    ("WA", "exact", "90+", "90+ Project SC"),
    ("WA", "exact", "3rsc", "Three Rivers Soccer Club"),
    ("WA", "exact", "atletico wa", "Atletico FC"),
    ("WA", "exact", "BVB IA WA - Eastside", "BVB IA WA"),
    ("WA", "exact", "BVB IA Washington", "BVB IA WA"),
    ("WA", "exact", "BVBIA WA - Seattle", "BVB IA WA"),
    ("WA", "exact", "CROSSFIRE SELECT", "Crossfire Select Soccer Club"),
    ("WA", "exact", "Everett FC", "Everett Youth Soccer Club"),
    ("WA", "exact", "Fife Milton Edgewood", "Fife Milton Edgewood JSC"),
    ("WA", "exact", "Harbor", "Harbor FC"),
    ("WA", "exact", "Harbor Premier", "Harbor FC"),
    ("WA", "exact", "HPFC Eagles", "Highline Premier FC"),
    ("WA", "exact", "HPFC Heat B2014 Red", "Highline Premier FC"),
    ("WA", "exact", "HPFC Heat B2015 Blue", "Highline Premier FC"),
    ("WA", "exact", "Kitsap Alliance FC G", "Kitsap Alliance FC"),
    ("WA", "exact", "Lake Hills YSC", "Lake Hills Soccer Club"),
    ("WA", "exact", "Little Warriors", "Little Warriors Sports Academy"),
    ("WA", "exact", "Mt. Rainier Futbol Club AD", "Mt. Rainier Futbol Club"),
    ("WA", "exact", "Mukilteo FC", "Mukilteo Youth SC"),
    ("WA", "exact", "Northshore Youth Soccer Association", "Northshore Select Club"),
    ("WA", "exact", "NSC", "Northshore Select Club"),
    ("WA", "exact", "Pac NW", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW B13 Maroon A", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW B15 Gold D", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW B16 Maroon A", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G11 Blue B", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G11 Maroon A", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G12 Blue B", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G12E", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G13 Blue B", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G13E", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G15 Maroon A", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G15 White C", "Pacific Northwest SC"),
    ("WA", "exact", "PacNW G16 White C", "Pacific Northwest SC"),
    ("WA", "exact", "Pilchuck Soccer Alliance - Force", "Pilchuck Soccer Alliance"),
    ("WA", "exact", "PSA Force", "Pilchuck Soccer Alliance"),
    ("WA", "exact", "Reign Academy", "Seattle Reign Academy"),
    ("WA", "exact", "Sound FC B11B", "Sound FC"),
    ("WA", "exact", "Sound FC B14A", "Sound FC"),
    ("WA", "exact", "Sound FC B14B", "Sound FC"),
    ("WA", "exact", "Sound FC B14C", "Sound FC"),
    ("WA", "exact", "Sound FC B14D", "Sound FC"),
    ("WA", "exact", "Sound FC G09A", "Sound FC"),
    ("WA", "exact", "Sound FC G11A", "Sound FC"),
    ("WA", "exact", "Sound FC G12A", "Sound FC"),
    ("WA", "exact", "Sound FC G13A", "Sound FC"),
    ("WA", "exact", "Sound FC G14A", "Sound FC"),
    ("WA", "exact", "Sound FC G15A", "Sound FC"),
    ("WA", "exact", "Sound FC G16A", "Sound FC"),
    ("WA", "exact", "South Kitsap Soccer Club - SK United", "South Kitsap Soccer Club"),
    ("WA", "exact", "SOZO FC - 8th grade GU15", "Sozo FC"),
    ("WA", "exact", "SOZO FC GOLD - BU12", "Sozo FC"),
    ("WA", "exact", "SOZO FC GOLD - GU14", "Sozo FC"),
    ("WA", "exact", "SOZO FC GOLD - GU15", "Sozo FC"),
    ("WA", "exact", "SOZO FC GOLD - GU16", "Sozo FC"),
    ("WA", "exact", "SOZO FC Gold- GU10", "Sozo FC"),
    ("WA", "exact", "SOZO FC Royal - BU14", "Sozo FC"),
    ("WA", "exact", "SOZO FC Royal - BU15", "Sozo FC"),
    ("WA", "exact", "Valor Soccer - G Trap", "Valor Soccer"),
    ("WA", "exact", "Valour FC", "Valor Soccer"),
    ("WA", "exact", "Warriors Sports Academy", "Little Warriors Sports Academy"),
    ("WA", "exact", "Washington East SC", "Washington East Surf"),
    ("WA", "exact", "Washington East Surf Soccer Club", "Washington East Surf"),
    ("WA", "exact", "Western Washington Surf", "Western Washington Surf SC"),
    ("WA", "exact", "Whatcom Rangers", "Whatcom FC Rangers"),
    ("WA", "exact", "wv surf", "WV Surf SC"),
    # ── Oklahoma (from full merge history - 4x prefers short form) ────────
    ("OK", "exact", "Oklahoma Celtic Football Club", "Oklahoma Celtic"),
    ("OK", "exact", "West Side Alliance", "West Side Alliance SC"),
    ("OK", "exact", "NEOFC", "NE Oklahoma FC"),
    ("OK", "exact", "Neofc Bartlesville", "NE Oklahoma FC"),
    ("OK", "exact", "North Oklahoma City", "North OKC SC"),
    ("OK", "exact", "NorthWest Optimist Club", "Northwest Optimist SC"),
    ("OK", "exact", "NW Oklahoma SA", "Northwest Soccer Club"),
    # ── Arkansas ──────────────────────────────────────────────────────────
    ("AR", "exact", "Ozark United FC Academy AD", "Ozark United FC Academy"),
    # ── North Carolina ────────────────────────────────────────────────────
    ("NC", "exact", "CESA", "Carolina Elite Soccer Academy"),
    ("NC", "regex", r"Charlotte Soccer Academy\s*\(CSA\)\s*$", "Charlotte Soccer Academy"),
    ("NC", "regex", r"Charlotte Independence SC\s*\(CISC\)\s*$", "Charlotte Independence SC"),
    ("NC", "regex", r"Waxhaw Athletic Association\s*\(WAA\)\s*$", "Waxhaw Athletic Association"),
    ("NC", "exact", "Liverpool FC IA Carolinas", "Liverpool FC International Academy Carolinas"),
    ("NC", "exact", "NCFC Youth", "NCFC"),
    ("NC", "exact", "Triangle Soccer Academy", "Triangle United"),
    ("NC", "exact", "Triangle Y SC", "Triangle United"),
    ("NC", "exact", "Wilmington Hammerheads Youth FC", "Wilmington Hammerheads FC"),
    ("NC", "exact", "Ashboro City FC", "Asheboro City Futbol Club"),
    ("NC", "exact", "Carolina Core FC", "Carolina Core FC Youth"),
    ("NC", "exact", "Charlotte SA", "Charlotte Soccer Academy"),
    ("NC", "exact", "Charlotte Soccer Academy (SC)", "Charlotte Soccer Academy"),
    ("NC", "exact", "Fox Soccer Academy Carolinas", "Fox Soccer Academy of the Carolinas"),
    ("NC", "exact", "Mebane Youth Soccer Association", "Mebane Youth SA"),
    ("NC", "exact", "North Carolina FC Youth (NCFCY)", "NCFC"),
    ("NC", "exact", "North Carolina FC", "NCFC"),
    ("NC", "exact", "Neuse River FA", "Neuse River Futbol Alliance"),
    ("NC", "exact", "Triad Union FC Inc.", "Triad Union FC"),
    ("NC", "exact", "Triangle United Soccer Association", "Triangle United"),
    ("NC", "exact", "United Soccer Club", "United Soccer Club NC"),
    ("NC", "exact", "Wesley Chapel Weddington AA", "Wesley Chapel Weddington Athletic Association"),
    # ── Texas ─────────────────────────────────────────────────────────────
    ("TX", "exact", "El Paso Locomotive Youth Soccer Club", "El Paso Locomotive FC"),
    ("TX", "exact", "FC Dallas Youth", "FC Dallas"),
    ("TX", "exact", "LTFC", "Lake Travis Football Club"),
    ("TX", "exact", "SA Athenians", "AC River"),
    ("TX", "exact", "Santa Fe YSC", "Santa Fe Youth Soccer"),
    ("TX", "exact", "Soccer Central", "AC River"),
    ("TX", "exact", "Soccer Central/AC River/SA Athenians", "AC River"),
    ("TX", "exact", "Valencia Academy Houston", "Valencia CF"),
    ("TX", "exact", "BVB international academy", "BVB International Academy Texas"),
    ("TX", "exact", "capital city south", "Capital City SC"),
    ("TX", "exact", "CAPITAL CITY NORTH", "Capital City SC"),
    ("TX", "exact", "COASTAL PREMIER FC", "Coastal Premier Alliance FC"),
    ("TX", "exact", "Coppell Youth SA", "Coppell FC"),
    ("TX", "exact", "Cosmos FC", "Cosmos FC Academy"),
    ("TX", "exact", "GFI ACADEMY NORTH", "GFI Academy"),
    ("TX", "exact", "gfi academy south", "GFI Academy"),
    ("TX", "exact", "global football innovation", "GFI Academy"),
    ("TX", "exact", "Global Football Innovation Academy", "GFI Academy"),
    ("TX", "exact", "Global Football Innocation Academy", "GFI Academy"),
    ("TX", "exact", "Houston Futsal Club (HFA)", "Houston Futsal Soccer Club"),
    ("TX", "exact", "HTX SOccer", "HTX"),
    ("TX", "exact", "juventus premier futbol club", "Juventus Premier FC"),
    ("TX", "exact", "kaptiva sports academy tx", "Kaptiva Sports Academy"),
    ("TX", "exact", "lone star soccer accociation", "Lonestar"),
    ("TX", "exact", "lone star soccer association", "Lonestar"),
    ("TX", "exact", "Lonestar SC", "Lonestar"),
    ("TX", "exact", "Lonestar Soccer Club", "Lonestar"),
    ("TX", "exact", "mafc", "Matias Almeyda Futbol Club"),
    ("TX", "exact", "SG1 SOCCER", "SG1"),
    ("TX", "exact", "TEXAS SPURS FC", "Texas Spurs"),
    ("TX", "exact", "texoma soccer academy", "Texoma SC"),
    ("TX", "regex", r"Juventus Academy Houston\s*\(JA\)\s*$", "Juventus Academy Houston"),
    ("TX", "exact", "Cavalry FC", "Cavalry Youth Soccer"),
    ("TX", "exact", "Atlético Dallas Youth", "Atletico Dallas Youth"),
    # ── Nevada ────────────────────────────────────────────────────────────
    ("NV", "exact", "LV Heat Surf SC", "Las Vegas Heat Surf SC"),
    # ── New York ──────────────────────────────────────────────────────────
    ("NY", "exact", "WNY Flash", "Western New York Flash"),
    ("NY", "exact", "East Coast Surf SC", "East Coast Surf"),
    ("NY", "exact", "Brentwood SC (lijsl)", "Brentwood SC"),
    ("NY", "exact", "BW Gottschee Academy", "Blau Weiss Gottschee"),
    ("NY", "exact", "Downtown United Soccer Club", "DUSC"),
    ("NY", "exact", "Elmont SC (LIJSL)", "Elmont Soccer Club"),
    ("NY", "exact", "Long Island Slammers", "Long Island SC"),
    ("NY", "exact", "Manhattan Kickers", "Manhattan Kickers FC"),
    ("NY", "exact", "Met Oval", "Metropolitan Oval"),
    ("NY", "exact", "New York Elite Alleycats", "Alleycats"),
    ("NY", "exact", "New York Elite Alleycats fc", "Alleycats"),
    ("NY", "exact", "New York Redbulls", "New York Red Bulls"),
    ("NY", "exact", "New York Rush", "NY Rush"),
    ("NY", "exact", "nycfc", "New York City FC"),
    ("NY", "exact", "Rochester NY FC", "RNY FC Youth"),
    ("NY", "exact", "Syracuse Development Academy", "SDA Syracuse Development Academy"),
    ("NY", "exact", "Syracuse Development Academy (SDA)", "SDA Syracuse Development Academy"),
    ("NY", "exact", "Tru Tekkers Soccer Club", "Tru Tekkers"),
    # ── Wisconsin ─────────────────────────────────────────────────────────
    ("WI", "exact", "FC WISCONSIN BOYS", "FC WISCONSIN"),
    ("WI", "exact", "FC WISCONSIN GIRLS", "FC WISCONSIN"),
    ("WI", "exact", "Jefferson County Soccer Association", "Jefferson United SC"),
    ("WI", "exact", "WI United", "Wisconsin United FC"),
    # ── Missouri ──────────────────────────────────────────────────────────
    ("MO", "exact", "Alliance FC", "Alliance Futbol Club (MO)"),
    ("MO", "exact", "Lou Fusz", "Lou Fusz Athletic"),
    ("MO", "exact", "Lou Fusz Athletic 2", "Lou Fusz Athletic"),
    ("MO", "exact", "Slsg", "St. Louis Scott Gallagher"),
    ("MO", "exact", "Sporting Kansas City U16", "Sporting Kansas City"),
    ("MO", "exact", "St. Louis Scott Gallagher St. Charles (M", "St. Louis Scott Gallagher"),
    ("MO", "exact", "St. Louis Stars", "St. Louis Stars SC"),
    # ── Kansas ────────────────────────────────────────────────────────────
    ("KS", "exact", "Kansas City Athletics Lax", "Kansas City Athletics"),
    ("KS", "exact", "KC Athletics", "Kansas City Athletics"),
    ("KS", "exact", "Overland Park Soccer Club", "OP Soccer Club"),
    ("KS", "exact", "Union KC Soccer Club", "Union KC"),
    # ── Idaho ─────────────────────────────────────────────────────────────
    ("ID", "exact", "Boise Timbers | Thorns", "Boise Timbers | Thorns FC"),
    ("ID", "exact", "Sting Soccer Club", "Sting Soccer Club Idaho"),
    # ── Iowa ──────────────────────────────────────────────────────────────
    ("IA", "exact", "FC United (Iowa)", "FC United Iowa"),
    ("IA", "exact", "Iowa Rush Soccer Club - South", "Iowa Rush Soccer Club"),
    ("IA", "exact", "Iowa United", "Iowa United FC"),
    ("IA", "exact", "Sporting Iowa Central", "Sporting Iowa"),
    ("IA", "exact", "Sporting Iowa East", "Sporting Iowa"),
    ("IA", "exact", "United Futbol Academy", "United Futbol Academy (UFA)"),
    ("IA", "exact", "UFA Soccer Academy", "United Futbol Academy (UFA)"),
    ("IA", "exact", "VSA Rush", "Vision Soccer Academy"),
    # ── Oregon ────────────────────────────────────────────────────────────
    ("OR", "exact", "Oregon Surf", "Oregon Surf SC"),
    ("OR", "exact", "FC Portland", "FC Portland Academy"),
    ("OR", "exact", "Saints Soccer Academy", "Saints Academy"),
    ("OR", "exact", "Lincoln Youth Soccer Association", "Lincoln Youth Soccer"),
    ("OR", "exact", "Portland City United", "Portland City United SC"),
    ("OR", "exact", "Portland Thorns FC", "Portland Thorns Academy"),
    # ── Utah ──────────────────────────────────────────────────────────────
    ("UT", "exact", "Sparta United", "Sparta United Soccer Club"),
    ("UT", "exact", "La Roca", "La Roca FC"),
    ("UT", "exact", "Atletico FC", "Atletico"),
    ("UT", "exact", "AYSO UTAH", "AYSO United"),
    ("UT", "exact", "blast fc", "Blast SC"),
    ("UT", "exact", "Club America", "Club America Nido Aguila Soccer Academy"),
    ("UT", "exact", "Colorado Elevation", "Colorado Elevation FC"),
    ("UT", "exact", "Copper Mountain Soccer Club", "Copper Mountain"),
    ("UT", "exact", "Elite FC (ut)", "Elite FC"),
    ("UT", "exact", "Gremio FC Utah", "Gremio FC"),
    ("UT", "exact", "Impact United", "Impact United SC"),
    ("UT", "exact", "Layton Strikers Soccer Club", "Layton Strikers"),
    ("UT", "exact", "la roca south", "La Roca FC"),
    ("UT", "exact", "la roca sf", "La Roca FC"),
    ("UT", "exact", "Liverpool FC", "Liverpool FC International Academy"),
    ("UT", "exact", "peak fc", "Peak SC"),
    ("UT", "exact", "rampage fc", "rampage sc"),
    ("UT", "exact", "Saratoga Youth Soccer", "Saratoga Springs FC"),
    ("UT", "exact", "St George FC", "St George FC (Ut)"),
    ("UT", "exact", "Swat sc", "SWAT Soccer"),
    ("UT", "exact", "Utah Athletic Academy", "Utah Athletic Club"),
    ("UT", "exact", "Utah Celtic", "Utah Celtic FC"),
    ("UT", "exact", "Utah Surf Soccer", "Utah Surf"),
    # ── South Carolina ────────────────────────────────────────────────────
    ("SC", "exact", "South Carolina United", "South Carolina United FC"),
    ("SC", "exact", "South Carolina Surf", "South Carolina Surf SC"),
    ("SC", "regex", r"James Island Youth SC\s+\(JIYSC\)\s*$", "James Island Youth SC"),
    ("SC", "exact", "Coast Futbol Alliance", "Coast FA"),
    # ── Tennessee ─────────────────────────────────────────────────────────
    ("TN", "exact", "FC Alliance", "FC Alliance TN"),
    ("TN", "exact", "All-in fc", "All-In FC TN"),
    ("TN", "exact", "All in Futbol Club Tennessee", "All-In FC TN"),
    ("TN", "exact", "Ayso Alliance", "AYSO Alliance Knoxville"),
    ("TN", "exact", "Chattanooga Football Club", "Chattanooga Football Club Academy"),
    ("TN", "exact", "Chattanooga Red Wolves Academy", "Chattanooga Red Wolves SC"),
    ("TN", "exact", "Kings Hammer Murfreesboro", "Kings Hammer Soccer Club"),
    ("TN", "exact", "Midsouth Bartlett", "Midsouth FC"),
    ("TN", "exact", "Music City F.C. Girls Soccer Club", "Music City SC"),
    ("TN", "exact", "One Knoxville SC", "One Knoxville Youth Club"),
    ("TN", "exact", "TENNESSEE SA", "Tennessee SC"),
    ("TN", "exact", "TENNESSEE SOCCER ACADEMY", "Tennessee SC"),
    ("TN", "exact", "Tennessee United", "Tennessee United SC"),
    # ── Minnesota ─────────────────────────────────────────────────────────
    ("MN", "exact", "St Croix Soccer Club", "St. Croix"),
    ("MN", "exact", "Minnesota Thunder Academy", "MN Thunder Academy"),
    ("MN", "exact", "New Ulm Area Youth Soccer", "New Ulm United"),
    ("MN", "exact", "North Suburban", "North Suburban SA"),
    ("MN", "exact", "Shakopee Soccer Association", "Shakopee SA"),
    ("MN", "exact", "ST Paul Blackhawks", "St. Paul Blackhawks"),
    ("MN", "exact", "Tonka United", "Tonka United SA"),
    # ── Michigan ──────────────────────────────────────────────────────────
    ("MI", "exact", "Nationals SC", "Nationals"),
    ("MI", "exact", "Legends fc", "Legends FC Michigan"),
    ("MI", "exact", "Liverpool fc-ia michigan", "Liverpool FC IA Michigan"),
    ("MI", "exact", "michigan jaguars united fc", "Michigan Jaguars"),
    ("MI", "exact", "Michgan jaguars u17", "Michigan Jaguars"),
    ("MI", "exact", "Michigan Stars Elite", "Michigan Stars Elite SC"),
    ("MI", "exact", "Midwest United", "Midwest United FC"),
    ("MI", "exact", "Vardar Soccer Club", "Vardar Soccer"),
    # ── Connecticut ───────────────────────────────────────────────────────
    ("CT", "exact", "Beachside Soccer Club CT", "Beachside of Connecticut"),
    ("CT", "exact", "AC Connecticut", "A.C. Connecticut"),
    ("CT", "exact", "Connecticut Rush", "CT Rush"),
    # ── Florida ───────────────────────────────────────────────────────────
    ("FL", "exact", "Athletum FC", "Athletum FC Academy"),
    ("FL", "exact", "Athletum SC", "Athletum FC Academy"),
    ("FL", "exact", "Barcelona Soccer Academy", "Barca Academy Pro Miami"),
    ("FL", "exact", "Cape Coral SA", "Cape Coral Soccer"),
    ("FL", "exact", "Chargers SC CLW", "Chargers Soccer Club"),
    ("FL", "exact", "Chargers sc lwr", "Chargers Soccer Club"),
    ("FL", "exact", "chargers sc tpa", "Chargers Soccer Club"),
    ("FL", "exact", "Chivas Futbol Club", "Chivas FC"),
    ("FL", "exact", "Fort Lauderdale FC", "Fort Lauderdale Select FC"),
    ("FL", "exact", "Ideasport sa", "IdeaSport Soccer Academy"),
    ("FL", "exact", "IMG", "IMG Academy"),
    ("FL", "exact", "Orlando City Youth SC", "Orlando City Youth Soccer"),
    ("FL", "exact", "palm beach gardens predat", "Palm Beach Gardens YSA"),
    ("FL", "exact", "Pinecrest Premier SC", "Pinecrest Premier Soccer"),
    ("FL", "exact", "south florida fa", "South Florida Football Academy"),
    ("FL", "exact", "Sunrise Surf", "Sunrise Soccer Club"),
    ("FL", "exact", "Tropical Soccer Club", "Tropical Soccer"),
    # ── Georgia ───────────────────────────────────────────────────────────
    ("GA", "exact", "NTH NASA", "NASA Tophat"),
    ("GA", "exact", "TopHat", "NASA Tophat"),
    ("GA", "exact", "Concord Fire", "Concorde Fire"),
    ("GA", "exact", "atlanta fire united academy", "Atlanta Fire United"),
    ("GA", "exact", "atlanta united FC", "Atlanta United"),
    ("GA", "exact", "BVB IA", "BVB IA Georgia"),
    ("GA", "exact", "Grow soccer evolutions-01", "Grow Soccer Evolution"),
    ("GA", "exact", "Inter Atlanta FC", "Inter Atlanta FC Blues"),
    ("GA", "exact", "lanier soccer academy", "Lanier Soccer Association"),
    ("GA", "exact", "UFA South Georgia", "United Futbol Academy"),
    ("GA", "exact", "UFA metro atlanta", "United Futbol Academy"),
    ("GA", "exact", "United Futbol Academy (UFA)", "United Futbol Academy"),
    # ── Virginia ──────────────────────────────────────────────────────────
    ("VA", "exact", "Springfield SYC Soccer", "Springfield SYC"),
    ("VA", "exact", "PWSI Courage", "Prince William Soccer Inc"),
    ("VA", "exact", "Arlington Soccer Association", "Arlington Soccer"),
    ("VA", "exact", "Arlington SA", "Arlington Soccer"),
    ("VA", "exact", "BRYC Academy", "Braddock Road Youth Club"),
    ("VA", "exact", "BRYC", "Braddock Road Youth Club"),
    ("VA", "exact", "LEE-MT. Vernon Sports Club", "LMVSC"),
    ("VA", "exact", "Loudoun Soccer", "Loudoun Soccer Club"),
    ("VA", "exact", "McLean Youth Soccer", "McLean YS"),
    ("VA", "exact", "FC Dulles United ACADEMY", "FC Dulles"),
    ("VA", "exact", "Fredericksburg soccer club", "Fredericksburg FC"),
    ("VA", "exact", "Sterling", "Sterling Soccer Club"),
    ("VA", "exact", "STJFA", "The St. James Football Club"),
    ("VA", "exact", "Virginia Rush", "VA Rush Soccer Club"),
    ("VA", "regex", r"Beach FC\s+\(VA\)\s*$", "Beach FC"),
    ("VA", "exact", "VA Reign FC", "Virginia Reign"),
    ("VA", "exact", "Richmond Utd", "Richmond United"),
    # ── New Jersey ────────────────────────────────────────────────────────
    ("NJ", "exact", "Match Fit Surf", "Match Fit Academy"),
    ("NJ", "exact", "Franklin Township Youth Soccer Association", "Franklin Township SC"),
    ("NJ", "exact", "atlantic United Soccer Club", "Atlantic United"),
    ("NJ", "exact", "Cedar Stars Academy Monmouth", "Cedar Stars Academy - Monmouth"),
    ("NJ", "exact", "Cedar Stars Academy Bergen", "Cedar Stars Academy - Bergen"),
    ("NJ", "exact", "Cherry Hill FC", "Cherry Hill SC"),
    ("NJ", "exact", "DEPTFORD SA", "Deptford Premier FC"),
    ("NJ", "exact", "Hibernian AA", "PDA Hibernian"),
    ("NJ", "exact", "monroe township ys", "Monroe Township SC"),
    ("NJ", "exact", "pda boys", "Players Development Academy"),
    ("NJ", "exact", "PSA Princeton", "PSA"),
    ("NJ", "exact", "Princeton SA", "PSA"),
    ("NJ", "exact", "New York Red Bulls", "Red Bulls (NJ)"),
    ("NJ", "exact", "sporting club premier (nj)", "Sporting Club Premier"),
    ("NJ", "exact", "STA MO", "STA Mount Olive Soccer Club"),
    ("NJ", "exact", "STA", "STA-MUSC"),
    ("NJ", "exact", "Morris United SA", "STA-MUSC"),
    # ── Ohio ──────────────────────────────────────────────────────────────
    ("OH", "exact", "Canton Force", "Canton Akron United Force"),
    ("OH", "exact", "Ohio Elite SA", "Ohio Elite Soccer Academy"),
    ("OH", "exact", "Cincinnati United", "Cincinnati United Premier Soccer Club"),
    ("OH", "exact", "club ohio united", "Club Ohio"),
    ("OH", "exact", "columbus crew u16", "Columbus Crew"),
    ("OH", "exact", "croatia juniors", "Croatia Jrs"),
    ("OH", "exact", "Cuyahoga valley soccer aca", "Cuyahoga Valley SA"),
    ("OH", "exact", "Blast FC Academy", "Blast FC Soccer Academy"),
    # ── Colorado ──────────────────────────────────────────────────────────
    ("CO", "exact", "ALBION SC CO", "Albion SC Colorado"),
    ("CO", "exact", "albion sc", "Albion SC Colorado"),
    ("CO", "exact", "chivas denver", "Chivas Denver Soccer Academy"),
    ("CO", "exact", "colorado edge sc", "Colorado Edge"),
    ("CO", "exact", "Colorado Futsal", "Colorado Futsal Academy"),
    ("CO", "exact", "colorado rapids", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "colorado rapids youth socc", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "colorado united sc", "Colorado United"),
    ("CO", "exact", "peak fc", "Pikes Peak FC"),
    ("CO", "exact", "Real Colorado u17", "Real Colorado"),
    ("CO", "exact", "Skyline Soccer Association", "Skyline"),
    # ── Pennsylvania ──────────────────────────────────────────────────────
    ("PA", "exact", "Beadling Soccer", "Beadling SC"),
    ("PA", "exact", "Lehigh Valley United Rush", "LVU Rush"),
    ("PA", "exact", "Northern Steel Select Soccer", "Northern Steel"),
    ("PA", "exact", "PA Classics Harrisburg (ldsa)", "PA Classics Harrisburg"),
    ("PA", "exact", "Penn Fusion SA", "Penn Fusion Soccer Academy"),
    ("PA", "exact", "Upper Moreland sc inc", "Upper Moreland SC"),
    ("PA", "exact", "West-Mont United", "West-Mont United S.A."),
    ("PA", "exact", "yms", "Yardley-Makefield Soccer"),
    # ── Massachusetts ─────────────────────────────────────────────────────
    ("MA", "exact", "FC Greater Boston Bolts", "FC Boston Bolts"),
    ("MA", "exact", "FC Juventud New England", "FC Juventus New England"),
    ("MA", "exact", "Intercontinental Football Academy of N", "IFA"),
    ("MA", "exact", "IFA West", "IFA"),
    ("MA", "exact", "NATICK SOCCER CLUB", "Natick Soccer"),
    ("MA", "exact", "NEFC South", "NEFC"),
    ("MA", "exact", "Seacoast of Bedford", "Seacoast United Massachusetts"),
    ("MA", "exact", "Seacoast United", "Seacoast United Massachusetts"),
    ("MA", "exact", "Seacoast United Mass", "Seacoast United Massachusetts"),
    # ── Kentucky ──────────────────────────────────────────────────────────
    ("KY", "exact", "Kentucky Rush - Hardin", "Kentucky Rush SC"),
    ("KY", "exact", "Lexington Sporting Club", "Lexington Sporting"),
    ("KY", "exact", "Louisville City Academy", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "Racing Louisville Academy", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "Racing Louisville FC", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "West louisville Soccer", "West Louisville Soccer Club"),
    # ── Illinois ──────────────────────────────────────────────────────────
    ("IL", "exact", "Addison United AUSC Eagles", "Addison United"),
    ("IL", "exact", "BLFC", "Bloomingdale Lightning FC"),
    ("IL", "exact", "Celtic FC", "Celtic FC Chicago"),
    ("IL", "exact", "Chicago Celtic SC", "Celtic FC Chicago"),
    ("IL", "exact", "Chicago Fire FC U16", "Chicago Fire Youth SC (CFYSC)"),
    ("IL", "exact", "Chicago Fire Youth SC", "Chicago Fire Youth SC (CFYSC)"),
    ("IL", "exact", "Chicago Fire FC", "Chicago Fire Youth SC (CFYSC)"),
    ("IL", "exact", "Chicago Inter Soccer", "Chicago Inter"),
    ("IL", "exact", "Chicago Soccer Academy", "Chicago Soccer Academy (CSA)"),
    ("IL", "exact", "FC Stars", "FC Stars (il)"),
    ("IL", "exact", "Sockers FC", "Sockers FC Chicago"),
    ("IL", "exact", "St. Louis Scott Gallagher", "St. Louis Scott Gallagher"),
    # ── Arizona ───────────────────────────────────────────────────────────
    ("AZ", "exact", "ARIZONA ARSENAL", "Arizona Arsenal Soccer Club"),
    ("AZ", "exact", "brazas", "Brazas Futebol Club"),
    ("AZ", "exact", "fbsl tuzos", "FBSL"),
    ("AZ", "exact", "fc tucson youth sc", "FC Tucson Youth Soccer"),
    ("AZ", "exact", "Next Level Soccer AZ", "Next Level Soccer (AZ)"),
    ("AZ", "exact", "Phoenix Premier", "Phoenix Premier FC"),
    ("AZ", "exact", "Phoenix Rising North Valley", "Phoenix Rising FC North Valley"),
    ("AZ", "exact", "pima county surf", "Pima County Surf Soccer Club"),
    ("AZ", "exact", "Real Salt Lake U16", "RSL Arizona"),
    ("AZ", "exact", "RSL-AZ", "RSL Arizona"),
    ("AZ", "exact", "RSL-AZ North", "RSL Arizona North"),
    ("AZ", "exact", "RSL-AZ South", "RSL Arizona South"),
    ("AZ", "exact", "RSL-AZ Southern AZ", "RSL Arizona Southern AZ"),
    ("AZ", "exact", "RSL-AZ West Valley", "RSL Arizona West Valley"),
    ("AZ", "exact", "RSL-AZ Yuma", "RSL Arizona Yuma"),
    ("AZ", "exact", "Utah Royals FC", "Utah Royals FC - AZ"),
    # ── California ────────────────────────────────────────────────────────
    ("CA", "exact", "Mustang SC", "Mustang Soccer"),
    ("CA", "exact", "FC Golden State Force", "FC Golden State"),
    ("CA", "exact", "Alameda sc", "Alameda Soccer Club"),
    ("CA", "exact", "apple valley sc storm", "apple valley sc"),
    ("CA", "exact", "Atletico Southern California", "atletico so cal"),
    ("CA", "exact", "bakersfield alliance s c", "bakersfield alliance"),
    ("CA", "exact", "Burlingame sc", "Burlingame Soccer Club"),
    ("CA", "regex", r"black\s+lion(?:['’\?])?\s*s?\s*usa\s*fc\s*$", "Black Lions FC USA"),
    ("CA", "regex", r"Beach FC\s+\(CA\)\s*$", "Beach Futbol Club"),
    ("CA", "exact", "AC Brea soccer", "AC Brea"),
    ("CA", "exact", "cal stars prep academy", "cal stars"),
    ("CA", "exact", "celtic sc", "Celtic Soccer Club (S-CA)"),
    ("CA", "exact", "FURY FC (S-CA)", "Fury FC"),
    ("CA", "exact", "capital city soccer club", "capitol city fc"),
    ("CA", "exact", "central california aztecs", "Central Cal Aztecs"),
    ("CA", "exact", "Central cost surf soccer club", "Central Coast Surf"),
    ("CA", "exact", "cfa", "California Football Academy"),
    ("CA", "exact", "claremont stars sc", "Claremont Stars Soccer Club"),
    ("CA", "exact", "crusaders soccer league", "Crusaders Soccer Club"),
    ("CA", "exact", "davis legacy", "Davis Legacy Soccer Club"),
    ("CA", "exact", "Downey FC", "Downey Futbol Club"),
    ("CA", "regex", r"development\s+academy\s+of\s+ca\s*(?:\(\s*dac\s*\))?\s*$", "Development Academy of CA"),
    ("CA", "regex", r"^\s*futbol\s+academy\s+of\s+(?:southern\s+california|socal)\s*$", "FASC"),
    ("CA", "exact", "el dorado hills sc", "El Dorado Hills Soccer Club"),
    ("CA", "exact", "elite academy fc", "Elite FC"),
    ("CA", "exact", "Elk Grove united soccer club", "Elk Grove Soccer"),
    ("CA", "exact", "Fresno Heat", "Fresno Heat FC"),
    ("CA", "exact", "FRAM", "Fram SC"),
    ("CA", "exact", "Flyte SC le", "Flyte SC"),
    ("CA", "exact", "foothill storm sc", "Foothill Storm"),
    ("CA", "exact", "fc premier", "FC Premier (CA)"),
    ("CA", "exact", "fc scorpions", "FC Scorpions (CA)"),
    ("CA", "exact", "Futboleros", "Futboleros FC"),
    ("CA", "exact", "golden eagle futbol club", "Golden Eagles FC"),
    ("CA", "exact", "interamerica", "Inter-America Soccer Club"),
    ("CA", "exact", "joga bonito (ca)", "Joga Bonito FC"),
    ("CA", "exact", "joga bonito", "Joga Bonito FC"),
    ("CA", "exact", "jusa select", "JUSA"),
    ("CA", "exact", "Juventus academy los angeles", "Juventus Academy LA"),
    ("CA", "exact", "Kickers FC", "Kickers FC (CA)"),
    ("CA", "exact", "LA BULLS", "Los Angeles Bulls Soccer Club"),
    ("CA", "exact", "la galaxy u16", "LA Galaxy"),
    ("CA", "exact", "la fc", "Los Angeles FC"),
    ("CA", "exact", "LAFC SOCAL", "Los Angeles FC"),
    ("CA", "exact", "los angeles football club", "Los Angeles FC"),
    ("CA", "exact", "los angeles sc", "Los Angeles Soccer Club"),
    ("CA", "exact", "los angeles surf", "LA Surf Soccer Club"),
    ("CA", "exact", "los gatos united", "Los Gatos United Soccer Club"),
    ("CA", "exact", "marin football club", "Marin FC"),
    ("CA", "exact", "monterey surf sc", "Monterey Surf Soccer Club"),
    ("CA", "exact", "Newbury Park Elite FC", "Newbury Park Elite"),
    ("CA", "exact", "np elite fc", "Newbury Park Elite"),
    ("CA", "exact", "oceanside", "Oceanside Breakers"),
    ("CA", "exact", "one ivy f.c.", "One Ivy FC"),
    ("CA", "exact", "Pajaro Valley Youth SC", "Pajaro Valley Youth Soccer Club"),
    ("CA", "exact", "Palo Alto Soccer Club", "Palo Alto SC"),
    ("CA", "exact", "Pateadores", "Pateadores Soccer Club"),
    ("CA", "exact", "Rebels SC", "Rebels Soccer Club"),
    ("CA", "exact", "Rosevill SC", "Roseville Youth Soccer Club"),
    ("CA", "exact", "sac united", "Sacramento United"),
    ("CA", "exact", "Sacramento United SC", "Sacramento United"),
    ("CA", "exact", "San diego Rush", "San Diego Rush Soccer Club"),
    ("CA", "exact", "San Diego Surf", "San Diego Surf Soccer Club"),
    ("CA", "exact", "sdsc surf", "San Diego Surf Soccer Club"),
    ("CA", "exact", "sf seals", "San Francisco Seals"),
    ("CA", "exact", "SF Elite", "San Francisco Elite Academy"),
    ("CA", "exact", "Silcon Valley Soccer Academy", "Silicon Valley SA"),
    ("CA", "exact", "South Valley Surf", "South Valley Surf SC"),
    ("CA", "exact", "South Valley United", "South Valley United Soccer Club"),
    ("CA", "exact", "Sporting CA USA", "Sporting California USA"),
    ("CA", "exact", "Sporting So-Cal", "Sporting So-Cal Soccer Club"),
    ("CA", "exact", "Steel United", "Steel United California"),
    ("CA", "exact", "TOTAL FUTBOL ACADEMY (CA)", "Total Futbol Academy"),
    ("CA", "exact", "Tudela FC Los Angeles", "Tudela FC"),
    ("CA", "exact", "Valley United Soccer Club Association", "Valley United SC"),
    ("CA", "exact", "Ventura Surf Sc", "Ventura Surf Soccer Club"),
    ("CA", "exact", "vista storm sc", "Vista Storm Soccer Club"),
    ("CA", "exact", "Walnut Creek Surf", "Walnut Creek Surf Soccer Club"),
    ("CA", "exact", "west covina ys", "West Covina SC"),
    ("CA", "exact", "west covina youth soccer corporation", "West Covina SC"),
    ("CA", "exact", "West Coast Soccer", "West Coast Soccer Tracy"),
    ("CA", "exact", "wsc crush", "Woodside Soccer Club Crush"),
    ("CA", "exact", "zerogravity usa academy", "ZeroGravity Academy"),
    ("CA", "exact", "so cal blues sc", "So Cal Blues"),
    ("CA", "exact", "San Francisco Glens sc", "San Francisco Glens"),
    ("CA", "exact", "San Francisco Glens Soccer Club", "San Francisco Glens"),
    ("CA", "exact", "San Juan SC", "San Juan Soccer Club"),
    ("CA", "exact", "Sand and Surf Soccer Club", "Sand and Surf SC"),
    ("CA", "exact", "Santa cruz mid county YSC", "Santa Cruz Mid-County Youth Soccer Club"),
    ("CA", "exact", "Santa Rosa United", "Santa Rosa United Soccer"),
    ("CA", "exact", "North Coast FC", "North Coast Futbol Club"),
    ("CA", "exact", "North Valley Soccer Club", "North Valley Youth Soccer League"),
    ("CA", "exact", "mvla", "Mountain View Los Altos Soccer Club"),
    ("CA", "exact", "mvla soccer club", "Mountain View Los Altos Soccer Club"),
    ("CA", "exact", "msa fc", "Murrieta Soccer Academy"),
    ("CA", "exact", "msa united", "Murrieta Soccer Academy"),
    ("CA", "exact", "lmfc", "LA Mirada FC"),
    ("CA", "exact", "LA surf", "LA Surf Soccer Club"),
    ("CA", "exact", "La mASIA ATHLETIC CLUB", "La Masia"),
    ("CA", "exact", "Legends FC", "Legends FC (CA)"),
    ("CA", "exact", "Legends FC- San Diego", "Legends FC-SD"),
    ("CA", "exact", "LAMORINDA SOCCER CLUB", "Lamorinda SC"),
    # ── Mississippi ───────────────────────────────────────────────────────
    ("MS", "exact", "MS Futbol Club", "Mississippi Rush"),
]


def matches_override(club: str, match_type: str, pattern: str) -> bool:
    """Check if ``club`` matches an override's ``(match_type, pattern)``.

    Preserves the exact semantics of the original ``_matches_override`` in
    ``scripts/full_club_analysis.py``: strip + case-insensitive comparison.
    """
    if not club:
        return False
    c = club.strip()
    if match_type == "exact":
        return c.lower() == pattern.lower()
    if match_type == "prefix":
        return c.lower().startswith(pattern.lower())
    if match_type == "regex":
        return bool(re.search(pattern, c, re.IGNORECASE))
    return False


# Pre-computed indices built once at import time.
def _build_by_state() -> Dict[str, List[Tuple[str, str, str]]]:
    """Group overrides by ``state_code`` for O(state_size) lookups."""
    out: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for state, mtype, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        out[state].append((mtype, pattern, canonical))
    return dict(out)


def _build_cross_state_safe() -> List[Tuple[str, str, str]]:
    """Return the subset of overrides whose ``(match_type, pattern)`` resolves
    to exactly one canonical across all states.

    Used when ``state_code`` is unknown — mirrors ``analyze_no_state_teams``
    in ``scripts/full_club_analysis.py``. An ambiguous pattern like
    ``"FC Stars"`` (claimed by both IL and a hypothetical TX entry under
    different canonical names) is excluded so we never silently rewrite a
    no-state row to the wrong canonical.
    """
    pattern_index: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for state, mtype, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        pattern_index[(mtype, pattern.lower())].append((state, canonical))

    safe: List[Tuple[str, str, str]] = []
    seen_patterns: set = set()
    for state, mtype, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        key = (mtype, pattern.lower())
        if key in seen_patterns:
            continue
        siblings = pattern_index[key]
        canonicals = {c for _, c in siblings}
        if len(canonicals) == 1:
            safe.append((mtype, pattern, canonical))
            seen_patterns.add(key)
    return safe


_BY_STATE: Dict[str, List[Tuple[str, str, str]]] = _build_by_state()
_CROSS_STATE_SAFE: List[Tuple[str, str, str]] = _build_cross_state_safe()


def canonicalize_club_name(state_code: Optional[str], raw_name: str) -> str:
    """Return the canonical club name for ``raw_name`` per the override registry.

    Behavior:
      - When ``state_code`` is a non-empty 2-letter code: try the state's
        overrides in declared order. **First match wins.**
      - When ``state_code`` is ``None`` / empty: try the cross-state-safe
        subset (patterns that resolve to one canonical across all states).
      - If no override matches, return ``raw_name`` unchanged so callers
        can always use the return value as a club name.

    Examples (assuming Monday's overrides have been applied to the DB):
      >>> canonicalize_club_name("CA", "Mustang SC")
      'Mustang Soccer'
      >>> canonicalize_club_name("CA", "Beach FC (CA)")
      'Beach Futbol Club'
      >>> canonicalize_club_name("WA", "XF")
      'Crossfire Premier'
      >>> canonicalize_club_name(None, "RSL-AZ")  # AZ-only pattern; cross-state-safe
      'RSL Arizona'
      >>> canonicalize_club_name("CA", "Some Unknown Club")
      'Some Unknown Club'
    """
    if not raw_name:
        return raw_name

    if state_code:
        code = state_code.strip().upper()
        for mtype, pattern, canonical in _BY_STATE.get(code, []):
            if matches_override(raw_name, mtype, pattern):
                return canonical
        # State-specific isolation: if the known state has no override
        # for this name, return raw rather than applying another state's
        # canonical. A TX team named ``"FC Stars"`` is NOT IL's
        # ``"FC Stars (il)"`` just because IL is the only state with an
        # exact override for that string.
        return raw_name

    # No state — fall back to cross-state-safe subset.
    for mtype, pattern, canonical in _CROSS_STATE_SAFE:
        if matches_override(raw_name, mtype, pattern):
            return canonical
    return raw_name


__all__ = [
    "CLUB_CANONICAL_OVERRIDES",
    "Override",
    "canonicalize_club_name",
    "matches_override",
]
