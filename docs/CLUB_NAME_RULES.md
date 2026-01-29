# Club Name Standardization Rules

> **Purpose:** This file captures all decisions and patterns for standardizing club names in the PitchRank database. Pitchrank Bot reads this before any club name work.

---

## 🤖 Autonomous Fixes (No Approval Needed)

I can fix these automatically:

### 1. Capitalization Issues
- `CCV STARS` → `CCV Stars` (use title case, not ALL CAPS)
- `SLAMMERS FC` → `Slammers FC`
- `San Diego FORCE FC` → `San Diego Force FC`
- **Rule:** Prefer title case unless it's an acronym (FC, SC, USA, etc.)

### 2. Punctuation Normalization
- `West Coast F.C.` → `West Coast FC` (remove periods from abbreviations)
- **Rule:** No periods in FC, SC, SA, etc.

---

## 📋 Naming Patterns (Learned Preferences)

### State/Region Abbreviations
- Prefer full state name in prefix: `RSL Arizona North` not `RSL-AZ North`
- Keep regional suffixes: North, South, Mesa, Yuma, etc. are separate clubs

### Club vs SC Suffixes
- **Strong preference for full "Soccer Club" form** over "SC" abbreviation
- Examples: `Los Gatos United Soccer Club`, `Rebels Soccer Club`, `Eagles Soccer Club`
- Exceptions (specific clubs that use short form): `Lamorinda SC`, `Solano Surf`, `Silicon Valley SA`
- Some clubs no suffix: `San Francisco Glens`, `AC Brea`

### Hyphen vs Space in Regional Names
- For City SC: no hyphen: `City SC San Marcos` not `City SC - San Marcos`
- For other clubs with regions: use ` - ` separator: `Total Futbol Academy - OC`
- Prefer abbreviations for regions: `OC` not `Orange County`, `VC` not `Ventura County`

### FC Prefix Position
- Prefer suffix: `Bay Area Surf` not `FC Bay Area Surf`
- Exception: When FC is part of official name (e.g., `FC Tucson Youth Soccer`)

### "Soccer Club" Spelling
- Use `FC` not `F.C.`
- Use `SC` not `S.C.`
- `Futbol Club` and `Football Club` are acceptable full forms

### Parenthetical State Codes
- Remove `(CA)` suffix: `TOTAL FUTBOL ACADEMY (CA)` → `Total Futbol Academy`
- State is tracked in `state_code` field, not club name

### USA Suffix
- Remove redundant `USA`: `Barca Residency Academy USA` → `Barca Residency Academy`

### Full Name vs Abbreviation
- `Pateadores Soccer Club` ✓ (full name preferred over just `Pateadores`)
- `Arizona Arsenal Soccer Club` ✓ (full name preferred over `AZ Arsenal`)
- **General rule:** Prefer the more complete/official name

---

## ✅ Specific Club Decisions

### Arizona Clubs
| Standardized Name | Also Known As / Merged From |
|-------------------|----------------------------|
| `CCV Stars` | CCV STARS |
| `Playmaker Futbol Academy` | PlayMaker Futbol Academy |
| `SC del Sol` | SC Del Sol (keep Spanish "del" lowercase) |
| `FC Tucson Youth Soccer` | FC Tucson Youth Soccer Club |
| `Arizona Arsenal Soccer Club` | AZ Arsenal |
| `Barca Residency Academy` | Barca Residency Academy USA |
| `RSL Arizona` | Main club (no region) |
| `RSL Arizona North` | RSL-AZ North |
| `RSL Arizona South` | RSL-AZ South |
| `RSL Arizona Southern AZ` | RSL-AZ Southern AZ |
| `RSL Arizona West Valley` | RSL-AZ West Valley |
| `RSL Arizona Yuma` | RSL-AZ Yuma |
| `RSL Arizona Mesa` | (already correct) |

### California Clubs
| Standardized Name | Also Known As / Merged From |
|-------------------|----------------------------|
| `Total Futbol Academy` | TOTAL FUTBOL ACADEMY (CA), TFA, Total FA |
| `Pateadores Soccer Club` | Pateadores |
| `West Coast FC` | West Coast F.C. |
| `San Francisco Glens` | San Francisco Glens SC, San Francisco Glens Soccer Club |
| `Lamorinda SC` | Lamorinda Soccer Club |
| `San Diego Force FC` | San Diego FORCE FC |
| `Slammers FC` | SLAMMERS FC |
| `Los Gatos United Soccer Club` | Los Gatos United |
| `Davis Legacy Soccer Club` | Davis Legacy |
| `Walnut Creek Surf Soccer Club` | Walnut Creek Surf |
| `San Diego Surf Soccer Club` | San Diego Surf |
| `Sacramento Republic FC` | Sacramento Republic |
| `Santa Rosa United Soccer` | Santa Rosa United |
| `Sheriffs FC` | Sheriffs Futbol Club |
| `Boca Orange County` | BOCA OC |
| `Solano Surf` | Solano Surf SC |
| `Silicon Valley SA` | Silicon Valley Soccer Academy |
| `Bay Area Surf` | FC Bay Area Surf |
| `LA Surf Soccer Club` | LA Surf, Los Angeles Surf |
| `Sporting California USA` | Sporting CA USA |
| `City SC San Diego` | City SC - San Diego |
| `City SC San Marcos` | City SC - San Marcos |
| `AC Brea` | AC Brea Soccer |
| `California Odyssey Soccer Club` | California Odyssey SC |
| `Central Coast Surf Soccer Club` | Central Coast Surf |
| `Eagles Soccer Club` | Eagles SC |
| `Elk Grove United Soccer Club` | Elk Grove United SC |
| `Los Angeles Soccer Club` | Los Angeles SC |
| `Rebels Soccer Club` | Rebels SC |
| `San Juan Soccer Club` | San Juan SC |
| `South Valley United Soccer Club` | South Valley United |

---

## 📊 Process

### Optimized Workflow (v2)
1. **One scan** — Pull ALL teams for scope in paginated query
2. **Local analysis** — Find all caps issues + naming variations in Python (no extra API calls)
3. **Auto-decide** — Pick majority option (more teams wins), fix caps autonomously
4. **Generate SQL batch** — Create ONE SQL script with all UPDATEs
5. **Report back** — Human runs SQL in Supabase SQL Editor (1 API call total)

**Cost:** ~2 API calls per full scan vs ~50+ individual calls

### Decision Rules
- **Caps issues:** Auto-fix (no approval needed)
- **Naming variations:** Go with majority (e.g., 24 teams beats 2 teams)
- **Close calls:** Still go with majority, even if 12 vs 11
- **Different clubs:** If clearly different orgs (e.g., CITY FC vs City SC), leave both

### Output
- One SQL file for ALL states combined
- Include comments showing what each fix does
- Filter every UPDATE by state_code

## ⚠️ CRITICAL: Always Filter by State!

**ALWAYS add `.eq('state_code', 'XX')` to UPDATE queries!**

Different states can have clubs with the same name that are completely different organizations:
- `Total Futbol Academy` in CA ≠ `Total Futbol Academy (OH)` in Ohio
- `Rebels Soccer Club` in CA ≠ `Rebels Soccer Club` in TX

When working state-by-state, ONLY update teams in that state.

---

## 📝 Change Log

| Date | Changes |
|------|---------|
| 2026-01-29 | Initial creation. AZ U16M complete. CA Male (all ages) complete. ~1300+ teams standardized. |
| 2026-01-29 | All other states Male analyzed. SQL ready: scripts/club_name_fixes_male_all_states.sql (13 fixes, 71 teams). |
| 2026-01-29 | Learned: Regional branches (CLW, TPA, etc.) are separate clubs, not naming variations. |

