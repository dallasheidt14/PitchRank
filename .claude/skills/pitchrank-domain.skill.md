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

### Birth Year to Age (2026 Season)
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

### Common Formats
- `14B` = 2014 birth year, Boys = **U12 Male**
- `U14B` = U14 age group, Boys = **U14 Male**
- `G2016` = Girls, 2016 birth year = **U10 Female**

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

### v53e Engine
1. Base score from win/loss/draw records
2. Strength of Schedule (SOS) - 3 iterations
3. Goal differential (capped)
4. Recency weighting (recent games matter more)

### ML Layer 13
- XGBoost model for predictive adjustment
- Trained on historical outcomes
- Adjusts base v53e scores

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
