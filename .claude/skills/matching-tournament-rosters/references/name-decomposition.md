# Name decomposition

Splitting a roster team name into club, league tokens, cohort token and qualifier, and matching
each part against how the database actually spells it.

## Contents

- The two name columns
- What normalisation removes
- Cohort tokens
- League and flight tokens
- The qualifier tail
- Matching the club
- Accents, punctuation and acronyms
- Reusing the repo's parser

## The two name columns

`teams.team_name_original` holds the provider's literal registration string. `teams.team_name` is
the normalised form — **but only on rows that carry an original**. Where no original was recorded,
no normalisation was recorded either, and `team_name` is whatever the provider sent.

| | share of rows | `team_name` still carries a gender token |
|---|---|---|
| has `team_name_original` | ~56% | ~1% |
| `team_name_original` IS NULL | ~44% | ~23% |

Nearly everything created since the last rollover falls in the second row. So for current-season
work the registered string often survives in `team_name` intact, gender letter and all, and
`team_name_original` is NULL exactly when you would most want it.

```
team_name                team_name_original          gender
DS Stars 2014 Maroon     DS Stars 14B Maroon         Male
DS Stars STXCL WC U13    DS Stars STXCL WC GU13      Female
West Texas Toros FC 2014 West Texas Toros FC 14B     Male
DS Stars STXCL WC GU11   (null)                      Female
```

Consequences:

- Search the roster string against `team_name` both verbatim and in normalised form.
- Retrieve on `team_name` regardless — it is the only trigram-indexed column
  (`idx_teams_name_lookup`, GIN). `ILIKE '%x%'` on `team_name_original` is a sequential scan around
  thirty times slower; on `club_name` it is a full index-only scan around fifty-five times slower,
  because `club_name` is only the leading column of a btree that a leading wildcard cannot use.
- Read `team_name_original` from the rows already fetched. Where it exists it is the authoritative
  gender and cohort check; a NULL is no evidence either way.
- Where an original does exist, the gender token is gone from `team_name` on essentially every row
  that carried one — so two rows can share an identical `team_name` and differ only in gender.

## What normalisation removes

Where it ran, normalisation strips the gender letter, expands a 2-digit year to 4, and deletes the
standalone words `Boys` and `Girls` **anywhere in the string, including inside the club name**:

```
Girls Unite - Girls Unite 2016G Impact Gray   ->  Unite - Unite 2016 Impact Gray
Bowie Boys and Girls Club - Bowie FC 2014B W  ->  Bowie and Club - Bowie FC 2014 W
New York City FC Girls - NYCFC Girls 2016 S   ->  New York City FC - NYCFC 2016 S
```

Nearly every original containing the word loses it. Parenthesised tails such as `(Female)` and
`(11u)` go too.

This is load-bearing: if the roster club contains `Boys` or `Girls`, strip it from the needle before
probing `team_name`, or the club probe returns nothing for exactly those clubs.

## Cohort tokens

A roster's cohort token names a birth year through the season that wrote it. Convert first:

```
age = season_end_year - birth_year        # U18 folds into U19
birth_year = season_end_year - age
```

Then search every spelling that birth year takes. Across the table as a whole the bare 4-digit
younger year dominates and U-age forms are comparatively rare.

Shapes to expand into, most specific first:

| Shape | Pattern | Example |
|---|---|---|
| `B2013/14` | `\y[BG](19\|20)[0-9]{2}/[0-9]{2}\y` | |
| `2013/14B` | `\y(19\|20)[0-9]{2}/[0-9]{2}[BG]\y` | `ALBION SC Dallas 2013/14B GP EA` |
| `B13/14` | `\y[BG][0-9]{2}/[0-9]{2}\y` | `FC Westlake STXCL WC B15/14 Blue` |
| `13/14B` | `\y[0-9]{2}/[0-9]{2}[BG]\y` | `Solar East 13/14B Hedges` |
| `BU13` | `\y[BG]U[0-9]{1,2}\y` | `FC Westlake Blue STXCL WC BU13` |
| `U13B` | `\yU[0-9]{1,2}[BG]\y` | |
| `B2014` | `\y[BG]-?(19\|20)[0-9]{2}\y` | |
| `2014G` | `\y(19\|20)[0-9]{2}[BG]\y` | |
| `B14` / `14B` | `\y[BG][0-9]{2}\y` / `\y[0-9]{2}[BG]\y` | `West Texas Toros FC 14B` |
| bare year | `\y(19\|20)[0-9]{2}\y` | `DS Stars 2014 Maroon` |
| bare U-age | `\yU[0-9]{1,2}\y` | `DS Stars STXCL WC U13` |

Rows created since the last rollover have largely shed the birth-year token — around a tenth carry a
4-digit year against roughly seven in ten of older rows — but they mostly replaced it with nothing.
More than half carry **no cohort token at all**, about a quarter carry some U-age form, and under a
tenth the `BU13` style. Do not expect to find a current-season row by its cohort token, and do not
read the token's absence as a mismatch.

Two-birth-year bands are named by the **younger** year, but the stored data follows that rule only
about half the time — and for names carrying two full 4-digit years it usually follows the older
year instead. Use the rule to rank candidates and never to exclude them.

## League and flight tokens

Strip these before comparing, longest match first, case-insensitively. `Pre` / `PRE` / `Pre-` is a
productive prefix on any of them, sometimes with no separator at all (`PreRL`), and hyphenated
sub-flights follow the same shape (`ECNL-RL`, `NAL-GR`, `E64-RL`).

```
STXCL WC | STXCL EC | STXCL
ECNL RL | ECNL-RL | ECNLRL | ECRL | ECNL
MLS NEXT | NEXT LEVEL
NAL | NAL-GR | EA2 | EA | NL
EDPL | EDP | SCCL | WFPL | TCSL
DPLO | DPL | NPL | OPDL | ODP
E64 | E64-RL | LIJSL | AYSO | COPA | ASPIRE | RCL
NTX | STX | WTX | ETX | HTX
N1 | N2 | D1 | D2
GA | HD | AD | RL
PREMIER | CLASSIC | SELECT | ELITE | ACADEMY
```

`NAL`, `EA`, `NL`, `EDP`, `SCCL`, `ECRL`, `WFPL`, `TCSL` and `D2` are all common and easy to miss.
`EA` and `NL` are two letters and will otherwise be read as an initial or a state code. `GA`
collides with the state abbreviation — require league context. `SELECT`, `ELITE`, `PREMIER` and
`ACADEMY` are tier words that also appear inside club names, which is a live source of false tier
mismatches when the club is literally named after one. `SECL`, `WDDOA` and `CTPL` are absent or
near-absent from stored names; leave them out.

`STXCL` carries a `WC`/`EC` sub-flight on a slim majority of its occurrences; the rest put the
cohort token straight after `STXCL`. Treat the sub-flight as optional in either direction, or the
cohort year gets mis-slotted as the flight.

A roster stacks league tokens (`ECNL RL STXCL`) that the stored row keeps only one of, and colour
and league frequently do not co-occur on the same stored row. Score league tokens as optional
evidence. Requiring all of them returns nothing.

## The qualifier tail

The last token of a name, classified across the whole table:

| Class | Share | Weight |
|---|---|---|
| Surname / mascot / other word | ~34% | Highest — a globally unique tail is near-definitive |
| Cohort token | ~22% | None, already handled |
| Colour | ~22% | Weak on its own; clubs run several colours per cohort |
| League / flight | ~12% | Weak, already stripped |
| Number or roman numeral | ~6% | Strong as a *distinguisher* — `II` means a second squad |
| Directional | ~1% | Negligible, not worth special-casing |

Roughly one team in ten has a tail token that occurs nowhere else in the table. When the roster
supplies one — `Hedges`, `Woodberry`, `Nunez`, `Shaffer` — search on it first and the cohort last.
A tail appearing on thousands of rows is a colour or a league word and carries nothing.

`teams.distinction` holds the same qualifier tokens, lowercase and pipe-delimited, but it is unset
on a third of rows and on essentially every fresh row, so it supplements the name rather than
replacing it.

## Matching the club

There is no clubs table. `club_name` is free text with thousands of distinct values, and the
variance is semantic rather than typographic — squashing case and punctuation collapses almost
nothing. One real club routinely occupies several unrelated strings:

```
Laredo Youth Soccer Assn
Mortega SC
Mortega Soccer Club Laredo Youth Soccer Academy
```

All three are the same club. Meanwhile that club's teams are named `Rayados Pflugerville`, which
shares no trigram with any of them.

So:

- Probe `team_name` and `club_name` independently and union the results. Scoring their concatenation
  averages the signal away.
- Accept that one club spans several `club_name` strings; union them rather than picking the single
  best string and filtering to it.
- `club_name` is absent from `team_name` on roughly half of rows, and is itself NULL or empty on a
  large share of fresh rows. Any `club_name ILIKE` predicate is an implicit NOT NULL filter that
  removes the newest rows first.
- `src/utils/club_normalizer.py` is DB-free and offers `are_same_club()` and `group_by_club()`
  against a canonical-club registry. Its confidence of 0.8 with `matched_canonical=False` means *no
  club was identified*, not "80% sure".

## Accents, punctuation and acronyms

`unaccent`, `fuzzystrmatch` and `citext` are **not installed**. pg_trgm is the only text extension
available, and the skill cannot install more. All accent folding, punctuation stripping and
abbreviation expansion happens in Python before the query is built.

The database holds both spellings, sometimes on the same row — `team_name` "Barça Academy Chicago
2012" with `club_name` "Barca Academy Chicago". Behaviour differs per operator: `%` bridges
Barca/Barça, `<%` does not at its default threshold, and `ILIKE` never does. Expand the needle
client-side into an explicit OR of both spellings rather than trusting any operator to bridge it.

Trigram similarity cannot bridge an acronym at all — `DKSC` against `Dallas Kicks SC` scores about
0.11, below every threshold, and no tuning will connect them. Roughly one club in seven is an
acronym or acronym-led. Build the initialism of the roster club's significant words and probe it as
a separate literal candidate. Strip a parenthesised state suffix (`Legends FC (CA)`) before
comparing.

Before scoring, remove generic words from the needle: `FC`, `SC`, `UNITED`, `ACADEMY`, `SOCCER`,
`CLUB`, `ELITE`, `PREMIER`. They are what a fabricated club name matches on.

Names also carry leading and trailing junk and a duplicated club prefix that both need stripping:

```
***GALACTICOS 2012/13 BLUE***
- 2010 EA
West Texas Toros FC - West Texas Toros FC 2016
```

## Reusing the repo's parser

`src/utils/team_name_utils.py` imports only `re`, `typing` and `src.utils.team_utils` at module
level, plus a lazy `src.utils.us_states` inside one function. Nothing touches the database, so it
needs no credentials and is the right substrate for offline parsing:

| Function | Use |
|---|---|
| `birth_years(name)` | Birth years from a name. Pass the **raw** name — it strips U-age tokens first, and normalising beforehand rewrites band labels into single wrong years |
| `birth_years_conflict(a, b)` | Subset test, the ready-made hard reject for same club, different year |
| `extract_distinctions(name)` | One positional argument. Returns colors, directions, programs, team_number, location_codes, state_codes, squad_words, age_tokens, secondary_nums and `coach_name`. `coach_name` is the parsed surname tail — use it before hand-rolling a tail heuristic |
| `resolve_distinction(name, club_name=, state_code=)` | The same distinguishers collapsed into one pipe-joined string with club tokens stripped. This is the form stored in `teams.distinction` |
| `normalize_name_for_matching(name)` | Comparison form |
| `extract_club_from_team_name(name)` | Club guess from a team name |
| `_UAGE_TOKEN` | The U-age regex. Covers the gender-affixed forms (`GU11`, `U11G`, `BU12`), the spelled-out and spaced ones (`Under 11`, `U 11`), and a U-led band whole (`U13/14`, `U17/18/19B`). Not the reverse-token spelling: `13/14U` matches from `14U` only |

`calculate_age_group_from_birth_year()` in `src/utils/team_utils.py` returns **uppercase** `U12`
while `teams.age_group` stores lowercase `u12`. Compare lowercased, or the query silently returns
nothing. Its `CURRENT_YEAR` is evaluated once at import, so a process running across a rollover keeps
the previous season's map.

Leave `scripts/fix_team_age_groups.extract_birth_year` alone. It is the most parser-complete
extractor in the repo and it takes the **older** year of a band, which is the wrong rule; its own
docstring says so and both its callers gate it off.
