# Investigation: Team 9da0e6d9-4e0e-40fc-9a86-11adf89eb690 — March 8 Game Imports

## Team Identity (from rankings data)
- **team_id_master:** `9da0e6d9-4e0e-40fc-9a86-11adf89eb690`
- **Age group:** U12
- **Gender:** Male
- **Games played:** 28
- **Status:** Active

## Which Data Sources Could Have Imported Games on March 8, 2026?

March 8, 2026 was a **Sunday**. Four automated workflows were scheduled to run Sunday night → Monday morning:

### 1. GotSport Team Game Scraper (`scrape-games.yml`)
- **Schedule:** Sunday 11:00 PM MT (Monday 6:00 AM UTC)
- **What it does:** Scrapes games for up to 25,000 teams from GotSport API
- **Script:** `scripts/scrape_games.py --provider gotsport --auto-import --limit-teams 25000`
- **Likely source for U12 teams?** YES — GotSport is the primary source for team-level game data

### 2. GotSport Event Scraper (`auto-gotsport-event-scrape.yml`)
- **Schedule:** Sunday 11:00 PM MT (Monday 6:00 AM UTC)
- **What it does:** Discovers and scrapes new GotSport events/tournaments
- **Script:** `scripts/scrape_new_gotsport_events.py`
- **Likely source?** YES — if the team played in a GotSport-listed tournament that weekend

### 3. TGS Event Scraper (`tgs-event-scrape-import.yml`)
- **Schedule:** Sunday 11:30 PM MT (Monday 6:30 AM UTC)
- **What it does:** Scrapes TGS events (range 4050-4150) and imports games
- **Script:** `scripts/scrape_tgs_event.py` → `scripts/import_games_enhanced.py`
- **Likely source?** POSSIBLE — if the team had TGS aliases and played in a TGS event

### 4. Affinity WA Scraper (`wa-scraper.yml`)
- **Schedule:** Sunday 11:00 PM Pacific (Monday 6:00 AM UTC)
- **What it does:** Scrapes Washington state tournaments (U10-U19)
- **Script:** `scripts/scrape_affinity_wa_tournament.py`
- **Likely source?** POSSIBLE — if this is a Washington state team

### Other Possible Sources
- **Manual import** — someone could have run `import_games_enhanced.py` manually
- **Modular11** — disabled for scheduled runs, but could be triggered manually (MLS NEXT league data)

## How to Determine the Exact Source

Run the investigation script on a machine with database access:
```bash
python scripts/investigate_team_march8.py
```

This will show:
1. **Team details** — provider_id tells you which data source created the team
2. **Team aliases** — shows all provider mappings (a team may appear in multiple providers)
3. **March 8 games** — each game has a `provider_id` and `source_url` field
4. **Build logs** — shows which import jobs ran on March 8-9

### Key fields to look at:
- `games.provider_id` → resolves to which provider (GotSport, TGS, etc.)
- `games.source_url` → direct link to the source page
- `games.scraped_at` → when the data was scraped
- `games.created_at` → when the game was inserted into the database
- `build_logs.parameters` → shows the input file and import parameters

## Most Likely Scenario

Given this is a **U12 Male** team:
- **Most likely: GotSport** — the primary source for youth soccer game data, and the `scrape-games.yml` workflow runs weekly for all teams
- **Second likely: GotSport Events** — if the team participated in a weekend tournament
- **Less likely: TGS** — TGS events tend to be larger showcases
- **Possible: Affinity WA** — only if the team is from Washington state
