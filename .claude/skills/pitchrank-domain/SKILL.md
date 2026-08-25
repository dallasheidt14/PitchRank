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

### Birth Year to Age

> Canonical: CLAUDE.md "### Age Groups (2026-27 Season)". The birth-year table, the
> `14B` / `U14B` / `G2016` shorthands and the U18-into-U19 rule all live there, and
> `tests/unit/test_agent_doc_references.py` pins that table to
> `calculate_age_group_from_birth_year`. CLAUDE.md is always loaded, so it is in context
> whenever this skill is.

Do not re-add a copy here. The last one drifted — still reading "26,442 `u19`" after
CLAUDE.md's count was corrected — and it made every Aug 1 rollover a two-file edit. This
skill adds only the season-arithmetic trap below.

### Season-year vs calendar-year trap

Cohorts roll on Aug 1; the calendar rolls on Jan 1. Year-offset cohort arithmetic computed
from the *calendar* year (`date.today().year - 9`) names the wrong cohort from Aug 1 to
Dec 31 — inside that window it points at real U10 (2017-born) teams while labelled "U9",
silently excluding them from scraping.

Derive from the season instead. `scrape_excluded_birth_years` in `src/utils/team_utils.py`
does it, off `_soccer_season_year()`, and is already what both Python callers use
(`scripts/drain_queue.py`, `scripts/scrape_games.py`); the scrape-eligibility RPCs mirror
the same offsets in SQL via `now() - interval '7 months'` (migration
`supabase/migrations/20260824120000_scrape_eligibility_uses_season_year.sql`). Call the
helper rather than recomputing an offset, and change the SQL with it if the range moves.

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
- Rate limit: env-overridable, and the two scraper classes default differently — read `GOTSPORT_DELAY_MIN` / `GOTSPORT_DELAY_MAX` in `src/scrapers/gotsport.py`
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
| `current_rankings` | Legacy rankings table the ranking run writes (a table, not a view over `rankings_full`) |
| `team_alias_map` | Provider ID → Master ID mapping |
| `quarantine_games` / `quarantine_teams` | Rows rejected at import (games are quarantined, never edited) |
| `team_match_review_queue` | Uncertain team matches awaiting review (0.75–0.90 confidence) |
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
