# Failure modes

Shapes in which the evidence has already been wrong. Use these to recognise a known shape
quickly, and to spend review effort hunting for new ones.

## Contents

- [A club that is uniformly mislabelled](#a-club-that-is-uniformly-mislabelled)
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

Nothing local can detect this: the club agrees with itself, so no tier disputes it, and a
sweep never looks at a team nothing disputes. The two things that do catch it are the place in
the name — "Boise" is 95% Idaho across 173 teams — and the registration record, which said
Idaho for all five teams that had one.

**Recognising it:** a small club, entirely in a state its name does not suggest. **Fixing it:**
`--team <uuid>` on any one of them always probes the provider, then check the clubmates.

## A club name that is not a club

`club_name` sometimes holds a league, a placeholder, or a tournament bucket. *No Club
Selection* holds 1,589 teams across 22 states. *Alliance Youth Soccer League* and *MYSA
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
reporting a clean zero. It now counts every outcome and aborts when calls are failing, because
a blocked probe must look like a blocked probe.

The same shape, elsewhere: a revert scoped to an actor that wrote nothing reverts nothing and
reports success; a `--limit` a workflow step never wired up caps nothing; a team no tier
reaches produces no decision and no queue row, and used to vanish from the report entirely.

**When a count comes back zero, establish that it is a real zero.**
