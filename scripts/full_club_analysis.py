#!/usr/bin/env python3
"""
Full club name analysis - finds BOTH caps issues AND naming variations.
Scans every state for both genders, gives teams with no state the canonical overrides
alone, and writes every fix as SQL.

A second pass, for SincSports and PlayMetrics teams only, lists club names carrying
age or gender text, strips a trailing tag naming the team's own state, and re-cases
ALL-CAPS names from how each word is written across the database. It writes per team
under --execute (not when --dry-run is also given) and reports to
logs/club_name_provider_changes.csv and logs/club_name_review.csv.
"""

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, NamedTuple

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils.us_states import STATE_CODE_TO_NAME

# Load environment
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client  # noqa: E402

SKIP_STATES = set()  # States left out of the scan

SQL_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "club_name_fixes_male_all_states.sql")
PROVIDER_CHANGES_PATH = Path("logs") / "club_name_provider_changes.csv"
REVIEW_PATH = Path("logs") / "club_name_review.csv"

PROVIDER_RULE_CODES = ("sincsports", "playmetrics")

# Hard-coded canonical overrides: (state_code, match_type, pattern, canonical_name)
# match_type: "exact" (case-insensitive), "prefix" (starts with), "regex"
CLUB_CANONICAL_OVERRIDES = [
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
    # Oklahoma (from full merge history - 4x prefers short form)
    ("OK", "exact", "Oklahoma Celtic Football Club", "Oklahoma Celtic"),
    ("OK", "exact", "West Side Alliance", "West Side Alliance SC"),
    ("OK", "exact", "NEOFC", "NE Oklahoma FC"),
    ("OK", "exact", "Neofc Bartlesville", "NE Oklahoma FC"),
    ("OK", "exact", "North Oklahoma City", "North OKC SC"),
    ("OK", "exact", "NorthWest Optimist Club", "Northwest Optimist SC"),
    ("OK", "exact", "NW Oklahoma SA", "Northwest Soccer Club"),
    # Arkansas
    ("AR", "exact", "Ozark United FC Academy AD", "Ozark United FC Academy"),
    # North Carolina
    ("NC", "norm", "AC Sandhills", "AC Sandhills"),
    ("NC", "norm", "Asheboro City Futbol Club", "Asheboro City Futbol Club"),
    ("NC", "norm", "Bogue Banks Futbol Club", "Bogue Banks Futbol Club"),
    ("NC", "norm", "Burke Soccer Association", "Burke SA"),
    ("NC", "exact", "Catawba Valley Youth Soccer", "Catawba Valley Youth Soccer Association"),
    ("NC", "norm", "Catawba Valley YSA", "Catawba Valley Youth Soccer Association"),
    ("NC", "exact", "Charlotte Independence", "Charlotte Independence SC"),
    ("NC", "exact", "Davidson County Youth SL", "Davidson County Youth Soccer League"),
    ("NC", "exact", "Denver United FC (DUFC)", "Denver United Futbol Club"),
    ("NC", "exact", "Fayetteville Soccer Club", "Fayetteville SC / Villarreal Force Academy"),
    ("NC", "exact", "Greater Cleveland Athletic Assn.", "Greater Cleveland Athletic Association"),
    # GCCSA is a different organisation from GCAA: its teams are the Cobras, GCAA's are
    # Cleveland United. Each folds within itself and never across.
    ("NC", "exact", "Greater Cleveland CNTY (GCCSA)", "Greater Cleveland Co. Soccer Association"),
    ("NC", "exact", "Greater Cleveland Co. SA", "Greater Cleveland Co. Soccer Association"),
    ("NC", "exact", "Asheville Buncombe Youth SA", "Asheville Buncombe Youth Soccer Association"),
    # "Barca Academy Carolinas West" is a branch (its team is at Belmont), not a spelling.
    ("NC", "exact", "Barca Academy Carolinas", "Barça Academy Carolinas"),
    ("NC", "exact", "Carolina United Soccer Association", "Carolina United SA"),
    ("NC", "exact", "Chaos United Soccer Club LLC", "Chaos United Soccer Club"),
    ("NC", "exact", "Coastal United Soccer Assn (CU)", "Coastal United SA"),
    ("NC", "exact", "Coastal United Soccer Association", "Coastal United SA"),
    ("NC", "exact", "Davidson County YSA", "Davidson County Youth Soccer League"),
    ("NC", "norm", "Eagles Royal FC", "Eagles RFC"),
    # Majority is "FRANKLIN WAKE SOCCER CLUB - YAKS", which is all caps with a mascot
    # appended; that is not a spelling of the club name, so the shorter one is canonical.
    ("NC", "exact", "FRANKLIN WAKE SOCCER CLUB - YAKS", "Franklin Wake SC"),
    ("NC", "exact", "Granville Keepers Soccer Club LLC", "Granville Keepers"),
    ("NC", "exact", "HIGH COUNTRY SOCCER ASSN (HCSA)", "High Country SA"),
    ("NC", "norm", "Highland Football Club", "Highland FC"),
    ("NC", "norm", "Impact FC", "Impact FC"),
    ("NC", "exact", "Lenoir Youth Soccer (LYSA)", "Lenoir Youth Soccer Association"),
    ("NC", "exact", "Lenoir Youth SA", "Lenoir Youth Soccer Association"),
    ("NC", "exact", "Mebane Youth Soccer Association (MYSA)", "Mebane Youth SA"),
    ("NC", "exact", "NC Courage", "NC Courage Academy"),
    # NC Rush Central is a separate branch and is never folded here.
    ("NC", "exact", "NC Rush Triad (NCRT)", "North Carolina Rush Triad SC"),
    ("NC", "exact", "North Carolina Rush Triad Soccer Club Inc", "North Carolina Rush Triad SC"),
    ("NC", "exact", "NC Rush", "North Carolina Rush Triad SC"),
    ("NC", "exact", "Delete - North Carolina Rush Triad SC", "North Carolina Rush Triad SC"),
    ("NC", "norm", "Neuse River Futbol Alliance", "Neuse River Futbol Alliance"),
    # Majority wins, except where the majority is not a spelling of the club's name:
    # a legal suffix, all caps, or a mascot appended. Those take the clean form.
    ("NC", "exact", "NEXT BIG THING SOCCER ACADEMY", "Next Big Thing Soccer Academy"),
    ("NC", "exact", "Next Big Thing SA", "Next Big Thing Soccer Academy"),
    ("NC", "exact", "OBX Storm, Inc", "OBX Storm"),
    ("NC", "exact", "One7 Academy", "One7"),
    ("NC", "exact", "Onslow Classic Soccer Assn - (OCSA)", "Onslow Classic SA"),
    ("NC", "exact", "Onslow Classic Soccer Association", "Onslow Classic SA"),
    ("NC", "exact", "PITT GREENVILLE SOCCER ASSN  (PGSA)", "Pitt Greenville SA"),
    ("NC", "exact", "Pitt Greenville Soccer Association", "Pitt Greenville SA"),
    ("NC", "exact", "Pitt-Greenville Soccer Association", "Pitt Greenville SA"),
    ("NC", "norm", "Pleasure Island Soccer Association", "Pleasure Island Soccer Association"),
    ("NC", "norm", "Porter Ridge Athletic Association", "Porter Ridge Athletic Association"),
    ("NC", "exact", "Queen City Mutiny FC", "Queen City Mutiny"),
    ("NC", "exact", "Rutherford County SA / Foothills FC", "Rutherford County Soccer Association"),
    ("NC", "exact", "Sanford Area Soccer League (SASL)", "Sanford Area SL"),
    ("NC", "exact", "Sanford Area Soccer League", "Sanford Area SL"),
    ("NC", "norm", "Seashore Soccer League", "Seashore Soccer League"),
    ("NC", "exact", "Seashore SL", "Seashore Soccer League"),
    ("NC", "exact", "Strikers of Gaston County SA(SGCSA)", "Strikers of Gaston County SA"),
    ("NC", "exact", "Strikers of Gaston County Soccer Association", "Strikers of Gaston County SA"),
    ("NC", "exact", "Elite Youth Soccer Club Inc", "Elite Youth Soccer Club"),
    ("NC", "exact", "Havelock Youth Soccer Assn (HYSA)", "Havelock Youth Soccer Association"),
    ("NC", "exact", "Havelock Youth SA", "Havelock Youth Soccer Association"),
    ("NC", "exact", "Indian Trail Athletic Assoc (ITAA)", "Indian Trail Athletic Association"),
    ("NC", "exact", "Swansboro Soccer Assn. (SSA)", "Swansboro Soccer Association"),
    ("NC", "exact", "Swansboro SA", "Swansboro Soccer Association"),
    ("NC", "exact", "TAR River Youth Soccer Assn (TRYSA)", "Tar River Youth SA"),
    ("NC", "exact", "Transylvania YSA (TYSA)/Ecusta FC", "Transylvania Youth Soccer Association"),
    ("NC", "exact", "Transylvania Youth SA", "Transylvania Youth Soccer Association"),
    ("NC", "exact", "Triangle United Soccer Assn", "Triangle United"),
    ("NC", "exact", "Union Youth Futbol Club - UYFC", "Union Youth FC"),
    ("NC", "exact", "United Soccer Club (NC)", "United Soccer Club NC"),
    ("NC", "exact", "United Soccer Club NC Inc", "United Soccer Club NC"),
    ("NC", "exact", "Wake Futbol Club, Inc", "Wake FC"),
    ("NC", "norm", "Wayne County United SC", "Wayne County United SC"),
    ("NC", "exact", "Wesley Chapel Weddington Athletic Association", "Wesley Chapel Weddington Athletic Assoc"),
    ("NC", "exact", "Wesley Chapel Weddington Athletic Assn.", "Wesley Chapel Weddington Athletic Assoc"),
    ("NC", "exact", "WCWAA", "Wesley Chapel Weddington Athletic Assoc"),
    ("NC", "exact", "Western United Soccer Club (WUSC)", "Western United SC"),
    ("NC", "exact", "Wilmington Hammerheads (WHYFC)", "Wilmington Hammerheads FC"),
    ("NC", "exact", "Wilmington United", "Wilmington United Futbol Academy"),
    ("NC", "exact", "Wilson Youth Soccer Assn", "Wilson Youth SA"),
    ("NC", "exact", "Wilson Youth Soccer Association", "Wilson Youth SA"),
    ("NC", "exact", "Wings of Wilkes", "Wings of Wilkes SC"),
    ("NC", "exact", "Yadkin SA", "Yadkin Soccer Association"),
    ("NC", "exact", "Ycvsc Eagles Soccer Club", "YCVSC Eagles Soccer Club"),
    ("NC", "exact", "YCVSC Eagles", "YCVSC Eagles Soccer Club"),
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
    # Texas
    ("TX", "exact", "El Paso Locomotive Youth Soccer Club", "El Paso Locomotive FC"),
    ("TX", "exact", "FC Dallas Youth", "FC Dallas"),
    ("TX", "exact", "LTFC", "Lake Travis Football Club"),
    ("TX", "exact", "SA Athenians", "AC River"),
    ("TX", "exact", "Santa Fe YSC", "Santa Fe Youth Soccer"),
    ("TX", "exact", "Soccer Central", "AC River"),
    ("TX", "norm", "Soccer Central/AC River/SA Athenians", "AC River"),
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
    # Nevada (from full merge history)
    ("NV", "exact", "LV Heat Surf SC", "Las Vegas Heat Surf SC"),
    # New York
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
    # Wisconsin
    ("WI", "exact", "FC WISCONSIN BOYS", "FC Wisconsin"),
    ("WI", "exact", "FC WISCONSIN GIRLS", "FC Wisconsin"),
    ("WI", "exact", "Jefferson County Soccer Association", "Jefferson United SC"),
    ("WI", "exact", "WI United", "Wisconsin United FC"),
    # Missouri
    ("MO", "exact", "Alliance FC", "Alliance Futbol Club (MO)"),
    ("MO", "exact", "Lou Fusz", "Lou Fusz Athletic"),
    ("MO", "exact", "Lou Fusz Athletic 2", "Lou Fusz Athletic"),
    ("MO", "exact", "Slsg", "St. Louis Scott Gallagher"),
    ("MO", "exact", "Sporting Kansas City U16", "Sporting Kansas City"),
    ("MO", "exact", "St. Louis Scott Gallagher St. Charles (M", "St. Louis Scott Gallagher"),
    ("MO", "exact", "St. Louis Stars", "St. Louis Stars SC"),
    # Kansas
    ("KS", "exact", "Kansas City Athletics Lax", "Kansas City Athletics"),
    ("KS", "exact", "KC Athletics", "Kansas City Athletics"),
    ("KS", "exact", "Overland Park Soccer Club", "OP Soccer Club"),
    ("KS", "exact", "Union KC Soccer Club", "Union KC"),
    # Idaho
    ("ID", "exact", "Boise Timbers | Thorns", "Boise Timbers | Thorns FC"),
    ("ID", "exact", "Sting Soccer Club", "Sting Soccer Club Idaho"),
    # Iowa
    ("IA", "exact", "FC United (Iowa)", "FC United Iowa"),
    ("IA", "exact", "Iowa Rush Soccer Club - South", "Iowa Rush Soccer Club"),
    ("IA", "exact", "Iowa United", "Iowa United FC"),
    ("IA", "exact", "Sporting Iowa Central", "Sporting Iowa"),
    ("IA", "exact", "Sporting Iowa East", "Sporting Iowa"),
    ("IA", "exact", "United Futbol Academy", "United Futbol Academy (UFA)"),
    ("IA", "exact", "UFA Soccer Academy", "United Futbol Academy (UFA)"),
    ("IA", "exact", "VSA Rush", "Vision Soccer Academy"),
    # Oregon
    ("OR", "exact", "Oregon Surf", "Oregon Surf SC"),
    ("OR", "exact", "FC Portland", "FC Portland Academy"),
    ("OR", "exact", "Saints Soccer Academy", "Saints Academy"),
    ("OR", "exact", "Lincoln Youth Soccer Association", "Lincoln Youth Soccer"),
    ("OR", "exact", "Portland City United", "Portland City United SC"),
    ("OR", "exact", "Portland Thorns FC", "Portland Thorns Academy"),
    # Utah
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
    ("UT", "exact", "rampage fc", "Rampage SC"),
    ("UT", "exact", "Saratoga Youth Soccer", "Saratoga Springs FC"),
    ("UT", "exact", "St George FC", "St George FC (Ut)"),
    ("UT", "exact", "Swat sc", "SWAT Soccer"),
    ("UT", "exact", "Utah Athletic Academy", "Utah Athletic Club"),
    ("UT", "exact", "Utah Celtic", "Utah Celtic FC"),
    ("UT", "exact", "Utah Surf Soccer", "Utah Surf"),
    # South Carolina
    ("SC", "exact", "South Carolina United", "South Carolina United FC"),
    ("SC", "exact", "South Carolina Surf", "South Carolina Surf SC"),
    ("SC", "regex", r"James Island Youth SC\s+\(JIYSC\)\s*$", "James Island Youth SC"),
    ("SC", "exact", "Coast Futbol Alliance", "Coast FA"),
    # Tennessee
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
    # Minnesota (4x each direction - pick St. Croix as canonical)
    ("MN", "exact", "St Croix Soccer Club", "St. Croix"),
    ("MN", "exact", "Minnesota Thunder Academy", "MN Thunder Academy"),
    ("MN", "exact", "New Ulm Area Youth Soccer", "New Ulm United"),
    ("MN", "exact", "North Suburban", "North Suburban SA"),
    ("MN", "exact", "Shakopee Soccer Association", "Shakopee SA"),
    ("MN", "exact", "ST Paul Blackhawks", "St. Paul Blackhawks"),
    ("MN", "exact", "Tonka United", "Tonka United SA"),
    # Michigan
    ("MI", "exact", "Nationals SC", "Nationals"),
    ("MI", "exact", "Legends fc", "Legends FC Michigan"),
    ("MI", "exact", "Liverpool fc-ia michigan", "Liverpool FC IA Michigan"),
    ("MI", "exact", "michigan jaguars united fc", "Michigan Jaguars"),
    ("MI", "exact", "Michgan jaguars u17", "Michigan Jaguars"),
    ("MI", "exact", "Michigan Stars Elite", "Michigan Stars Elite SC"),
    ("MI", "exact", "Midwest United", "Midwest United FC"),
    ("MI", "exact", "Vardar Soccer Club", "Vardar Soccer"),
    # Connecticut
    ("CT", "exact", "Beachside Soccer Club CT", "Beachside of Connecticut"),
    ("CT", "exact", "AC Connecticut", "A.C. Connecticut"),
    ("CT", "exact", "Connecticut Rush", "CT Rush"),
    # Florida
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
    # Georgia
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
    # Virginia
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
    ("VA", "exact", "Alexandria Soccer Association", "Alexandria SA"),
    ("VA", "norm", "Prince William Soccer Inc", "Prince William Soccer Inc"),
    ("VA", "norm", "Braddock Road Youth Club", "Braddock Road Youth Club"),
    ("VA", "exact", "Stafford Soccer Club", "Stafford Soccer"),
    ("VA", "exact", "Lee Mount Vernon Sports Club", "LMVSC"),
    ("VA", "exact", "Virginia Legacy Soccer Club  (VLSC)", "Virginia Legacy SC"),
    ("VA", "exact", "Northern Virginia SC (NVSC)", "NVSC"),
    ("VA", "exact", "Northern Virginia Soccer Club", "NVSC"),
    ("VA", "exact", "Shenandoah Valley United SC", "Shenandoah Valley United Inc"),
    ("VA", "norm", "Fairfax Police Youth Club", "Fairfax Police Youth Club"),
    ("VA", "exact", "Skyline Elite SC", "Skyline Elite"),
    ("VA", "exact", "Richmond Strikers SC", "Richmond Strikers"),
    ("VA", "exact", "Annandale Boys & Girls", "Annandale Boys & Girls Club"),
    ("VA", "exact", "Augusta United Soccer Club", "Augusta United"),
    ("VA", "norm", "Northern Virginia Alliance", "Northern Virginia Alliance"),
    ("VA", "exact", "Charlottesville Alliance SC", "Charlottesville Alliance Sports Club"),
    ("VA", "exact", "Richmond Kickers", "Richmond Kickers YSC"),
    ("VA", "norm", "Piedmont Youth Soccer League", "Piedmont Youth Soccer League"),
    ("VA", "exact", "Forest Youth Athletic Assn", "Forest Youth Athletic Association"),
    ("VA", "exact", "Baystars FC", "Baystars"),
    ("VA", "exact", "The St. James", "The St. James Football Club"),
    ("VA", "exact", "South County Athletic Assn (SCAA)", "South County Athletic Association"),
    ("VA", "exact", "Elite Kickers", "Elite Kickers Soccer Club"),
    ("VA", "exact", "Danville Soccer Club    (DSC)", "Danville SC"),
    ("VA", "norm", "Clarke County Soccer League", "Clarke County Soccer League"),
    ("VA", "exact", "703 Warriors YSC", "703 Warriors"),
    ("VA", "norm", "Chantilly Youth Association", "Chantilly Youth Association"),
    ("VA", "exact", "Team America Football Club", "Team America"),
    ("VA", "exact", "Sterling Youth Soccer", "Sterling Soccer Club"),
    ("VA", "norm", "Churchland Soccer League", "Churchland Soccer League"),
    ("VA", "exact", "U.S. Futsal", "U.S. Futsal Club"),
    ("VA", "exact", "HYS", "Herndon Youth Soccer"),
    ("VA", "norm", "Chesapeake United SC", "Chesapeake United SC"),
    ("VA", "norm", "Christiansburg SC", "Christiansburg SC"),
    ("VA", "norm", "Premier AC", "Premier AC"),
    ("VA", "exact", "Prince William Courage", "Prince William Soccer Inc"),
    ("VA", "exact", "McLean Youth Soccer / VA Union FC", "McLean YS"),
    ("VA", "exact", "Great Falls/reston SC (gfrsc)", "Great Falls Reston Soccer Club"),
    ("VA", "exact", "Springfield South County YC (SYC)", "Springfield SYC"),
    ("VA", "exact", "Richmond Kickers Youth Soccer Club", "Richmond Kickers YSC"),
    ("VA", "exact", "FREDERICKSBURG SC Inc (FSCI)", "Fredericksburg FC"),
    # Held pending a decision, since each may be two clubs rather than two spellings of one.
    # None of the three pairs has ever played the other, which is consistent with one club
    # but does not establish it.
    # ("VA", "norm", "Old Dominion Football Club (odfc)", "Old Dominion Soccer Club (ODSC)"),
    # ("VA", "norm", "Manassas United Academy", "Manassas United"),
    # ("VA", "norm", "Herndon Football Club", "Herndon Youth Soccer"),
    # New Jersey
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
    # Ohio
    ("OH", "exact", "Canton Force", "Canton Akron United Force"),
    ("OH", "exact", "Ohio Elite SA", "Ohio Elite Soccer Academy"),
    ("OH", "exact", "Cincinnati United", "Cincinnati United Premier Soccer Club"),
    ("OH", "exact", "club ohio united", "Club Ohio"),
    ("OH", "exact", "columbus crew u16", "Columbus Crew"),
    ("OH", "exact", "croatia juniors", "Croatia Jrs"),
    ("OH", "exact", "Cuyahoga valley soccer aca", "Cuyahoga Valley SA"),
    ("OH", "exact", "Blast FC Academy", "Blast FC Soccer Academy"),
    # Colorado
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
    # Pennsylvania
    ("PA", "exact", "Beadling Soccer", "Beadling SC"),
    ("PA", "exact", "Lehigh Valley United Rush", "LVU Rush"),
    ("PA", "exact", "Northern Steel Select Soccer", "Northern Steel"),
    ("PA", "exact", "PA Classics Harrisburg (ldsa)", "PA Classics Harrisburg"),
    ("PA", "exact", "Penn Fusion SA", "Penn Fusion Soccer Academy"),
    ("PA", "exact", "Upper Moreland sc inc", "Upper Moreland SC"),
    ("PA", "exact", "West-Mont United", "West-Mont United S.A."),
    ("PA", "exact", "yms", "Yardley-Makefield Soccer"),
    # Massachusetts
    ("MA", "exact", "FC Greater Boston Bolts", "FC Boston Bolts"),
    ("MA", "exact", "FC Juventud New England", "FC Juventus New England"),
    ("MA", "exact", "Intercontinental Football Academy of N", "IFA"),
    ("MA", "exact", "IFA West", "IFA"),
    ("MA", "exact", "NATICK SOCCER CLUB", "Natick Soccer"),
    ("MA", "exact", "NEFC South", "NEFC"),
    ("MA", "exact", "Seacoast of Bedford", "Seacoast United Massachusetts"),
    ("MA", "exact", "Seacoast United", "Seacoast United Massachusetts"),
    ("MA", "exact", "Seacoast United Mass", "Seacoast United Massachusetts"),
    # Kentucky
    ("KY", "exact", "Kentucky Rush - Hardin", "Kentucky Rush SC"),
    ("KY", "exact", "Lexington Sporting Club", "Lexington Sporting"),
    ("KY", "exact", "Louisville City Academy", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "Racing Louisville Academy", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "Racing Louisville FC", "LouCity/ Racing Youth Academy"),
    ("KY", "exact", "West louisville Soccer", "West Louisville Soccer Club"),
    # Illinois
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
    # Arizona
    ("AZ", "exact", "ARIZONA ARSENAL", "Arizona Arsenal Soccer Club"),
    ("AZ", "exact", "brazas", "Brazas Futebol Club"),
    ("AZ", "exact", "CCV Stars", "CCV Stars"),
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
    # California
    ("CA", "exact", "Mustang SC", "Mustang Soccer"),
    ("CA", "exact", "FC Golden State Force", "FC Golden State"),
    ("CA", "exact", "Alameda sc", "Alameda Soccer Club"),
    ("CA", "exact", "apple valley sc storm", "Apple Valley SC"),
    ("CA", "exact", "Atletico Southern California", "Atletico So Cal"),
    ("CA", "exact", "bakersfield alliance s c", "Bakersfield Alliance"),
    ("CA", "exact", "Burlingame sc", "Burlingame Soccer Club"),
    ("CA", "regex", r"black\s+lion(?:['’\?])?\s*s?\s*usa\s*fc\s*$", "Black Lions FC USA"),
    ("CA", "regex", r"Beach FC\s+\(CA\)\s*$", "Beach Futbol Club"),
    ("CA", "exact", "AC Brea soccer", "AC Brea"),
    ("CA", "exact", "cal stars prep academy", "Cal Stars"),
    ("CA", "exact", "celtic sc", "Celtic Soccer Club (S-CA)"),
    ("CA", "exact", "FURY FC (S-CA)", "Fury FC"),
    ("CA", "exact", "capital city soccer club", "Capitol City FC"),
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
    # Mississippi
    ("MS", "exact", "MS Futbol Club", "Mississippi Rush"),
]

# Acronyms to keep uppercase
ACRONYMS = {
    "FC",
    "SC",
    "SA",
    "AC",
    "CF",
    "CD",
    "YSA",
    "YSO",
    "YSL",
    "SL",
    "CC",
    "AD",
    "AYSO",
    "MLS",
    "RSL",
    "US",
    "USA",
    "USYS",
    "USSF",
    "ECNL",
    "GA",
    "MLS",
    "LA",
    "NY",
    "NJ",
    "OC",
    "DC",
    "KC",
    "STL",
    "ATL",
    "PHX",
    "AL",
    "AK",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NM",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "AFC",
    "CFC",
    "SFC",
    "VFC",
    "PFC",
    "LAFC",
    "NYCFC",
    "NCFC",
}


US_STATE_CODES = frozenset(STATE_CODE_TO_NAME)

# A state code that is also a word ("La", "De", "In") keeps the vocabulary's protection;
# SC is South Carolina's code too, but in a club name it abbreviates Soccer Club.
_CLUB_ACRONYMS = frozenset(ACRONYMS) - (US_STATE_CODES - {"SC"})

_OVERRIDE_OUTPUTS = frozenset(canonical for _, _, _, canonical in CLUB_CANONICAL_OVERRIDES)
_OVERRIDE_OUTPUTS_LOWER = frozenset(canonical.lower() for canonical in _OVERRIDE_OUTPUTS)

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_APOSTROPHE = re.compile(r"(['’])")
_VOWELS = frozenset("AEIOUY")
_ACRONYM_ENDINGS = ("SC", "FC", "SA", "AC", "FA")

_AGE_OR_GENDER = re.compile(
    r"(?<![A-Za-z0-9])(?:[BG]?U-?[0-9]{1,2}[BG]?|[BG]?20[0-9]{2}(?:-[0-9]{2})?|Boys|Girls|Boy|Girl)(?![A-Za-z0-9])",
    re.ASCII | re.IGNORECASE,
)
_TRAILING_TAG = re.compile(r"^(.*\S)\s*\(([^()]+)\)\s*$", re.ASCII)
_TWO_LETTERS = re.compile(r"[A-Za-z]{2}", re.ASCII)
_ALNUM_RUN = re.compile(r"[a-z0-9]+", re.ASCII)
_NON_ALNUM = re.compile(r"[^a-z0-9]+", re.ASCII)
_COMMENT_BREAKS = re.compile(r"[\s\x00-\x1f\x7f]+")

_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n"})
_PROVIDER_TEXT_COLUMNS = frozenset({"team_name", "club", "before", "after"})


class Vocabulary(NamedTuple):
    """How each lower-cased word is written in club names that hold a lowercase letter.

    `spellings` holds the words seen often enough to trust; `mixed_names` counts, for
    every word, the distinct names that write it with a lowercase letter.
    """

    spellings: Dict[str, str]
    mixed_names: Dict[str, int]


def _stems(name):
    """Yield (start, stem_end, word_end, stem, in_brackets, non_ascii) per word.

    A trailing 's or ’s is not part of the stem, and `in_brackets` tracks parentheses only.
    """
    depth, pos = 0, 0
    for m in _WORD.finditer(name):
        gap = name[pos : m.start()]
        depth = max(0, depth + gap.count("(") - gap.count(")"))
        word = m.group(0)
        stem = word[:-2] if len(word) > 2 and word[-2] in "'’" and word[-1] in "sS" else word
        non_ascii = any(c.isalpha() and not c.isascii() for c in stem)
        yield m.start(), m.start() + len(stem), m.end(), stem, depth > 0, non_ascii
        pos = m.end()


def looks_all_caps(name):
    """A name holding a non-ASCII letter never looks all-caps, so it is never re-cased."""
    letters = [c for c in name if c.isalpha()]
    return len(letters) >= 4 and all(c.isascii() for c in letters) and not any(c.islower() for c in name)


def looks_like_acronym(stem):
    letters = _APOSTROPHE.sub("", stem).upper()
    if len(letters) <= 4 or not set(letters) & _VOWELS:
        return True
    run = longest = 0
    for ch in letters:
        run = 0 if ch in _VOWELS else run + 1
        longest = max(longest, run)
    if longest >= 4:
        return True
    return len(letters) <= 6 and letters.endswith(_ACRONYM_ENDINGS)


def learn_vocabulary(club_names):
    """Learn each word's spelling from every club name that holds a lowercase letter.

    A word is kept once it appears in 3 distinct names, or 20 when it has four letters or
    fewer, because short words are where acronyms and ordinary words collide. It is
    spelled all-caps when at least a third of its occurrences are, else its most common
    spelling. A word holding a non-ASCII letter is never learned.
    """
    spellings = defaultdict(Counter)
    names_with = defaultdict(set)
    mixed_names = defaultdict(set)
    for raw in club_names:
        name = (raw or "").strip()
        if not any(c.islower() for c in name):
            continue
        for _, _, _, stem, _, non_ascii in _stems(name):
            if non_ascii:
                continue
            key = stem.lower()
            spellings[key][stem] += 1
            names_with[key].add(name)
            if any(c.islower() for c in stem):
                mixed_names[key].add(name)

    learned = {}
    for key, counts in spellings.items():
        letters = len(_APOSTROPHE.sub("", key))
        if len(names_with[key]) < (20 if letters <= 4 else 3):
            continue
        caps = sum(n for spelling, n in counts.items() if spelling.isupper())
        if caps * 3 >= sum(counts.values()):
            learned[key] = key.upper()
        else:
            learned[key] = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return Vocabulary(learned, {key: len(names) for key, names in mixed_names.items()})


def proper_case(name, vocabulary):
    """Re-case an ALL-CAPS name without lowering an abbreviation; any other name is returned as is."""
    if not looks_all_caps(name) or name in _OVERRIDE_OUTPUTS:
        return name
    out, pos = [], 0
    for start, stem_end, word_end, stem, in_brackets, non_ascii in _stems(name):
        out.append(name[pos:start])
        if in_brackets or non_ascii or stem in ACRONYMS:
            cased = stem
        elif stem.lower() in vocabulary.spellings:
            cased = vocabulary.spellings[stem.lower()]
        elif looks_like_acronym(stem):
            cased = stem
        else:
            cased = "".join(part[:1].upper() + part[1:].lower() for part in _APOSTROPHE.split(stem))
        out.append(cased)
        if word_end > stem_end:
            out.append(name[stem_end] + ("s" if any(c.islower() for c in cased) else "S"))
        pos = word_end
    out.append(name[pos:])
    return "".join(out)


def is_partial_recase(name, vocabulary):
    """True when a word of 3+ letters left in capitals and absent from the vocabulary's spellings is
    written with a lowercase letter in 3+ names (bracketed, non-ASCII and ACRONYMS words aside)."""
    for _, _, _, stem, in_brackets, non_ascii in _stems(name):
        if in_brackets or non_ascii or stem in ACRONYMS or stem.lower() in vocabulary.spellings or not stem.isupper():
            continue
        if len(_APOSTROPHE.sub("", stem)) >= 3 and vocabulary.mixed_names.get(stem.lower(), 0) >= 3:
            return True
    return False


def merge_case_variants(variants, club_counts, every_variant, vocabulary):
    """Start from the most common of `variants`. A club code ("SC") or a bracketed word,
    being a tag or an abbreviation, takes the capitals any of `every_variant` gives it, an
    ALL-CAPS variant included; another short word the capitals another of `variants` gives
    it, unless the vocabulary writes it in lowercase ("Rush"). A word holding a non-ASCII
    letter is kept as the most common variant writes it."""
    base = min(variants, key=lambda v: (-club_counts[v], v))
    out, pos = [], 0
    for start, stem_end, _, stem, in_brackets, non_ascii in _stems(base):
        out.append(base[pos:start])
        upper = stem.upper()
        learned = vocabulary.spellings.get(stem.lower(), "")
        code = upper in _CLUB_ACRONYMS
        short = len(_APOSTROPHE.sub("", stem)) <= 4 and not any(c.islower() for c in learned)
        peers = [v for v in (every_variant if in_brackets or code else variants) if len(v) == len(base)]
        if not non_ascii and (short or in_brackets or code) and any(p[start:stem_end] == upper for p in peers):
            out.append(upper)
        else:
            out.append(stem)
        pos = stem_end
    out.append(base[pos:])
    return "".join(out)


def caps_winner(variants, club_counts, state_code, vocabulary):
    """Pick the spelling a group of case variants should share, or None to leave the group alone."""
    lowered = variants[0].lower()
    for state, _, _, canonical in CLUB_CANONICAL_OVERRIDES:
        if state == state_code and canonical.lower() == lowered:
            return canonical
    mixed = [v for v in variants if any(c.islower() for c in v)]
    if mixed:
        return merge_case_variants(mixed, club_counts, variants, vocabulary)
    base = min(variants, key=lambda v: (-club_counts[v], v))
    winner = proper_case(base, vocabulary)
    if is_partial_recase(winner, vocabulary):
        return None
    return winner


def normalize_for_grouping(name):
    """Normalize name to find genuine naming variations.

    CONSERVATIVE approach: Normalize suffix/prefix variations to a canonical form
    instead of stripping them. This prevents false matches like:
      - "FC Arkansas" ≠ "Arkansas Soccer Club"  (prefix FC ≠ suffix SC)
      - "FC United Soccer Club" ≠ "United Soccer Club"  (different clubs)

    Only matches genuine variations like:
      - "Pride SC" = "Pride Soccer Club"  (same suffix, different abbreviation)
      - "Florida West F.C." = "Florida West FC"  (same suffix, different format)
    """
    n = name.lower().strip()

    # Normalize trailing suffix variations to canonical "sc" or "fc"
    # "Soccer Club" / "S.C." → " sc"
    n = re.sub(r"\s+soccer\s+club\s*$", " sc", n)
    n = re.sub(r"\s+s\.c\.\s*$", " sc", n)

    # "Football Club" / "Futbol Club" / "F.C." → " fc"
    n = re.sub(r"\s+football\s+club\s*$", " fc", n)
    n = re.sub(r"\s+futbol\s+club\s*$", " fc", n)
    n = re.sub(r"\s+f\.c\.\s*$", " fc", n)

    # Normalize leading prefix: "FC X" → "fc x" (keep the FC, just lowercase)
    # Do NOT strip it — "FC Dallas" and "Dallas SC" are different clubs

    return n.strip()


TEAM_COLUMNS = "team_id_master, team_name, club_name, gender, state_code, provider_id"


def fetch_all_teams(client, state_code):
    """Fetch all active teams for a state (both genders) using pagination."""
    all_teams = []
    offset = 0
    page_size = 1000

    while True:
        result = (
            client.table("teams")
            .select(TEAM_COLUMNS)
            .eq("state_code", state_code)
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + page_size - 1)
            .execute()
        )

        if not result.data:
            break
        all_teams.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    return all_teams


def club_acronym(name: str) -> str:
    """A club name's acronym: each word's initial, or the whole word where it already is one.

    "Northern Virginia SC" gives "nvsc" rather than "nvs", because SC is an abbreviation
    standing for itself -- which is how a club writes its own tag.
    """
    words = _ALNUM_RUN.findall(name.lower())
    return "".join(word if word.upper() in _CLUB_ACRONYMS else word[0] for word in words)


def normalized_club(club: str) -> str:
    """Fold a club name to the form a "norm" override compares on.

    Drops a trailing tag that only repeats the name's own acronym, then case, punctuation,
    spacing and a plural ending. Those are the differences that separate two spellings of
    one club without naming a different one, so one entry covers a club's whole family
    instead of one entry per spelling.
    """
    tag = trailing_tag(club)
    if tag and club_acronym(tag[0]) == _NON_ALNUM.sub("", tag[1].lower()):
        club = tag[0]
    folded = _NON_ALNUM.sub("", club.lower())
    return folded[:-1] if folded.endswith("s") else folded


def _matches_override(club: str, match_type: str, pattern: str) -> bool:
    """Check if club name matches the override pattern."""
    if not club:
        return False
    c = club.strip()
    if match_type == "exact":
        return c.lower() == pattern.lower()
    if match_type == "norm":
        return normalized_club(c) == normalized_club(pattern)
    if match_type == "prefix":
        return c.lower().startswith(pattern.lower())
    if match_type == "regex":
        return bool(re.search(pattern, c, re.IGNORECASE))
    return False


def fetch_no_state_teams(client):
    """Fetch active teams that have NULL or empty state_code (both genders)."""
    all_teams = []
    page_size = 1000
    for is_null in (True, False):
        offset = 0
        while True:
            q = client.table("teams").select(TEAM_COLUMNS).eq("is_deprecated", False)
            q = q.is_("state_code", "null") if is_null else q.eq("state_code", "")
            result = q.order("team_id_master").range(offset, offset + page_size - 1).execute()
            if not result.data:
                break
            all_teams.extend(result.data)
            if len(result.data) < page_size:
                break
            offset += page_size
    return all_teams


def fetch_provider_codes(client):
    result = client.table("providers").select("id, code").execute()
    return {p["id"]: p["code"] for p in result.data or []}


def analyze_no_state_teams(teams):
    """Apply CANONICAL overrides to teams with a NULL or empty state_code.

    Only applies an override whose (match_type, pattern) gives one canonical name in
    every state that lists it — "peak fc" is Peak SC in UT and Pikes Peak FC in CO, so
    it is skipped.
    """
    if not teams:
        return []

    # Group overrides by (match_type, pattern.lower()) to detect cross-state collisions
    pattern_index = defaultdict(list)
    for state, mtype, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        pattern_index[(mtype, pattern.lower())].append((state, canonical))

    # Safe overrides: pattern resolves to exactly one canonical name across all states
    safe_overrides = []
    for state, mtype, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        siblings = pattern_index[(mtype, pattern.lower())]
        canonicals = {c for _, c in siblings}
        if len(canonicals) == 1:
            safe_overrides.append((mtype, pattern, canonical))

    club_counts = defaultdict(int)
    for team in teams:
        club = team.get("club_name")
        if club:
            club_counts[club] += 1

    fixes = []
    processed = set()
    for mtype, pattern, canonical in safe_overrides:
        for club in list(club_counts.keys()):
            if club in processed:
                continue
            if _matches_override(club, mtype, pattern):
                if club != canonical:
                    fixes.append(
                        {
                            "from": club,
                            "to": canonical,
                            "count": club_counts[club],
                            "type": "CANONICAL_NO_STATE",
                            "state": None,  # no state filter on update
                        }
                    )
                    processed.add(club)
    return fixes


def analyze_state(teams, state_code, vocabulary):
    """Analyze club names in a state; returns (fixes, team count, teams listed for review)."""
    if not teams:
        return [], 0, []

    # Count club names
    club_counts = defaultdict(int)
    for team in teams:
        club = team.get("club_name")
        if club:
            club_counts[club] += 1

    fixes = []
    listed = []
    processed = set()

    # 0. Apply hard-coded canonical overrides (state-specific)
    for state, match_type, pattern, canonical in CLUB_CANONICAL_OVERRIDES:
        if state != state_code:
            continue
        for club in list(club_counts.keys()):
            if club in processed:
                continue
            if _matches_override(club, match_type, pattern):
                if club != canonical:
                    fixes.append(
                        {
                            "from": club,
                            "to": canonical,
                            "count": club_counts[club],
                            "type": "CANONICAL",
                            "state": state_code,
                        }
                    )
                    processed.add(club)

    # 1. Find caps issues (same lowercase, different case)
    by_lower = defaultdict(list)
    for club in club_counts:
        by_lower[club.lower()].append(club)

    for lower, variants in by_lower.items():
        if len(variants) > 1:
            winner = caps_winner(variants, club_counts, state_code, vocabulary)
            if winner is None:
                listed.extend((team, "partial_recase") for team in teams if team.get("club_name") in variants)
                processed.update(variants)
                continue

            for variant in variants:
                if variant != winner and variant not in processed:
                    fixes.append(
                        {
                            "from": variant,
                            "to": winner,
                            "count": club_counts[variant],
                            "type": "CAPS",
                            "state": state_code,
                        }
                    )
                    processed.add(variant)
                    processed.add(winner)

    # 2. Find naming variations (SC vs Soccer Club etc)
    by_normalized = defaultdict(list)
    for club in club_counts:
        if club not in processed:
            norm = normalize_for_grouping(club)
            by_normalized[norm].append(club)

    for norm, variants in by_normalized.items():
        if len(variants) > 1:
            # Pick majority
            sorted_v = sorted(variants, key=lambda x: -club_counts[x])
            winner = sorted_v[0]

            for variant in sorted_v[1:]:
                fixes.append(
                    {
                        "from": variant,
                        "to": winner,
                        "count": club_counts[variant],
                        "type": "NAMING",
                        "state": state_code,
                    }
                )

    return fixes, len(teams), listed


def generate_sql(all_fixes):
    """Generate SQL UPDATE statements."""
    lines = [
        "-- Club Name Standardization Fixes (all teams, both genders)",
        "-- Generated automatically by full_club_analysis.py",
        "-- Includes BOTH caps fixes AND naming variations",
        "--",
        "-- Each UPDATE filtered by state_code (applies to both Male and Female)",
        "",
        "BEGIN;",
        "",
    ]

    by_state = defaultdict(list)
    for fix in all_fixes:
        by_state[fix["state"] or "__NO_STATE__"].append(fix)

    for state in sorted(by_state.keys()):
        state_fixes = by_state[state]
        label = "NO_STATE" if state == "__NO_STATE__" else state
        lines.append(f"-- ========== {label} ==========")

        for fix in sorted(state_fixes, key=lambda x: (-x["count"], x["from"])):
            from_esc = fix["from"].replace("'", "''")
            to_esc = fix["to"].replace("'", "''")
            from_note = _COMMENT_BREAKS.sub(" ", fix["from"])
            to_note = _COMMENT_BREAKS.sub(" ", fix["to"])
            lines.append(f'-- [{fix["type"]}] "{from_note}" → "{to_note}" ({fix["count"]} teams)')
            if state == "__NO_STATE__":
                lines.append(
                    f"UPDATE teams SET club_name = '{to_esc}' WHERE club_name = '{from_esc}' "
                    "AND (state_code IS NULL OR state_code = '') AND is_deprecated = false;"
                )
            else:
                state_esc = state.replace("'", "''")
                lines.append(
                    f"UPDATE teams SET club_name = '{to_esc}' "
                    f"WHERE club_name = '{from_esc}' AND state_code = '{state_esc}' AND is_deprecated = false;"
                )
            lines.append("")
        lines.append("")

    lines.append("COMMIT;")
    return "\n".join(lines)


def execute_fixes(client, all_fixes, dry_run=True):
    """Apply club name fixes directly via Supabase REST API."""
    if not all_fixes:
        print("No fixes to apply.")
        return 0, 0

    if dry_run:
        print(f"\n[DRY RUN] Would apply {len(all_fixes)} club name fixes")
        for fix in all_fixes[:20]:
            print(f'  {fix["state"]}: "{fix["from"]}" → "{fix["to"]}" ({fix["count"]} teams)')
        if len(all_fixes) > 20:
            print(f"  ... and {len(all_fixes) - 20} more")
        return len(all_fixes), 0

    print(f"\nApplying {len(all_fixes)} club name fixes...")
    applied = 0
    failed = 0

    for fix in all_fixes:
        try:
            q = (
                client.table("teams")
                .update({"club_name": fix["to"]})
                .eq("club_name", fix["from"])
                .eq("is_deprecated", False)
            )
            if fix["state"] is None:
                # No-state-code teams: apply globally for this exact club_name
                # but ONLY where state_code is NULL/empty so we don't touch
                # teams the per-state pass already handled.
                q = q.or_("state_code.is.null,state_code.eq.")
            else:
                q = q.eq("state_code", fix["state"])
            q.execute()
            applied += 1
            label = fix["state"] or "NO_STATE"
            print(f'  ✅ {label}: "{fix["from"]}" → "{fix["to"]}"')
        except Exception as e:
            failed += 1
            label = fix["state"] or "NO_STATE"
            print(f'  ❌ {label}: "{fix["from"]}" → error: {e}')

    print(f"\nApplied: {applied}, Failed: {failed}")
    return applied, failed


def overlay_fixes(teams, fixes):
    """Copies of `teams` holding the club each has once `fixes` land in order, as execute_fixes applies them."""
    overlaid = [dict(team) for team in teams]
    by_state = defaultdict(list)
    for team in overlaid:
        by_state[team.get("state_code") or None].append(team)
    for fix in fixes:
        for team in by_state[fix["state"]]:
            if team.get("club_name") == fix["from"]:
                team["club_name"] = fix["to"]
    return overlaid


def has_age_or_gender_text(club):
    return bool(_AGE_OR_GENDER.search(club))


def trailing_tag(club):
    """Split "Name (TAG)" into ("Name", "TAG"), or None when no bracketed tag ends the name."""
    m = _TRAILING_TAG.match(club)
    return (m.group(1), m.group(2)) if m else None


def apply_provider_rules(teams, provider_codes, vocabulary):
    """Decide the SincSports/PlayMetrics-only changes over overlaid teams; returns (changes, listed)."""
    changes, listed = [], []
    for team in teams:
        provider = provider_codes.get(team.get("provider_id"))
        club = team.get("club_name")
        if provider not in PROVIDER_RULE_CODES or not club or club.lower() in _OVERRIDE_OUTPUTS_LOWER:
            continue
        if has_age_or_gender_text(club):
            listed.append((team, "age_gender"))
            continue

        result, rules = club, []
        tag = trailing_tag(club)
        if tag:
            head, code = tag
            state = (team.get("state_code") or "").upper()
            if not _TWO_LETTERS.fullmatch(code) or code.upper() not in US_STATE_CODES:
                listed.append((team, "tag_other"))
            elif code.upper() != state:
                listed.append((team, "tag_mismatch"))
            elif any(s == state and _matches_override(head, mt, pat) for s, mt, pat, _ in CLUB_CANONICAL_OVERRIDES):
                listed.append((team, "tag_override"))
            else:
                result = head
                rules.append("tag")

        if looks_all_caps(result):
            recased = proper_case(result, vocabulary)
            if is_partial_recase(recased, vocabulary):
                listed.append((team, "partial_recase"))
            elif recased != result:
                result = recased
                rules.append("caps")

        if result != club:
            changes.append(
                {
                    "team_id_master": team["team_id_master"],
                    "team_name": team.get("team_name"),
                    "provider": provider,
                    "state": team.get("state_code"),
                    "before": club,
                    "after": result,
                    "rule": "+".join(rules),
                }
            )
    return changes, listed


def write_provider_changes(client, changes):
    """Write each change only where the team is live and still holds the club the pass read."""
    written = unmatched = failed = 0
    for change in changes:
        try:
            result = (
                client.table("teams")
                .update({"club_name": change["after"]})
                .eq("team_id_master", change["team_id_master"])
                .eq("is_deprecated", False)
                .eq("club_name", change["before"])
                .execute()
            )
        except Exception as e:
            failed += 1
            print(f'  ❌ {change["team_id_master"]}: "{change["before"]}" → error: {e}')
            continue
        if result.data:
            written += 1
        else:
            unmatched += 1
    print(f"Provider rule writes: {written} written, {unmatched} no longer matched, {failed} failed")
    return written, unmatched, failed


def csv_safe(value):
    """`value` with a leading quote when a spreadsheet would read it as a formula."""
    if isinstance(value, str) and value[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _write_csv(path, fieldnames, rows):
    """Write `rows`, defanging the provider text a spreadsheet would read as a formula."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {column: csv_safe(value) if column in _PROVIDER_TEXT_COLUMNS else value for column, value in row.items()}
            for row in rows
        )


def get_supabase(require_service_role=False):
    supabase_url = os.getenv("SUPABASE_URL")
    service_role = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    supabase_key = service_role or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
        sys.exit(1)
    if require_service_role and not service_role:
        # anon holds the UPDATE grant but no UPDATE policy, so RLS filters every write to
        # zero rows and PostgREST answers 200 with an empty body.
        print("ERROR: --execute needs SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY; the anon key writes nothing")
        sys.exit(1)
    return create_client(supabase_url, supabase_key)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Full club name analysis and fixing")
    parser.add_argument("--execute", action="store_true", help="Apply fixes via Supabase (default: generate SQL only)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without applying")
    args = parser.parse_args()
    execute = args.execute and not args.dry_run

    client = get_supabase(require_service_role=execute)

    # Get all states (paginate to ensure we capture every state_code)
    print("Fetching states...")
    all_states = set()
    offset = 0
    page_size = 1000
    while True:
        result = (
            client.table("teams")
            .select("state_code")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        for t in result.data:
            if t.get("state_code"):
                all_states.add(t["state_code"])
        if len(result.data) < page_size:
            break
        offset += page_size
    states = sorted(all_states - SKIP_STATES)

    skip_note = f" (skipping {', '.join(sorted(SKIP_STATES))})" if SKIP_STATES else ""
    print(f"Processing {len(states)} states{skip_note}\n")

    print("Fetching teams...")
    teams_by_state = {state: fetch_all_teams(client, state) for state in states}
    no_state_teams = fetch_no_state_teams(client)
    every_team = no_state_teams + [team for state in states for team in teams_by_state[state]]
    vocabulary = learn_vocabulary(team.get("club_name") for team in every_team)
    provider_codes = fetch_provider_codes(client)

    all_fixes = []
    listed = []
    summary = {}

    # No-state pass: apply collision-safe canonical overrides to teams with a NULL or
    # empty state_code.
    print("Analyzing teams with no state_code...", end=" ")
    no_state_fixes = analyze_no_state_teams(no_state_teams)
    if no_state_fixes:
        affected = sum(f["count"] for f in no_state_fixes)
        all_fixes.extend(no_state_fixes)
        summary["__no_state__"] = {
            "canonical": len(no_state_fixes),
            "caps": 0,
            "naming": 0,
            "affected": affected,
            "total": affected,
        }
        print(f"{len(no_state_fixes)} canonical ({affected} teams)")
    else:
        print("clean")

    for state in states:
        print(f"Analyzing {state}...", end=" ")
        fixes, total, state_listed = analyze_state(teams_by_state[state], state, vocabulary)
        all_fixes.extend(fixes)
        listed.extend(state_listed)

        if fixes:
            affected = sum(f["count"] for f in fixes)
            canonical = sum(1 for f in fixes if f["type"] == "CANONICAL")
            caps = sum(1 for f in fixes if f["type"] == "CAPS")
            naming = sum(1 for f in fixes if f["type"] == "NAMING")
            summary[state] = {
                "canonical": canonical,
                "caps": caps,
                "naming": naming,
                "affected": affected,
                "total": total,
            }
            print(f"{canonical} canonical, {caps} caps, {naming} naming ({affected} teams)")
        else:
            print("clean")

    # Generate SQL (always, for audit trail)
    output_path = SQL_OUTPUT_PATH
    sql = generate_sql(all_fixes)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)

    total_fixes = len(all_fixes)
    total_affected = sum(f["count"] for f in all_fixes)
    total_canonical = sum(1 for f in all_fixes if f["type"] in ("CANONICAL", "CANONICAL_NO_STATE"))
    total_caps = sum(1 for f in all_fixes if f["type"] == "CAPS")
    total_naming = sum(1 for f in all_fixes if f["type"] == "NAMING")

    for state in sorted(summary.keys()):
        s = summary[state]
        parts = []
        if s.get("canonical"):
            parts.append(f"{s['canonical']} canonical")
        if s.get("caps"):
            parts.append(f"{s['caps']} caps")
        if s.get("naming"):
            parts.append(f"{s['naming']} naming")
        print(f"  {state}: {' + '.join(parts)} = {s['affected']} teams affected")

    print("-" * 60)
    print(f"TOTAL: {total_fixes} fixes ({total_canonical} canonical + {total_caps} caps + {total_naming} naming)")
    print(f"       {total_affected} teams will be updated")
    print(f"\nSQL written to: {output_path}")

    # Execute if requested
    fix_failures = provider_failures = 0
    if execute:
        _, fix_failures = execute_fixes(client, all_fixes, dry_run=False)
    elif args.dry_run:
        execute_fixes(client, all_fixes, dry_run=True)

    # Provider pass: each write's predicate is the club the fixes above leave behind.
    overlaid = overlay_fixes(every_team, all_fixes)
    changes, provider_listed = apply_provider_rules(overlaid, provider_codes, vocabulary)
    listed.extend(provider_listed)

    changes.sort(key=lambda c: (c["provider"], c["state"] or "", c["before"], c["team_id_master"]))
    review = sorted(
        (
            {
                "team_id_master": team.get("team_id_master"),
                "team_name": team.get("team_name"),
                "provider": provider_codes.get(team.get("provider_id")),
                "state": team.get("state_code"),
                "club": team.get("club_name"),
                "reason": reason,
            }
            for team, reason in listed
        ),
        key=lambda r: (r["reason"], r["provider"] or "", r["state"] or "", r["club"] or "", r["team_id_master"]),
    )
    _write_csv(
        PROVIDER_CHANGES_PATH,
        ["team_id_master", "team_name", "provider", "state", "before", "after", "rule"],
        changes,
    )
    _write_csv(REVIEW_PATH, ["team_id_master", "team_name", "provider", "state", "club", "reason"], review)

    tagged = sum(1 for c in changes if "tag" in c["rule"].split("+"))
    recased = sum(1 for c in changes if "caps" in c["rule"].split("+"))
    print(f"\nPROVIDER RULES: {len(changes)} changes ({tagged} tag + {recased} caps); {len(review)} listed for review")
    print(f"Provider rule lists: {PROVIDER_CHANGES_PATH} and {REVIEW_PATH}")

    if execute:
        _, _, provider_failures = write_provider_changes(client, changes)

    if fix_failures or provider_failures:
        print(f"ERROR: {fix_failures} club name fixes and {provider_failures} provider rule writes failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
