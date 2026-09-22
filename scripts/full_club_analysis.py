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
    # Redirected when "Wenatchee FC" itself folded into the 87-team "Wenatchee FA".
    ("WA", "exact", "Wenatchee FC Youth", "Wenatchee FA"),
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
    ("NC", "exact", "SPORTING CHARLOTTE FC", "Sporting Charlotte FC"),
    # Held: the team names say these are two organisations, not two spellings.
    # Charlotte FC's teams read "Matthews King", which is also a Charlotte Soccer
    # Academy pattern, but Charlotte FC is the MLS club's own name.
    # Waxhaw's teams read "WAA Navy" against "WSC Navy" -- different acronyms.
    # ("NC", "exact", "Charlotte FC", "Charlotte Soccer Academy"),
    # ("NC", "exact", "Waxhaw Soccer Club", "Waxhaw Athletic Association"),
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
    ("TX", "norm", "El Paso Premier League", "El Paso Premier League"),
    ("TX", "exact", "DFeeters Kicks Soccer Club (DKSC)", "DKSC"),
    ("TX", "exact", "Dallas Texans Soccer Club", "Dallas Texans"),
    ("TX", "exact", "Frisco SA", "Frisco Soccer Association"),
    ("TX", "exact", "PASO DEL NORTE", "Paso Del Norte SA"),
    # Held: Tyler FC is its own club, not Tyler SA's spelling. Its teams read "TYLER FC
    # U10G" against "Tyler SA Vipers", and one of them carries the club name where the
    # team name should be -- which is a team-name problem, not a club-name one.
    ("TX", "exact", "Tyler Soccer Association", "Tyler SA"),
    ("TX", "exact", "San Antonio City", "San Antonio City SC"),
    ("TX", "exact", "Greater Lewisville Area SA (GLASA)", "GLASA"),
    ("TX", "exact", "Lubbock Soccer Association", "Lubbock Soccer"),
    ("TX", "exact", "Arlington Soccer Association", "Arlington SA"),
    ("TX", "exact", "Mckinney Soccer Assn", "McKinney Soccer"),
    # "Midland Alliance" teams read "Midland SA Mambas FC" and "Midland SA Toucans".
    ("TX", "exact", "Midland Alliance", "Midland SA"),
    ("TX", "exact", "Houston Surf", "Houston Surf Soccer Club"),
    ("TX", "norm", "Greater Longview SA", "Greater Longview SA"),
    ("TX", "exact", "SA United", "SA United Soccer Club"),
    ("TX", "exact", "Dallas Hornets Youth", "Dallas Hornets"),
    ("TX", "exact", "Alamo Area YSA   (AAYSA)", "Alamo Area Youth Soccer Assn"),
    ("TX", "exact", "Georgetown Soccer Assn (gsa)", "Georgetown Soccer Association"),
    ("TX", "exact", "Dallas Kicks SC", "DKSC"),
    ("TX", "exact", "210 Soccer", "210 FC"),
    # 210 is San Antonio's area code, so this is the club's own name with its city
    # appended rather than a branch: 17 of its 18 teams read "210 FC ...", on the same
    # ECNL RL STXCL pattern and under the same coaches. No fold reaches a trailing place
    # name, and deliberately so -- stripping one would merge real branches.
    ("TX", "exact", "210 FC San Antonio", "210 FC"),
    ("TX", "exact", "Fever United FC", "Fever United"),
    ("TX", "exact", "Bedford-euless Soccer (besa)", "Bedford-Euless Soccer"),
    # The HUFC rows read "Hurst United SA FC Hurst United 15B", and HUSA's own teams
    # carry "FC Hurst United" names, so all three spellings are the one club.
    ("TX", "exact", "FC Hurst United", "Hurst United SA"),
    ("TX", "exact", "Hurst United FC (HUFC)", "Hurst United SA"),
    ("TX", "exact", "New Braunfels Youth SA", "New Braunfels YSA"),
    # Both live spellings carry a redundant (BOYSA) tag, so the canonical drops it.
    (
        "TX",
        "norm",
        "Brownsville Opportunity Youth Soccer Association",
        "Brownsville Opportunity Youth Soccer Association",
    ),
    ("TX", "exact", "Brownsville Opportunity YSA (BOYSA)", "Brownsville Opportunity Youth Soccer Association"),
    ("TX", "exact", "KLEIN", "Klein SC"),
    ("TX", "exact", "Odessa Soccer Association", "Odessa SA"),
    ("TX", "exact", "Grapevine-Southlake Soccer", "Grapevine Southlake SA"),
    ("TX", "exact", "Aspire Soccer Club", "Aspire FC"),
    ("TX", "exact", "Greater Wichita Falls SA", "Greater Wichita Falls Soccer Association"),
    ("TX", "exact", "Beaumont Youth SC (BYSC)", "Beaumont YSC"),
    ("TX", "exact", "Leander Youth SA", "Leander YSA"),
    ("TX", "exact", "Hardin County Youth Soccer  (HCYSC)", "Hardin County YSC"),
    ("TX", "exact", "Baytown Saints Youth SC  (BSYSC)", "Baytown Saints YSC"),
    ("TX", "exact", "South BELT Youth SC    (SBYSC)", "South Belt YSC"),
    ("TX", "exact", "South BELT Youth SA    (SBYSA)", "South Belt YSC"),
    ("TX", "exact", "Katy Youth SC", "Katy YSC"),
    ("TX", "norm", "Royse City SA", "Royse City SA"),
    ("TX", "exact", "Real Greens SA  (RGSA)", "Real Greens Soccer Academy"),
    ("TX", "exact", "Liberty Hill Youth Soccer Association", "Liberty Hill Youth Soccer"),
    ("TX", "norm", "Santa Fe Youth Soccer", "Santa Fe Youth Soccer"),
    # All three read "SAFC ECNL RL" in their team names.
    ("TX", "exact", "SAFC", "San Antonio FC"),
    ("TX", "exact", "San Antonio Athletic Football Club", "San Antonio FC"),
    ("TX", "exact", "San Antonio FC Academy", "San Antonio FC"),
    ("TX", "exact", "Bee Youth Soccer Organization", "BYSO"),
    ("TX", "norm", "Brazosport Youth Soccer Assn.", "Brazosport Youth Soccer Assn."),
    ("TX", "exact", "Brazosport Youth Soccer Association (BYSA)", "Brazosport Youth Soccer Assn."),
    ("TX", "exact", "East Texas United", "East Texas United SC"),
    ("TX", "norm", "Juventus Premier FC", "Juventus Premier FC"),
    ("TX", "exact", "FORT WORTH VAQUEROS", "Fort Worth Vaqueros FC"),
    ("TX", "exact", "Texas Select FC (LUBBOCK)", "Texas Select Futbol Club"),
    ("TX", "exact", "Little ELM Soccer", "Little Elm Youth SA"),
    ("TX", "norm", "Wells Branch SA", "Wells Branch SA"),
    ("TX", "exact", "Cosmos FC (TX)", "Cosmos FC Academy"),
    ("TX", "norm", "North Austin Soccer Alliance", "North Austin Soccer Alliance"),
    ("TX", "exact", "Henderson County Soccer Assn (HCSA)", "Henderson County SA"),
    ("TX", "exact", "RSA", "Richardson SA"),
    ("TX", "exact", "Amarillo Soccer Assn (ASA)", "Amarillo SA"),
    ("TX", "exact", "EL PASO SURF", "El Paso Surf Soccer Club"),
    ("TX", "exact", "Houston City Soccer Academy", "Houston City SA"),
    ("TX", "exact", "North Texas Soccer Assn (NTSA)", "North Texas Soccer Association"),
    ("TX", "exact", "Lockhart Youth SA", "Lockhart YSA"),
    ("TX", "exact", "San Angelo Elite Soccer Academy", "San Angelo Elite"),
    ("TX", "exact", "Quest Soccer Club", "Quest YSC"),
    ("TX", "exact", "WACO UNITED YOUTH SPORTS", "Waco United SC"),
    ("TX", "exact", "FC Cardinals", "FC Cardinals Academy"),
    # "MT. Pleasant FC" is left out: its one team reads "MP Elite 2024".
    ("TX", "exact", "MT. Pleasant Youth Soccer Assn", "Mt. Pleasant Youth Soccer Association"),
    ("TX", "exact", "Houston Dynamo", "Houston Dynamo FC"),
    ("TX", "exact", "Houston Dynamo FC Academy", "Houston Dynamo FC"),
    ("TX", "exact", "Academia de fútbol Dallas", "Academia DE Futbol Dallas"),
    ("TX", "exact", "Hill Country FC (ASSN OF SPORTS)", "Hill Country Youth Soccer Association"),
    ("TX", "exact", "Houston Dutch Lions", "Houston Dutch Lions FC"),
    ("TX", "exact", "Texas Lonestars FC", "Texas Lonestars Soccer Club"),
    ("TX", "exact", "Castroville United FC", "Castroville United"),
    ("TX", "norm", "Club America - Tarrant County", "Club America - Tarrant County"),
    ("TX", "exact", "Bayern Munich FC", "Bayern Munich"),
    ("TX", "exact", "Irving Elite FC", "Irving Elite Soccer Academy"),
    ("TX", "exact", "Austin Texans", "Austin Texans Soccer Club"),
    ("TX", "exact", "Prime TIME Soccer Club (PTSC)", "Prime Time SC"),
    ("TX", "exact", "UNIVERSAL FC", "Universal Soccer Club"),
    ("TX", "exact", "Texas Rangers FC", "Texas Rangers"),
    ("TX", "exact", "SS UNITED", "SS United FC"),
    ("TX", "exact", "Big Country Soccer Assn (BCSA)", "Big Country SA"),
    # Both live spellings only tag the state, so the canonical drops the tag.
    ("TX", "exact", "Strikers FC (TX)", "Strikers FC"),
    ("TX", "exact", "Strikers FC( Texas)", "Strikers FC"),
    # Read off the club list by eye. None of these shapes is reachable by any fold: a
    # place name appended to the club's own name looks exactly like a branch, and a
    # branch is its own club.
    ("TX", "exact", "Cedar Stars Rush", "Cedar Stars Rush Houston"),
    ("TX", "exact", "Centex Storm", "Centex Storm Soccer Club"),
    # Its teams are all "Rayados", CF Monterrey's own nickname. MTY abbreviates the
    # club's name away, so the full name is canonical even though it is the minority.
    ("TX", "exact", "CF MTY", "CF Monterrey"),
    ("TX", "exact", "Classic Elite STX SA", "Classics Elite SA"),
    # A partner brand in the name, the shape North Carolina met as "Fayetteville SC /
    # Villarreal Force Academy". Coppell's coaches field teams under both spellings, and
    # Crosby Youth Soccer already fields a "Crosby United FC" team of its own.
    ("TX", "exact", "Coppell Youth SA / Coppell FC", "Coppell FC"),
    ("TX", "exact", "Crosby Youth SC / Crosby United FC", "Crosby Youth Soccer"),
    # Pinned against the caps pass, which had already damaged the majority spelling and
    # was about to copy it onto the correct minority. "Laughlin" is a proper noun (Del Rio
    # holds Laughlin AFB) and a past re-case lowered it on 18 of 20 rows; "de" is a Spanish
    # preposition that the same pass read as a two-letter acronym and raised to "DE" on 9 of
    # 10. `caps_winner` returns an override's canonical for the group, so naming the right
    # spelling here both stops the next write and repairs the rows already written.
    ("TX", "exact", "Del Rio-laughlin Youth Soccer Assn", "Del Rio-Laughlin Youth Soccer Assn"),
    ("TX", "exact", "Club DE Futbol Houston Rayados", "Club De Futbol Houston Rayados"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   "TIGRES" is Odessa Tigres in West Texas; Tigres Soccer Academy plays STXCL.
    #   South Texas Youth Soccer Association is the governing body, not South Texas FC.
    #   "FCD" is FC Divas, not FC Dallas.
    #   "Dragons Soccer Club" fields "Lady Dragons"; Dragon FC Academy names itself.
    #   Elite FC, "Esa", "ESC" and a Wichita Falls branch are four different acronyms.
    #   El Paso Soccer League's one team is "EL Paso Sundevils FC".
    #   Texas Sport Club fields "Tejas FC", and Texas Alliance SC a Fort Worth Vaqueros team.
    #   "Titans FC" is "Titanes"; "Titans SC" holds a "Hawks SC" team.
    #   "Scorpions (tx)" holds a team called "Bears".
    #   Real Academia Futbol and Real Sport FC are different names.
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
    # Redirected when "Jefferson United SC" itself folded away: all three Jefferson
    # spellings field "JC United" teams, and "Jefferson County SC" is the majority.
    ("WI", "exact", "Jefferson County Soccer Association", "Jefferson County SC"),
    ("WI", "exact", "Jefferson County United SC", "Jefferson County SC"),
    ("WI", "exact", "Jefferson United SC", "Jefferson County SC"),
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
    ("SC", "exact", "Carolina Elite SA (CESA)", "Carolina Elite Soccer Academy"),
    ("SC", "norm", "South Carolina United FC", "South Carolina United FC"),
    ("SC", "exact", "Charleston Soccer Club (CSC)", "Charleston Soccer Club"),
    ("SC", "exact", "Furman United", "Furman United SC"),
    ("SC", "exact", "Clemson Anderson Soccer Alliance", "Clemson Anderson SA"),
    ("SC", "norm", "Mount Pleasant FC", "Mount Pleasant FC"),
    ("SC", "exact", "Mount Pleasant Soccer Club", "Mount Pleasant FC"),
    ("SC", "exact", "Fort Mill United", "Fort Mill United Soccer Club"),
    ("SC", "exact", "Lowcountry United", "Lowcountry United Soccer Academy"),
    ("SC", "exact", "Beach United Football Club (bufc)", "Beach United FC"),
    ("SC", "exact", "Clover Elite FC", "Clover Elite"),
    ("SC", "exact", "Florence SA", "Florence Soccer Association"),
    ("SC", "exact", "Spartanburg United Soccer Academy", "Spartanburg United SA"),
    ("SC", "exact", "United FC Furman", "United FC - Furman"),
    ("SC", "norm", "Impact City FC", "Impact City FC"),
    ("SC", "exact", "Impact City FC (Charleston)", "Impact City FC"),
    ("SC", "norm", "Daniel Island Soccer Academy", "Daniel Island Soccer Academy"),
    ("SC", "exact", "Bluffton United FC", "Bluffton United"),
    # A second pass read off the club list. The CESA regex catches rows whose club field
    # holds a CESA team name; the Augusta Arsenal canonical matches the Georgia side, so the
    # club reads the same on both sides of the border.
    ("SC", "exact", "Augusta Arsenal SC (SC)", "Augusta Arsenal SC"),
    ("SC", "exact", "Augusta Arsenal Soccer Club", "Augusta Arsenal SC"),
    ("SC", "exact", "BILU International SA (BISA)", "Bilu International Soccer Academy"),
    ("SC", "exact", "BLYTHEWOOD SOCCER CLUB", "Blythewood Soccer Club"),
    ("SC", "regex", "^(U[0-9]+B )?CESA[ ]", "Carolina Elite Soccer Academy"),
    ("SC", "exact", "Easley Soccer Club", "Easley SC"),
    ("SC", "exact", "SUMTER SOCCER CLUB", "Sumter Soccer Club"),
    ("SC", "exact", "TECHNICAL SOCCER CLUB", "Technical Soccer Club"),
    ("SC", "exact", "Tormenta FC Academy", "Tormenta FC"),
    # Left apart deliberately: Dorchester United against Dorchester United SC, a tie with no
    # tiebreaker, and the 'Augusta Arsenal SC (ga)' row, which is a Georgia tag on a South
    # Carolina team and so asks which state it belongs to rather than which name.
    # Also 21 rows whose club field reads 'BU10 Black', 'BU11 Blue North' and the like. Those
    # are not Bluffton United: BU is Boys-U-age, and each row's label matches its own
    # age_group exactly (BU10 -> u10 ... BU18 -> u19). Their SincSports ids and their
    # opponents -- Coast FA, Mount Pleasant FC, Charleston United, Daniel Island -- put them
    # in Charleston, two hours from Bluffton. The rows name no club at all, so any club is a
    # guess.
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
    ("TN", "exact", "FC Alliance (TN)", "FC Alliance TN"),
    ("TN", "exact", "Germantown Legends Soccer Club", "Germantown Legends"),
    ("TN", "exact", "Lobos Rush Soccer", "Lobos Rush"),
    ("TN", "exact", "Chattanooga FC Youth", "Chattanooga Football Club Academy"),
    ("TN", "exact", "Chattanooga FC Academy", "Chattanooga Football Club Academy"),
    ("TN", "exact", "Jackson SC(TN)", "Jackson Soccer Club"),
    ("TN", "exact", "Signal Mountain Soccer League", "Signal Mountain SL"),
    ("TN", "exact", "East Nashville Athletics", "East Nashville Athletics FC"),
    ("TN", "norm", "Futsal Escola", "Futsal Escola"),
    ("TN", "exact", "Kononia FC", "Kononia SC"),
    ("TN", "exact", "Tennessee Select Soccer Academy", "Tennessee Select SA"),
    ("TN", "exact", "Tennessee Premier Soccer Academy", "Tennessee Premier"),
    ("TN", "norm", "Memphis International FC", "Memphis International FC"),
    ("TN", "norm", "North River Soccer Assn", "North River Soccer Assn"),
    ("TN", "exact", "North River SA", "North River Soccer Assn"),
    ("TN", "norm", "Tri-Cities United SC", "Tri-Cities United SC"),
    ("TN", "exact", "Paris Soccer Club", "Paris FC"),
    ("TN", "exact", "Celtic Soccer Club (TN)", "Celtic Soccer Club"),
    # A second pass read off the club list. The regexes catch rows whose club field holds a
    # team name carrying the club's own name or acronym.
    ("TN", "exact", "All-IN Futbol Club", "All-In FC TN"),
    ("TN", "regex", "^All-In FC TN[ ]", "All-In FC TN"),
    ("TN", "exact", "Clarksville Soccer Club", "Clarksville SC"),
    ("TN", "regex", "^Clarksville SC[ (]", "Clarksville SC"),
    ("TN", "exact", "LAKEWAY SOCCER CLUB", "Lakeway Soccer Club"),
    ("TN", "exact", "Lakeway Cannons", "Lakeway Soccer Club"),
    ("TN", "exact", "Midsouth Bartlett Futbol Club", "Midsouth FC"),
    ("TN", "exact", "Music City Football Club", "Music City SC"),
    ("TN", "exact", "Music City FC (REYES)", "Music City SC"),
    ("TN", "exact", "Nashville United Soccer ACD (NUSA)", "Nashville United Soccer Academy"),
    ("TN", "regex", "^NUSA[ ]", "Nashville United Soccer Academy"),
    ("TN", "exact", "B12/13 NUSA Navy (U14)", "Nashville United Soccer Academy"),
    ("TN", "exact", "One Knoxville YC", "One Knoxville Youth Club"),
    ("TN", "regex", "^One Knox[ ]", "One Knoxville Youth Club"),
    ("TN", "exact", "Paris United Futbol Club", "Paris FC"),
    ("TN", "exact", "Rampage Soccer Club", "Rampage SC"),
    ("TN", "regex", "^Rampage U[0-9]", "Rampage SC"),
    ("TN", "exact", "Redoubt Soccer", "Redoubt SA"),
    ("TN", "exact", "U15 Redoubt General Black", "Redoubt SA"),
    ("TN", "exact", "SOCCER CLUB OF OAK RIDGE", "Soccer Club of Oak Ridge"),
    ("TN", "regex", "^Stones River (FC )?[0-9U]", "Stones River Futbol Club"),
    ("TN", "exact", "Tennessee Soccer Club", "Tennessee SC"),
    ("TN", "regex", "^Tennessee SC[ ]", "Tennessee SC"),
    # Left apart deliberately: Nashville SC, the MLS club, against NASHVILLE FUTBOL CLUB,
    # whose teams read "NFC". Music City and Redoubt were held here and are now decided.
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
    ("FL", "exact", "SPORTING JAX", "Sporting Jax Soccer Academy"),
    ("FL", "exact", "West Florida Flames SC", "West Florida Flames"),
    ("FL", "exact", "Miami Stars SC", "Miami Stars Soccer"),
    ("FL", "exact", "Space Coast United SC", "Space Coast United"),
    ("FL", "exact", "Florida Celtic Soccer Club", "Florida Celtic"),
    ("FL", "exact", "CAPE CORAL SOCCER ASSOCIATION", "Cape Coral Soccer"),
    ("FL", "exact", "Pinecrest Premier Soccer Club", "Pinecrest Premier Soccer"),
    ("FL", "exact", "Brevard Soccer Academy", "Brevard SA"),
    # Both spellings field "ASG" teams.
    ("FL", "exact", "Warner Soccer (ASG FLORIDA FC)", "Warner Soccer Club"),
    ("FL", "exact", "W & H America Soccer", "W&H America"),
    ("FL", "norm", "DME Academy Sarasota", "DME Academy Sarasota"),
    ("FL", "exact", "Key Biscayne Soccer Club (KBSC)", "Key Biscayne SC"),
    ("FL", "exact", "Rip City Surf", "Rip City Surf Soccer Club"),
    ("FL", "exact", "Miramar Optimist Club", "Miramar Optimist"),
    ("FL", "exact", "Kings Hammer SWAN City", "Kings Hammer Swan City Soccer Club"),
    # A legal suffix is not a spelling of the club's name, so the clean form is canonical
    # even where the suffixed one is the majority.
    ("FL", "exact", "FC Sarasota Inc", "FC Sarasota"),
    ("FL", "exact", "AC Delray, Inc.", "AC Delray"),
    ("FL", "exact", "Pinellas County United", "Pinellas County United SC"),
    ("FL", "exact", "Futbol Beach Soccer Futsal (FBS-FC)", "Futbol Beach Soccer Futsal Club"),
    ("FL", "exact", "Sporting Gainesville (GNV)", "Sporting Gainesville Soccer Academy"),
    ("FL", "exact", "Ancient City Soccer", "Ancient City SC"),
    ("FL", "exact", "INTER MIAMI", "Inter Miami CF"),
    ("FL", "exact", "North Manatee SC", "North Manatee Soccer"),
    ("FL", "exact", "Stetson Futbol Association", "Stetson FA"),
    ("FL", "exact", "Team Boca Soccer", "Team Boca SC"),
    ("FL", "exact", "Img Academy", "IMG Academy"),
    ("FL", "exact", "IMG Soccer Academy", "IMG Academy"),
    ("FL", "exact", "Miami Shores Futbol Club", "Miami Shores Soccer Club"),
    ("FL", "exact", "Indialantic Youth Soccer Assn", "Indialantic Youth Soccer Association"),
    ("FL", "exact", "Indialantic YSA", "Indialantic Youth Soccer Association"),
    ("FL", "exact", "Sporting Tallahassee (TLH)", "Sporting Tallahassee Soccer Academy"),
    ("FL", "exact", "United Soccer Academy", "United Soccer Alliance"),
    ("FL", "exact", "Jupiter United Soccer Club", "Jupiter United Soccer"),
    ("FL", "exact", "Players Club of Tampa Bay (PCTB)", "Players Club of Tampa Bay"),
    ("FL", "exact", "Winter Haven Youth Soccer  (WHYSA)", "Winter Haven SC"),
    ("FL", "exact", "Kings Hammer Bay United (KHBU)", "Kings Hammer Bay United Soccer Club"),
    ("FL", "exact", "Forge FC, Inc.", "Forge FC"),
    ("FL", "exact", "Nature Coast Soccer Club, Inc.", "Nature Coast SC"),
    ("FL", "norm", "Nature Coast SC", "Nature Coast SC"),
    ("FL", "exact", "Elite Soccer Academy", "Elite Soccer Academy (FL)"),
    ("FL", "exact", "BOLD & Gold Sports International", "Bold and Gold Sports International"),
    ("FL", "exact", "San Carlos Park Scorpions Soccer", "San Carlos Park Scorpion SC"),
    ("FL", "exact", "South Kendall Sunblazer Soccer Club, Inc.", "South Kendall Sunblazer Soccer Club"),
    ("FL", "exact", "Florida United SC", "Florida United"),
    ("FL", "exact", "Impact City FC (South Florida)", "Impact City FC"),
    ("FL", "exact", "Immokalee Soccer Pit Cobras Inc", "Immokalee Soccer PIT Cobras"),
    # Both spellings field "CSMYS ... Magic" teams.
    ("FL", "exact", "Manatee Area YSO", "Manatee Area YSA"),
    ("FL", "exact", "Columbia Youth Soccer Assn (CYSA)", "Columbia Youth Soccer Association"),
    ("FL", "exact", "Central Academy Youth SA   (CAYSA)", "Central Academy Youth Soccer Association"),
    ("FL", "norm", "St. Andrews Soccer Club", "St. Andrews Soccer Club"),
    ("FL", "exact", "Englewood Youth Soccer Assn", "Englewood Youth Soccer Association"),
    ("FL", "exact", "Sarasota Spartans SC", "Sarasota Spartans"),
    ("FL", "exact", "LASE Youth SC", "LASE INC"),
    ("FL", "exact", "Rural Youth Soccer Association", "Rural YSA"),
    ("FL", "exact", "South Tampa Gold FC", "South Tampa Gold"),
    ("FL", "exact", "Eagle Creek SA", "Eagle Creek Soccer Academy"),
    # Both spellings field a "RIO SECO FC U10" team.
    ("FL", "exact", "International Soccer Club", "International Soccer Association"),
    ("FL", "exact", "International Soccer Assn (ISA)", "International Soccer Association"),
    ("FL", "norm", "MY Soccer Academy", "MY Soccer Academy"),
    ("FL", "exact", "AYSO REGION 660 - KEY WEST", "AYSO Region 660 - Key West Soccer"),
    ("FL", "exact", "Citrus United Soccer", "Citrus United SC"),
    # Both spellings field a "First Coast Breeze FC" team.
    ("FL", "exact", "USSSA Soccer", "USSSA"),
    ("FL", "norm", "Dr. Phillips Soccer Club", "Dr. Phillips Soccer Club"),
    ("FL", "exact", "FORT MYERS BEACH SC", "Fort Myers Beach Soccer"),
    ("FL", "exact", "WILD ABOUT SPORTS ACADEMY (WASA)", "Wild About Sports Academy"),
    ("FL", "exact", "Wild About Sports Academy LLC", "Wild About Sports Academy"),
    ("FL", "exact", "Seminole Shooting Stars", "Seminole Shooting Stars SA"),
    ("FL", "exact", "Orlando lions", "Orlando Lions Academy FC"),
    ("FL", "exact", "Coral Springs SC", "Coral Springs Soccer Academy"),
    # Read off the club list by eye. No fold reaches a misspelling, a partner brand
    # joined by a slash, a place or "USA" appended, or an apostrophe that splits the
    # name into extra tokens.
    ("FL", "exact", "Azzuri Storm", "Azzurri Storm"),
    ("FL", "exact", "Azzurri Storm Soccer, Inc.", "Azzurri Storm"),
    ("FL", "exact", "B1 Soccer Academy", "B1 Soccer Academy USA"),
    ("FL", "exact", "Boynton Knights FC", "Boynton Beach Knights"),
    ("FL", "exact", "Brevard Beachside Soccer Club Inc", "Brevard Beachside Impact SC"),
    ("FL", "exact", "Clay County SC United Soccer Alliance", "Clay County SC"),
    ("FL", "exact", "COLO COLO Soccer Academy", "Colo Colo Soccer Academy USA"),
    ("FL", "exact", "Coral Estates SC    (CESC)", "Coral Estates S.C."),
    ("FL", "exact", "Coral Springs Soccer Academy & Futsal", "Coral Springs Soccer Academy"),
    ("FL", "exact", "Coral Springs Soccer/Futsal Academy", "Coral Springs Soccer Academy"),
    ("FL", "exact", "DME Academy", "DME Academy Sarasota"),
    ("FL", "exact", "FC Prime Miami", "FC Prime"),
    ("FL", "exact", "FORT LAUDERDALE FC (FLFC)", "Fort Lauderdale Select FC"),
    ("FL", "exact", "GOLDEN GOAL SPORTS", "GGS Soccer Academy"),
    ("FL", "exact", "GREATER BOCA YSA / BOCA UNITED", "Greater Boca YSA"),
    ("FL", "exact", "Hunters Creek Soccer Club", "Hunter's Creek SC"),
    ("FL", "exact", "Iconz Experience Elite", "Iconz Experience"),
    # A second pass read off the club list. "SS" is Orlando City's own abbreviation for
    # Soccer School, and those rows are branches of it rather than of the undecided
    # Orlando City group below.
    ("FL", "exact", "Impact City FC - FL", "Impact City FC"),
    ("FL", "exact", "IVES Estate Thunder Soccer", "Ives Estate"),
    ("FL", "exact", "Miami AC", "Miami Athletic Club"),
    ("FL", "exact", "MILAN OF MIAMI F.C INC", "Milan DE Miami FC"),
    ("FL", "exact", "One FC Miami", "One FC"),
    ("FL", "exact", "Orlando City SS Hunters Creek", "Orlando City Soccer School Hunters Creek"),
    ("FL", "exact", "ORLANDO CITY SS LAKE NONA", "Orlando City Soccer School Lake Nona"),
    ("FL", "exact", "Orlando Soccer School Lake Nona", "Orlando City Soccer School Lake Nona"),
    ("FL", "exact", "Orlando City Soccer School Lk Nona", "Orlando City Soccer School Lake Nona"),
    ("FL", "exact", "PORT SAINT JOHN UNITED", "Port St. John SC"),
    ("FL", "exact", "Paris Saint Germain (PSG)", "Paris Saint Germain Academy Orlando"),
    ("FL", "exact", "Pensacola Futbol Club", "Pensacola FC Rush"),
    ("FL", "exact", "RONALDO ACADEMY TAMPA BAY", "Ronaldo Academy Tampa Bay"),
    ("FL", "exact", "Ronaldo Academy Tampa - R9", "Ronaldo Academy Tampa Bay"),
    ("FL", "exact", "Soccer Paradise F.C.", "Soccer Paradise"),
    ("FL", "exact", "Soccer Paradise SPFC 2010", "Soccer Paradise"),
    ("FL", "exact", "SOL SPORTS CLUB (SOL SC)", "Sol SC Florida"),
    # Left apart deliberately:
    #   Miami FC Academy is The Miami FC, the USL club -- its teams read "MFC", "USLC",
    #   "USL1" -- not Miami Athletic Club. The rest of that group is undecided.
    #   Orlando City Soccer Club fields "OCSS South" teams against Orlando City Youth
    #   Soccer's "Orlando City Youth SC"; whether OCSS is the same body is undecided.
    #   St. John's Football Club reads "SJFC" and St. John's Soccer Club names only
    #   itself, so there is no evidence either way.
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
    ("GA", "exact", "Concorde Fire Soccer Club", "Concorde Fire"),
    ("GA", "exact", "NASA Tophat (NTH)", "NASA Tophat"),
    ("GA", "exact", "UFA", "United Futbol Academy"),
    ("GA", "exact", "United Football Academy", "United Futbol Academy"),
    ("GA", "norm", "Gwinnett Soccer Academy", "Gwinnett Soccer Academy"),
    ("GA", "exact", "Atlanta Fire United SA", "Atlanta Fire United"),
    ("GA", "exact", "Rush Union", "Rush Union Soccer"),
    ("GA", "exact", "Lanier", "Lanier Soccer Association"),
    ("GA", "exact", "Athens United Soccer", "Athens United SA"),
    ("GA", "exact", "Georgia Impact", "Georgia Impact SC"),
    ("GA", "exact", "Triumph Youth Soccer Association", "Triumph Youth Soccer"),
    ("GA", "exact", "Georgia Storm SA", "Georgia Storm Soccer Academy"),
    ("GA", "norm", "Georgia Storm Soccer Academy", "Georgia Storm Soccer Academy"),
    ("GA", "norm", "North Georgia Soccer Academy", "North Georgia Soccer Academy"),
    ("GA", "exact", "Rapids FC (ga)", "Rapids FC"),
    ("GA", "exact", "Rapids Futbol Club", "Rapids FC"),
    ("GA", "exact", "Georgia Revolution", "Georgia Revolution FC"),
    ("GA", "exact", "Piedmont Soccer Academy", "Piedmont SA"),
    ("GA", "exact", "KSA", "Kalonji Soccer Academy"),
    ("GA", "exact", "Madison Area YSA (MAYSA)", "Madison Area Youth Soccer Association"),
    ("GA", "exact", "Georgia United Soccer Academy", "Georgia United SA"),
    ("GA", "norm", "Grow Soccer Evolution", "Grow Soccer Evolution"),
    ("GA", "exact", "Harris County Soccer Association", "Harris County Soccer Assn"),
    ("GA", "norm", "Decatur Dekalb YMCA Soccer Club", "Decatur Dekalb YMCA Soccer Club"),
    ("GA", "exact", "Decatur-Dekalb Ymca Soccer Club", "Decatur Dekalb YMCA Soccer Club"),
    ("GA", "exact", "ATL Xpress FC", "ATL Xpress"),
    ("GA", "exact", "Bryson Park Soccer Club", "Bryson Park"),
    ("GA", "exact", "Rayados Hazlehurst Soccer Academy", "Hazlehurst Rayados Soccer Academy"),
    ("GA", "exact", "SSA Cartersville (Rec)", "SSA Cartersville"),
    ("GA", "norm", "Vaders Elite Nation FC", "Vaders Elite Nation FC"),
    # A second pass read off the club list. "Georgia Storm Revolution" fields Georgia
    # Revolution FC teams, so the Storm prefix is an affiliate marker rather than the club.
    ("GA", "exact", "ALIANZA SOCCER CLUB", "Alianza Soccer Club"),
    ("GA", "exact", "Alliance Soccer Club", "Alliance SC"),
    ("GA", "exact", "Atlanta Furious Soccer Club", "Atlanta Furious"),
    ("GA", "exact", "Augusta Arsenal SC (ga)", "Augusta Arsenal SC"),
    ("GA", "exact", "Decatur DeKalb YSC   (DDYSC)", "Decatur Dekalb YMCA Soccer Club"),
    ("GA", "exact", "Georgia Storm Revolution", "Georgia Revolution FC"),
    ("GA", "exact", "GEORGIA WOLVES SC", "Georgia Wolves SC"),
    ("GA", "exact", "Grow Soccer Evolutions - 01", "Grow Soccer Evolution"),
    ("GA", "exact", "MACON SOCCER CLUB", "Macon Soccer Club"),
    ("GA", "exact", "Madison Area Ymca", "Madison Area Youth Soccer Association"),
    # "Select" is a programme label rather than the club: Savannah United already fields a
    # "Select 14b Blue" team, and Savannah United Select fields plain "Savannah United" ones.
    ("GA", "exact", "Richmond Hill Soccer Club", "Richmond Hill SC"),
    ("GA", "exact", "Savannah United Select", "Savannah United"),
    ("GA", "exact", "TASA FC/Thomas Area Soccer Assn", "Thomas Area Soccer Association"),
    ("GA", "exact", "Tophat Soccer Club", "NASA Tophat"),
    # Southern Soccer Academy keeps its branch rows apart -- Swarm, Swarm Marietta, Coastal,
    # Cartersville and Coweta each stay their own club, on the owner's call 2026-09-21. The
    # team names argue the other way: the parent fields "SSA Swarm ... Paulding" and "SSA
    # Swarm 11G Cartersville" squads, and SSA Coastal fields "SSA Swarm Coastal 17B", so the
    # places read as programmes. The convention that a branch is its own club decided it
    # anyway, as it did for Richmond Strikers South and NC Rush Central. About 156 teams.
    ("GA", "exact", "Tormenta FC Academy", "Tormenta FC"),
    # Left apart deliberately: Georgia Soccer Association is the state governing body,
    # not a club -- its teams are 'GA ODP' sides. Also Calhoun FC against FC Calhoun,
    # the Southern States tie, the 'Augusta Arsenal Soccer Club (SC)' row, and the two
    # Albion rows, which are one squad each with the team name written into the club field.
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
    # Redirected when "Cuyahoga Valley SA" itself folded away; both spellings are CVSA.
    ("OH", "exact", "Cuyahoga valley soccer aca", "Cuyahoga Valley Soccer Academy"),
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
    # Maryland
    # "DC" is a state code, so club_acronym drops it to "d" and the redundant-tag
    # fold never sees (DCSC) repeating the name. Named exactly instead.
    ("MD", "exact", "DC Soccer Club (DCSC)", "DC Soccer Club"),
    ("MD", "exact", "Lutherville Timonium SC (LTSC)", "Lutherville Timonium Soccer Club"),
    (
        "MD",
        "exact",
        "Greater Severna Park Athletic Association",
        "Greater Severna Park Athletic Assoc",
    ),
    ("MD", "exact", "Severna Park Soccer", "Greater Severna Park Athletic Assoc"),
    ("MD", "exact", "Towson United SC", "Towson United"),
    ("MD", "exact", "Catonsville Youth Soccer League", "Catonsville Soccer"),
    ("MD", "exact", "Broadneck SC (BAYS)", "Broadneck Soccer Club"),
    ("MD", "exact", "Baltimore Bays", "Baltimore Bays Soccer Club"),
    ("MD", "exact", "A3 Soccer Club", "A3 Soccer"),
    # Future FC already fields five "Future Monarchs" teams of its own, so the four rows
    # under "Future Soccer Club" are the same club's Monarchs squads, not a second club.
    ("MD", "exact", "Future Soccer Club", "Future FC"),
    # CCSC is Central Carroll's own tag -- its teams read "CCSC B2016/17 Lightning
    # Yellow", and the neighbouring North Carroll Soccer Club writes NCSC.
    ("MD", "exact", "CCSC", "Central Carroll Soccer Club"),
    # All 27 rows read "Westminster United ..." in their team names. WSA is an all-caps
    # acronym rather than a spelling of the name, so the one-team full form is canonical.
    ("MD", "exact", "WSA", "Westminster Soccer Association"),
    ("MD", "exact", "Davidsonville Athletic Assn", "Davidsonville Football Club"),
    ("MD", "exact", "Cecil FC", "Cecil Soccer League"),
    ("MD", "exact", "CECIL SOCCER", "Cecil Soccer League"),
    # All four rows read "... Youth Academy ..." in their team names.
    ("MD", "exact", "Maryland Bobcats FC", "Maryland Bobcats Youth Academy"),
    ("MD", "exact", "Harundale Youth Soccer", "Harundale Youth Sports League"),
    # Legal suffix, so the clean form is canonical even at 13 teams against 1.
    ("MD", "exact", "Mount Washington Soccer Club, Inc.", "Mount Washington SC"),
    # The acronym in every one of these teams' names is PPA, never TPPA, so the article
    # is not part of the club's name -- canonical against a 40-to-8 majority.
    ("MD", "exact", "The Player Progression Academy", "Player Progression Academy"),
    ("MD", "norm", "Player Progression Academy", "Player Progression Academy"),
    (
        "MD",
        "exact",
        "Liverpool FCIA Maryland",
        "Liverpool FC International Academy Maryland",
    ),
    ("MD", "exact", "Liverpool FC IA", "Liverpool FC International Academy Maryland"),
    ("MD", "exact", "Harford Football Club (HFC United)", "Harford FC United"),
    (
        "MD",
        "exact",
        "Olney Boys/Girls Sports Assn (OBGC)",
        "Olney Boys and Girls Club Community Sports Association",
    ),
    ("MD", "exact", "Achilles FC U16", "Achilles FC"),
    (
        "MD",
        "exact",
        "Jr. Eagles (FSK)- Tournament Team",
        "Francis Scott Key Jr Eagles Soccer Club",
    ),
    ("MD", "exact", "Independent - Maryland", "MD Independent"),
    # Soccer Association of Columbia and Baltimore Armour are two brands in one
    # partnership, and their own team names separate them cleanly: all 109 rows under
    # "SAC/BA" read "SAC Boys U10 - Pre-MLS NEXT", and all 12 under "Baltimore Armour/SAC"
    # read "BA 2017" or "2009 GA" or "2010 Aspire" and never SAC. The SAC canonical is a
    # clean name no row holds, because every live spelling either abbreviates the club
    # away or carries the partner brand.
    ("MD", "exact", "SAC/BA", "Soccer Association of Columbia"),
    ("MD", "exact", "SA of Columbia", "Soccer Association of Columbia"),
    ("MD", "exact", "Soccer Assn Of Columbia(SAC United)", "Soccer Association of Columbia"),
    ("MD", "exact", "Baltimore Armour/SAC", "Baltimore Armour"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Silver Spring FC fields "Sky Blue" and "Sapphire"; Silver Spring Soccer Club
    #     writes SSSC and fields "Sharks" and "Spirit". Two clubs, two acronyms.
    #   Ellicott City Soccer Club's teams read "CiTY 2016 Boys Yellow"; FC Ellicott City
    #     names itself in full on every team.
    #   BUSA Frederick is a place appended to the club's own name, which is the shape of
    #     a branch; its teams read "BUSA Frederick Boys 15/16".
    #   BRAUSA (Brausa United Futebol Club) and BUSA (Brazilian United Soccer Academy)
    #     are different acronyms on different teams.
    #   "Bethesda SC - Hagerstown" fields "BSC-H U15 Academy I" -- a branch, not a spelling.
    #   Towsontowne Soccer is not Towson United, and South Bowie is not Bowie.
    #   "Maryland Independent M.U.S.C." and "Arundel FC" are open questions, not holds:
    #     MUSC's three teams read "Maryland United S.C 2011" against Maryland United FC's
    #     own "Maryland United FC ..." spelling, and Arundel FC's only team is named "U16".
    # Indiana
    ("IN", "exact", "Indy Premier", "Indy Premier SC"),
    # Its three teams read "Premier GA U14" -- the club name was split at its own space,
    # leaving the first word as the club and the rest as the team.
    ("IN", "exact", "Indy", "Indy Premier SC"),
    # Ten rows whose club field holds the team's own label. Aspire and Inspire are Girls
    # Academy tiers rather than branches, so they belong to the club like the rest.
    ("IN", "regex", r"^Indy Premier (U\d{1,2}[BG]|Fall HS|Aspire|Inspire)\b", "Indy Premier SC"),
    ("IN", "exact", "Indy Eleven", "Indy Eleven Academy"),
    # All 19 rows read "Zionsville Youth Soccer Association - ...", two of them ending
    # "- Union FC Ind". ZYSA is this club's former name and holds no club value of its own.
    ("IN", "norm", "Union FC Indy", "Union FC Indy"),
    ("IN", "exact", "Westside United", "Westside United FC"),
    ("IN", "exact", "Columbus Express Soccer Club", "Columbus Express"),
    # Every one of the 100 teams reads USAI. The all-caps acronym is not a spelling of
    # the club's name, so the full form is canonical even at 26 rows against 73.
    ("IN", "exact", "USAI", "United Soccer Alliance of Indiana"),
    ("IN", "exact", "USA of Indiana", "United Soccer Alliance of Indiana"),
    ("IN", "norm", "Elkhart County United", "Elkhart County United"),
    ("IN", "norm", "Bloomington Football Club", "Bloomington Football Club"),
    ("IN", "exact", "Delaware County FC   (DCFC)", "Delaware County Futbol Club"),
    ("IN", "exact", "Millennium SA", "Millennium Soccer Association"),
    ("IN", "exact", "Millenium Soccer Association", "Millennium Soccer Association"),
    ("IN", "norm", "Circle City FC", "Circle City FC"),
    ("IN", "exact", "Komets FC", "Komets Soccer Club"),
    ("IN", "exact", "Southern Indiana FC", "Southern Indiana FC Youth Academy"),
    ("IN", "norm", "Blue River SA", "Blue River SA"),
    # Both spellings field German-named teams -- "FWSC U15G Koln", "FWSC 2009B
    # Osnabruck". Fort Wayne United FC is a different club and stays apart.
    ("IN", "exact", "Fort Wayne SC (FWSC)", "Fort Wayne Sport Club"),
    ("IN", "exact", "Hoosier Premier U16", "Hoosier Premier"),
    # Warsaw Travel SC already fields "Warsaw Wave Rapids", "Wave Storm" and "Wave Crush",
    # so "the Wave" in the club name is its own programme rather than a second club.
    ("IN", "exact", "Warsaw Travel Soccer - the Wave", "Warsaw Travel SC"),
    ("IN", "exact", "South Central Soccer Academy", "South Central Soccer Academy Eleven"),
    # One spelling is the bare acronym and the other repeats it after the full name, so
    # the canonical is a clean form neither row holds.
    ("IN", "exact", "SWISA", "Southwest Indiana SA"),
    ("IN", "exact", "Southwest Indiana SA -  SWISA", "Southwest Indiana SA"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Indy Eleven North and Indy Eleven Spirit name themselves on every team; both are
    #     branches, and a branch is its own club.
    #   FC Midwest Academy Kendallville is a place appended to the club's own name.
    #   Fort Wayne United FC fields "CFC U15 Boys" and "FWU U19 Boys NAL", never FWSC.
    #   Southern Indiana United writes SIU; Southern Indiana FC writes its name in full.
    #   Hoosier Premier's teams are all "U16 HD"/"U18 AD"; Hoosier Futbol Club's read
    #     "Hoosier FC". Different acronyms, different competitions.
    #   Michiana Echo Soccer Club is not Michiana Soccer Association.
    # Three open questions, not holds: "Northern Indiana FC" and "Northern Indiana
    # Express" both field NIE teams that Elkhart County United also fields; "NIFC
    # Academy" holds teams of at least three clubs; and "NORTHWOOD SC Pumas" is a team
    # name in the club field whose own two teams are named "Colorado United 2012b Gold".
    # Alabama
    ("AL", "exact", "Alabama Rush Soccer", "Alabama Rush"),
    ("AL", "norm", "Hoover-Vestavia Soccer", "Hoover-Vestavia Soccer"),
    ("AL", "exact", "Tuscaloosa United SC (tusc)", "Tuscaloosa United Soccer Club"),
    ("AL", "norm", "Phoenix FC AL", "Phoenix FC AL"),
    ("AL", "exact", "Phoenix FC 2014-15B Black", "Phoenix FC AL"),
    ("AL", "exact", "Phoenix FC Boys HS Showcase", "Phoenix FC AL"),
    # The state tag stays here, unlike the Texas "Strikers FC" case: AYSO United is a
    # national franchise whose state is part of which club this is, and Utah already
    # holds a separate AYSO United of its own.
    ("AL", "norm", "AYSO United (Alabama)", "AYSO United (Alabama)"),
    ("AL", "exact", "Madison Blaze", "Madison Blaze Soccer Club"),
    # Eleven of the twelve "Prattville United SC" rows carry a team named "Prattville
    # United FC", and the five FC rows read PUFC, so the minority spelling is the club's.
    ("AL", "exact", "Prattville United SC", "Prattville United FC"),
    ("AL", "norm", "Gardendale SC", "Gardendale SC"),
    ("AL", "exact", "Alexander City Youth/Club Soccer", "Alexander City Club Soccer"),
    ("AL", "exact", "Decatur City FC", "Decatur City Fútbol Club"),
    # All three of its teams are named "Decatur City FC 09 Boys" and the like, and no
    # other row in the state names River City.
    ("AL", "exact", "River City United SC", "Decatur City Fútbol Club"),
    ("AL", "exact", "Marshall  United Futbol Club", "Marshall United FC"),
    ("AL", "norm", "Club Independent", "Club Independent"),
    ("AL", "exact", "Enterprise United", "Enterprise United SC"),
    # "Asso" is a truncation rather than an abbreviation anyone writes, so the canonical
    # is the full form even though it is the spelling with the most teams behind it.
    ("AL", "exact", "Springville Youth Soccer Asso", "Springville Youth Soccer Association"),
    ("AL", "exact", "Springville Youth Soccer Assn", "Springville Youth Soccer Association"),
    ("AL", "exact", "Springville Youth Soccer", "Springville Youth Soccer Association"),
    ("AL", "norm", "Birmingham United SA", "Birmingham United SA"),
    ("AL", "norm", "Enterprise Select SC", "Enterprise Select SC"),
    ("AL", "exact", "Enterprise Select", "Enterprise Select SC"),
    ("AL", "exact", "Huntsville City FC", "Huntsville City FC Academy"),
    ("AL", "exact", "Rebano Chivas Alabama", "Rebaño Chivas Alabama"),
    ("AL", "exact", "Moody Soccer Club", "Moody Youth Soccer Club"),
    ("AL", "norm", "Moody Youth Soccer Club", "Moody Youth Soccer Club"),
    # Six rows whose club field is the team's own label, character for character. The
    # pattern stops short of "Alabama FC South", "Alabama FC Huntsville" and the five
    # rows carrying a North or South marker, which are branch questions still open.
    ("AL", "regex", r"^Alabama FC (ECNL|N1 Boys|Red [12]$|U12 Pre-ENCL)", "Alabama FC"),
    # AFCHSV-USC spells out the club; its teams read "AFC HSV 2013 Boys Black". The bare
    # "AFC ..." rows are left alone because AFC is also Alabama FC's acronym.
    ("AL", "regex", r"^(AFCHSV[ -]|AFC Huntsville Premier$)", "AFCHSV/United SC"),
    ("AL", "exact", "Cottontown United 2015", "Cottontown United Soccer Club"),
    ("AL", "exact", "K Cottontown United 13/14 Boys", "Cottontown United Soccer Club"),
    ("AL", "exact", "Athletic SC AL 2015/16 Boys Premier", "Athletic SC Alabama"),
    ("AL", "exact", "Athletic SC AL 2016/17 Boys Academy Elite", "Athletic SC Alabama"),
    ("AL", "exact", "Athletic SC Alabama N1 Boys 2012/2013 Premier", "Athletic SC Alabama"),
    # Each spelling holds teams named the other way -- "NOW SWARM FC N1 Boys" sits under
    # NOW FC and "NOW FC 2012" under NOW Swarm FC -- so they are one club.
    ("AL", "exact", "NOW Swarm FC", "NOW FC"),
    ("AL", "exact", "NOW SWARM FC U12 White", "NOW FC"),
    ("AL", "norm", "North Star Soccer Club", "North Star Soccer Club"),
    ("AL", "exact", "Total Futbol Club - Alabama", "Total Futbol Club"),
    (
        "AL",
        "exact",
        "Smiths Station United SA / SUFC",
        "Smiths Station United Soccer Association",
    ),
    ("AL", "exact", "CLUB AMERICA NIDO AGUILA", "Nido Aguila"),
    # BAH is Barca Academy Hoover, which already fields "Bah U10b Daurat" and
    # "Bah U12b Grana" under its own name.
    ("AL", "exact", "Bah U10b Blau", "Barca Academy - Hoover"),
    ("AL", "exact", "Bah U11b Blau", "Barca Academy - Hoover"),
    ("AL", "exact", "VERO FC", "Vero FC"),
    ("AL", "exact", "VERO FC NASC SCCL B2014/15 Premier", "Vero FC"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Prattville Elite FC writes PEFC, not PUFC.
    #   Decatur Soccer fields "Decatur Soccer PDP" teams and is not Decatur City FC.
    #   Opelika Crush SC is not Opelika Soccer Asso.
    #   Alabama FC South and Fultondale SC ("busa fultondale 2011") are branches.
    #   Phoenix Football Club's one team reads "Phoenix FC 2013/2014 Boys", but Maryland
    #     holds a real 17-team club of that name, so an exact rule on the string would
    #     reach stateless teams elsewhere. Left for a decision.
    # Five open questions, not holds: what Vero FC is (its 95 teams name NASC, Athletic
    # SC Alabama and Shoals SC, and Cullman United fields "CUSC Vero FC 2012B Elite");
    # whether the six North/South/Huntsville "Alabama FC" rows belong to the parent or a
    # branch; which club the five bare "AFC ..." rows are; and whether Club Independent,
    # every one of whose teams reads "Hampton Cove SC", should be renamed to it.
    # New Hampshire
    ("NH", "exact", "Seacoast United SC", "Seacoast United"),
    # Thirty-eight of these forty-two teams are named "Seacoast United Bedford ...", and
    # the club value they name already exists. Massachusetts maps the same spelling to
    # "Seacoast United Massachusetts", which is that state's Seacoast programme; here the
    # MA teams sit under "Seacoast United (MA)" instead and are left alone.
    ("NH", "exact", "Seacoast of Bedford", "Seacoast United Bedford"),
    ("NH", "exact", "Become Elite Soccer SC", "Become Elite Soccer"),
    ("NH", "exact", "Nashua Youth SL   (NYSL)", "Nashua Youth Soccer League"),
    ("NH", "norm", "Windham Soccer Association", "Windham Soccer Association"),
    (
        "NH",
        "exact",
        "Exeter Youth Soccer Assn",
        "Exeter Youth Soccer Association - FC Exeter",
    ),
    ("NH", "exact", "Oyster River Youth Soccer Assn", "Oyster River United"),
    # The 36 rows already under "FC Stars" are almost all "FC Stars New Hampshire" teams,
    # so this state's branch is filed there; Illinois keeps its own "FC Stars (il)".
    ("NH", "exact", "FC Stars NH", "FC Stars"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Manchester Lightning is not Lightning SC, whose teams read "Lightning Soccer Club".
    #   Team Exeter fields "TEAM EXETER BULLDOGS"; Exeter YSA fields "FC Exeter".
    #   Fieldhouse Sports fields "Ballers FC"; The Fieldhouse at Homestead Mills fields FAC.
    #   Bedford Athletic Club writes "BAC Bulldogs" and is not Seacoast's Bedford branch.
    #   "Seacoast United (MA)" is that branch's own name; its teams sitting on New
    #     Hampshire states is a state question, not a naming one.
    # More Wisconsin
    ("WI", "exact", "Milwaukee Kickers SC (MKSC)", "Milwaukee Kickers Soccer Club"),
    # Its teams are the same mix the parent holds -- "MKSC Union", "AC Toros",
    # "Milwaukee Kickers 07G DPL" -- so Academy is a tier here, not a branch.
    ("WI", "exact", "Milwaukee Kickers Academy", "Milwaukee Kickers Soccer Club"),
    ("WI", "exact", "Milwaukee Kickers - Tosa", "Milwaukee Kickers Soccer Club - Tosa"),
    (
        "WI",
        "exact",
        "Milwaukee Kickers - Mukwonago",
        "Milwaukee Kickers Soccer Club - Mukwonago",
    ),
    ("WI", "exact", "North Shore United", "North Shore United Soccer Club"),
    ("WI", "exact", "Germantown Soccer Club - NSU", "North Shore United Soccer Club"),
    ("WI", "exact", "Madison 56ers Soccer Club", "Madison 56ers"),
    ("WI", "exact", "Croatian Eagles", "Croatian Eagles SC"),
    # The acronym on both sides is BUSC, and one of the 59 short-form rows is a team
    # literally named "SC" -- the club name was split at its last word. So the minority
    # spelling is the club's own, even at 44 rows against 59.
    ("WI", "exact", "Bavarian United", "Bavarian United SC"),
    ("WI", "norm", "Lakeshore United FC", "Lakeshore United FC"),
    ("WI", "exact", "Lakeshore United 14U Navy Boys", "Lakeshore United FC"),
    ("WI", "exact", "RUSH Wisconsin Soccer Club", "RUSH Wisconsin"),
    ("WI", "exact", "Rush WI", "RUSH Wisconsin"),
    ("WI", "norm", "RUSH Wisconsin West", "RUSH Wisconsin West"),
    ("WI", "exact", "RUSH WI West", "RUSH Wisconsin West"),
    ("WI", "exact", "Rush Union WI", "Rush Union Wisconsin"),
    ("WI", "exact", "Rock Soccer Club", "Rock SC Rush"),
    ("WI", "norm", "Capital East SC", "Capital East SC"),
    ("WI", "exact", "Forward Madison FC Youth", "Forward Madison FC"),
    ("WI", "exact", "Forward Madison", "Forward Madison FC"),
    ("WI", "exact", "Let Kids Fly (lkf - Hawk Soccer)", "Let Kids Fly"),
    ("WI", "exact", "Fond Du Lac SA", "Fond du Lac Soccer Association"),
    ("WI", "exact", "Street Dreams", "Street Dreams Soccer Academy"),
    ("WI", "norm", "Portage County Youth Soccer", "Portage County Youth Soccer"),
    ("WI", "exact", "Eau Claire United  (ECU)", "Eau Claire United Soccer Club"),
    ("WI", "exact", "Oshkosh United", "Oshkosh United Soccer Club"),
    ("WI", "exact", "Delavan Soccer Club (DYSC)", "Delavan Youth Soccer Club"),
    ("WI", "exact", "Green Bay Lightning Soccer Club", "Green Bay Lightning"),
    ("WI", "exact", "Fox Cities United Soccer Club", "Fox Cities United"),
    ("WI", "exact", "Monona Grove FC", "Monona Grove Soccer Club"),
    ("WI", "exact", "Monona Grove SC   (MGSC)", "Monona Grove Soccer Club"),
    ("WI", "exact", "Mount Horeb SC", "Mount Horeb Youth Soccer Club"),
    ("WI", "norm", "Freedom Futbol Club", "Freedom Futbol Club"),
    ("WI", "exact", "Elmbrook United-brookfield/elm Grov", "Elmbrook United"),
    ("WI", "exact", "WI United FC", "Wisconsin United FC"),
    # All twelve of its teams are named "AFC Union ...", which is the club Racine's
    # association now plays as.
    ("WI", "exact", "Racine Area Soccer Association", "AFC Union"),
    # "No Club Selection" is deliberately not an entry, although Wisconsin's four
    # teams under it do all read "FC WISCONSIN - ..." and were moved by team id.
    # It is a provider placeholder rather than a club -- 1,594 teams carry it
    # nationally and 1,349 of those have no state -- so an entry here would have
    # renamed every stateless one to FC Wisconsin through analyze_no_state_teams,
    # pooling unrelated teams under a real club. src/utils/placeholder_clubs.py
    # holds the full set and tests/unit/test_placeholder_clubs.py guards it.
    ("WI", "exact", "East Troy SC", "East Troy SC 43"),
    ("WI", "exact", "Sauk Prairie SC", "Sauk Prairie Strikers"),
    (
        "WI",
        "exact",
        "New Richmond Soccer Club",
        "New Richmond Area Youth Soccer Association",
    ),
    # "- WYSA Direct Registration" is how the state association's own registration path
    # writes a club, not part of any club's name. Two of these rejoin a spelling that
    # already exists; the rest simply lose the suffix.
    ("WI", "exact", "Hartford Soccer Club - WYSA Direct Registration", "Hartford Soccer Club"),
    ("WI", "exact", "Freedom Futbol Club - WYSA Direct Registration", "Freedom Futbol Club"),
    (
        "WI",
        "exact",
        "Cuernavaca Wisconsin United - WYSA Direct Registration",
        "Cuernavaca Wisconsin United",
    ),
    ("WI", "exact", "Tigritos - WYSA Direct Registration", "Tigritos"),
    ("WI", "exact", "Blue Stars FC - WYSA Direct Registration", "Blue Stars FC"),
    ("WI", "exact", "FC Al-Quds - WYSA Direct Registration", "FC Al-Quds"),
    ("WI", "exact", "Jackson Soccer Club - WYSA Direct Registration", "Jackson Soccer Club"),
    ("WI", "exact", "Richfield Soccer - WYSA Direct Registration", "Richfield Soccer"),
    ("WI", "exact", "Deportivo Silao - WYSA Direct Registration", "Deportivo Silao"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Hartford United SC writes HUSC; Hartford Soccer Club writes HSC.
    #   Portage Youth Soccer Association is a different town from Portage County.
    #   SC Wave's Titletown, New Berlin and Washington County rows are branches, as are
    #     RUSH WI Southeast and "Milwaukee Kickers - South", which has no counterpart.
    #   AC Toros is a Milwaukee Kickers member club that names itself on every team.
    #   Racine Storm is not Racine Area SA, and MKE United FC is not Milwaukee Kickers.
    # Six open questions, not holds: "Plymouth" holds five "Reign SC ECNL RL" teams and
    # no Reign SC value exists; "Hudson SA/Western WI Soccer/FC" splits two ways; SAYSA's
    # one team is a Loudoun (VA) side; the four Legacy values carry no acronym to read;
    # "Watertown Youth Soccer Assn" holds one "WYSA U16 Boys (SD)" team; and
    # "FC Milwaukee Torrent" against "FC Milwaukee Torrent Wales Soccer" is the
    # partner-brand shape. "Georgia Storm Lake Country United FC" sits here too and is
    # already on Georgia's open list.
    # Oklahoma
    ("OK", "exact", "West Side Alliance (WSA)", "West Side Alliance SC"),
    ("OK", "norm", "Oklahoma Energy FC", "Oklahoma Energy FC"),
    ("OK", "exact", "Broken Arrow SC    (BASC)", "Broken Arrow Soccer Club"),
    ("OK", "exact", "Edmond Soccer Club (esc)", "Edmond SC"),
    ("OK", "exact", "Broken Arrow Express SC", "Broken Arrow Express"),
    ("OK", "exact", "Midwest City Soccer Club  (MWCSC)", "Midwest City SC"),
    # One club, per the owner on 2026-09-22. 109 of the 110 teams filed under "South
    # Lakes SC" are named "Oklahoma Cosmos ...", so that spelling is canonical for all
    # 157 even though it holds fewer rows. The norm form also carries the "(SLSC)"
    # tagged spelling. Southlake Soccer stays apart: none of its 16 teams reads Cosmos.
    ("OK", "norm", "South Lakes SC", "Oklahoma Cosmos"),
    ("OK", "norm", "Stillwater SC", "Stillwater SC"),
    ("OK", "exact", "Union Tulsa FC", "Union FC Tulsa"),
    ("OK", "exact", "Unión Tulsa Blue Fc", "Union FC Tulsa"),
    ("OK", "exact", "OKC The 405 Futbol Club", "OKC 405 FC"),
    # Fifteen of Ponca City SA's eighteen teams are named "PC United".
    ("OK", "exact", "PC United", "Ponca City SA"),
    ("OK", "exact", "Weatherford Soccer Club Elite", "Weatherford SC"),
    ("OK", "exact", "North East Oklahoma FC (neofc)", "NE Oklahoma FC"),
    ("OK", "exact", "Sporting OK", "Sporting Oklahoma"),
    # Choctaw SA already fields "CNP ROGUE 12G" and "CNP ROGUE 11G", so Rogue is a team
    # line inside CNP rather than a club. The (CNP) tag stays because Choctaw SA's own
    # acronym is CSA -- CNP is Choctaw-Nicoma Park, which the tag is not repeating.
    ("OK", "exact", "Choctaw-Nicoma Park SA  (CNP)", "Choctaw SA (CNP)"),
    ("OK", "exact", "CNP Rogue", "Choctaw SA (CNP)"),
    # "FC1" is a stray digit rather than a spelling: all fifteen teams read "APEX FC".
    ("OK", "exact", "Apex FC1", "Apex FC"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Southlake Soccer fields "Southlake SIFC" and "Southlake Select"; South Lakes SC
    #     fields Oklahoma Cosmos. Two clubs whose names only look alike.
    #   Northwest Optimist SC writes NWO; Northwest Soccer Club fields "OKC Crew".
    #   Northeast Oklahoma Soccer Association writes NEOSA; NE Oklahoma FC writes NEOFC.
    #   Union SC is the Union school district's club, not Union FC Tulsa.
    # Seven open questions, not holds: whether South Lakes SC and Oklahoma Cosmos are one
    # club, since all 110 South Lakes teams are named "Oklahoma Cosmos ..."; whether APEX
    # FC is Stillwater SC's competitive brand, since Stillwater fields "APEX FC U14 Boys
    # Orange"; "Chisholm Trail SA (CTSA)", whose two teams are Loudoun (VA) sides;
    # "Metro Tulsa SC United (MTSC UNITED)", whose one team is "Nvsc Nvsc 2015b Gold";
    # Tahlequah Sports League against Tahlequah SC; "Test Club", which holds actual test
    # data; and "No Club Selection", a bucket naming at least four real clubs.
    # Colorado
    ("CO", "exact", "Colorado Rapids Youth SC (CRYSC)", "Colorado Rapids Youth Soccer Club"),
    (
        "CO",
        "exact",
        "Colorado Rapids Youth Soccer Club U14",
        "Colorado Rapids Youth Soccer Club",
    ),
    # The parent already files hundreds of "Rapids Central ..." and "Rapids South ..."
    # teams, so these are that club's sites rather than branches with their own identity.
    ("CO", "exact", "Colorado Rapids Central", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "Colorado Rapids South", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "Colorado Rapids Castle Rock", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "USYS Subscribers", "Colorado Rapids Youth Soccer Club"),
    ("CO", "exact", "Colorado EDGE (Arvada Soccer Assn)", "Colorado EDGE"),
    ("CO", "exact", "Skyline Soccer Assn (SSA)", "Skyline"),
    ("CO", "exact", "Pueblo Rangers", "Pueblo Rangers SC"),
    # Sixteen rows each way, so the tie goes to the spelling that names the club in full.
    ("CO", "exact", "Colorado Ignite", "Colorado Ignite SC"),
    ("CO", "exact", "Crestmoor Cranmer SC", "Crestmoor Cranmer"),
    ("CO", "exact", "Westy Soccer", "Westy Soccer Club"),
    ("CO", "exact", "Westminster Soccer", "Westy Soccer Club"),
    ("CO", "exact", "United Soccer Club", "United Soccer Club CO"),
    ("CO", "exact", "Telluride Youth SC", "Telluride YSA"),
    (
        "CO",
        "exact",
        "CISA Colorado International Soccer Academy",
        "Colorado International SA",
    ),
    ("CO", "exact", "Colorado Elevation FC", "CO Elevation FC"),
    # NOCO is Northern Colorado, and all three of these values hold Windsor Warriors AFC
    # teams; Colorado Lightning Soccer Academy fields "Colorado Lightning Girls" and is a
    # different club.
    ("CO", "exact", "NOCO Lightning Academy", "Northern Colorado Lightning Academy"),
    ("CO", "exact", "Windsor Warriors AFC", "Northern Colorado Lightning Academy"),
    ("CO", "exact", "Grand County Intermountain SC", "Grand County SC"),
    ("CO", "exact", "Roaring Fork United", "Roaring Fork Valley Soccer Club"),
    ("CO", "exact", "Flatirons FC", "Flatirons Rush"),
    ("CO", "exact", "Colorado Rush Mountain", "Mountain Rush"),
    ("CO", "exact", "Colorado Rush North", "North Denver Rush"),
    # One club, per the owner on 2026-09-22, so the state-tagged spellings fold into the
    # plain one rather than the other way round as Washington's BVB IA WA does.
    ("CO", "exact", "BVB International Academy CO", "BVB International Academy"),
    ("CO", "exact", "BVB International Academy Colorado", "BVB International Academy"),
    # Peak Football Club is Peak FC, per the owner on 2026-09-22, and "peak fc" already
    # resolves to Pikes Peak FC in this state two lines above.
    ("CO", "exact", "Peak Football Club", "Pikes Peak FC"),
    # Left apart deliberately: Albion SC Colorado, Denver and Boulder County are
    # branches, and so is each Rush affiliate -- COS, Northern Colorado, North Denver,
    # Flatirons, LFA, Mountain and Victory all name themselves on their own teams.
    # Two open questions, not holds: the bare "Rush" row, whose one team is "Rush U13G
    # Academy White ECNL-RL" and which eleven affiliates could claim; and "Grand Junction
    # Fire FC", one of whose two teams reads "Grand Junction SC 2012/13 United".
    # New Jersey
    ("NJ", "exact", "Berkeley Soccer Assn", "Berkeley Soccer Association"),
    ("NJ", "exact", "Bridgewater Soccer Association", "Bridgewater SA"),
    ("NJ", "exact", "Cape Express SC", "Cape Express"),
    ("NJ", "exact", "Chatham United", "Chatham United SA"),
    ("NJ", "exact", "Chatham United Soccer Assn", "Chatham United SA"),
    ("NJ", "norm", "Cherry Hill SC", "Cherry Hill SC"),
    # The partner-brand shape: both teams read "Deptford Premier FC", and the existing
    # "DEPTFORD SA" entry above already resolves that half of the name the same way.
    ("NJ", "exact", "Deptford SA / Deptford Premier FC", "Deptford Premier FC"),
    ("NJ", "exact", "East Brunswick Soccer Club", "East Brunswick"),
    ("NJ", "exact", "FC Berna", "FC Berna Legacy"),
    ("NJ", "exact", "Freehold Soccer Club", "Freehold SL"),
    # The owner grouped these two on 2026-09-22 without Hoboken United, so the tagged
    # spelling folds onto the plain one and Hoboken United stays its own club -- even
    # though the HCFC rows' teams read "Hoboken United-g12-gandhi".
    ("NJ", "exact", "Hoboken City Futbol Club    (HCFC)", "Hoboken City FC"),
    # All 35 teams read "Jackson SC ...". The majority spelling carries a malformed state
    # tag and the next a legal suffix, so the canonical is the clean form none of them holds.
    ("NJ", "exact", "Jackson SC(NJ)", "Jackson SC"),
    ("NJ", "exact", "Jackson Soccer Club", "Jackson SC"),
    ("NJ", "exact", "Jackson Soccer Club Inc", "Jackson SC"),
    ("NJ", "exact", "Montville Soccer Association", "Montville SA"),
    ("NJ", "exact", "Neptune SA", "Neptune Soccer Association"),
    ("NJ", "norm", "Northern Valley SC", "Northern Valley Soccer Club"),
    ("NJ", "norm", "Princeton FC", "Princeton FC"),
    ("NJ", "norm", "Real Futbol Academy", "Real Futbol Academy"),
    # Both of these are the same shape: a club's MLS NEXT sides filed under a shorter
    # spelling of its name, beside the main club. "The Football Academy" holds only
    # "U18 HD"/"U14 AD" rows, and "Tsf Academy" only "U17 AD"/"U19 HD" ones.
    ("NJ", "exact", "The Football Academy", "The Football Academy NJ"),
    ("NJ", "exact", "Tsf Academy", "TSF Academy - NJ"),
    ("NJ", "exact", "Voorhees", "Voorhees SA"),
    ("NJ", "exact", "Voorhees Soccer", "Voorhees SA"),
    ("NJ", "norm", "West Deptford SC", "West Deptford SC"),
    ("NJ", "exact", "WSA/Union County FC (UCFC)", "WSA"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   "Pro Soccer Academy LLC (NJ)" abbreviates to PSA and its two teams are named
    #     "PSA" and "PSA Select 2016", but PSA in this state is Princeton Soccer Academy
    #     -- its teams read "PSA Princeton", "PSA Monmouth" and "PSA North", and two
    #     entries above already resolve Princeton's spellings to it. Two clubs, one
    #     acronym, the same shape as Pinelands SA against PSA.
    #   Union Beach Soccer Club writes UB and fields Force, Storm and Hericanes; Union
    #     City Soccer Club writes "UnionCity-B17-Samaniego". Two boroughs, two acronyms.
    #   Pinelands SA fields "Pinelands SA Cobras"; PSA is Princeton. Harrison Futbol
    #     Club writes "Harrison FC Cosmos" against Harrison SC's "Harrison Hurricanes".
    #     Passaic FC fields "Passaic FC Academy"; Passaic Youth Soccer fields mascots.
    #     North Plainfield Soccer Elite writes NPSE, North Plainfield SC writes NPSC.
    #     FC Monmouth is not Monmouth United, which writes MUSC. Hamilton SC, Hamilton
    #     Elite FC and Hamilton United Elite SC are three clubs. "Bridgewater United
    #     Ajax" is not Bridgewater SA, and North Warren United writes NWU.
    #     Berkeley Heights Youth SC and Ridgefield Park SA are different towns from
    #     Berkeley Soccer Association and Ridgefield FC.
    # Left open on 2026-09-22 rather than folded: Delran Soccer Club, Franklin,
    # Freehold Soccer League, Mantua Township Soccer Assn, Montclair United SC, the
    # three PDA/Vistula spellings, Roxbury Travel Soccer Club, Sayreville Soccer Club,
    # the two Scotch Plains spellings, South Jersey Girls SL (SJGSL) and
    # Swedesboro-Woolwich SA; plus whether WSA should read Westfield SA, what Nesa,
    # FC Allstars, Glen Rock, Players SC and Peninsula City SC are, and whether the
    # 104 branch-named teams under Players Development Academy move to PDA Hibernian,
    # Blue (North), White (Shore) and South.
    # More Arkansas
    ("AR", "exact", "Arkansas Rising", "Arkansas Rising Soccer Club"),
    ("AR", "exact", "Sporting Arkansas SC", "Sporting Arkansas"),
    ("AR", "exact", "LITTLE ROCK RANGERS", "Little Rock Rangers Academy"),
    ("AR", "exact", "Central Arkansa SC", "Central Arkansas Soccer Club"),
    ("AR", "exact", "Central Arkansas SC (casc)", "Central Arkansas Soccer Club"),
    # The bare acronym is not a spelling of the club's name, so the two-team full form
    # is canonical -- the same call Maryland's WSA and Indiana's USAI took.
    ("AR", "exact", "AVSA", "Arkansas Valley Soccer Association"),
    ("AR", "exact", "Arkansas Valley SA (avsa)", "Arkansas Valley Soccer Association"),
    ("AR", "exact", "Greene County SA (gcsa)", "Greene County Soccer"),
    ("AR", "exact", "Bentonville Prodigy FC", "Bentonville FC Prodigy"),
    ("AR", "exact", "Bentonville FC", "Bentonville FC Prodigy"),
    ("AR", "exact", "Conway Soccer Club", "Conway Soccer"),
    ("AR", "exact", "Arkansas Legends", "Arkansas Legends SC"),
    # Its three teams read "AFC Benton 2012B Classic Blue" and the like. Arkansas Soccer
    # Club writes ASC and stays apart.
    ("AR", "exact", "Arkansas Football Club", "Arkansas Football Club Benton"),
    ("AR", "exact", "FC Horizon", "F.C. Horizon"),
    ("AR", "exact", "Searcy YSA / Searcy Rangers", "Searcy YSA"),
    # Left apart deliberately: Arkansas Soccer Club fields "ASC Edson" against the
    # Arkansas Football Club family's "AFC Benton", and NWA Dragons is not NWA Lightning.
    # Two open questions: "Prodigy Warriors", whose one team is "Prodigy Warriors 2012B";
    # and "No Club Selection", three of whose four teams read "Academia Tigres Arkansas"
    # while Tigres Academy already exists.
    # More Michigan
    ("MI", "exact", "Michigan Jaguars FC", "Michigan Jaguars"),
    ("MI", "norm", "Detroit City FC", "Detroit City FC"),
    # Both spellings field ENVY teams -- "ENVY FC 2013 White" and "ENVY 12B-Orange".
    ("MI", "exact", "Northville SA", "Northville FC"),
    ("MI", "exact", "Vardar Soccer Club (MI)", "Vardar Soccer"),
    ("MI", "exact", "Lakeshore Soccer Club", "Lakeshore Football Club"),
    ("MI", "exact", "Owosso Soccer Club", "Owosso"),
    # South Carolina resolves this pair the other way round, because there the club that
    # holds the teams is Mount Pleasant FC. Each entry is scoped to its own state.
    ("MI", "exact", "Mount Pleasant FC (MPFC)", "Mount Pleasant Soccer Club"),
    ("MI", "exact", "Michigan Stars FC", "Michigan Stars Elite SC"),
    # Nineteen of its twenty-two teams read "Monroe United", so the nine-team spelling is
    # the club's own name even against a twenty-two-team majority.
    ("MI", "exact", "Monroe Area S.A.", "Monroe United"),
    ("MI", "exact", "All Stars Soccer Academy - Tournament Team", "Nationals"),
    # All 23 teams read "Detroit City FC North ...", a branch that held no club value of
    # its own while its siblings West and South Oakland both do.
    ("MI", "exact", "Saginaw Township SA", "Detroit City FC North"),
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Oxford SC writes OSC; Oxford United Soccer Club writes OUSC.
    #   Michigan Futbol Academy (MFA), Michigan Youth Soccer Club (MYSA) and Michigan FC
    #     are three clubs the loose fold groups only because "Michigan" is shared.
    #   West Michigan Youth Soccer Association is the association, fielding Athletic SC
    #     GEO, AYSO United BYR and East FC teams; it is a bucket, not a club.
    #   Dearborn Heights SC is a different place from Dearborn SC.
    # Five open questions: Chaos Soccer against Chaos FC, whose team names are coloured
    # and mascotted respectively; "Sturgis SC", 7 of whose teams read "Midwest United FC
    # - Sturgis"; "Dearborn SC", every team of which reads "Michigan Juniors FC Dearborn";
    # and the Forza and "Nationals SC Union" rows, whose teams are named only "U15",
    # "U16" and "U18".
    # Ohio
    ("OH", "exact", "Club Ohio Soccer", "Club Ohio"),
    ("OH", "exact", "Mercury Soccer", "Mercury"),
    ("OH", "exact", "KINGS HAMMER", "Kings Hammer Soccer Club"),
    ("OH", "exact", "Ohio Premier Soccer Club", "Ohio Premier"),
    ("OH", "exact", "Ohio Premier Futbol Club (OPFC)", "Ohio Premier"),
    ("OH", "exact", "Canton Akron United Force (CAU)", "Canton Akron United Force"),
    # The 54-team spelling is missing the space before its tag, so the canonical is the
    # same name written properly. California holds its own "Total Futbol Academy", which
    # is why the Ohio tag stays rather than being dropped.
    ("OH", "exact", "Total Futbol Academy(OH)", "Total Futbol Academy (OH)"),
    ("OH", "exact", "Total Futbol Academy", "Total Futbol Academy (OH)"),
    ("OH", "exact", "Cuyahoga Valley SA", "Cuyahoga Valley Soccer Academy"),
    ("OH", "exact", "NWC Alliance", "NWC Alliance Soccer Club"),
    ("OH", "exact", "Ambassadors FC", "Ambassadors FC (oh)"),
    ("OH", "exact", "Green Soccer Association (GSA)", "Green SA"),
    ("OH", "exact", "Croatia Jrs SC", "Croatia Jrs"),
    ("OH", "exact", "Polaris Youth Soccer Club", "Polaris Soccer Club"),
    ("OH", "exact", "Anthony Wayne United", "Anthony Wayne United SC"),
    ("OH", "norm", "Central Ohio Elite", "Central Ohio Elite"),
    # "Pcfc" is the club's acronym with its case mangled rather than a spelling of the
    # name, so the one-team full form is canonical. Every team reads "PCFC ...".
    ("OH", "exact", "Pcfc", "Putnam County FC"),
    # One spelling is the bare acronym and the other misspells "Football", so the
    # canonical is a corrected form neither row holds.
    ("OH", "exact", "LUFC", "Lakewood United Football Club"),
    (
        "OH",
        "exact",
        "Lakewood United Footbal Club (LUFC)",
        "Lakewood United Football Club",
    ),
    ("OH", "exact", "Hudson United SC    (HUSC)", "Hudson United Soccer Club"),
    ("OH", "exact", "Fairview Park Soccer Assn (FPSA)", "Fairview Park Soccer Association"),
    ("OH", "exact", "ashland united", "Ashland United Soccer"),
    # Its two teams are named "United Soccer 2012 Black D5sw" -- the club name split at
    # its own space, leaving the first word as the club.
    ("OH", "exact", "Ashland", "Ashland United Soccer"),
    ("OH", "exact", "BSA Celtic", "BSA Celtics"),
    # All 21 of its teams read "Oak Hills Premier ...", which is a club value in its own
    # right, so the two-team spelling is canonical.
    ("OH", "exact", "Oak Hills Youth Athletics", "Oak Hills Premier"),
    ("OH", "exact", "Cincinnati Soccer Club (Cincy SC)", "Cincy SC"),
    ("OH", "exact", "Delaware Select SC - Knights", "Delaware Knights"),
    (
        "OH",
        "exact",
        "Shaker Youth Soccer Association",
        "Shaker Youth Soccer Assn - Premier Football Club",
    ),
    # Cincinnati United Premier and Cincinnati United Soccer Club are two clubs, per the
    # owner on 2026-09-22: CUP against CUSC. These three rows are CUP's -- the slash row
    # fields "Cincinnati United CUP 2013 King N" and "CU North 2012 Elite 1", and CUP's
    # own teams already read "CUSE 11B Elite" and "CUSM 15B Cagliari".
    ("OH", "exact", "Cincinnati United SC / CUP", "Cincinnati United Premier Soccer Club"),
    (
        "OH",
        "exact",
        "Cincinnati United North (CU North)",
        "Cincinnati United Premier Soccer Club",
    ),
    (
        "OH",
        "exact",
        "Cincinnati United Southeast  (CUSE)",
        "Cincinnati United Premier Soccer Club",
    ),
    # "OSU" is deliberately not an entry here. Ohio Strikers United's seventeen teams were
    # moved by team id instead, because the same club value carries three Ontario teams
    # and twenty-four stateless ones, one of them named "Ottawa South United - OSU 2016
    # Force Academy". An override reaches stateless teams in every state, so a rule would
    # have renamed a Canadian club's squads to an Ohio one.
    # Left apart deliberately, each on its team names rather than on its club name:
    #   Cleveland Futbol Club fields "Lady Flames"; Cleveland Football Academy writes CFA.
    #   Legend SC writes "LEGEND SC B 2015"; Legends FC names itself in full.
    #   FC United (Ohio) fields "FC United 08G Red", not Ohio United FC's "Unity" teams.
    #   Ohio Soccer Association writes OSA and is not Ohio Youth Academy.
    #   Dublin Soccer League writes DSX; Dublin United Soccer Club writes DUSC.
    #   Shelby Youth Soccer fields "Shelby Storm"; Shelby County's teams all read WOU.
    #   Bay Area Soccer League, FC Columbus and Dayton Futbol Academy are each their own
    #     club rather than a spelling of Bay Soccer Club, Columbus United or FC Dayton.
    # Three open questions: "Northwest Cincy Soccer Coalition", 13 of whose 14 teams read
    # "Northwest Cincy SC" while Cincy SC sits separately; "Shelby County Youth Soccer",
    # every team of which reads "Western Ohio United"; and "Ohio Valley Soccer League"
    # against "Ohio Valley Football Club".
    # More Kansas
    ("KS", "exact", "Union KC Soccer Club (KS)", "Union KC"),
    # All caps is not a spelling, and 32 of these 40 teams read "Kansas Rush Wichita",
    # which is a club value of its own. Kansas Rush itself fields no Wichita teams, so
    # this is that club's Wichita branch rather than the parent.
    ("KS", "exact", "WICHITA RUSH", "Kansas Rush Wichita"),
    # Left apart deliberately: Kansas City FC writes KCFC against KC Athletics, FC
    # Wichita is not Wichita United FC, and "Kansas Premier Soccer League" and "Kansas
    # Premier Soccer Elite Academy" are league buckets fielding Pack United, BK Academy,
    # KC United Arsenal and HAFC teams rather than spellings of one club.
    # One open question: "SOUTHWEST KANSAS", whose fifteen teams name several different
    # clubs, against "Southwest Kansas Soccer Association", whose eight all read
    # "Southwest KS United FC".
    # Nebraska
    ("NE", "norm", "Gretna Elite Academy", "Gretna Elite Academy"),
    ("NE", "exact", "Lincoln Spirit Club (LSC)", "Lincoln Spirit SC"),
    ("NE", "norm", "Western Nebraska FC", "Western Nebraska FC"),
    ("NE", "exact", "Hawks FC", "Hawks FC (ne)"),
    ("NE", "exact", "International SA", "International Soccer Academy"),
    # Twenty-three of its twenty-four teams read "Lincoln Surf", which is a club value in
    # its own right, so the eleven-team spelling is canonical.
    ("NE", "exact", "Dreamers FC", "Lincoln Surf"),
    ("NE", "exact", "Schuyler Soccer Club", "Schuyler YS"),
    # "Evolution SC" is deliberately not an entry. Nebraska's twelve teams were moved by
    # team id instead, because that club value is mostly Illinois' -- 58 teams there
    # against 12 here, plus four stateless ones that an override would have renamed
    # "Evolution SC (NE)" sight unseen. Same reason as Ohio's OSU above.
    # Left apart deliberately: "United Futbol Academy (UFA)" fields "UFA Siouxland"
    # against United Association Football's UAF, and International Soccer Club writes ISC
    # rather than the INTER that both International Soccer Academy spellings use.
    # Three open questions: Hastings FC against Hastings SC, which writes "HSC Eagle
    # Junior"; "Schuyler Predators", whose one team is named for itself while both
    # Schuyler clubs field Warriors; and "Wichita Regional Soccer Association", a Kansas
    # name sitting on Nebraska teams called "UNITED FC GRAND ISLAND 14B".
    # Nevada
    ("NV", "exact", "Player SC", "Players SC"),
    ("NV", "exact", "Great Basin Youth SL (GBYSL)", "Great Basin Youth Soccer League"),
    ("NV", "exact", "Sierra Surf", "Sierra Surf SC"),
    ("NV", "exact", "Las Vegas Sports Acad(LVSA / LVPSA)", "Las Vegas Sports Academy"),
    # Left apart deliberately: Las Vegas Alliance FC shares only the city with Las Vegas
    # Sports Academy, and Nevada Youth Soccer is the state association -- its teams are
    # "Northern NV ODP U12 Boys" and "NYSA RFC" -- not a spelling of Nevada Futbol Club.
    # One open question: "Northern Nevada Youth Soccer League", fielding LEONCITOS and
    # "Reno Legacy Fc", against Northern Nevada Soccer Club's Reno teams.
    # District of Columbia
    ("DC", "exact", "DC United", "D.C. United"),
    ("DC", "exact", "D.C. United U16", "D.C. United"),
    # Left apart: DC Soccer Club is not D.C. United; the two share only the city.
    # North Dakota
    ("ND", "exact", "Tri-City United Soccer Club (TCU)", "Tri-City United"),
    # Alaska
    ("AK", "exact", "Alaska Rush SC", "Alaska Rush"),
    # Hawaii
    ("HI", "exact", "Hawaii RUSH soccer club", "Hawaii Rush"),
    # Left apart: Hawaii Youth Soccer Association is the state body, fielding "Ka'oi" and
    # "Hawai'i 2009 Boys", not a spelling of Hawaii Soccer Academy. The two one-team
    # Warriors rows field "St'at'imc Warriors" and "MISO N1 BIG ISLAND WARRIORS".
    # Delaware
    ("DE", "exact", "Delaware Football Club (DEFC)", "Delaware Football Club"),
    # Left apart: Delaware Futbol Academy writes DFA on all 38 teams, never DEFC.
    # Wyoming
    ("WY", "exact", "Yellowstone Fire Soccer Assn.", "Yellowstone Fire Soccer Assoc"),
    # West Virginia
    ("WV", "exact", "WVFC", "West Virginia Futbol Club"),
    ("WV", "exact", "West Virginia Soccer Assn (WVSA)", "West Virginia Soccer"),
    ("WV", "exact", "West Virginia SC", "West Virginia Soccer"),
    ("WV", "exact", "Mountaineer United SC (MUSC)", "Mountaineer United Soccer Club"),
    ("WV", "norm", "Square One Sports", "Square One Sports"),
    ("WV", "exact", "East River Soccer Assn", "East River Soccer Club"),
    # Three teams each, and both spellings field teams named "FC Wheeling", so the tie
    # goes to the fuller form.
    ("WV", "exact", "FC Wheeling United", "FC Wheeling United SC"),
    # Left apart: West Virginia Futbol Club writes WVFC and West Virginia Soccer writes
    # "WV Soccer". The scan groups them because the state name is shared; the acronyms
    # separate them.
    # South Dakota
    ("SD", "exact", "Dakota Alliance SC   (DASC)", "Dakota Alliance SC"),
    # "DASC" is deliberately not an entry, although South Dakota's 106 teams under it are
    # Dakota Alliance and were moved by team id. Nebraska holds eight teams under the same
    # value and ten more carry it with no state at all, and an override reaches stateless
    # teams in every state -- so a rule would have decided those ten sight unseen.
    ("SD", "exact", "Black Hills Rapids", "Black Hills Rapids SC"),
    ("SD", "exact", "Brandon Area Soccer Assn (BASA)", "Brandon Area SA"),
    ("SD", "exact", "Brandon Area Soccer Association", "Brandon Area SA"),
    ("SD", "exact", "Spearfish Soccer", "Spearfish SA"),
    ("SD", "exact", "Ignite Soccer Club(SD)", "Ignite Soccer Club (SD)"),
    ("SD", "exact", "Ignite Soccer Club", "Ignite Soccer Club (SD)"),
    ("SD", "norm", "Watertown Youth Soccer Assn", "Watertown Youth Soccer Assn"),
    # "LLC" is a legal suffix rather than a spelling, so the clean form wins the tie.
    ("SD", "exact", "Ambush LLC", "Ambush Soccer Academy"),
    # All sixteen of its teams read "Yankton United", which is a club value of its own.
    ("SD", "exact", "Yankton Youth SA", "Yankton United"),
    # Left apart: South Dakota Youth Soccer Association is the state body, not a spelling
    # of South Dakota United Futbol Club. One open question: "Vermillion SC" fields
    # "Vermillion Predators U12" against "Vermillion Youth SL"'s "Vermillion U10G".
    # Montana
    ("MT", "exact", "Flathead Valley United", "Flathead Valley United SC"),
    ("MT", "exact", "Gallatin Elite SC    (GESC)", "Gallatin Elite Soccer Club"),
    ("MT", "exact", "Northwest Elite", "Northwest Elite Soccer Club"),
    ("MT", "exact", "Polson Youth Soccer", "Polson FC"),
    # Three of its four teams are named "Billings Wolves", which is a club value of its
    # own; Billings United's own teams read "BU B2014 Pink".
    ("MT", "exact", "Billings United SC", "Billings Wolves"),
    # New Hampshire and New York hold their own Queen City Football Club, so the state
    # tag stays rather than being dropped.
    ("MT", "exact", "Queen City Football Club", "Queen City Football Club (Mt)"),
    # Left apart: "Nelson Soccer Association" fields "Kootenay United Football Academy",
    # a British Columbia side, and non-US clubs are out of scope.
    # Rhode Island
    # The MLS NEXT shape: its six teams are all "U16 AD"/"U18 AD".
    ("RI", "exact", "Rhode Island Surf SC", "Rhode Island Surf"),
    ("RI", "exact", "Barrington Soccer Club", "Barrington Soccer"),
    ("RI", "exact", "Narragansett Youth SA (NYSA)", "Narragansett"),
    ("RI", "exact", "West Warwick SA", "West Warwick Soccer Association"),
    # RI Strikers FC already fields "Select RI Strikers U12 Boys" under its own name.
    ("RI", "exact", "Select RI Strikers", "RI Strikers FC"),
    # Maine
    ("ME", "norm", "Cumberland Soccer Club", "Cumberland Soccer Club"),
    ("ME", "exact", "Gorham Youth Soccer Assn   (GYSA)", "Gorham YSA"),
    # More Mississippi
    ("MS", "norm", "South Mississippi SC", "South Mississippi SC"),
    ("MS", "exact", "Southern States Soccer Club", "Southern States Soccer"),
    ("MS", "exact", "Greenville Youth Soccer Association", "Greenville Youth SA"),
    ("MS", "norm", "Pearl Youth Soccer League", "Pearl Youth Soccer League"),
    ("MS", "exact", "Pearl YSL", "Pearl Youth Soccer League"),
    ("MS", "exact", "DC Thunder FC, Inc.", "DC Thunder FC"),
    ("MS", "norm", "East Central Soccer Club", "East Central Soccer Club"),
    ("MS", "exact", "East Central SC", "East Central Soccer Club"),
    ("MS", "exact", "Cleveland Youth Soccer Assn", "Cleveland Youth Soccer Assoc."),
    ("MS", "norm", "Southern Alliance SC", "Southern Alliance SC"),
    ("MS", "exact", "SASC", "Southern Alliance SC"),
    ("MS", "exact", "Bay Area YS", "Bay Area Youth Soccer"),
    # Each of these names a club value that already exists, on every one of its teams.
    ("MS", "exact", "Desoto County SA", "Desoto FC"),
    ("MS", "exact", "Pyramid Athletic Organization", "PAO DC Panthers"),
    ("MS", "exact", "DC Panthers", "PAO DC Panthers"),
    ("MS", "exact", "Greenwood YSO", "Delta Red Bulls"),
    ("MS", "exact", "Brookhaven Soccer Association", "Ole Brook FC"),
    # Left apart: Biloxi Soccer Organization fields "BSO Inferno" against Biloxi Soccer
    # Academy's "MS Coast Wave", and Pearl River Soccer Club writes PRSC, not PFC.
    # One open question: "Pearl FC", whose two teams are "Madrid FC" and "The MS 6-7".
    # Vermont needs nothing: its scan is clean, and Vermont Soccer Association is the
    # state body rather than a spelling of Vermont United Soccer Academy.
    # New Mexico
    ("NM", "norm", "New Mexico Soccer Academy", "New Mexico Soccer Academy"),
    # LAFC is Los Alamos Football Club's acronym and both spellings write it, so the
    # eleven-team form is canonical against a fifteen-team league name.
    ("NM", "exact", "Los Alamos Youth Soccer League", "Los Alamos Football Club"),
    # The MLS NEXT shape: its three teams are all "U14 AD"/"U17 AD"/"U18 AD".
    ("NM", "exact", "Roswell Soccer Club", "Roswell Youth Soccer Association"),
    ("NM", "exact", "FC United", "FC United (NM)"),
    ("NM", "exact", "AYSA", "Artesia Youth Soccer Association"),
    # Four spellings of one club, all fielding Guadalajara and Chivas teams. The
    # seventeen-team majority is all caps and the rest abbreviate, so the canonical is
    # the only spelling that writes the name out.
    ("NM", "exact", "GUADALAJARA NM", "Guadalajara Soccer Club of New Mexico"),
    ("NM", "exact", "Guadalajara Soccer Club(NM)", "Guadalajara Soccer Club of New Mexico"),
    ("NM", "exact", "Guadalajara Soccer Association", "Guadalajara Soccer Club of New Mexico"),
    ("NM", "exact", "New Mexico United Academy", "New Mexico United"),
    # "Durango United" is deliberately not an entry. New Mexico's two teams under it
    # are named "Rio Rapids Durango SC" and were moved by team id, but Colorado holds
    # fifteen teams under the same value and three more are stateless, which an
    # override would have decided sight unseen.
    ("NM", "exact", "Farmington United", "Farmington SC"),
    ("NM", "exact", "Hobbs Youth Soccer Association", "Hobbs United FC"),
    ("NM", "exact", "Thunderbirds Hobbs United", "Hobbs United FC"),
    # Left apart: New Mexico Youth Soccer is the state body, fielding "DC NUTMEG" and
    # "FSC Blizzard"; Bravos Paseo del Norte Hobbs NM and Alianza FC Hobbs are their own
    # clubs, sharing only the town with Hobbs United.
    # Louisiana
    ("LA", "exact", "Louisiana Fire", "Louisiana Fire SC"),
    ("LA", "norm", "Baton Rouge SC", "Baton Rouge SC"),
    ("LA", "norm", "Bayou Soccer Club", "Bayou Soccer Club"),
    # Twenty-two of its twenty-three teams read "Covington FC", which is a club value of
    # its own.
    ("LA", "exact", "Covington Youth Soccer Association", "Covington FC"),
    ("LA", "exact", "Pards Soccer Club (PSC)", "PARDS Soccer Club"),
    ("LA", "exact", "Lafourche Soccer", "Lafourche Soccer League"),
    ("LA", "exact", "South Tangi Youth Soccer Assn", "South Tangi Youth Soccer Association"),
    ("LA", "norm", "North Louisiana United", "North Louisiana United"),
    ("LA", "exact", "Red River FC", "Red River Soccer Association"),
    ("LA", "norm", "Soccer Innovations of America", "Soccer Innovations of America"),
    ("LA", "exact", "West Ouachita Sports Association", "WOYSA Futbol Club"),
    # Iowa
    ("IA", "norm", "Vision Soccer Academy", "Vision Soccer Academy"),
    ("IA", "exact", "United Futbol Academy (IA)", "United Futbol Academy (UFA)"),
    ("IA", "exact", "Iowa Rush", "Iowa Rush Soccer Club"),
    ("IA", "exact", "Bettendorf SA", "Bettendorf Soccer Association"),
    # One spelling is all caps and the other ends in a stray full stop, so the canonical
    # is the name neither row writes cleanly.
    ("IA", "exact", "Quad City Strikers.", "Quad City Strikers"),
    ("IA", "exact", "QUAD CITY STRIKERS", "Quad City Strikers"),
    ("IA", "norm", "North Scott Soccer Club", "North Scott Soccer Club"),
    ("IA", "norm", "Cedar Valley Soccer Club", "Cedar Valley Soccer Club"),
    ("IA", "exact", "Cedar River SA", "Cedar River Soccer Association"),
    ("IA", "norm", "Muscatine Soccer Club", "Muscatine Soccer Club"),
    ("IA", "norm", "Southeast Soccer Academy", "Southeast Soccer Academy"),
    ("IA", "exact", "Iowa Storm", "Iowa Storm Soccer Club"),
    ("IA", "exact", "FC America", "FC America (ia)"),
    ("IA", "exact", "WEST DES MOINES SC  (WDMSC)", "West Des Moines Soccer Club"),
    # Fourteen of its fifteen teams read "Iowa United FC", which is a club value of its own.
    ("IA", "exact", "J-Hawk Soccer Club", "Iowa United FC"),
    ("IA", "exact", "Prairie Soccer Club", "PSC Iowa"),
    ("IA", "exact", "Rockford Raptors FC", "Fuerza Raptors"),
    ("IA", "exact", "TNT Soccer", "TNT Soccer Elite"),
    # Left apart: "FC United Iowa" names itself on every team and is not "Iowa United
    # FC"; Iowa Soccer Association is the state body, fielding "Iowa ODP" and "Iowa IDP",
    # not a spelling of Iowa Soccer Club; Des Moines SC writes DMSC against West Des
    # Moines' WDSC.
    # More Idaho
    ("ID", "exact", "Idaho Rush", "Idaho Rush Soccer Club"),
    ("ID", "exact", "Boise Timbers/Thorns", "Boise Timbers | Thorns FC"),
    ("ID", "exact", "PVSC United", "PVSC United (GCYSL)"),
    ("ID", "exact", "Idaho Surf", "Idaho Surf SC"),
    ("ID", "exact", "Idaho Storm Soccer Club", "Idaho Storm"),
    ("ID", "exact", "Idaho Storm Soccer", "Idaho Storm"),
    ("ID", "exact", "Indie Chicas FC", "Indie Chicas"),
    ("ID", "exact", "Indie Chicas Soccer Club", "Indie Chicas"),
    ("ID", "exact", "Legacy SC (ID)", "Legacy SC"),
    # Left apart: Idaho Youth Soccer Association is the state body, fielding "Idaho ODP"
    # teams, not a spelling of Idaho Juniors FC.
    # More Kentucky
    ("KY", "exact", "LouCity/ Racing Youth Academy", "LouCity / Racing Youth Academy"),
    ("KY", "exact", "Kings Hammer Academy", "Kings Hammer Soccer Club"),
    ("KY", "exact", "Javanon Soccer Club", "Javanon FC"),
    ("KY", "exact", "SKY Soccer Club (KY)", "SKY Soccer Club"),
    ("KY", "exact", "Louisville Soccer Club/Alliance", "Louisville Soccer"),
    ("KY", "exact", "FERN Creek Optimist FC", "Fern Creek Optimist SC"),
    ("KY", "exact", "Sawyer YSA", "Sawyer Youth Soccer Association"),
    # "Inc" is a legal suffix rather than a spelling, so the clean short form wins.
    ("KY", "exact", "Trident Football Club, Inc.", "Trident FC"),
    ("KY", "exact", "Murray Calloway County Soccer Assoc.", "Murray Calloway County Soccer Assn"),
    # Both spellings field "BG Elite FC" teams; the canonical drops the redundant tag and
    # writes the town out.
    ("KY", "exact", "Bowling Green Elite FC (BG ELITE)", "Bowling Green Elite FC"),
    ("KY", "exact", "BG Elite FC", "Bowling Green Elite FC"),
    # "Futbal" is a misspelling and the other spelling is all caps, so the canonical is
    # the form the teams themselves write.
    ("KY", "exact", "Golightly Futbal Chemistry/GFC", "Golightly FC"),
    ("KY", "exact", "GOLIGHTLY FC", "Golightly FC"),
    # Left apart: Winchester Youth Soccer League fields "WinCity United" against
    # Winchester Soccer Club's WSC, and Lexington SC fields "Lex Sporting Club" against
    # Lexington Youth SA's LYSA.
    # Connecticut
    ("CT", "exact", "Connecticut Football Club (CFC)", "Connecticut FC"),
    ("CT", "exact", "Vale Sports Club", "Vale SC"),
    ("CT", "exact", "Olé FC", "Ole FC"),
    ("CT", "norm", "Chelsea Piers SC", "Chelsea Piers SC"),
    ("CT", "exact", "West Hartford Soccer Club", "West Hartford FC"),
    ("CT", "exact", "West Hartford Youth Soccer Association", "West Hartford FC"),
    ("CT", "exact", "Northeast United Premier SC", "Northeast United Premier Soccer"),
    ("CT", "exact", "Enfield SA", "Enfield SC"),
    # Left apart: Hartford SC fields "Hartford Hellions" against Hartford Athletic Youth
    # Academy's "Hartford Athletic" teams.
    # More Oregon
    # This state's recurring shape is a bare acronym filed beside the club's full name,
    # both fielding the same teams. The acronym is not a spelling of the name, so the
    # full form is canonical each time -- twice against a larger acronym row.
    ("OR", "exact", "SCA", "Soccer Chance Academy"),
    ("OR", "exact", "Westside Metros", "Westside Metros FC"),
    ("OR", "norm", "Oregon Premier FC", "Oregon Premier FC"),
    ("OR", "exact", "CUSC", "Clackamas United Soccer Club"),
    ("OR", "exact", "RVT", "Rogue Valley Timbers"),
    ("OR", "exact", "Saints", "Saints Academy"),
    ("OR", "exact", "LFC", "Lincoln FC"),
    ("OR", "norm", "Lincoln Youth Soccer", "Lincoln Youth Soccer"),
    ("OR", "exact", "Lake Oswego Soccer Club   (LOSC)", "Lake Oswego SC"),
    ("OR", "exact", "OFA", "Oregon Futbol Academy"),
    ("OR", "exact", "PFA", "Pelada Football Academy"),
    # "FCP" is deliberately not an entry: Oregon's eight teams under it are FC
    # Piamonte and were moved by team id, but California holds four of its own and
    # two more are stateless.
    ("OR", "exact", "Basin United", "Basin United SC"),
    ("OR", "exact", "Basin United Soccer Club (BUSC)", "Basin United SC"),
    ("OR", "exact", "MSC", "McMinnville SC"),
    ("OR", "exact", "McMinnville Soccer Club (MSC)", "McMinnville SC"),
    ("OR", "exact", "NCSC", "North Clackamas SC"),
    ("OR", "exact", "Southeast Soccer Club", "Southeast Soccer Club (OR)"),
    ("OR", "exact", "CVFC", "Central Valley Futbol Club"),
    ("OR", "exact", "Foothills SC", "Foothills Soccer"),
    ("OR", "exact", "UUSC", "Umpqua United Soccer Club"),
    ("OR", "exact", "SOSA", "Southern Oregon Soccer Academy"),
    ("OR", "exact", "Southern Oregon SA  (SOSA)", "Southern Oregon Soccer Academy"),
    ("OR", "exact", "CVSC", "Chehalem Valley Soccer Club"),
    ("OR", "exact", "LCYSA", "Lower Columbia Youth SA"),
    # Left apart: Oregon Youth Soccer Association is the state body, not a spelling of
    # Oregon Futbol Academy. One open question: whether Lincoln FC and Lincoln Youth
    # Soccer are one club -- Lincoln FC fields a team named "LYS 17B Red", but the two
    # acronyms are otherwise kept apart on their own teams.
    # More Utah
    ("UT", "exact", "Copper Mountain Soccer", "Copper Mountain"),
    ("UT", "exact", "Utah Surf SC", "Utah Surf"),
    ("UT", "exact", "7 Elite Academy (GB)", "7 Elite Academy"),
    ("UT", "norm", "Northern Utah United Soccer", "Northern Utah United Soccer"),
    ("UT", "exact", "SSFC", "Saratoga Springs FC"),
    ("UT", "exact", "Atletico SC", "Atletico"),
    ("UT", "exact", "Shooter Soccer Club", "Shooters SC"),
    # "Summit SC" is deliberately not an entry: Utah's two teams under it read
    # "summit fc MB" and were moved by team id, but New Jersey holds 27 teams under
    # the same value and two more are stateless.
    ("UT", "exact", "Ignite", "Ignite FC"),
    ("UT", "exact", "Strikers SC", "Strikers FC"),
    ("UT", "exact", "South Cache Soccer League", "South Cache SL"),
    # WJFC is West Jordan FC's acronym and both spellings write it, so the one-team form
    # is canonical.
    ("UT", "exact", "West Jordan YS", "West Jordan FC"),
    # Left apart: Utah Youth Soccer is the state body, fielding "Utah ODP"; Utah FC and
    # Utah Athletic Club name themselves on their own teams; Magic United SC writes
    # "SCSL MAGIC UNITED" against Magic FC's own name.
    # More Arizona
    ("AZ", "norm", "Phoenix Rising FC", "Phoenix Rising FC"),
    ("AZ", "exact", "PHOENIX RISING", "Phoenix Rising FC"),
    # The bare acronym is not a spelling, so the one-team full form is canonical for all
    # 177 teams.
    ("AZ", "exact", "FBSL", "Futbolito Bimbo Soccer League"),
    ("AZ", "exact", "Futbolito Bimbo SL (FBSL)", "Futbolito Bimbo Soccer League"),
    ("AZ", "exact", "fc tucson", "FC Tucson Youth Soccer"),
    ("AZ", "exact", "FC Tucson Youth Soccer Club", "FC Tucson Youth Soccer"),
    ("AZ", "exact", "Next Level Soccer - AZ", "Next Level Soccer (AZ)"),
    ("AZ", "norm", "Vail SC", "Vail SC"),
    ("AZ", "exact", "Canyon Del Oro SC    (CDO)", "Canyon Del Oro Soccer Club"),
    ("AZ", "exact", "Southern Arizona SC   (SASC)", "Southern Arizona Soccer Club"),
    ("AZ", "exact", "AZ Arsenal", "Arizona Arsenal Soccer Club"),
    ("AZ", "exact", "Legends FC Arizona", "Legends FC AZ"),
    ("AZ", "exact", "AYSO United Arizona", "AYSO United (az)"),
    ("AZ", "exact", "East Valley FC/NSFC", "East Valley/NSFC"),
    ("AZ", "exact", "Barca Residency Academy USA", "Barca Residency Academy"),
    # Left apart: Arizona Soccer Association is the state body, fielding "AZ ODP";
    # Arizona Soccer Academy writes ASA; Phoenix Premier FC is not Phoenix United Futbol
    # Club; FC Elite Arizona is not FC Arizona; Tucson Elite SC is not FC Tucson. And
    # "Legends FC AZ" is deliberately NOT folded into "FC Arizona" -- its teams read
    # "Legends FC - Arizona - ...", which merely contains that club's name as a substring.
    # Two open questions: the junk rows "Arizona (000)" and "Utah (000)", and "No Club
    # Selection", five of whose six teams read "Arizona Soccer Club" but which is a
    # provider placeholder that must never become a rule.
    # Minnesota
    ("MN", "exact", "MTA", "MN Thunder Academy"),
    ("MN", "exact", "St. Croix Soccer Club", "St. Croix"),
    ("MN", "exact", "Minneapolis United Soccer Club", "Minneapolis United"),
    ("MN", "exact", "CC United", "CC United Soccer Club"),
    # The bare acronym is not a spelling, so the seven-team full form is canonical.
    ("MN", "exact", "EPSC", "Eden Prairie SC"),
    ("MN", "norm", "Eden Prairie SC", "Eden Prairie SC"),
    ("MN", "exact", "North Suburban Soccer Assn (NSSA)", "North Suburban SA"),
    ("MN", "norm", "Park Valley United FC", "Park Valley United FC"),
    ("MN", "exact", "Shakopee Soccer Assn (SSA)", "Shakopee SA"),
    ("MN", "exact", "Central Minnesota Youth Soccer Association", "Central Minnesota Youth SA"),
    ("MN", "exact", "Cottage Grove United SC  (CGU)", "Cottage Grove United SC"),
    ("MN", "norm", "North Oaks Soccer Club", "North Oaks Soccer Club"),
    ("MN", "exact", "Byron Youth Soccer Association", "Byron Futbol Club"),
    ("MN", "exact", "Owatonna Soccer Assn", "Owatonna SA"),
    ("MN", "exact", "Arrowhead Youth Soccer Association", "Arrowhead Youth SA"),
    # All thirteen teams across these two read "St. Paul Blackhawks", which is a club
    # value of 108 teams in its own right.
    ("MN", "exact", "Saint Paul Blackhawks", "St. Paul Blackhawks"),
    ("MN", "exact", "Saint Paul Blackhawks SC", "St. Paul Blackhawks"),
    ("MN", "exact", "SHATTUCK-ST. MARY'S ACADEMY", "Shattuck-St. Mary's"),
    ("MN", "exact", "Shattuck-St. Mary’s", "Shattuck-St. Mary's"),
    ("MN", "exact", "Minnesota United", "Minnesota United FC"),
    ("MN", "exact", "New Ulm United Soccer Club", "New Ulm United"),
    ("MN", "exact", "Kmysa", "Kasson-Mantorville YSA"),
    ("MN", "exact", "Faribault Soccer", "Faribault Soccer Club"),
    ("MN", "norm", "Minnesota TwinStars Academy", "Minnesota TwinStars Academy"),
    ("MN", "exact", "Waconia AA / Waconia Soccer Club", "Waconia SC"),
    # Left apart: Minnesota Youth Soccer Association is the state body; Twin Cities
    # Soccer Leagues fields "TCSL Reps" and is the league whose name appears in half this
    # state's team names, not a spelling of Twin Cities Youth Soccer Club; and Lakes Area
    # Youth Soccer Association fields "Brainerd United" rather than Lakes United FC.
    # One open question: "Esko Soccer Club", whose one team is "CEC FC U12".
    # More Missouri
    ("MO", "exact", "St Louis Scott Gallagher", "St. Louis Scott Gallagher"),
    ("MO", "norm", "Lou Fusz Athletic", "Lou Fusz Athletic"),
    ("MO", "exact", "Missouri Rush Soccer Club", "Missouri Rush"),
    ("MO", "exact", "Southwest MO Rush (SWMO)", "Southwest MO Rush"),
    ("MO", "exact", "Sporting City Soccer", "Sporting City Soccer Club"),
    ("MO", "exact", "AFA Fillies Sports", "AFA Fillies"),
    ("MO", "exact", "United Capital City", "United Capital City Athletic"),
    # Every team reads "REAL WC St. Louis", so the canonical restores the capitals the
    # 35-team spelling lost.
    ("MO", "exact", "Real Wc St. Louis Soccer Club", "Real WC St. Louis Soccer Club"),
    ("MO", "exact", "Real WC St. Louis", "Real WC St. Louis Soccer Club"),
    ("MO", "exact", "AJAX ST. LOUIS SC", "Ajax St Louis SC"),
    ("MO", "exact", "Cottleville United FC (CUFC)", "Cottleville United"),
    ("MO", "exact", "St Louis Legends SC", "St. Louis Legends SC"),
    ("MO", "exact", "Hawks FC (st. Louis)", "Hawks FC"),
    ("MO", "exact", "ST LOUIS CITY", "St. Louis City SC"),
    # The bare acronym is not a spelling, so the one-team full form is canonical.
    ("MO", "exact", "SUFC", "Southeast United FC"),
    ("MO", "exact", "Moberly Area Soccer Association", "Moberly Area SA"),
    ("MO", "exact", "WGSC Soccer", "Webster Groves SC"),
    ("MO", "exact", "Webster Groves SC (WGSC)", "Webster Groves SC"),
    ("MO", "exact", "United St. Louis Academy", "United STL Academy"),
    # Massachusetts
    ("MA", "exact", "Scorpions Soccer", "Scorpions SC"),
    ("MA", "exact", "Western United Pioneers", "Western United Pioneers FC"),
    ("MA", "norm", "Western United Pioneers FC", "Western United Pioneers FC"),
    ("MA", "exact", "Needham Soccer Club, Inc.", "Needham Soccer Club"),
    ("MA", "exact", "Northfields United SC", "Northfields United"),
    ("MA", "exact", "Sudbury Youth Soccer Academy (SYSA)", "Sudbury Academy"),
    ("MA", "exact", "Aztec", "Aztec Soccer Club"),
    ("MA", "exact", "Boston Bolts", "FC Boston Bolts"),
    # Left apart: Boston Athletic Soccer Club names itself on every team and is not
    # Boston Football Club; Wellesley Premier Club does the same against Wellesley United
    # Soccer Club, whose teams are all mascots. One open question: "Bridgewater FC",
    # whose one team is "Bridgewater 2012 Grassa" against BYSA's own teams.
    # More Washington
    ("WA", "exact", "Washington East Surf SC", "Washington East Surf"),
    ("WA", "exact", "Seattle United FC", "Seattle United"),
    ("WA", "exact", "Crossfire Premier Soccer", "Crossfire Premier"),
    ("WA", "exact", "Seattle Celtic FC", "Seattle Celtic"),
    ("WA", "norm", "Northshore Select Club", "Northshore Select Club"),
    ("WA", "exact", "Mt Rainier FC     (MRFC)", "Mt. Rainier Futbol Club"),
    ("WA", "exact", "SU", "Snohomish United"),
    ("WA", "exact", "Columbia Premier", "Columbia Premier Soccer Club"),
    ("WA", "exact", "Wenatchee FC", "Wenatchee FA"),
    ("WA", "norm", "Highline Premier FC", "Highline Premier FC"),
    ("WA", "exact", "Harbor Soccer Club", "Harbor FC"),
    ("WA", "exact", "Harbor YSC", "Harbor FC"),
    ("WA", "exact", "Emerald City Football Club   (ECFC)", "Emerald City FC"),
    ("WA", "exact", "Basin Sounders SC", "Basin Sounders"),
    ("WA", "exact", "90+ Project YSO", "90+ Project SC"),
    ("WA", "exact", "- Spokane Legacy soccer academy", "Spokane Legacy Soccer Academy"),
    ("WA", "exact", "Spokane legacy", "Spokane Legacy Soccer Academy"),
    ("WA", "exact", "Fife Milton Edgewood SC", "Fife Milton Edgewood JSC"),
    ("WA", "exact", "Atletico Futbol Club (WA)", "Atletico FC"),
    ("WA", "exact", "Atlético", "Atletico FC"),
    ("WA", "exact", "LWPFC", "Lake Washington Premier Football Club"),
    ("WA", "exact", "Club America Nido Aguila SA", "Club America Nido Aguila"),
    ("WA", "exact", "Sequim Junior Soccer FC", "Sequim Junior Soccer Club"),
    ("WA", "exact", "NWSC", "North Whidbey SC"),
    ("WA", "exact", "SEATTLE SOUNDERS", "Seattle Sounders FC"),
    ("WA", "exact", "south tacoma united", "South Tacoma United Soccer Club"),
    ("WA", "exact", "VANCOUVER WHITECAPS", "Vancouver Whitecaps FC"),
    # A family of rows whose club field holds the team's own label; Sozo FC's 49 teams
    # sit under its name already.
    ("WA", "regex", r"^SOZO FC\s+\S", "Sozo FC"),
    # Left apart: Washington Youth Soccer is the state body. Three open questions: the
    # "WSSC ..." and "PacFW-R ..." rows, each of which is a team label in the club field
    # with no parent club value in this state to fold onto; "Highline SC", whose one team
    # is "Warriors FC"; and the junk row "Washington (000)".
    # More Illinois
    ("IL", "exact", "Rockford Raptors", "Rockford Raptors FC"),
    ("IL", "exact", "Eclipse Select", "Eclipse Select Soccer Club"),
    ("IL", "exact", "Chicago Rush", "Chicago Rush Soccer Club"),
    # Four spellings of one club. 65 of the 88 teams under "FC United Soccer Club" are
    # named "Chicago FC United", so that is the canonical even as the minority.
    ("IL", "exact", "FC United Soccer Club", "Chicago FC United"),
    ("IL", "exact", "FC United", "Chicago FC United"),
    ("IL", "exact", "FC United (chicago)", "Chicago FC United"),
    ("IL", "exact", "Galaxy", "Galaxy SC"),
    ("IL", "exact", "CIU", "Central Illinois United"),
    ("IL", "exact", "Illinois Youth Soccer Assn (IYSA)", "Illinois Youth Soccer Association"),
    ("IL", "exact", "Chicago Fire Youth SC (CFYSC)", "Chicago Fire Youth SC"),
    ("IL", "exact", "CHICAGO FIRE", "Chicago Fire Youth SC"),
    ("IL", "exact", "Greater Libertyville SA", "Greater Libertyville Soccer Association"),
    ("IL", "exact", "Chicago Empire", "Chicago Empire FC"),
    ("IL", "exact", "St. Louis Scott Gallagher (IL)", "St. Louis Scott Gallagher"),
    ("IL", "norm", "Elmhurst City Surf", "Elmhurst City Surf"),
    ("IL", "exact", "Wheaton United", "Wheaton United SC"),
    ("IL", "exact", "Gateway Rush", "Gateway Rush Soccer Club"),
    ("IL", "exact", "Chicago KICS", "Chicago KICS Football Club"),
    ("IL", "exact", "Pegasus", "Pegasus FC"),
    ("IL", "exact", "Lindenhurst Area SC (LASC)", "Lindenhurst Area Soccer Club"),
    ("IL", "exact", "Lyons Township SC (LTSC)", "Lyons Township SC"),
    ("IL", "exact", "Lyons Township Soccer (ltsc)", "Lyons Township SC"),
    ("IL", "exact", "QUAD CITIES RUSH SC", "Quad Cities Rush"),
    ("IL", "exact", "Chicago Magic", "Chicago Magic Soccer Club"),
    ("IL", "norm", "Team Elmhurst SC", "Team Elmhurst SC"),
    ("IL", "exact", "Wilmette Wings", "Wilmette Wings SC"),
    ("IL", "exact", "DeKalb County United SC (DKCU)", "DeKalb County United Academy"),
    ("IL", "exact", "DKCU Academy", "DeKalb County United Academy"),
    ("IL", "exact", "Tri-Cities Soccer Assn (TCSA)", "Tri Cities Soccer Association"),
    ("IL", "exact", "Legion FC Chicago", "Chicago Legion FC"),
    ("IL", "exact", "SAA United", "SAA United SC"),
    ("IL", "exact", "Orland Park Sting", "Orland Park Sting FC"),
    ("IL", "exact", "Campton United", "Campton United SC"),
    ("IL", "exact", "Mayas FC", "FC Mayas"),
    ("IL", "exact", "Chicago Blast Soccer Club", "Chicago Blast"),
    ("IL", "exact", "Force", "Force Football Club"),
    ("IL", "exact", "South Suburban Soccer Academy", "South Suburban"),
    ("IL", "exact", "Carol Stream Panthers", "Carol Stream Panthers SC"),
    ("IL", "exact", "Inter Athletic Club (INTER FC)", "Inter AC"),
    ("IL", "exact", "Metro Alliance Irish FC (F:ALTON)", "Metro Alliance Irish FC"),
    ("IL", "exact", "STRIKERS FOX VALLEY SOCCER CLUB", "Strikers Fox Valley"),
    ("IL", "exact", "Heart of the City (hotc)", "Heart of The City"),
    ("IL", "exact", "Windy City Pride SC", "Windy City Pride"),
    ("IL", "exact", "Deportivo 59", "Deportivo 59 FC"),
    ("IL", "exact", "Chicago House AC", "Chicago House Athletic Club"),
    ("IL", "exact", "Jacksonville United", "Jacksonville United Soccer Club"),
    ("IL", "exact", "Mahomet Seymour SC", "Mahomet-Seymour Soccer Club"),
    ("IL", "exact", "Pekin Pride Soccer Club", "Pekin Pride Soccer"),
    ("IL", "exact", "VC Soccer Academy", "VC Academy"),
    ("IL", "exact", "MVSC", "Mount Vernon SC"),
    ("IL", "exact", "Mount Vernon SC (MVSC)", "Mount Vernon SC"),
    ("IL", "exact", "RBFC Soccer Club", "RBFC"),
    ("IL", "exact", "Inter South", "Inter South Soccer Club"),
    ("IL", "exact", "Chicago Knights FC", "Chicago Knights SC"),
    ("IL", "exact", "Woodstock United", "Woodstock United Soccer Club"),
    ("IL", "exact", "OAK BROOK SOCCER CLUB (OBSC)", "Oak Brook SC"),
    ("IL", "exact", "Sterling United Soccer Club", "Sterling United"),
    ("IL", "exact", "VHSC", "Vernon Hills Soccer Club"),
    ("IL", "exact", "UA (UKRANIAN SOCCER ACADEMY)", "UA (Ukrainian Soccer Academy)"),
    ("IL", "exact", "Chicago Arsenal FC", "Chicago Arsenal Soccer Club"),
    ("IL", "exact", "Gallardo Futbol Club", "Gallardo Academy"),
    ("IL", "exact", "NWS Tigres", "Tigres NWS"),
    ("IL", "exact", "FC Tryzub Academy", "FC Tryzub"),
    ("IL", "exact", "LISC", "Little Illini SC"),
    # Each of these names a club value that already exists, on all or nearly all of its
    # teams.
    ("IL", "exact", "LG Celtics", "Lagrange Celtics"),
    ("IL", "exact", "Lakers FC (glen Ellyn Pk District)", "Glen Ellyn Lakers"),
    ("IL", "exact", "Ajax FC", "Ajax FC Naperville"),
    ("IL", "exact", "Gremio FC Chicago", "Gremio Futbol Club Chicago"),
    ("IL", "exact", "Green & White", "Green White SC"),
    ("IL", "exact", "AYSO Region 300 United", "AYSO 300 United"),
    ("IL", "exact", "Kankakee CO Soccer Academy (KCSA)", "Kankakee County Soccer Academy"),
    ("IL", "exact", "Chicago Power Strikers SC", "Chicago Powerstrikers"),
    ("IL", "exact", "Illinois Premier", "Arlington Aces"),
    # Left apart: Chicago Soccer Academy writes CSA and Chicago Futbol Alliance CFA.
    # Five open questions: the Illinois FC / Illinois Alliance pair, which hold each
    # other's teams; whether "Greater Libertyville Soccer Association" belongs under
    # "FC 1974 Libertyville", which 52 of its 80 teams name; whether Wilmette Wings SC is
    # "Chicago Rush North Shore", which 25 of its 38 name; "Legacy FC" against
    # "Legacy SC"; and "Harvard FC", "Allegiant FC" and "Young SPORTSMENS SL (YSSL)",
    # each of which names another club on only some of its teams. "No Club Selection" is
    # a provider placeholder and must never become a rule, whatever its teams read.
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
