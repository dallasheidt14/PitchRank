# YSSL scraper — spec

Status: approved 2026-10-07; updated 2026-10-08 to match what shipped

## Goal

Import scored games from the Young Sportsmen's Soccer League (YSSL, yssl.org), a Chicago-area
boys league, every week, and link its teams to the IL teams PitchRank already has. Create a new
IL team only when no existing team fits.

Success:
- A weekly run brings in each scored YSSL game once, on both teams' records.
- Most YSSL teams link to an existing PitchRank team. Spot checks show the clubs that appear in
  both sources (Ajax, Chicago Empire, Eclipse, Pegasus, AAC Eagles, WCOB, Berber City) already have
  10–117 IL teams each.
- No duplicate teams are created for clubs PitchRank already carries.

## Owner decisions (2026-10-07)

- Walk the site club by club: `clublinks.php` → `club.php` → `team.php`.
- Every team is IL. *Revised 2026-10-07:* four YSSL clubs are Indiana clubs in PitchRank (NWI Lions,
  Millennium, Rangers Academy, BVB Waterloo); the owner chose a per-club state in the club map, IL by default.
- Run weekly on a schedule.
- Import played (scored) games only. No unplayed fixtures.
- Match on club name, team name, state and age group.

## What the site exposes (probed 2026-10-07)

Plain server-rendered HTML. A browser User-Agent works, with no proxy, no bot challenge and no ZenRows.

| Page | Contents |
|---|---|
| `clublinks.php` | 136 links `club.php?clu_code=<CODE>` (3-letter codes, e.g. `AAC`) |
| `club.php?clu_code=<CODE>` | Club display name (`AAC EAGLES CHICAGO`); "Fall 2026 Teams": per team a `team.php?tea_id=<n>` link whose text is `<division> <team name>` (`U12/1 AAC EAGLES CHICAGO 14/15 GOLD`), then the team code (`AACM121`) and contact. 2–72 teams per club. |
| `team.php?tea_id=<n>` | Team name, team code, club, coaches. Then a games table: `Num`, `Date/Time` (a changed game shows two dates: the **first is the actual date** and the second the original, confirmed because a played game's result exists while its second date is still in the future), opponent link `team.php?tea_num=<code>` + name, `H/A`, field, `Result` written **from this team's side** (sums match the page's GF/GA). Record, GF, GA. |

- Team code `AACM121`: club code + gender letter (`M` in all 122 sampled) + U-age digits + squad
  index. The U-age changes every Aug 1, so a code lasts one season year.
- `tea_id` looks reissued per season, so it is not used as identity.
- Team names carry a two-year band (`14/15`, `2014/15`, `18/19B`). Divisions read `U12/1`,
  `U08-5V5/4S`, `U07-4V4/E`.
- Only the current season is visible, with no archive.

## Design

### 1. Scraper — `scripts/import_yssl.py` (scrape, roster pass and import in one driver)

- Walk clubs → teams → team pages, sequentially, at a random 1–2 s between requests (single
  process). That is about 1,200 requests and 30–40 min per run.
- Decode as UTF-8 when no charset is declared (scraper-patterns: *Decoding an HTML response*).
- Per team, record: team code, `tea_id`, team name, club code, club display name, division.
- Per game, keep a row only when `Result` holds a score. Use the first (actual) date and parse the
  year from the season: fall dates belong to the season's start year, spring dates to the
  following year.
- Deduplicate by YSSL game number (each game appears on both teams' pages). Orient each kept row
  by its `H/A` so home and away are correct, and check the two pages' scores agree. When they
  disagree, report the game and hold it back.
- Filter to `--days-back` (default 14) by game date.
- Write the CSV in the importer's whitelist columns (`provider`, `team_id`, `opponent_id`,
  names, `goals_for/against`, `game_date`, `home_away`, `club_name`, `state_code` (the club's, IL by default),
  `age_group`, `gender`, `source_url`). Check `import_games_enhanced.py`'s two loaders: a column
  not on both whitelists is dropped silently.
- `--club` (repeatable) limits a pilot to named clubs.

### 2. Reading a team

- **Age** comes from the band in the team name, using the CLAUDE.md label key (younger year names
  the band: `14/15` → U12). A band-named team playing up is filed by its band (owner,
  2026-09-18). The division's U-age is used only when the name has no band. Teams below U10 are
  left out with a reason, as Athletes2Events does. They have no board.
- **Gender** comes from the team code's letter (`M` → Male, `F` → Female), except that a name
  saying `GIRLS` is filed Female (owner, 2026-10-07).
- **State** is the club map row's `state_code`, IL when blank (see *Open risk* on `state_source`).

### 3. Club map — `config/yssl_club_map.csv` (one-time, reviewed; `data/` is gitignored)

YSSL abbreviates clubs and splits some into branches (`ECLIPSE` vs "Eclipse Select Soccer Club";
`RUSH NORTH`, `RUSH OSWEGO`, `RUSH - WILMETTE WINGS` vs "Chicago Rush Soccer Club" / "Chicago Rush
North Shore" / "Gateway Rush Soccer Club"; `CFYSC` with no obvious match). Matching with the wrong
club either misses real links or links two clubs' squads.

- Columns: `yssl_code, yssl_name, team_prefix, pitchrank_club_name, state_code, decided_by, note`. A row with a
  `team_prefix` (`RUSH NORTH`) claims the teams of that club code whose names start with it, ahead
  of the club's own row, so a branch can map to its own PitchRank club.
- A helper proposes `pitchrank_club_name` from existing IL club names. Exact and normalized-equal
  names are auto-filled. Everything else goes to the owner as a short list with candidates, per
  the rule that **club branches are separate clubs** (never merge by name prefix).
- For a YSSL club with no PitchRank club, the owner writes the name to create it under. A blank
  name always means *undecided*, never "no club".
- A club code with no decided row has its teams left out. Every other club still imports, and
  the run exits 1 so the workflow goes red. A new club is never matched blind.

### 4. Matcher — `src/models/yssl_matcher.py`

A thin subclass of `Athletes2EventsGameMatcher`, driven by a roster pass in
`scripts/import_yssl.py`, as Athletes2Events is. The game import is then alias-only. The subclass
overrides `_match_team` and `_fetch_candidates` (a candidate must carry every squad, branch or
location word of the YSSL name, and the same squad number) and team creation, so a created team
keeps its full YSSL name:

1. **Direct id**: an approved `team_alias_map` row for the team code.
2. **Fuzzy**: candidates are in the club's state, same gender, same age group, and the mapped PitchRank club.
   Gate with the shared helpers in `tournament_name_gates.py` (club stripped from both names,
   squad marks, tiers with `tier_extra` bound, colors, locations such as Darien/Naperville).
   Break ties by exact name, otherwise send to review.
   - ≥ 0.90 → link (`fuzzy_auto`); 0.75–0.90 → review queue (clamped to 0.89); below → create.
   - Two YSSL teams landing on one PitchRank team is a conflict: every fuzzy-linked team of the
     pair is held (no alias, no queue row, games held back) and the run exits 1.
3. **Create**: a new team with club, age, gender, the club's `state_code`, plus a `direct_id` alias. The
   alias is written in `_match_team`, not the create helper.

The matcher gates every write on `dry_run`, with its own branch in
`EnhancedETLPipeline._ensure_initialized`, and is added to the three hand-written test registries
(`AUTOCREATING_MATCHERS`, the create-helper parametrize list, `_SUBCLASS_PATHS`).

**Season rollover:** on Aug 1 each team code passes to the next cohort's squad, so the provider
team id is the code scoped to its season (`2026-AACM121`). A new season's ids start unlinked and
re-match by name onto the right teams; a bare code would have carried last season's link onto a
different squad (final review, 2026-10-07).

### 5. Provider row

Migration `supabase/migrations/<ts>_seed_yssl_provider.sql` seeds `providers` with
(`yssl`, `YSSL`, `https://www.yssl.org`), mirroring `20260911120000_seed_affinity_or_provider.sql`.

### 6. Weekly workflow — `.github/workflows/yssl-scraper.yml`

- Monday 08:15 UTC with a season-to-date window (120 days), so a game held while its team waits in
  review imports after the review. Runs before data hygiene (11:00) and rankings (12:30), plus `workflow_dispatch`
  with `days_back` and `dry_run`.
- One step runs `import_yssl.py`, which scrapes, registers teams and runs
  `import_games_enhanced.py <csv> yssl`; the CSVs upload as an artifact.
- The import step is gated by `AGE_ROLLOVER_FREEZE == 'false'` and added to the rollover-freeze
  coverage lists and CLAUDE.md's list of gated workflows.
- Concurrency lock. The step fails when the scrape finds zero scored games in-season, because a
  green, empty run must not pass silently.

### 7. Pilot before the schedule

1. Run a dry run on 3–5 clubs (including Eclipse and one Rush branch). Report linked / review /
   created counts and read the real rows.
2. Owner reviews the club map and the pilot output.
3. Do a full backfill of the current season (`--days-back` covering Aug 1 onward).
4. Turn on the cron.

## Testing

- Fixtures: saved copies of `clublinks.php`, two club pages and one team page. Cover a
  rescheduled game, an unplayed game, a home and an away game, and a U7 small-sided team.
- Parser tests assert literal values: a game's date, score orientation, team code → gender, and
  band → age group.
- Dedup test: the same game from both teams' pages produces one row, and a score disagreement
  holds the game back.
- Matcher tests cover a direct id, an auto-link, a review, a create, and a two-teams-one-target
  conflict. The dry-run test asserts no insert.
- Import composition test: drive the scrape → CSV → pipeline with doubles, and assert the
  `state_code` and `club_name` columns reach the matcher.

## Out of scope

- Unplayed fixtures.
- Past seasons, which the site does not expose.
- Coaches and contacts. They are not stored.

## Open risk

- The club map's state is stamped without `state_source`, the same gap the backlog tracks for
  WA/OR/PlayMetrics. Follow whatever that entry settles on, and note the new provider on it.
- `tea_num` stability between fall and spring is unverified. A team given a new code in spring
  re-matches by name, which costs only review-queue volume. A code passed to a different squad
  keeps its fall link, because spring shares the fall season's scoped id; only an age or gender
  change is caught (`off_board_links`).
