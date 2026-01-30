# Team Merge Rules

> **Purpose:** Document patterns and rules for merging duplicate teams from multiple data sources. Accurate merging is CRITICAL — fragmented game history breaks power rankings.

---

## Why Merging Matters

PitchRank scrapes team/game data from multiple sources (TGS, GotSport, etc.). Each source uses slightly different team naming conventions. If the same team exists as multiple records:

- ❌ Game history gets split across duplicates
- ❌ Power rankings become inaccurate/illegitimate
- ❌ Same team appears multiple times in rankings

**Goal:** One canonical team record per actual team, with all games consolidated.

---

## Merge Statistics (as of Jan 2026)

- **Total merges:** 1,401
- **Primary reviewer:** dallasheidt@gmail.com
- **AI suggestion acceptance:** High (96-100% confidence threshold)

---

## Common Merge Patterns

### 1. CAPS_DIFFERENCE (6%)
Same name, different capitalization.

| Deprecated | Canonical |
|------------|-----------|
| `SS ACADEMY 2014B SELECT` | `SS Academy 2014B Select` |
| `Autobahn SC Boys 2014 gold` | `Autobahn SC Boys 2014 Gold` |
| `B2010 PREMIER` | `B2010 Premier` |

**Rule:** Prefer Title Case. Auto-merge when only caps differ.

### 2. PUNCTUATION_SPACING (34%)
Minor formatting differences (hyphens, spaces, trailing chars).

| Deprecated | Canonical |
|------------|-----------|
| `WAYS Elite G2014 - Ruiz` | `WAYS Elite G2014 Ruiz` |
| `ALBION SC San Diego B14 Academy I` | `ALBION SC San Diego B14 Academy I''` |
| `ELI7E FC- PREMIER 2014` | `ELI7E FC- PREMIER 2014` |

**Rule:** Normalize spacing around hyphens. Remove trailing special chars.

### 3. NAME_VARIATION (60%)
Actual naming differences requiring judgment.

| Deprecated | Canonical | Pattern |
|------------|-----------|---------|
| `Napa United 14/15B Development` | `Napa United 14B Development` | Combined age → single age |
| `East Coast Surf G2016` | `East Coast Surf 2016G` | Gender prefix vs suffix |
| `Phoenix Premier FC 14B Black` | `Phoenix Premier FC 14B SW Black` | Missing region code |
| `Dothan Shockers FC 13/14G` | `Dothan Shockers FC 13/14GC` | Missing division suffix |
| `G13 ACADEMY DPLO - KS*` | `G13 Academy DPLO - KS` | Trailing asterisk + caps |

---

## Decision Rules

### Auto-Merge (High Confidence)
- CAPS only difference → merge
- Punctuation/spacing only → merge
- Extra trailing chars (`*`, `'`, numbers) → merge

### Requires Review
- Different age groups mentioned (14/15 vs 14)
- Missing/extra region codes (Black vs SW Black)
- Different division suffixes (DPL vs DPLO)
- Significantly different team names

### DO NOT Merge
- Different clubs entirely
- Different states (even if same name)
- Different genders
- Different age groups (u14 vs u15)
- **Different squad identifiers** (see below)

---

## Team Name Structure

```
[Club Name] + [Age/Gender] + [Squad Identifier]
```

**Squad identifiers distinguish teams within same club/age:**
- **Roman numerals:** I, II, III, IV, V
- **Colors:** Black, Blue, Red, White, Navy, Gold, Orange, Green
- **Coach names:** Ruiz, Valdez, Smith, Mahe, etc.
- **Divisions:** Premier, Elite, Academy, Select, DPL, DPLO, NPL, GA, MLS Next
- **ECNL tiers:** ECNL ≠ ECNL-RL / RL ≠ Pre-ECNL (all different, need manual review)
- **MLS NEXT / HD / AD:** Cannot auto-match across these divisions (need manual)
- **Regions:** North, South, SW, Central, East, West

**Examples:**
```
Phoenix Premier FC 14B Black  ≠  Phoenix Premier FC 14B Blue    ❌ DIFFERENT TEAMS
Phoenix Premier FC 14B Black  =  Phoenix Premier FC B2014 Black ✅ SAME TEAM
Rebels SC 2014G Premier       ≠  Rebels SC 2014G Academy       ❌ DIFFERENT TEAMS
```

---

## Age Group ↔ Birth Year Mapping (CRITICAL)

Youth soccer uses TWO naming systems interchangeably:

| Birth Year | Age Group |
|------------|-----------|
| 2016 | U10 |
| 2015 | U11 |
| 2014 | U12 |
| 2013 | U13 |
| 2012 | U14 |
| 2011 | U15 |
| 2010 | U16 |
| 2009 | U17 |
| 2008 | U18 |

**All of these refer to the SAME team:**
- `Phoenix Premier FC 2014B`
- `Phoenix Premier FC U12B`
- `Phoenix Premier FC B2014`
- `Phoenix Premier FC 12B`

**CRITICAL: B/G usually means GENDER, not "Boys U-age"**
- `14B` = 2014 Boys = **U12 Male** (birth year!)
- `14G` = 2014 Girls = **U12 Female**
- `U14B` = U14 Boys = **U14 Male** (age group - DIFFERENT!)

The **"U" prefix is the signal:**
- NO "U" → number is birth year
- HAS "U" → number is age group

**Gender equivalents:**
- B = Boys = Male
- G = Girls = Female

**Age normalizer must normalize to:**

**Birth year formats → 4-digit year (gender extracted separately):**
- `12B` / `B12` → `2012` + Male
- `2012B` / `B2012` → `2012` + Male
- `12 Boys` / `2012 Boys` → `2012` + Male
- `G2016` / `2016G` → `2016` + Female

**Age group formats → `U##` (gender extracted separately):**
- `U14B` / `U-14` / `BU14` → `U14` + Male
- `U14` → `U14` (no gender)

**Key principle:** Preserve the original system (birth year vs age group), just strip gender indicators.

---

## Data Sources & Their Quirks

| Source | Common Patterns |
|--------|-----------------|
| TGS | Often has division suffixes (HD, AD) |
| GotSport | Sometimes uses combined ages (14/15) |
| ECNL | Usually clean, standardized names |
| League sources | May have region prefixes |

---

## Process

1. **AI suggests** merge with confidence score
2. **Human reviews** suggestions ≥90% confidence
3. **Merge executes** via `execute_team_merge` RPC
4. **Games consolidated** under canonical team_id_master
5. **Deprecated team** marked `is_deprecated = true`

---

## Future Automation Opportunities

Based on 1,401 merges analyzed:
- ~40% could be auto-merged (CAPS + PUNCTUATION patterns)
- ~60% need human judgment (NAME_VARIATION)

Consider building rules engine for high-confidence auto-merges.
