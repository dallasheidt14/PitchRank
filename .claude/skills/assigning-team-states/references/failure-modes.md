# Failure modes

Shapes in which the evidence has already been wrong. Use these to recognise a known shape
quickly, and to spend review effort hunting for new ones.

## Contents

- [A club that is uniformly mislabelled](#a-club-that-is-uniformly-mislabelled)
- [A hunt that finds mostly false friends](#a-hunt-that-finds-mostly-false-friends)
- [A club name that is not a club](#a-club-name-that-is-not-a-club)
- [Two clubs sharing a name](#two-clubs-sharing-a-name)
- [A city that is not a city](#a-city-that-is-not-a-city)
- [A border club that is not wrong](#a-border-club-that-is-not-wrong)
- [Evidence that corroborates itself](#evidence-that-corroborates-itself)
- [A silent zero](#a-silent-zero)

## A club that is uniformly mislabelled

The one that got past the tool. *Boise Timbers | Thorns* has six teams; five said Wyoming and
the sixth said California. Tier B looked at the club, found one meaningful state, and wrote
Wyoming onto the sixth. Every step behaved correctly and the answer was wrong, because the
club's own data was the thing that was broken.

Nothing local can detect this: the club agrees with itself, so no tier disputes it. The two
things that do catch it are the place in the name — "Boise" is 95% Idaho across 173 teams —
and the registration record, which said Idaho for all five teams that had one.

**Recognising it:** a small club, entirely in a state its name does not suggest.

**Fixing it:** `--audit-contradictions` is the systematic remedy. Once any team of the club
carries a provider-confirmed state, its mislabelled club-mates contradict that anchor and the
audit selects them, whether or not a tier ever objected. `--team <uuid>` stays the one-off
route, and it is what produces the first confirmed team when a club has none.

## A hunt that finds mostly false friends

Knowing the shape above is not the same as knowing where to look for it. Two obvious searches
were measured on 2026-08-31 and both are poor: each returns a list nobody can act on without
checking it against the provider, and the checking is the expensive part.

**Asking whether a club's name points where none of its teams are stored.** 18 clubs, 262
teams. Fifteen were false friends — Delaware Knights is in Ohio, Oregon SC in Wisconsin,
Georgia United in Vermont, all real places sharing a state's name. Three were real candidates
and two survived probing.

**Judging one provider's teams on every other provider's evidence.** Rebuilding the club and
locality indexes without TGS and re-deciding TGS teams against them breaks the circularity
directly and costs nothing: 153 candidates across 47 clubs. But only 14 had a GotSport record
to check against, and **12 of the 13 that answered were false positives** — the stored state
was right and the audit was wrong. One of them, *Colorado Elevation FC*, holds UT and reads
like an obvious catch; UT is correct.

**What pays instead** costs nothing to compute, because it reuses registration records already
paid for:

> a team whose state contradicts a club-mate's already-confirmed `state_source = 'tier_a'`
> state, for clubs where every confirmed team agrees on one state — excluding teams whose
> stored state is a Canadian province, which Tier A never corrects.

Of 150 sampled, 143 had a record, 129 answered, and **65 were genuinely wrong — 50.4%**,
against a **2.9%** base rate for a random team no tier disputes. Seventeen times better per
paid call. Those two ratios should hold; the populations they came from will not.

The province clause is load-bearing rather than a footnote: every team it drops is a call Tier
A would never act on. For the counts, see SKILL.md Step 2a.

It reaches a uniformly mislabelled club only *after* someone has probed one of its teams —
which is exactly the `--team <uuid>` fix above. That first probe stamps `tier_a` on one team
and turns the rest of the club into candidates, so the rule mechanises the manual fix rather
than replacing it.

Its false positives have one cause: a generic `club_name` covering teams that are genuinely
different clubs — *North FC*, *Valley United SC*, *Elite FC*, *Eastside FC*, *Legacy FC*. That
is [two clubs sharing a name](#two-clubs-sharing-a-name) wearing a state problem's costume, and
the database already knows it in places, since `Eastside FC (WA)` exists beside a bare
`Eastside FC`.

Two limits worth stating before anyone plans around this. Only a team with a GotSport alias can
be probed at all — 175,688 of 197,961 stated teams. And TGS, the provider that generates the
most blanks, is the population it reaches *least*: 6,256 of its 22,819 stated teams have a
record, leaving 16,563 with no external truth available by any current means.

The value is targeting rather than exclusivity: 39% of the candidates are already in the
sweep's disputed set, because `club_derived_state` excludes the team being decided from its own
club counts, so a club with two wrong teams against 41 right ones *is* disputed by Tier B. A
full sweep reaches those too, at roughly six times the calls.

`--audit-contradictions` implements this rule, with the province narrowing noted above: see
SKILL.md Step 2a. The measurements behind this section are in
`.turbo/reports/2026-08-31-targeting-the-gotsport-probe.md`.

## A club name that is not a club

`club_name` sometimes holds a league, a placeholder, or a tournament bucket. *No Club
Selection* holds 1,596 teams across 23 states. *Alliance Youth Soccer League* and *MYSA
Independent Teams* are leagues. These are in the registry as curated, so club-level evidence
queues rather than applies, but new ones appear.

**Recognising it:** a large club whose teams spread across states that share no border, or a
name containing "league", "association", "independent", or "selection".

## Two clubs sharing a name

*FC Stars* is a Massachusetts club with 343 teams; *FC Stars (IL)* is a different club. *Elite
FC* is three clubs across Ohio, Utah and Nevada. *Legends FC* is one club in California and
another in Ohio. Counting teams across the merged bucket answers a question nobody asked.

**Recognising it:** two states that both look like real programs — both with teams whose names
are geographically consistent with their own state. Contrast with contamination, where the
minority state's team names read as the majority's.

## A city that is not a city

Tier E learns place words from the data, which means a word that merely correlates with a
state can look like a place. Brand words are excluded by name. What remains are league codes
that are genuinely regional (`STXCL` is South Texas, `LIJSL` is Long Island) and the
occasional coincidence.

The observed cost is over-queueing rather than wrong writes: a team of the *Georgia Soccer
Association* went to review because a word in its name pointed at Texas while the club
correctly said Georgia.

## A border club that is not wrong

*Sporting Blue Valley* is in Overland Park, Kansas, and Kansas City straddles the state line,
so a couple of its teams register with Missouri Youth. *Shreveport Strikers* is a Louisiana
club that plays essentially all its games in Texas.

Neither is a data error. A team's state is where its club is based, so registration and travel
both being out of state changes nothing.

**Recognising it:** a minority state adjacent to the majority, with a metro area spanning
both.

## Evidence that corroborates itself

The full-name `state` column separates a state a provider reported from one a heuristic
derived — but only four writers set it, and **two of them are backfills**. On 2026-08-29 a
capped backfill run wrote both columns for 1,159 teams, so those teams look provider-reported
and are not.

Treat a filled `state` column as "not obviously guessed", never as corroboration. When
measuring, exclude teams whose state was written by the run you are measuring.

## A silent zero

The recurring shape in this project, and it has bitten inside this tool.

The first version of the GotSport probe swallowed every error as "this team has no
association". When a direct burst got the whole run blocked with HTTP 403, that read as 6,180
teams quietly having no registration record — a tier that had been switched off by the network
reporting a clean zero. It now counts every outcome and stops when calls are failing, because
a blocked probe must look like a blocked probe — a sweep aborts outright, while an audit
decides from the answers it already holds and then exits non-zero.

Suppressing re-probes from the ledger can reproduce the shape. A 404 and an empty payload are
durable facts about one team and a provider-wide failure about a thousand; filed as answers for
a whole run they would silence that population for the full re-probe window and exit 0. So the
404 counts toward the failure ratio, and a batch of at least twenty calls that mapped fewer
than a fifth of them is treated as blocked however it phrased its silence. A share rather than
a bare zero, because one mapped answer in a thousand is still an outage — and a floor, because
below it an empty answer is a fact about a team rather than about the provider.

The same shape, elsewhere: a revert scoped to an actor that wrote nothing reverts nothing and
reports success; a `--limit` a workflow step never wired up caps nothing; a team no tier
reaches produces no decision and no queue row, and used to vanish from the report entirely.

**When a count comes back zero, establish that it is a real zero.**
