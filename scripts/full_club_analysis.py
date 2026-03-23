#!/usr/bin/env python3
"""
Full club name analysis - finds BOTH caps issues AND naming variations.
Generates SQL for all states (Male only), excluding CA and AZ.
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

SKIP_STATES = set()  # Scan all states (CA/AZ were previously skipped)

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
    # North Carolina
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
    ("WI", "exact", "FC WISCONSIN BOYS", "FC WISCONSIN"),
    ("WI", "exact", "FC WISCONSIN GIRLS", "FC WISCONSIN"),
    ("WI", "exact", "Jefferson County Soccer Association", "Jefferson United SC"),
    ("WI", "exact", "WI United", "Wisconsin United FC"),
    # Idaho
    ("ID", "exact", "Boise Timbers | Thorns", "Boise Timbers | Thorns FC"),
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
    ("UT", "exact", "rampage fc", "rampage sc"),
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
    # Mississippi
    ("MS", "exact", "MS Futbol Club", "Mississippi Rush"),
]

# Acronyms to keep uppercase
ACRONYMS = {
    'FC', 'SC', 'SA', 'AC', 'CF', 'CD', 'YSA', 'YSO', 'YSL', 'SL', 'CC', 'AD',
    'AYSO', 'MLS', 'RSL', 'US', 'USA', 'USYS', 'USSF', 'ECNL', 'GA', 'MLS',
    'LA', 'NY', 'NJ', 'OC', 'DC', 'KC', 'STL', 'ATL', 'PHX',
    'AL', 'AK', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN',
    'IA', 'KS', 'KY', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE',
    'NV', 'NH', 'NM', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'AFC', 'CFC', 'SFC', 'VFC', 'PFC', 'LAFC', 'NYCFC', 'NCFC'
}

def proper_case(name):
    """Convert to proper title case, preserving acronyms."""
    words = name.split()
    result = []
    for i, word in enumerate(words):
        upper = word.upper()
        # Check for acronyms
        if upper in ACRONYMS:
            result.append(upper)
        # Lowercase articles/prepositions (except first word)
        elif word.lower() in ('del', 'de', 'la', 'el', 'los', 'y', 'the', 'of', 'and', 'at', 'in') and i > 0:
            result.append(word.lower())
        # F.C. -> FC
        elif re.match(r'^[A-Za-z]\.[A-Za-z]\.?$', word):
            result.append(word.upper().replace('.', ''))
        else:
            result.append(word.capitalize())
    return ' '.join(result)

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
    n = re.sub(r'\s+soccer\s+club\s*$', ' sc', n)
    n = re.sub(r'\s+s\.c\.\s*$', ' sc', n)
    
    # "Football Club" / "Futbol Club" / "F.C." → " fc"
    n = re.sub(r'\s+football\s+club\s*$', ' fc', n)
    n = re.sub(r'\s+futbol\s+club\s*$', ' fc', n)
    n = re.sub(r'\s+f\.c\.\s*$', ' fc', n)
    
    # Normalize leading prefix: "FC X" → "fc x" (keep the FC, just lowercase)
    # Do NOT strip it — "FC Dallas" and "Dallas SC" are different clubs
    
    return n.strip()

def fetch_all_teams(client, state_code):
    """Fetch all active teams for a state (both genders) using pagination."""
    all_teams = []
    offset = 0
    page_size = 1000
    
    while True:
        result = client.table('teams').select(
            'team_id_master, team_name, club_name, gender'
        ).eq('state_code', state_code).eq('is_deprecated', False).range(
            offset, offset + page_size - 1
        ).execute()
        
        if not result.data:
            break
        all_teams.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    
    return all_teams

def _matches_override(club: str, match_type: str, pattern: str) -> bool:
    """Check if club name matches the override pattern."""
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


def analyze_state(client, state_code):
    """Analyze club names in a state, return fixes needed."""
    teams = fetch_all_teams(client, state_code)
    if not teams:
        return [], 0

    # Count club names
    club_counts = defaultdict(int)
    for team in teams:
        club = team.get('club_name')
        if club:
            club_counts[club] += 1

    fixes = []
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
                    fixes.append({
                        'from': club,
                        'to': canonical,
                        'count': club_counts[club],
                        'type': 'CANONICAL',
                        'state': state_code
                    })
                    processed.add(club)

    # 1. Find caps issues (same lowercase, different case)
    by_lower = defaultdict(list)
    for club in club_counts:
        by_lower[club.lower()].append(club)
    
    for lower, variants in by_lower.items():
        if len(variants) > 1:
            # Pick majority, or proper case if tied
            sorted_v = sorted(variants, key=lambda x: -club_counts[x])
            winner = sorted_v[0]
            # Apply proper case
            winner = proper_case(winner)
            
            for variant in variants:
                if variant != winner:
                    fixes.append({
                        'from': variant,
                        'to': winner,
                        'count': club_counts[variant],
                        'type': 'CAPS',
                        'state': state_code
                    })
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
                fixes.append({
                    'from': variant,
                    'to': winner,
                    'count': club_counts[variant],
                    'type': 'NAMING',
                    'state': state_code
                })
    
    return fixes, len(teams)

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
        ""
    ]
    
    by_state = defaultdict(list)
    for fix in all_fixes:
        by_state[fix['state']].append(fix)
    
    for state in sorted(by_state.keys()):
        state_fixes = by_state[state]
        lines.append(f"-- ========== {state} ==========")
        
        for fix in sorted(state_fixes, key=lambda x: (-x['count'], x['from'])):
            from_esc = fix['from'].replace("'", "''")
            to_esc = fix['to'].replace("'", "''")
            lines.append(f"-- [{fix['type']}] \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
            lines.append(f"UPDATE teams SET club_name = '{to_esc}' WHERE club_name = '{from_esc}' AND state_code = '{state}';")
            lines.append("")
        lines.append("")
    
    lines.append("COMMIT;")
    return '\n'.join(lines)

def execute_fixes(client, all_fixes, dry_run=True):
    """Apply club name fixes directly via Supabase REST API."""
    if not all_fixes:
        print("No fixes to apply.")
        return 0, 0
    
    if dry_run:
        print(f"\n[DRY RUN] Would apply {len(all_fixes)} club name fixes")
        for fix in all_fixes[:20]:
            print(f"  {fix['state']}: \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
        if len(all_fixes) > 20:
            print(f"  ... and {len(all_fixes) - 20} more")
        return len(all_fixes), 0
    
    print(f"\nApplying {len(all_fixes)} club name fixes...")
    applied = 0
    failed = 0
    
    for fix in all_fixes:
        try:
            result = client.table('teams').update(
                {'club_name': fix['to']}
            ).eq('club_name', fix['from']).eq('state_code', fix['state']).execute()
            applied += 1
            print(f"  ✅ {fix['state']}: \"{fix['from']}\" → \"{fix['to']}\"")
        except Exception as e:
            failed += 1
            print(f"  ❌ {fix['state']}: \"{fix['from']}\" → error: {e}")
    
    print(f"\nApplied: {applied}, Failed: {failed}")
    return applied, failed


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Full club name analysis and fixing')
    parser.add_argument('--execute', action='store_true', help='Apply fixes via Supabase (default: generate SQL only)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without applying')
    args = parser.parse_args()
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all states (paginate to ensure we capture every state_code)
    print("Fetching states...")
    all_states = set()
    offset = 0
    page_size = 1000
    while True:
        result = client.table('teams').select('state_code').eq(
            'is_deprecated', False
        ).range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        for t in result.data:
            if t.get('state_code'):
                all_states.add(t['state_code'])
        if len(result.data) < page_size:
            break
        offset += page_size
    states = sorted(all_states - SKIP_STATES)
    
    skip_note = f" (skipping {', '.join(sorted(SKIP_STATES))})" if SKIP_STATES else ""
    print(f"Processing {len(states)} states{skip_note}\n")
    
    all_fixes = []
    summary = {}
    
    for state in states:
        print(f"Analyzing {state}...", end=" ")
        fixes, total = analyze_state(client, state)
        all_fixes.extend(fixes)
        
        if fixes:
            affected = sum(f['count'] for f in fixes)
            canonical = sum(1 for f in fixes if f['type'] == 'CANONICAL')
            caps = sum(1 for f in fixes if f['type'] == 'CAPS')
            naming = sum(1 for f in fixes if f['type'] == 'NAMING')
            summary[state] = {'canonical': canonical, 'caps': caps, 'naming': naming, 'affected': affected, 'total': total}
            print(f"{canonical} canonical, {caps} caps, {naming} naming ({affected} teams)")
        else:
            print("clean")
    
    # Generate SQL (always, for audit trail)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'club_name_fixes_male_all_states.sql')
    sql = generate_sql(all_fixes)
    with open(output_path, 'w') as f:
        f.write(sql)
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    
    total_fixes = len(all_fixes)
    total_affected = sum(f['count'] for f in all_fixes)
    total_canonical = sum(1 for f in all_fixes if f['type'] == 'CANONICAL')
    total_caps = sum(1 for f in all_fixes if f['type'] == 'CAPS')
    total_naming = sum(1 for f in all_fixes if f['type'] == 'NAMING')

    for state in sorted(summary.keys()):
        s = summary[state]
        parts = []
        if s.get('canonical'):
            parts.append(f"{s['canonical']} canonical")
        if s.get('caps'):
            parts.append(f"{s['caps']} caps")
        if s.get('naming'):
            parts.append(f"{s['naming']} naming")
        print(f"  {state}: {' + '.join(parts)} = {s['affected']} teams affected")

    print('-'*60)
    print(f"TOTAL: {total_fixes} fixes ({total_canonical} canonical + {total_caps} caps + {total_naming} naming)")
    print(f"       {total_affected} teams will be updated")
    print(f"\nSQL written to: {output_path}")
    
    # Execute if requested
    if args.execute:
        execute_fixes(client, all_fixes, dry_run=False)
    elif args.dry_run:
        execute_fixes(client, all_fixes, dry_run=True)

if __name__ == '__main__':
    main()
