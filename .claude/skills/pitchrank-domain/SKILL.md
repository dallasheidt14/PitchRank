---
name: pitchrank-domain
description: Youth soccer domain knowledge for PitchRank - age groups, providers, team structure, ranking concepts
---

# PitchRank Domain Knowledge

You are working on PitchRank, a youth soccer ranking platform. This skill teaches you the domain.

## Age Groups

### U-Age Format
- U10, U11, U12, U13, U14, U15, U16, U17, U18, U19
- "U" = "Under" (U14 = Under 14 years old)

### Birth Year to Age (2026-27 Season)

Rolled over on 2026-08-01. Seasons run Aug 1 - Jul 31, so every cohort moves up
one each Aug 1 and this table is only valid for the season named above. Check
the current season before trusting any birth-year mapping you find in code
comments or docs.

| Birth years (Aug 1 - Jul 31) | Real-world | PitchRank |
|---|---|---|
| 2018 / 2017 | U9  | u9 |
| 2017 / 2016 | U10 | u10 |
| 2016 / 2015 | U11 | u11 |
| 2015 / 2014 | U12 | u12 |
| 2014 / 2013 | U13 | u13 |
| 2013 / 2012 | U14 | u14 |
| 2012 / 2011 | U15 | u15 |
| 2011 / 2010 | U16 | u16 |
| 2010 / 2009 | U17 | u17 |
| 2009 / 2008 | U18 | **u19** (merged) |
| 2008 / 2007 | U19 | u19 |

A cohort's birth window runs Aug 1 - Jul 31, so it spans two calendar years.
The band is named by its **younger** year; `calculate_age_group_from_birth_year(2016)` is `U11`
because 2026 − 2016 + 1 = 11. Reading a `2015/2016` division from the older year gives U12 and is wrong.

PitchRank deliberately files U18 into U19 rather than running a separate U18
board, so 2009 resolves to `u19`. There are 0 `u18` teams and 26,442 `u19`.
Do not "fix" this by splitting the cohort.

### Common Formats
- `14B` = 2014 birth year, Boys = **U13 Male**
- `U14B` = U14 age group, Boys = **U14 Male**
- `G2016` = Girls, 2016 birth year = **U11 Female**

**CRITICAL**: B/G = Gender (Boys/Girls), NOT part of age number!

## Gender

### Normalization
| Input | Normalized |
|-------|------------|
| B, Boys, Boy, Male, M | Male |
| G, Girls, Girl, Female, F | Female |

## Data Providers

### Primary: GotSport
- Largest dataset (25K+ teams)
- Provider code: `gotsport`
- Rate limit: 0.1-2.5 sec between requests
- Primary source of team schedules

### Secondary: TGS (Total Global Sports)
- Provider code: `tgs`
- Event IDs: 4050-4150 range
- Tournament-focused

### Tertiary: Modular11
- Provider code: `modular11`
- Tournament data
- Divisions: HD (High Division), AD (Academy Division)

### Other: SincSports
- Provider code: `sincsports`
- Supplementary source

## Division Tiers (CRITICAL)

### ECNL vs ECNL-RL
- **ECNL** = Elite Clubs National League (TOP tier)
- **ECNL-RL** = ECNL Regional League (SECOND tier)
- **These are DIFFERENT tiers - never merge teams across them!**

### MLS NEXT Divisions
- **HD** = High Division (top)
- **AD** = Academy Division (lower)
- **These are DIFFERENT - never merge across divisions!**

### Other Leagues
- DPL = Development Player League
- NPL = National Premier League
- GA = Girls Academy
- Premier, Elite, Select, Classic = club-specific tiers

## Team Structure

### Team Name Components
```
[Club Name] [Age/Year] [Gender] [Squad Identifier]
Example: "Phoenix Premier FC 14B Black"
         └─ Club ─┘    └Age┘└G┘ └Squad┘
```

### Squad Identifiers
- **Colors**: Black, Blue, Red, White, Gold, Navy
- **Numbers**: I, II, III (Roman numerals)
- **Regions**: North, South, East, West
- **Coaches**: Sometimes "- C. Smith" suffix

## Ranking Algorithm

### Glicko-2 Engine (production; v53e is legacy, reachable only via `--engine v53e`)
1. Two-pass Glicko-2 convergence per (age, gender) cohort; log-margin outcomes, goal
   difference capped at 6, recency-weighted inside the convergence loop
2. Strength of Schedule from opponent mu (repeat cap, trim) with SCF dampening for regional bubbles
3. Within-cohort sigmoid normalization → PowerScore, then age anchors for cross-age scale

### ML Layer 13
- XGBoost model for predictive adjustment
- Trained on historical outcomes
- Adjusts the Glicko-2 PowerScore (`powerscore_adj` → `powerscore_ml`)

### PowerScore
- Final ranking metric
- Range: **0.0 to 1.0** (always!)
- Higher = better team
- Calculated weekly

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `games` | Individual game records (immutable) |
| `teams` | Master team registry |
| `rankings_full` | Current rankings with all metrics |
| `current_rankings` | Legacy compatibility view |
| `team_alias_map` | Provider ID → Master ID mapping |
| `team_quarantine` | Unmatched teams awaiting review |
| `team_merge_map` | Deprecated → Canonical team mapping |

## Game Identification

### game_uid
- Deterministic hash of game properties
- Prevents duplicate imports
- Format: Hash of (provider, teams, date, score)

### Immutability
- Games are NEVER updated after import
- Wrong data → quarantine, not edit
- Preserves audit trail

## State Codes
- Standard 2-letter US state codes
- All 50 states + DC supported
- Teams belong to one state (by club location)

## Seasons
- Soccer season: August → May
- Rankings use 365-day lookback window
- Weekly recalculation every Monday
