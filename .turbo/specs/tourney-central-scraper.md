# Tourney Central Tournament Scraper and Importer

**Date:** 2026-10-14
**Status:** Approved 2026-10-14 (plan: `.turbo/plans/tourney-central-scraper.md`)
**Slug:** `tourney-central-scraper`

## Goal

Add Tourney Central (`*.tourneycentral.com`) as a provider. An operator runs one command against
a tournament's address, and it scrapes that tournament's divisions, teams and scored games, links
or creates the teams, and imports the games. The first event is the Warrior Fall Classic
(`https://wfc.tourneycentral.com`, played 2026-10-10 and 10-11).

User decisions, 2026-10-14:

- Scope: "Run per tournament (Recommended)". This means an operator-run command for any one
  tournament, with no schedule. A weekly workflow was offered and not chosen.
- Approach: mirror Athletes2Events (own scraper, matcher and import script, reusing the shared
  name helpers), approved with "ya". The two alternatives were rejected: merging this provider
  and Athletes2Events into one shared tournament importer, and pushing a CSV through the generic
  importer.
- The error handling and testing design below was approved with "go".
- Cross-age games (2026-10-14, while planning): import them and also list them, as
  Athletes2Events and YSSL do. The user said: "Yes, again it doesnt matter if a u12 team is playing
  up in the u13 division. We need to try and identify them as a u12 from their Team name." An
  earlier draft of this spec said to hold them back. That came from a stale line in the
  scraper-patterns skill, and the shipped drivers do the opposite.

## What the source exposes (verified 2026-10-14)

Tourney Central (Rivershark Inc.) hosts 52 tournaments on its calendar
(`https://tourneycentral.com/tournament-calendar`), mostly Ohio and Michigan, one subdomain each.
`wfc`, `buckeyecup`, `copadetroit` and `mumcup` were checked. All four serve the same layout, and
plain `requests` with a browser User-Agent gets through with no proxy and no bot challenge. Pages
declare `charset=ISO-8859-1`.

- **`/games.html`**: the division list, as `<option value="B11Gold">` entries in a
  `select name=t_div`, plus the event's play dates as `<option value="2026-10-10">`. A site shows
  only its current year.
- **Division schedule**: `GET /cgi-bin/teams.cgi?fnc=sked&sny=Y&t_div=<division>` (the page's
  form POSTs the same fields and gets the same page). One
  table holds the games. A day-header row (`Saturday, Oct 10, 2026`) is followed by game rows
  with these columns:
  - `No.`: the game number, unique across the whole event (183 of 183 at WFC)
  - `Div` and `Time`
  - `Field`
  - home team: a link `fnc=sked&t=<team id>`, with a pool seed written into the text
    (`Warrior SC B15/16 White - A4`)
  - home score and away score
  - away team: a link, with the seed written in front (`A2 - Olimpia ...`)
  - an empty column
  - `Type`: blank, or `FINAL`

  A final also carries `Champion` and `Finalist` notes under the team names.
- **Division team list**: `GET /cgi-bin/teams.cgi?fnc=adiv&t_div=<division>`. One row per
  team with these cells:
  - `Bkt`: the pool seed (`A1`)
  - `Team/Location`: the team name in bold, the club in italics, then `City, ST`
  - `Coach` and `Colors`
  - a form carrying `name=t value=<team id>`

  Some rows also carry a `[ + ]` link to the team's website.
- **Team ids are one platform-wide sequence.** None of 444 ids taken from four tournaments
  collide. But a team gets a **new id for each tournament it enters**: Olimpia's WFC and Buckeye
  Cup squads have different ids. So name, club and state matching is the main path on every
  event, and an id lookup will rarely hit.
- **Division codes** read as `<B|G><U-age>[-<U-age>][<n>v<n>]<flight>`:
  - `B11Gold` is Boys U11, flight Gold
  - `B107v7Gold` is Boys U10, 7v7
  - `B129v9Red` is Boys U12, 9v9
  - `B14-15Gold` is Boys U14 and U15 combined
  - `B09Red` is Boys U9

WFC as captured on 2026-10-14:

- 21 divisions, 106 teams, 183 games. Every game is scored, and none has a placeholder team.
- 4 divisions are U9 (`B09Gold`, `B09Red`, `G09Gold`, `G09Red`). They hold 21 teams and 37
  games, which leaves 85 teams and 146 games in scope before matching.
- **7 same-day rematches.** In each one, a pool game and the final share a date and the same two
  teams.

Data quirks seen at WFC, which the parser must survive:

- Locations: `Parkersburg, WV, WV`, `Kettering, OH, QC`, `Marysville, OH, OH`, `dayton/ohio, OH`,
  and `GC Cosmos 2014/2015 white, OH` (a team name typed into the city field).
- A club of `Tournament Only team`.
- Club spellings that differ from PitchRank's: `Elite FC (Oh)` and `Elite FC (OHS)`.
- Typos: `Oakswood United`, `Cincinanti`, `Worthingotn`.
- Graduation years in names: `NWC 2033 Boys Elite (U12)`.
- Two U-ages in one name: `Ohio Fusion SC BU11/U10 Blue`.

## Design

### Components

1. **Provider row.** A migration seeding `providers` with code `tourneycentral`, name
   `Tourney Central` and base URL `https://tourneycentral.com`, using the same
   `ON CONFLICT (code) DO NOTHING` form as `20260919120000_seed_athletes2events_provider.sql`.
   One provider covers every subdomain, because team ids are platform-wide.
2. **Driver: `scripts/import_tourneycentral_event.py`.** It takes `--event-url` (any page on the
   tournament's host), `--execute` (otherwise it is a dry run), and the same output and report
   files as `scripts/import_athletes2events_event.py`. It does the fetching, the parsing, the
   roster build, team registration and the game CSV, then calls the importer.
3. **Matcher: `src/models/tourneycentral_matcher.py`, `TourneyCentralGameMatcher`.** It
   subclasses `Athletes2EventsGameMatcher`, as `YSSLGameMatcher` does, so it inherits the club,
   squad and tier gates, state scoping, the review clamp and the alias write unchanged. It
   overrides the create helper (under the inherited name `_create_new_athletes2events_team`,
   which the parent's `_match_team` calls by name), keeping the team's full name as written
   rather than cutting the club off the front, still gated on `dry_run`. It also overrides
   `_fuzzy_match_team` to gate on the team list's club and, when that matches no candidate, on
   the club as the name writes it. Added during implementation: the live preview showed
   `VASC B12/13` (club field `Valentis`) about to duplicate a stored `VASC B12/13` filed under a
   third club name. The written club itself is the driver's job (see the club rule below).
4. **Pipeline branch.** `EnhancedETLPipeline._ensure_initialized` gains a `tourneycentral`
   branch that constructs the matcher with `dry_run`. Without it, the fallback matcher would
   write during a dry run.
5. **Rematches.** Add `tourneycentral` to `REMATCH_PROVIDERS` in `src/models/game_matcher.py` and
   carry the event-wide game number as `schedule_id`. Without both, the 7 WFC finals that
   replay a pool game collapse into the pool game and their results are lost.
6. **Test registries.** Add the matcher to `AUTOCREATING_MATCHERS`, `REGISTRATION_MATCHERS` and
   the `(provider, cls, create)` list in `tests/unit/test_provider_matcher_dry_run.py`, and to
   `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py`.

### Data flow

1. Read `/games.html` for the division codes and play dates. The **event season** is the
   Aug 1 – Jul 31 season of the earliest play date. The **board season** is
   `_soccer_season_year()`. Keep the two separate, as the scraper-patterns skill requires.
2. Parse each division code into gender, its U-age or U-age pair and its format.
   Leave out a division when:
   - its oldest age is U9 or below, since U9 has no board. This limits which pages are read; it
     never sets a team's age.
   - its format is 6v6 or smaller, which is small-sided play. 7v7 and 9v9 stay in.
   - the code does not parse; it is reported rather than guessed
3. For each division in scope, fetch its team list and then its schedule.
4. **Check the event's label season, across the whole event.** For every team whose name carries
   a two-year band, compare the band's U-age under the event season with its division's age.
   The method is the one under "Reading a Provider's Age Labels" in the scraper-patterns skill.
   - When teams one year below their division outnumber teams at their division's age, the
     event labels by another season. The run then stops before registering anything, and says
     why.
   - With fewer than 5 band-named teams there is no signal, and the check passes.

   This guards spring events that label by the coming season. It runs per event rather than per
   division because a single division is too small to judge. Measured on WFC (2026-10-14), over
   the 17 in-scope divisions the check reads: 28 band-named teams at their division's age and 5
   one year below. `B11White`'s
   only two band-named teams both play up, so a per-division test would have wrongly dropped it.
5. **Build the roster.** Each team row is keyed by its team id and taken from the team list.
   - **Name:** taken from the bold cell, never from the schedule, so seeds like `A2 -` never
     reach a stored name.
   - **Club:** taken from the italic cell, unless that cell is blank or `Tournament Only team`.
     In that case the club comes from `split_club` on the name.
   - **Written club** (what the squad gates strip): the club cell when it opens the name, else
     the words before the first age, a bare band such as `13/14` included. Added during
     implementation. Taking too much stripped `White` from `Warrior SC 13/14 White`, which
     would have created a duplicate. It also stripped `Navy 1` from
     `Worthington United Navy 1 U14`, which would have linked it to a markless
     `WSP Eagle Warriors 2013 Girls`.
   - **State:** if the parts of the location after its first comma name exactly one distinct US
     state code, that is the state. Otherwise the team has no state, and it is left
     out with a reason, as Athletes2Events does. So `Kettering, OH, QC` gives OH.
   - **Coach:** kept on the report only.
6. **Age group comes from the team's own name alone.** It is read through `respell_ages` and
   `age_from_name`, imported from `scripts.import_athletes2events_event` (a packaged import),
   with **no division passed**.
   - The division is neither a bound nor a fallback. The owner's standing rule, restated on
     2026-10-08: "it DOESNT matter what Divison they are in in the tournament at all". An
     earlier draft of this spec used the division as both, which was corrected during
     implementation.
   - The label key decides: a band by its younger year, a single birth year as a band's younger
     year (`G2016` is U11, `WOU B14` is U13 even in a U12 division), a U-age against the event
     season.
   - A name with no age, an odd year span, or two U-ages is left out for a person to decide.
   - `board_cohort` turns the result into the board the team sits on now.
7. **Register teams.** Use the same steps as Athletes2Events:
   - Existing approved aliases first.
   - Then the matcher: link to an existing team, create one with its club and state, or send it
     to review.
   - When two event squads link to one PitchRank team, hold the link as a conflict.
   - Hold off-board links, meaning a linked team whose stored board disagrees with its roster
     row.
8. **Build the games.** Write a game only when:
   - it has both scores
   - both of its teams are on the roster
   - both teams are settled

   A game between teams on different boards (a team playing up) is imported **and** also listed
   in `*_cross_age.csv`, as Athletes2Events does. Each side resolves through its own alias, and
   the rankings read each team's own age group.
   `schedule_id` is `<subdomain>-<game number>`, and `source_url` is the division's schedule.
9. **Import.** Hand the game CSV to the importer with provider `tourneycentral`.
   - A dry run reports everything and writes nothing.
   - `--execute` writes aliases first, then games.
   - Re-running skips stored games as duplicates; see Unready games for why a tournament is
     imported once.

### Errors

- **Pacing.** One request at a time, with a random delay between requests (1–2 s). WFC is 35
  requests (the games page plus two per in-scope division), roughly a minute.
- **Retries.** A connection error or 5xx is retried twice, through the same retry adapter the
  Athletes2Events driver uses. If it still fails, the run stops before registering any team or
  writing anything, so a tournament is never imported half-read. A page that answers 200
  without its table (a team list without its header, a schedule without its `No.` header) stops
  the run the same way. That was added in review: a maintenance page must not read as a
  division with no games.
- **Charset.** Decode pages with the charset they declare in `<meta>`, which `requests` never
  reads. A declared ISO-8859-1 is read as windows-1252, as browsers read it, so a curly
  apostrophe in a team name survives.
- **Unready games.** A game with no score, or with a team cell that has no team link (an
  unfilled bracket slot), is left out and listed among the run's problems. A final whose
  orientation and score repeat its same-day pool game's is lost to the composite key, and once
  the pool game is stored a later run's master-id check also drops a swapped repeat (IMP-213),
  so import a tournament once, after it finishes.
- **Team ids and game numbers.** Read every team id through `clean_provider_id`, and accept only
  ASCII digits of bounded length for ids and game numbers, since both reach database writes.
  A blank or malformed id never reaches an alias.
- **Operator files.** The team report and the cross-age file defang a leading `= + - @`, since
  they carry registrant-typed names and are opened in spreadsheets. The importer's own CSV keeps
  names as written.

### Testing

- **Fixtures.** Saved WFC pages go in `tests/fixtures/tourneycentral/`:
  - `games.html`
  - the team list and schedule of `B11Gold` (a final), `B14-15Gold` (a two-age division),
    `B14-15Red` (a `[ + ]` website link), `G13Gold` (`Tournament Only team`) and `B13Red`
    (`Parkersburg, WV, WV`). The U9 skip is tested from `games.html`.

  The pages hold no credentials. Check them for anything else before committing.
- **Unit tests.**
  - Division-code parsing, including the U9 and small-sided skips and an unparseable code.
  - Location-to-state, covering every quirk listed above.
  - Club fallback.
  - Age from the name alone, including a name older than its division and a nameless age left out.
  - Game parsing: date carry-over from day headers, scores, game numbers, seeds never leaking
    into names.
  - A team id that is `null`/`None` coming out as `""`.
  - The label-season check.
  - Cross-age games: imported and also listed.
  - A rematch pair surviving as two games through `REMATCH_PROVIDERS`.
- **Dry-run tests.** These come from the shared registries, through the registry additions above.
- **Live dry run on WFC.** Before any `--execute`, read the actual output rows, not the summary.
  Report teams linked, created, sent to review, in conflict and left out (with reasons), and
  games to import, with the cross-age ones counted. The user sees those numbers before anything is written.
  The figures in this spec describe the 2026-10-14 capture. If the database or the site has
  moved since, the live run is the baseline, not this document.

## Out of scope

- Any scheduled workflow (the user chose per-tournament runs).
- Moving `age_from_name` and its helpers out of the Athletes2Events driver into a shared module.
  This spec imports them as they are.
- Unplayed fixtures. Only scored games are imported.
- Divisions at U9 and below, and small-sided play.
- Importing the other 51 tournaments. Each one is an operator run after this ships.
