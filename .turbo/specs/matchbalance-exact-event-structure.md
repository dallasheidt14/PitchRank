# MatchBalance backtest — read a played event's exact structure, then match its teams

**Status**: draft for review
**Date**: 2026-09-10
**Surface**: `tournament_intake.py` Backtest view, `src/tournaments/`

---

## 1. Purpose

A MatchBalance backtest replays a tournament that has already been played, using
**the structure that tournament actually had**, so a director can be shown the seeding
they should have used. Everything downstream of that — reseeding, simulation, the
actual-versus-optimised comparison — depends on the replay copying the real event
rather than an approximation of it.

This spec covers only the front half of that flow:

1. Paste a played GotSport event URL and walk it.
2. Capture its **exact** structure: every division, its pools with membership, and
   every fixture including the knockout games.
3. Match the teams it found to teams in the PitchRank database, using the resolver
   the Seeding tab already uses.

### Out of scope

- Reseeding, simulation, balance scoring, the director-facing comparison.
- Rewiring the Backtest tab's existing triage list, division editor, or
  Run-backtest control. They keep running off the current intake for now.
- Any change to the Seeding tab's behaviour.
- Importing, creating, or updating anything in the PitchRank database (see §3).

---

## 2. Why the structure is read, not inferred

Today `src/tournaments/schedule_simulator.py:infer_division_schedule_template`
derives a format by arithmetic: it subtracts a pool round-robin's game count from
the actual game count and maps the remainder onto a playoff shape. The operator
supplies the pool sizes by hand through the division editor.

Measured against the 39 real GotSport division pages already saved in
`tests/fixtures/gotsport/`, both halves of that are unsound:

- **The structure is printed on the page.** Each division's schedule page carries
  one standings table per pool, listing that pool's teams. Every one of the 52
  standings tables across those pages sits inside a `div.panel-collapse` whose
  sibling `div.panel-heading` names the pool (`Bracket A`) and whose `id` is
  `collapse-<digits>` — GotSport's own pool id. Read the label from that panel,
  not from the nearest preceding text: two of the pages put "Standings" and a
  tiebreaker link immediately above the table, and proximity reads those as the
  pool's name. Knockout games are labelled outright in the Match # cell —
  `56 Final`, `55 Third Place`, `53 Consolation A`, `Semi-Finals A`,
  `Play In Game`, `5th Place Game`. Pool games carry a bare number.
- **The arithmetic misreads real events.** `event_49371__group_485425` has two
  standings tables of 3 and 9 non-knockout games, of which **9 are cross-pool and 0
  are within a pool** — the two "brackets" only ever played each other. Inference
  reads that as `(3,3)` pool play with 3 unexplained extras and would replay a
  format that never took place. `event_44692__group_391315` is a pool of 6 that
  played 9 games rather than a 15-game round robin. Neither is recoverable from
  counts.
- **Pools and fixtures join on an id.** Standings tables carry the same
  `?team=<registration_id>` links the fixture rows do, so pool membership attaches
  to fixtures by identifier, never by name similarity.

A confidently wrong structure yields a confidently wrong "you should have seeded it
this way". Reading beats inferring, and an unreadable division must present as
unreadable rather than as a guess.

---

## 3. Hard constraint: this flow writes nothing to the PitchRank database

MatchBalance reads the team registry to find a match. It must not create teams,
write aliases, queue review rows, or enqueue scrapes.

This is not automatic. The **current** Backtest intake violates it:
`GotsportScraper.fetch_teams_by_cohort` routes through
`src/tournaments/alias_writer.py`, which inserts into `team_alias_map` and
`team_match_review_queue` on every scrape. The Seeding tab's resolver path, by
contrast, is read-only — verified across `roster_resolver.py`,
`event_roster_intake.py` and `gotsport_event_roster.py`: no `insert`, `upsert`,
`update`, `delete` or `rpc` call exists in any of them.

Therefore:

- This flow uses the resolver path, never the alias writer.
- `src/tournaments/seeding_enqueue.py` (which calls the `enqueue_scrape_request`
  RPC) is **not** wired into this surface.
- A test enforces the constraint rather than a convention (§9).

---

## 4. Data model

New, in `src/tournaments/gotsport_event_structure.py`:

```python
@dataclass(frozen=True)
class PoolMember:
    registration_id: str
    team_name: str
    standings_position: int   # row order in the standings table

@dataclass(frozen=True)
class Pool:
    pool_id: str              # GotSport's own id, from the panel's "collapse-<id>"
    label: str                # "Bracket A"; "" when the page names none
    members: tuple[PoolMember, ...]

@dataclass(frozen=True)
class Fixture:
    match_number: str
    bracket_label: str        # "Final", "Third Place", ""; verbatim from the page
    kind: str                 # "pool" | "cross_pool" | "bracket" | "unknown"
    home_registration_id: str | None
    away_registration_id: str | None
    home_score: int | None
    away_score: int | None
    kickoff: str              # verbatim page text; not parsed to a datetime in v1
    location: str

@dataclass(frozen=True)
class ScrapedDivision:
    group_id: str
    division_label: str
    pools: tuple[Pool, ...]
    fixtures: tuple[Fixture, ...]
    pools_readable: bool
    fixtures_readable: bool
    warnings: tuple[str, ...]
```

Notes that are load-bearing:

- **`standings_position` is the final table position, not a seed.** A played event's
  standings table is sorted by points. Nothing in this flow may read it as the
  seeding the director used.
- **`kind` is derived only by lookup**, never by arithmetic: a fixture with a
  non-empty `bracket_label` is `bracket`; otherwise both ids are looked up in the
  pool map and the fixture is `pool` when they share a pool, `cross_pool` when they
  do not, and `unknown` when either id is absent.
- **No format name is stored.** The record holds pools and the fixture graph. A
  human-readable label may be computed for display, but the replay consumes the
  graph.

---

## 5. Components

| Component | Responsibility |
|---|---|
| `src/tournaments/gotsport_event_structure.py` *(new)* | Pure parsing. Division-page HTML → `ScrapedDivision`. No HTTP, no Supabase, no Streamlit. |
| `src/tournaments/gotsport_event_roster.py` *(extended)* | The existing walker calls the parser on each division page it **already fetches**. Returns results as a new field on `EventRoster`. No new page fetches, so no change to what a walk costs. |
| `src/tournaments/storage/event_structure.py` *(new)* | Read/write `event_structure.json`, following the `_io.write_json` + `stamp_schema_version` conventions used by `frozen_medians.py` and its siblings. |
| New UI module under `src/tournaments/` | The intake surface. `tournament_intake.py` calls one render function, mirroring how `division_render.py` and `reports/ui.py` already hold UI helpers outside the 4,635-line app file. |

### Extending `EventRoster`

Additive only:

```python
divisions: tuple[ScrapedDivision, ...] = ()
```

`teams`, `warnings`, every counter and the `is_complete` property are untouched, so
the Seeding tab cannot regress.

**The recovery file must carry it.** `_write_event_roster_recovery` in
`tournament_intake.py` exists so a walk that was paid for survives a stray click.
If `divisions` is not persisted there, a recovered walk comes back structureless and
the event has to be bought again. The recovery reader must reject a payload whose
divisions it cannot rebuild faithfully, matching the existing field-by-field refusal
in `_recovered_walk`.

### Reuse rather than duplication

Two bodies of existing code are used as-is:

1. **The paid-walk machinery** in `tournament_intake.py` — cross-tab lock, recovery
   file written before anything interruptible, priced two-division probe, "load the
   walk already paid for", and the Streamlit rerun protections documented in those
   functions. It is currently bound to `_seeding_*` session-state keys. Parameterise
   the key prefix so one implementation serves both views. Do not copy it.
2. **The matching path** — `resolve_master_ids` → `to_seeding_rows` →
   `resolve_unlinked`, then the paste-a-link override box for what is left. Teams
   join to the structure on `registration_id`, which both sides already carry.

---

## 6. Persisted format

`reports/<event_key>/intake/event_structure.json`, stamped with
`schema_version` per `storage/schema_version.py`, written atomically through
`storage/_io.write_json`.

```json
{
  "schema_version": 1,
  "event_id": "51783",
  "walked_at": "2026-09-10T00:00:00+00:00",
  "is_complete": false,
  "divisions": [
    {
      "group_id": "485425",
      "division_label": "U-12 BOYS SILVER",
      "pools_readable": true,
      "fixtures_readable": true,
      "pools": [{"pool_id": "672784", "label": "Bracket A", "members": [{"registration_id": "...", "team_name": "...", "standings_position": 1}]}],
      "fixtures": [{"match_number": "56", "bracket_label": "Final", "kind": "bracket", "...": "..."}],
      "warnings": []
    }
  ]
}
```

It sits beside the existing intake artifacts and replaces none of them.

---

## 7. UI flow (Backtest view)

1. Paste a GotSport event URL.
2. **Probe** two divisions to price the event, exactly as the Seeding tab does.
   The full-walk button unlocks only once a probe has actually read a division.
3. **Walk** the event, under the cross-tab lock, with the recovery file written
   before any interruptible work.
4. **Show what was found**, per division: pools and their sizes, fixture counts
   split by pool / cross-pool / knockout, the knockout labels seen, and anything
   unreadable stated plainly.
5. **Match** the teams: matched-by-GotSport-id and matched-by-name counts, then a
   paste-a-link box for each team still undecided.

The existing `Scrape` button and Resume dropdown stay on the tab. The screens below
them continue to read the old intake's `raw_scrape.jsonl`; rewiring them is the next
phase. This is a deliberate temporary state, agreed with the owner.

---

## 8. Error handling — the never-guess rules

- A division whose standings tables cannot be read is recorded with
  `pools_readable=False` and no pools. **Pools are never reconstructed from
  fixtures.**
- A division whose fixture tables cannot be read is recorded with
  `fixtures_readable=False`. Its pools still stand.
- A fixture row that parses partially keeps what it has, sets the missing fields to
  `None`, and takes `kind="unknown"`. It is never dropped silently; the count of
  such rows is surfaced.
- An unreadable division label never costs the division its teams — the walker's
  existing behaviour, preserved.
- A team that cannot be matched stays visibly unmatched. Nothing is created to make
  a count look better.
- A walk that ends early is `is_complete=False`, and a partial walk never overwrites
  a complete one on disk — the guard `_write_event_roster_recovery` already applies.

---

## 9. Testing

**Parser, against real HTML.** The 39 saved division pages in
`tests/fixtures/gotsport/` are the corpus; the test discovers them by glob rather
than by a hand-written list, so a page added later cannot sit silently outside the
guard. Per file it asserts pool count, pool sizes, and the set of knockout labels.

**Named regression cases**, because they defeat count-based logic:

| Fixture | Expectation |
|---|---|
| `event_49371__group_485425` | 2 pools of 3; 9 fixtures `cross_pool`, 0 `pool`; 1 `bracket` (`Final`) |
| `event_44692__group_391315` | 1 pool of 6; 9 `pool` fixtures — not the 15 a round robin implies |
| `event_42433__group_365847` | 2 pools of 4; 12 `pool`; 4 `bracket` — `Consolation A`, `Consolation B`, `Third Place`, `Final` |
| `event_49371__group_485294` | 1 pool of 4; 6 `pool`; 0 `bracket` |

**No-database-write test.** The matching path runs against a Supabase double that
raises on any `insert` / `upsert` / `update` / `delete` / `rpc`. Per this repo's
testing rules the double records at `.execute()`, not at builder construction, so a
call that builds a write without executing it is still caught by assertion on what
`execute()` recorded.

**Mutation checks.** Every multi-part guard is reverted one conjunct at a time, not
as a hunk — in particular the `kind` classifier's pool-lookup branches and the
recovery reader's field-by-field refusals.

**Recovery round-trip.** A walk carrying divisions is written, read back, and
asserted equal; a payload with a malformed division is refused rather than repaired.

---

## 10. Acceptance

Event **51783** (`https://system.gotsport.com/org_event/events/51783`), walked in
full through the UI:

1. Every division is listed with its pools and their sizes.
2. Every knockout game the event played appears with the label the page gave it.
3. Fixture counts split by pool / cross-pool / knockout, and reconcile with the
   division's total fixture count.
4. Divisions the parser could not read are named as unreadable — not absent, not
   guessed.
5. Team match counts are shown, with every unmatched team listed and fixable by
   pasting a link.
6. `event_structure.json` on disk reproduces all of the above.
7. No row is written to any PitchRank table during the entire run.

---

## 11. Follow-ups this deliberately defers

- Rewiring the triage list, division editor and Run-backtest control onto
  `event_structure.json`, and retiring the old alias-writing intake.
- Reseeding, simulation and the director-facing comparison.
- Whether `storage.DivisionStructure` (`name`, `team_count`, `pool_sizes`,
  `advancement`) is extended or superseded — it cannot express pool membership,
  which the replay needs.
