# Targeting the GotSport probe: what a paid call should be spent on

Measured 2026-08-31. Every number here came from probing production, not from estimation.

## The question

`teams.state_code` is wrong for a meaningful number of teams and nothing local can find
them, because every free tier is learned from the column being audited. A club whose teams
are uniformly mislabelled agrees with itself. `assign_team_states.py` says so in its own
comment, and it is the reason Tier A exists.

Tier A costs one paid ZenRows call per team. Asking every team is not affordable. So: which
teams are worth asking about?

## How wrong is the database

**2.9%**, measured against teams no tier disputes.

200 stated teams sampled at random from the 195,935 that every rule currently agrees with;
173 had a GotSport record and answered; **5 disagreed** with what we store. Extrapolated,
roughly **5,700 teams** carry a state their own provider record contradicts, with a range of
about 3,000–8,000 at that sample size.

Not every disagreement is ours: Quad Cities Rush straddles the Iowa/Illinois line and either
answer is arguable. But West Seneca SC stored as Ontario, when West Seneca is a Buffalo
suburb, is plainly wrong.

## Why the free signals do not work

Two were tried and both failed against validation.

**A club whose name points where none of its teams are stored.** 18 clubs, 262 teams. Fifteen
are the false friends already documented in the skill: Delaware Knights really is in Ohio,
Oregon SC really is in Wisconsin, Georgia United really is in Vermont. Three were real
candidates; probing confirmed two.

**Judging TGS teams on non-TGS evidence only.** This was the promising one — it breaks the
circularity directly, by rebuilding the club and locality indexes without TGS and re-deciding
TGS teams against them. It produced 153 candidates across 47 clubs, free.

Then validation: only 14 of the 153 had a GotSport record to check against, and of the 13
that answered, **12 were false positives**. Including Colorado Elevation FC, which reads like
an obvious catch and is correctly stored Utah. Eight were one club, `Utah Royals FC - AZ`,
whose name contains the word "utah" — a Tier E defect fixed separately in #1069.

The lesson is not that the idea was bad. It is that a heuristic which reads names produces a
list nobody can act on without checking it, and checking it is the expensive part.

## The rule that works

> **A team whose state contradicts a club-mate's already-confirmed GotSport state.**

It costs nothing to compute. It reuses confirmations already paid for: 5,873 teams carry
`state_source = 'tier_a'`, and 2,107 clubs have at least one, all agreeing.

| Population | Teams | Hit rate |
|---|---|---|
| Random team no tier disputes | 195,935 | **2.9%** |
| **Contradicts a confirmed club-mate** | **1,210** | **50.4%** |

Measured: 150 sampled, 143 had a record, 129 answered, **65 confirmed wrong**. Seventeen
times better than random, and the confidence interval at n=129 is roughly 42–59%.

In spend: the 1,173 selected after the Canadian exclusion cost roughly 1,110 paid calls (only
alias-bearing teams reach the probe) and yield ~600 corrections. Reaching 600 corrections by
random probing would cost about 20,700.

**It compounds.** Each confirmed probe stamps a new `tier_a` anchor on a club, which can
expose further contradicting team-mates on the next run. The rule feeds on its own output.

### The candidate set, broken down

Measured against production the same day, using the tool's own `club_key` grouping rather than
the raw lowercasing the first pass used. Both give 1,210, so placeholder clubs contribute none
today — the exclusion is structural rather than load-bearing.

| | Teams |
|---|---|
| Candidates matching the rule | 1,210 |
| …storing a Canadian province — R7 returns `None`, so the call buys nothing | 37 |
| **Selected after that exclusion** | **1,173** |
| …already in `disputed`, so a full sweep probes them too | 457 (39%) |
| …**marginal — reachable no other way** | **716** |
| …storing `DC` — R8 queues rather than applies, so the call buys a review row | 23 |
| Anchored by 2 or more confirmed club-mates | 622 |
| Anchored by exactly 1 | 588 |

**The rule's value is targeting, not exclusivity.** 39% of its candidates are already disputed
by a free tier, because `club_derived_state` excludes the team being decided from its own club
counts — so the Mandeville shape, 2 teams at AL/TX against 41 at LA, *is* disputed by Tier B and
would be probed by any full sweep. What changes is the price: a full sweep reaches those 457 at
a cost of ~6,200 calls; this reaches all 1,173 for ~1,110. The other 716 are reachable no other
way. Measured by intersecting the candidate set with the decisions in workflow run 33419639457's
snapshot. Whether the overlap falls evenly across the 1-anchor and 2+-anchor buckets is
unmeasured.

The near-even 622/588 split is why ordering by anchor count is worth doing: a full run yields
two cohorts of comparable size whose hit rates can be compared directly, which is the only way
to settle the untested refinement below.

**Selected candidates are not paid calls.** Only alias-bearing teams reach the probe — 143 of
the 150 sampled had a GotSport record, about 95% — so 1,173 selected teams cost roughly 1,110
calls, not 1,173.

## What the false positives are

All 45.7% of them come from one shape: a generic `club_name` covering teams that are
genuinely different clubs.

The three outcomes account for the full sample: 65 confirmed wrong (50.4%), 59 false
positives (45.7%), 5 where GotSport named a third state (3.9%) — 129 answers in total.

| Club driving false positives | Teams in sample |
|---|---|
| North FC | 11 |
| Valley United SC | 10 |
| Elite FC | 10 |
| Eastside FC | 5 |
| Cold Spring Harbor Huntington (LIJSL) | 5 |
| Legacy FC | 4 |

This is a club-identity problem wearing a state-problem costume. The database already knows
it in places — `Eastside FC (WA)` exists as a distinct `club_name` alongside a bare
`Eastside FC`.

**Untested refinement:** require the anchor club to have **two or more** confirmed teams. A
single anchor is exactly what a name collision produces, so this should cut the noise. It is
worth measuring before it is assumed.

## Reach, and what this can never fix

Only teams with a GotSport alias can be probed at all.

| | Teams |
|---|---|
| Stated teams with a GotSport record | 175,688 |
| …of which ever actually probed | 5,873 |
| TGS stated teams | 22,819 |
| …of which have a GotSport record | 6,256 |
| …with no external truth available at all | **16,563** |

So TGS — the provider that generates the most blanks — is the population this method reaches
*least*, not most. 73% of TGS teams cannot be checked by any means currently available.

## The gap that stops this getting smarter

**No probe outcome is recorded unless it changes something.** `team_state_audit` is fired by
a trigger on `state_code`, and `state_source = 'tier_a'` is only stamped on a write. A probe
that agrees with what we store leaves no trace anywhere.

Three consequences, all of which compound in the wrong direction:

1. **Every verified-correct team is re-probed forever.** The random control confirmed 168
   teams as correct; that knowledge is already unrecoverable.
2. **"Verified correct" is indistinguishable from "never checked."**
3. **The false positives cannot be learned.** Elite FC and North FC will produce the same
   noise every run. A ledger recording that probes there keep contradicting the anchor would
   let the rule demote them on its own.

A probe ledger is the single change that converts this from a fixed-cost sweep into something
that improves. It was deferred on 2026-08-31 so the audit could ship first, then **brought back
into scope the same day** once review showed the gap is not only a cost.

**It makes a budgeted audit stall.** A candidate that produces no change — no alias, a failed
call, or an answer that agrees — gets no `tier_a` stamp, so it still matches the selector next
run and still sorts to the same place. With deterministic ordering and a prefix budget, once N
such teams occupy the head, every later capped run re-probes exactly them and never reaches the
tail. Filtering to alias-bearing teams before the limit fixes only the no-alias third of that.
The ledger is therefore a prerequisite for a capped run, and is PR1 of
`.turbo/plans/state-contradiction-audit.md`.

## Confirmed fixes from this work

- **Washington East Surf Soccer Club** — 34 teams scattered across ID, OR, WY, UT, NY, MT, MN,
  NC, NV, TX and CA. GotSport says WA. 32 corrected; the rest already agreed.
- **Pacific FC Washington** — 13 teams stored OR. 12 corrected to WA; one, *Pacific FC 15G
  Tsunami*, is genuinely registered in Oregon and was correctly left alone.
- **Mandeville Soccer Club** — 2 teams stored AL and TX against 41 in LA. Both corrected.
- **Northwest Indiana Surf** — flagged by the name hunt, probed, **correctly stored** Illinois.
  A Chicago-metro club.

48 writes in total, actor `assign_team_states`, action `correct`, source `tier_a`, 2026-08-31
18:33–19:35 UTC — 46 for the two Washington clubs and 2 for Mandeville. Reversible with
`revert_team_states` scoped to that actor and window.
