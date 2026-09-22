# Handoff: State-by-state club-name cleanup — every state now has a pass

Supersedes `2026-09-22-state-by-state-club-name-cleanup-3.md`. That file's mechanism,
conventions and traps all still hold; read it first. This one records the 2026-09-22
evening round, which finished the four states it left.

## Where this stands

Branch `club-names-ca-ny-pa-nj`, three commits off `origin/main` at `c37640e4a`
(which carried the previous round in as #1203).

**Every US state now has a deliberate pass.** California, New York, Pennsylvania and
the New Jersey remainder are done; 2,859 teams moved across 361 new rules.

| state | teams consolidated | rules | groups before | groups left |
|---|---|---|---|---|
| California | 1,812 | 241 | 206 | 35 |
| Pennsylvania | 636 | 62 | 54 | 5 |
| New York | 306 | 43 | 42 | 8 |
| New Jersey | 105 | 15 | 15 | 5 |

Every batch was read back from the database after its write and every state re-scanned.
Each group that remains is a refusal or an open question commented in place inside
`CLUB_CANONICAL_OVERRIDES`.

Undo logs are `data/exports/{ca,ny,pa,nj}_club_batch*_log.csv` — gitignored, so they
exist only in this checkout. Replay backwards with
`python scripts/apply_vetted_club_names.py --revert <log> --execute`.

## The crosscheck is worth building in, and here is what it found

The previous handoff said `crosscheck.py` — *does this club's teams mostly name a
DIFFERENT existing club?* — earned its keep and was not in the repo. It still is not,
but it was rebuilt and it found, in states the shipped scan called clean:

- **Pennsylvania**: Nether Providence AA, whose 56 teams all read "Nether United FC";
  Southern Chester County SA's 23 reading "FC Chesco"; the 18 filed under the literal
  club value `WAS WCUSC - NOW PENN FUSION`; Cheltenham Sports' 4 reading "Cheltenham
  Jayvees"; `Philadelphia Soccerland Academy (Northeast Wolves FC)`.
- **New York**: Empire State Youth Soccer Club's 31 reading Alleycats; `WSSL TT`'s 19
  reading "West Side Soccer League Tournament"; BWP Albany's 7 reading the parent.
- **California**: `Teen Rec`'s 15 reading "Clovis Crossfire"; Visalia Youth Soccer
  Association's 4 reading "Central Valley Premier FC"; `Azzuri FC` beside the club it
  misspells; `Modesto YSA / Ajax United`; `Palm Desert SC` reading Desert Empire Surf.

**None of these is reachable by any fold**, because the two spellings share no tokens.
About 350 teams this round came from it. A `pairs.py` (organisation words stripped
anywhere, rather than only trailing) added `FC Westchester` / `Westchester SC` — which
turned out to be two clubs — and PA's `FC Pittsburgh` / `Pittsburgh Football Club`,
also two clubs. Cheap to read, mostly refusals.

**Both are rebuilt in the session scratchpad and are about 40 lines each.** So is a
`reach.py` that prints, per entry, what it moves in-state and what it reaches among
stateless teams, which is the check the previous handoff asks for and the only way to
run it per entry rather than per pattern.

## What this round learned

### A `norm` self-entry can silently reach nothing

`("CA", "norm", "Southwest Soccer Club", "Southwest Soccer Club")` never matched
`Southwest Soccer Club (SWSC)`: `club_acronym` reads that name as **SSC**, because
"Southwest" is one word, so the `(SWSC)` tag never looks redundant and
`normalized_club` keeps it. The entry looked fine in every check — a self-entry always
"holds" its canonical, so it is never flagged as reaching nothing.

**Verify a `norm` self-entry by what it MOVES, not by whether it matches.** The
scratchpad check is four lines: for each `norm` entry where pattern == canonical, list
the live club values it matches that are not the canonical, and report the ones with
none. Run it before applying, not after — this one was caught by the post-apply
re-scan, which cost a second batch.

### The build guard for retired canonicals pays for itself on a reconciled state

California arrived with 102 inherited rules. Three of them pointed at canonicals this
round retires — `JUSA`, and `West Covina SC` twice —
and `test_no_override_names_a_canonical_that_another_override_moves_on_from` named all
three on the first run. **Expect this on any state with inherited rules**; the fix is
to redirect the old entry, not to drop it.

### The stateless check can be non-zero and the rule still be right

Two California spellings reach stateless teams: `CDA Slammers FC` (30) and `Leopardos`
(2). Unlike Ohio's OSU or Nebraska's Evolution SC, those stateless rows are **the same
club** — their own team names read "CDA Slammers FC ..." and "Leopardos FC ...".

The rule was still left out and both populations moved by team id, because that is what
the convention says and because a rule reaching nationally should not be invisible. But
the check answers "does this pattern reach stateless rows", not "would that be wrong",
so **read the stateless rows' team names before deciding which remedy applies**: a
collision needs the rows left alone, a same-club overlap wants them moved too.

### Two new conventions this round settled

- **A club's branch set takes one style, not one style per group.** Strikers FC writes
  its branches without a dash on 128 of its 168 rows, so all three branches take that
  form even though the CM/NB group's own majority is dashed. Deciding each group on its
  own majority would have left one branch spelled differently from its siblings.
- **A league tag's case is decided by the league, not by the club.** Thirty-odd Long
  Island clubs carry `(LIJSL)` and seven write it lower case. Where a club had two
  spellings anyway the canonical took the league's case; the five clubs whose only
  spelling is lower case are an open question rather than a silent sweep.

## Open, needing the owner

`grep -n "open question" scripts/full_club_analysis.py` lists all 24 blocks, each
commented beside its own state. The four new states add:

- **California** (eight): whether Total Futbol Academy splits into its twelve existing
  branch values — the same question PDA asks, and the same shape, 308 parent rows each
  naming a branch; whether Milpitas YSL is FC Milpitas; City SC against CITY FC;
  whether Lincoln Youth Soccer Club is Lincoln FC, which the club's own retired tag
  says; West Sacramento SC against West Sacramento FC; whether the Athletic SC branches
  are now AYSO United and United SoCal, a rebrand spanning four values and 500-odd
  teams; whether `U.S. Futsal`, `AYSO`, `Real`, `SAN JOSE` and `California` belong in
  `src/utils/placeholder_clubs.py`; and the three SoCal Athletic spellings.
- **New Jersey** (six): whether WSA should read Westfield SA; what Nesa stands for —
  it is **not** Nutley Elite SA, which the scan pairs it with on the acronym, because
  two of its teams read "CSA Newark"; whether FC Allstars and Allstars F.C are one club
  in two word orders; Glen Rock Shooting Stars against Glen Rock United; which Franklin
  the one `Franklin` row is; and what `Peninsula City SC` is.
- **New York** (five): the one `Cedar Stars` row, which Staten Island or Hudson Valley
  could claim; whether Brooklyn Force Soccer Club is Metropolitan Oval Academy
  Brooklyn; CNY Coliseum against Coliseum; the two Long Island City clubs; and the five
  lone lower-case `(lijsl)` tags.
- **Pennsylvania** (three): whether `Tournament Team` (42 teams, each naming a different
  club) and `Tournament Team - PA` belong in `placeholder_clubs.py`; whether Abington
  Soccer Club and AC United are one club; and the single PA team under
  `Union Soccer Club (NJ)`, which is a state question.

**The PDA split is still the owner's call and is now costed.** A proposal script in the
scratchpad reproduces the previous round's figures exactly — 44 to PDA White (Shore),
32 to PDA Blue (North), 25 to PDA Hibernian, 3 to PDA South, 47 staying on the parent —
reading the place or partner word before any colour word, which is what keeps
`Hibernian Adams White U12` under Hibernian and `PDA South Blue ECNL RL 2009` under
South. It writes a vetted file and applies nothing.

## Two findings outside this job

- **The caps pass re-cases a provider placeholder.** California has one team under
  `no club` and the weekly cleanup queues `'no club' -> 'NO Club'`. That is the same
  shape as the Del Rio-laughlin and Club DE Futbol damage, on a value
  `is_placeholder_club` already recognises. Cosmetic today, because the lowered form
  still matches, but `merge_case_variants` should skip a placeholder outright.
- **`scan_club_name_variants.py` still cannot see a dotted abbreviation.** PA's
  `West-mont United SA` sat apart from `West-Mont United S.A` for the reason the two
  previous handoffs both name, and the crosscheck is what found it. The tokenizer fix
  is still not done.

## Next step

Push and open the PR — three commits, not yet pushed. Then the owner's 24 open-question
blocks, which nothing in the pipeline will surface again on its own.
