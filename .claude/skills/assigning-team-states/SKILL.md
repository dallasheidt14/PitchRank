---
name: assigning-team-states
description: "Fills missing team states and corrects wrong ones in PitchRank, deciding each team from ranked evidence rather than one heuristic, with every write logged and reversible. Use when asked to fix a team's state, fill missing state codes, correct wrong states, run the state assignment sweep, work the state review queue, undo a state batch, decide which state a club belongs to, or investigate why a team appears on the wrong state board."
---

# Assigning team states

A team's state is **where its club is based**, not where it plays. Every wrong state in this
database was written by something that confused the two: an opponent's state copied onto a
team it travelled to play, a tournament host's state stamped on its visitors. The tiers below
all answer the club question, and the signals that answer the travel question are excluded on
purpose — they are why the problem exists.

The column is read by the public state boards, and it was write-once until this tool existed:
every earlier script filtered on `state_code IS NULL` in its SELECT, so nothing could correct
a wrong value and nothing recorded where a value came from. Two consequences shape everything
here. A correction is a heavier act than a fill, so it needs stronger evidence. And a run's
own report is not evidence that it did the right thing — verify against the database.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Preflight — credentials, then prove the rules still fire
- [ ] Step 2: Take a snapshot with a dry run
- [ ] Step 2a: Or audit the contradictions instead
- [ ] Step 3: Read the evidence before writing anything
- [ ] Step 4: Apply a small batch and verify it against the database
- [ ] Step 5: Apply the rest from the same snapshot
- [ ] Step 6: Work the review queue
- [ ] Step 7: Record what ran, and what you could not decide
```

## Step 1: Preflight

**Credentials.** The Supabase keys are in root `.env`, and `assign_team_states.py` prefers
`.env.local` when it exists. Both work on this checkout; a missing key surfaces as
`Missing SUPABASE_URL or SUPABASE_KEY` before any read.

**The probe ledger has to exist.** Every Tier A run writes `team_state_probe_log`, and that
write is deliberately fatal, so a missing table surfaces as a PostgREST error naming a
relation rather than a migration — on a `--team` run, *after* the paid probe. Apply
`supabase/migrations/20260831120000_add_team_state_probe_log.sql` before the first run.
Migrations here go on by hand, so the ledger does too:
`supabase migration repair --status applied 20260831120000`.

**Prove the rules.** Run `python scripts/check_state_skill_assumptions.py`. It drives the real
decision code and asserts the behaviours this document promises: that a stored Canadian
province is never corrected, that a curated club queues rather than applies, that a correction
from a name never auto-applies, that a reverted value is not re-applied. **A failure means
this skill is now wrong, not that the codebase is broken** — fix the prose, then continue. The
measurements below the assertions never fail; they warn when a count this document quotes has
drifted more than 20%.

## Step 2: Take a snapshot with a dry run

```bash
python scripts/assign_team_states.py --out run.json
```

Makes **no team-state and no review-queue writes, but it does persist paid-probe
observations**. It reads every live team, decides each one, and persists the decisions to the
`--out` file along with the state each team had at that moment.

**The dry run is the only thing that decides.** `--execute` replays the file and never
recomputes, for two reasons that both bite silently. A fill written early changes the clubmate
distribution a later team's Tier B reads, so a run that decided as it went would interfere
with itself. And the other weekly writers can move a team between the two commands, turning a
decision recorded as a fill into an unrecorded correction. Each write carries the snapshotted
state as a predicate, so a team that moved is skipped and reported rather than overwritten.

The GotSport probe costs one paid request per candidate — about 2,600 on a full run as of
2026-09-02 (1,636 disputed teams and 982 stateless ones that carry a GotSport id; a hand
count, which `check_state_skill_assumptions.py` does not guard because measuring it means
running every tier over every team), routed through ZenRows because a direct burst gets
blocked. `--no-tier-a` skips it deliberately and
says so in the report. Do not confuse that with the tier being quiet: on a sweep a blocked
probe aborts the run rather than deciding without evidence it was supposed to have.

Every one of those calls lands in `team_state_probe_log`, whatever it returned — which is why
a dry run is not write-free. The call is paid for whether or not its answer is recorded, and
on a sweep an agreement is visible nowhere else: it changes no state, so nothing else logs it.
(Steps 2a and 2b are different — there an agreement becomes a confirm, which is ledgered.)
See [references/evidence-tiers.md](references/evidence-tiers.md).

**A sweep never reads that ledger back.** Only the modes below do. Two sweeps a day apart buy
the same disputed teams twice, so if the question is "what did the provider say", ask it once
with a sweep and thereafter through Step 2a or 2b, which reuse an answer for 90 days.

## Step 2a: Or audit the contradictions instead

```bash
python scripts/assign_team_states.py --audit-contradictions --probe-limit 50 --out audit.json
```

A different question from the sweep's, and a much cheaper one. The sweep asks about teams a
tier disputes; this asks about teams whose state contradicts a club-mate the provider already
confirmed. The two populations overlap — about 39% of these teams are disputed by a tier as
well — so the gain is targeting, not exclusivity: a full sweep reaches the same teams for
roughly six times the calls. The rest are teams no tier flags, because their club agrees with
itself.

**The audit's population is stated here and nowhere else**, and it moves in both
directions: it falls as the audit runs — an agreeing answer is written as a confirm, so the
team leaves the population — and it regrows whenever a Tier A write lands somewhere new,
because every anchor exposes its dissenters, which is the point of Step 2b. Measured at the
end of 2026-09-02, after the pilot: **1,558 teams qualify, 1,386 with a GotSport id**, all of
them already answered on an earlier run. A club that comes to hold two confirmed states is
dropped from the anchor index as two clubs sharing a name, so its remaining dissent is never
audited. `check_state_skill_assumptions.py` warns when this drifts.
The candidate rule excludes a team that is not askable: a stored Canadian province, which
Tier A never corrects, or a value an operator set by hand, which no automated write may move.

**Read the hit rate carefully — the two available numbers measure different things.** A
hand-checked sample of 150, taken 2026-08-31 against the pre-province-clause population, found
**65 genuinely wrong of 129 answered — 50.4%**, against a 2.9% base rate for a team picked at
random. That is a *confirmed-wrong* rate, established by hand. The run itself prints a
*disagreement* rate, which is looser and necessarily at least as high: a decision the tiers
queued rather than applied — a DC relabel under R8, a value you already reverted under R17 — is
counted as a disagreement, because the tool refuses to call those established corrections.

Three things it does differently from the sweep — and Step 2b's passes with it:

- It writes **only decisions the provider answered**. An unanswered candidate produces
  nothing, rather than a correction guessed from the club that mislabelled it.
- `--probe-limit` bounds what it **pays for**, not what it decides. A team answered on an
  earlier run is not asked again; if that answer named a state it still counts, and if it did
  not — no association on file, no GotSport id — the team drops out until its window expires,
  which the run reports separately as "skipped: answered before, but with no state to offer".
  So a capped run drains the backlog a batch at a time. Start capped, read what comes back,
  then run it uncapped.
- An answer is reused for **90 days**, after which the team is asked again — a registration
  moves at a season boundary at most. `--reprobe-after-days N` sets that window; it will not
  accept 0 or less, which would put the cutoff at or after now and re-buy everything.

**A blocked probe behaves differently here.** A sweep stops at the probe with no snapshot
written — though the calls it already made *are* in `team_state_probe_log`, written before the
block is detected. An audit finishes deciding from the answers it already
holds, writes the snapshot, and *then* exits non-zero.

Keep that file rather than discarding it — not to protect the calls, which the ledger already
holds and a retry reads back for free, but because re-deriving the decisions costs another full
pass over the table. Do not reach for `--no-tier-a` here: it is refused alongside
`--audit-contradictions`, which would leave the mode nothing to ask.

Apply it the same way as any other snapshot, from Step 4 on.

## Step 2b: Or anchor the clubs the audit cannot reach

```bash
python scripts/assign_team_states.py --anchor-clubs --probe-limit 2500 --out anchors.json
```

The audit only works inside a club that already holds a provider-confirmed team. The
current population is stated here and guarded by `check_state_skill_assumptions.py`: at the
end of 2026-09-02, **947 clubs with two or more askable teams have no confirmed member,
holding 6,973 teams, 3,181 of them with a GotSport id**. That is the population the checker
measures; the tool prints fewer, the clubs it can pick a team from once the alias lookup and
the retry cap have had their say. The base rate says about 2.9% of their teams are wrong.
This mode asks **one team per unanchored club**,
largest clubs first so a capped run buys the most coverage per call: a team stored in the
club's majority state, so that a disagreeing answer is an ordinary Tier A correction and an
agreeing one becomes a **confirm**. A team stored as a Canadian province, or set by an
operator, is not askable — nothing the call could return is actionable — and both passes
count club membership without them, so a border club of one US team and one Canadian team
is a single-team club to the anchor pass and its US team belongs to the unclubbed pass.

**Only the record's own decisions apply in these modes.** A provider answer `decide` throws
away — the unset default `AL` with a local reading against it — still marks the team as
answered, and on a club split two and two the club count then tells the anchor to swap sides
(IMP-161). So a Tier B correction here is queued with "provider gave no usable answer" rather
than written, and the report's "auto-applied" count is Tier A's alone.

A confirm is the same write through `apply_team_state` with the stored state on both sides:
the provenance becomes `tier_a` without the state moving, and the ledger records it as action
`confirm` — the trigger fires on a provenance change too, so `revert_team_states` can undo a
batch of confirms exactly as it undoes corrections. The action needs migration `20260902210000` applied first; before it, the ledger's
check refuses the row and the apply stops at the first confirm. Three values are never
confirmed over: one the record already vouches for (a replay after a `--limit` batch would
otherwise stamp it twice), one an operator set by hand with `--set`, and one an operator
reverted away from (R17), which is what makes a revert of an anchor batch stick.
It is not a fill and not a correction — `--fills-only` withholds it, `--limit` bounds it as its
own outcome, the report counts it on its own line, and it is never mirrored to a board.

Once a club is anchored its dissenters are the audit's candidates, so **run Step 2a after every
anchor pass**. The free `--audit-contradictions --probe-limit 0` run counts what the anchors
exposed; that number is the anchor pass's yield. Measured on the 5,000-call pilot of
2026-09-02 (a free rehearsal run before the pilot, with the largest clubs still unanchored,
printed 4,635 clubs to pick from and 16,700 aliased unclubbed teams): 2,500 anchor calls
confirmed 2,519 teams and corrected 16, and raised the audit's
population from 2,182 to 5,005; the next 2,500 calls on those dissenters found the provider
disagreeing on 1,567 of 2,670 answered (80.8% where two or more club-mates anchored, 48.9%
under a single anchor), 1,486 of them applied unattended. About 300 corrections per thousand
calls, against 29 for a team picked at random.

A team that answered without a state is passed over for a club-mate on the next run, and three
such answers retire the club as one the provider does not know — as does every aliased
member answering that way, since a two-team club never reaches three. A retired club is
reported under "passed over (clubs)" as "unanswerable". A club asked through a club-mate is
not passed over — it was asked — so it gets its own line, "clubs asked a club-mate". A
`no gotsport alias` row counts toward neither: no call was made. An answer already in the
ledger is used instead of a paid call, as in the audit.

```bash
python scripts/assign_team_states.py --probe-unclubbed --probe-limit 2000 --out unclubbed.json
```

is the tail no anchor reaches — a team with no club name, or the only askable team of its
club: **16,455 teams at the end of 2026-09-02, 15,628 with a GotSport id** — the tool
prints the aliased count — asked directly, lowest id first, with the same confirm rule and
the same exclusions (a stored province, an operator's answer, a team the record already
vouches for). Teams with no GotSport id are reported under "passed over (teams)" as "no
alias", as the anchor pass reports its clubs under "passed over (clubs)".

Order the three: anchor, audit, unclubbed. All three share `--probe-limit`,
`--reprobe-after-days` and Step 2a's blocked-probe behaviour, and none may be combined with
another or with `--no-tier-a`.

## Step 3: Read the evidence before writing anything

The run prints a table of fills and corrections per tier. Before applying, know these three
things about what you are looking at.

**Corrections outnumber fills, and that is the point.** The blanks are nearly gone; the
remaining work is fixing values earlier heuristics guessed. On the 2026-08-29 run, 96% of
proposed corrections replaced a state no provider had ever reported.

**Tier B is the workhorse and it has one blind spot.** It reads the club, so a club whose
teams are *uniformly* mislabelled agrees with itself and gets its error propagated to the last
team rather than corrected. Tier E exists to catch that — see
[references/evidence-tiers.md](references/evidence-tiers.md). It reads no club at all for a
placeholder like TGS's "No Club Selection", the largest `club_name` here;
`src/utils/placeholder_clubs.py` holds the list.

**What the run says it cannot decide is as important as what it decides.** Teams no tier
reaches cannot be queued either, because a review row carries a proposal. The run counts them
and names any that are ranked Active, which means they are on a state board right now with no
state. Those need `--set`.

## Step 4: Apply a small batch and verify it against the database

Split the snapshot first, and apply the half that is safe:

```bash
python scripts/hold_unsafe_state_applies.py run.json safe.json held.json
python scripts/assign_team_states.py --execute --snapshot safe.json --limit 50
```

It holds two shapes. A non-A tier overwriting a value the record or an operator stamped — 41 of
202 free-tier applies on 2026-09-02, the loop in which a fill moves the club counts and the
next sweep undoes the last. And a Tier B correction on a club the same run sends to two states
— a club stored as exactly two teams in each of two states tells both pairs to swap, forever
(IMP-161; RSL-AZ Yuma was 2 CA and 2 TX and is in Arizona). Read the held file as a person:
those rows are the ones most worth a `--team` probe, and a sweep with Tier A on settles most of
them by itself.

Then verify — not from the run's output:

```sql
SELECT a.old_state_code, a.new_state_code, t.team_name, t.club_name, t.state_source
FROM team_state_audit a JOIN teams t ON t.team_id_master = a.team_id_master
WHERE a.applied_by = 'assign_team_states' ORDER BY a.id DESC LIMIT 20;
```

Read them as a person would: does the club name or the team name place it where the tool put
it? Gettysburg to PA and Mankato to MN are right for reasons no tier states. If one looks
wrong, it probably is — see [references/failure-modes.md](references/failure-modes.md) before
applying the rest.

## Step 5: Apply the rest from the same snapshot

```bash
python scripts/assign_team_states.py --execute --snapshot safe.json
```

The same split file Step 4 applied, deliberately — not the unsplit one, which would write
everything the split held back, and not a fresh dry run, which would produce a different
snapshot computed against a database the first batch already changed. The held file is a bare
list for reading and cannot be applied. A replay re-reads provenance immediately before its
writes, and again before its confirms, so a team the record (`tier_a`) or an
operator (`--set`) has vouched for since the split is skipped and counted, not overwritten;
the one write that goes through is Tier A over the record's own stamp, which is the record
refreshing itself. A value approved through the review queue carries its tier's provenance,
not an operator's, and this gate does not protect it.

**To undo a batch**, scope by actor *and* date — both, or you will undo more than you meant:

```sql
SELECT * FROM revert_team_states(
  'assign_team_states', '2026-08-29 19:00+00', '2026-08-29 21:00+00',
  'your-name', NULL, 500, false, 'why'
);
```

It returns `(rows_changed, last_team_id)` for one page; loop, feeding `last_team_id` back as
the fifth argument, until it returns no id. Three traps: a revert scoped to an actor that
wrote nothing in the window silently reverts nothing and reports success; answers a person
gave by hand are stamped `operator` rather than `assign_team_states`, so a sweep revert leaves
them alone by design; and a team another writer has moved since the batch is skipped rather
than dragged back.

## Step 6: Work the review queue

Everything the tool would not do on its own authority is in `team_state_review_queue`, with
the tier, the confidence and the reason. The Streamlit dashboard's **State Review Queue**
section approves or rejects them.

Approving applies the change and mirrors it to the state board in the same transaction.
Rejecting changes nothing — and is the only thing that stops the same proposal being raised
again next week, so reject deliberately rather than leaving a row pending.

An approval fails if the team has moved since the row was filed. That is correct: the decision
you are looking at was computed against a state that no longer exists. Re-run the sweep.

## Step 7: Record what ran, and what you could not decide

Note the actor and the time window you used, so the batch can be found later. Then look at
what the run reported as undecidable. A team that is ranked and Active with no state is
visible on a board today; use `--set` with the reason:

```bash
python scripts/assign_team_states.py --team <uuid> --set OH --reason "why you know this" --execute
```

That writes your answer at confidence 1.0, stamped `operator` — also when the team already
holds that value, as a confirm, so the stamp lands and the next anchor pass defers to it
rather than overwriting a held row you agreed with. Use it when the evidence a
person would use is not evidence the tool may act on — who a team plays is the clearest
example, and it is excluded from the tiers precisely because acting on it is what filled this
database with wrong states.

## References

- [references/evidence-tiers.md](references/evidence-tiers.md) — what each tier reads, why the
  order is what it is, and the exceptions that outrank the cascade.
- [references/failure-modes.md](references/failure-modes.md) — shapes in which the evidence has
  already been wrong, and how to recognise them.
