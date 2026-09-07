# Search recipes

Query patterns for candidate retrieval, absence testing, verification and tie-breaking.

## Contents

- pg_trgm, as it actually behaves
- Candidate retrieval
- Batched retrieval for a large roster
- Testing for absence
- Verifying a candidate from fixtures
- The ingest clock
- Finding an unnamed row that already holds the fixtures
- Season-crossing links
- Tie-breaking
- Query hygiene

## pg_trgm, as it actually behaves

pg_trgm is the only text extension installed. `unaccent`, `fuzzystrmatch` and `citext` are not, so
`levenshtein()` and `unaccent()` both fail.

**`SET pg_trgm.*` does not survive to the next call.** A `SET` and a read in one statement work; the
next call reports the parameter as unrecognised — a fresh session where the module is not loaded.
Tuning the threshold in one call and querying in the next silently gets the defaults, with no error.
Write thresholds as explicit predicates instead.

**`%` is length-sensitive and fails the verbose-club case.** `'Mortega SC' % 'Mortega Soccer Club
Laredo Youth Soccer Academy'` is false — similarity ~0.21, under the 0.3 default. Word similarity
handles it (~0.82) but is **directional**: the short needle must be on the left.

Use the operator so the GIN index drives the query, and an explicit function call to control the
cut, in the same statement:

```sql
SELECT team_id_master, team_name, club_name, gender, age_group, state_code,
       is_deprecated, created_at,
       GREATEST(word_similarity(:needle, team_name),
                word_similarity(team_name, :needle)) AS wsim
FROM teams
WHERE :needle <% team_name                          -- index-driven
  AND GREATEST(word_similarity(:needle, team_name),
               word_similarity(team_name, :needle)) > 0.45
ORDER BY wsim DESC
LIMIT 200;
```

`GREATEST` of both directions removes the direction trap. The function form alone does not use the
index, so both the operator and the function are needed.

Retrieve on `team_name` — see [name-decomposition.md](name-decomposition.md) for why the other name
columns are not viable retrieval targets.

## Candidate retrieval

Attributes are SELECTed for scoring, never filtered on.

```sql
SELECT t.team_id_master, t.team_name, t.team_name_original, t.club_name,
       t.gender, t.age_group, t.state_code, t.is_deprecated,
       t.created_at::date, t.provider_team_id
FROM teams t
WHERE t.team_name ILIKE '%' || :distinctive_token || '%'
ORDER BY similarity(t.team_name, :full_roster_name) DESC
LIMIT 200;
```

Run this once per distinctive token — the qualifier tail first, then the club token — and union the
results. Then run the club probe separately, because a club's identifying word is missing from
`team_name` on about half of rows:

```sql
SELECT t.team_id_master, t.team_name, t.club_name, t.gender, t.age_group, t.state_code
FROM teams t
WHERE t.club_name ILIKE '%' || :club_token || '%'
LIMIT 200;
```

Union, never intersect. For the Mortega-shaped case the roster club and the stored `team_name` share
literally nothing, so a team-name search scores zero while a club-name search finds the rows — and
vice versa for clubs whose teams are named after the club.

Expand the cohort token into every spelling before searching, and widen `age_group` only when
ranking:

```sql
-- roster says "B2013/14" -> birth years 2013 and 2014 -> cohorts u14 and u13
SELECT team_id_master, team_name, age_group, gender, state_code, club_name
FROM teams
WHERE team_name ~* '\y(2013|2014|13|14|B2013|B2014|B13|B14|BU13|BU14|U13|U14|2013/14|13/14)\y';
```

## Batched retrieval for a large roster

One pool per cohort and gender, all the roster's distinctive tokens in a single pass, scored in
Python afterwards:

```sql
SELECT t.team_id_master, t.team_name, t.team_name_original, t.club_name,
       t.gender, t.age_group, t.state_code, t.is_deprecated, t.created_at::date
FROM teams t
WHERE t.age_group = ANY(:cohorts)
  AND EXISTS (
        SELECT 1 FROM unnest(:tokens::text[]) tok
        WHERE t.team_name ILIKE '%' || tok || '%'
           OR t.club_name ILIKE '%' || tok || '%'
      );
```

`:cohorts` is the believed cohort plus one either side. This is the one place a cohort predicate is
acceptable, because it bounds the pool rather than selecting the answer — keep it wide, and never
add gender or state to it.

## Testing for absence

`%` never returns empty. A fabricated club name returns hundreds of rows, every one a generic-word
collision on `United` / `FC` / `SC`, all scoring identically. An agent that reports its top hit
emits a confident false match for a club we do not hold.

Decide absence with a word-similarity probe or ILIKE on the single most distinctive token, across
all three name columns:

```sql
SELECT count(*) FILTER (WHERE team_name  ILIKE '%' || :token || '%') AS by_team_name,
       count(*) FILTER (WHERE team_name_original ILIKE '%' || :token || '%') AS by_original,
       count(*) FILTER (WHERE club_name  ILIKE '%' || :token || '%') AS by_club
FROM teams;
```

Strip generic words from the needle first — `FC`, `SC`, `UNITED`, `ACADEMY`, `SOCCER`, `CLUB`,
`ELITE`, `PREMIER` — and strip `Boys`/`Girls`, which normalisation deletes from stored names. Zero
across all three columns is absence. A non-zero `by_club` with zero elsewhere means the club exists
but this squad does not.

## Verifying a candidate from fixtures

`games.division_name` is empty on current-season rows — filter on `competition`.

```sql
SELECT g.game_date, g.competition, g.division_name,
       CASE WHEN g.home_team_master_id = :id THEN 'H' ELSE 'A' END AS side,
       COALESCE(oh.team_name, oa.team_name) AS opponent,
       g.home_score, g.away_score
FROM games g
LEFT JOIN teams oh ON oh.team_id_master = g.away_team_master_id AND g.home_team_master_id = :id
LEFT JOIN teams oa ON oa.team_id_master = g.home_team_master_id AND g.away_team_master_id = :id
WHERE g.home_team_master_id = :id OR g.away_team_master_id = :id
ORDER BY g.game_date DESC
LIMIT 60;
```

Read the opponents' names too — they carry the cohort and gender conventions of the flight the team
actually plays in, which is often clearer than the team's own row.

League names get their season suffix stripped between seasons: a competition recorded as
`STXCL-WC 2025-2026 Leagues` appears in the following season as plain `STXCL Leagues`. Strip season
tokens and trailing `Fall` / `Spring` / `Season Play` / `-WC` from both sides before comparing.

## The ingest clock

Registrations arrive in discrete weekly batches, not continuously — GotSport in one evening batch,
TGS on a separate morning. Confirm where today sits before concluding a name is absent:

```sql
SELECT t.created_at::date AS d, to_char(t.created_at, 'Dy') AS dow,
       p.code AS provider, count(*) AS rows_created,
       count(*) FILTER (WHERE t.team_name LIKE 'unknown\_%') AS placeholders
FROM teams t LEFT JOIN providers p ON p.id = t.provider_id
WHERE t.created_at >= :since
GROUP BY 1, 2, 3
ORDER BY 1;
```

## Finding an unnamed row that already holds the fixtures

```sql
SELECT t.team_id_master, t.provider_team_id, t.state_code, t.age_group, t.gender,
       count(g.id) AS fixtures,
       count(*) FILTER (WHERE g.home_score IS NOT NULL) AS scored,
       string_agg(DISTINCT g.competition, ' | ') AS competitions
FROM teams t
JOIN games g ON g.home_team_master_id = t.team_id_master
             OR g.away_team_master_id = t.team_id_master
WHERE t.team_name LIKE 'unknown\_%'
  AND t.age_group = ANY(:cohorts) AND t.gender = :gender
  AND t.state_code = ANY(:states)
  AND g.game_date >= :season_start
GROUP BY 1, 2, 3, 4, 5
ORDER BY fixtures DESC
LIMIT 50;
```

Match the roster row to the opponent set. This is the one place attribute predicates are correct: a
placeholder has no name to search, so the attributes are all there is. When the roster carries no
state column, pass every state the club's other rows appear in as `:states`.

## Season-crossing links

A provider registration ID never links two seasons. No `(provider_id, provider_team_id)` pair maps
to more than one canonical team, and the provider mints a new ID each season, so an ID lookup for a
current roster name returns nothing every time. A bare `provider_team_id` is *not* unique on its own
— thousands are shared across two teams from different providers — so always pair it with
`provider_id`.

`team_merge_map` is the only structural link, and it has been applied to a tiny fraction of current
registrations. Check it in both directions before declaring two rows unlinked, and expect "not
linked yet":

```sql
SELECT t.team_id_master, t.team_name, t.created_at::date, t.is_deprecated,
       (SELECT count(*) FROM team_alias_map a
         WHERE a.team_id_master = t.team_id_master) AS n_aliases,
       m_out.canonical_team_id AS merged_into,
       (SELECT count(*) FROM team_merge_map mi
         WHERE mi.canonical_team_id = t.team_id_master) AS absorbed_rows
FROM teams t
LEFT JOIN team_merge_map m_out ON m_out.deprecated_team_id = t.team_id_master
WHERE t.team_id_master = ANY(:candidate_ids);
```

Two or more aliases on a recently created row is the positive signal that the season-crossing link
already exists. A single alias means the prior-season row is still floating.

`team_alias_map.division` is not a matching key — it is populated on about one row in a hundred and
carries only MLS NEXT tier tokens (`AD`, `HD`).

## Tie-breaking

Exact ties on name within a cohort are common. Apply in order:

1. Drop `is_deprecated` rows
2. Prefer a row with a current-season fixture
3. Prefer more games
4. Prefer the more recent `created_at`

Steps 1 and 2 together still leave about half the tie groups tied. Game count settles almost all of
the remainder, and `created_at` settles the rest — it is sub-second-unique, so no group ever reaches
a `team_id_master` tiebreak. But `created_at` is a timestamp, not evidence: **a group resolved only
at step 4 is still tier C.** Report one row and name the alternates. Collapsing them silently is the
failure this cascade exists to prevent.

Where every candidate in a tie group is deprecated, `team_merge_map` resolves all but about twenty
rows table-wide. Where it has no entry, report that rather than inventing a survivor.

## Query hygiene

The MCP result has a hard token cap and a large result is rejected outright, losing the work.
Aggregate first — `count`, `GROUP BY` — then pull a narrow sample. Select explicit column lists.

Batch `.in_()` filters to at most 100 IDs, and paginate anything that could exceed 1000 rows.

`state_rankings_view` is only safe filtered by ID; unfiltered `ROW_NUMBER` queries against it time
out.
