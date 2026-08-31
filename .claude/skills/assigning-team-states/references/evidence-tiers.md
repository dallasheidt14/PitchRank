# Evidence tiers

What each tier reads, why they rank the way they do, and the rules that outrank the cascade
entirely.

## Contents

- [The question every tier answers](#the-question-every-tier-answers)
- [Tier A — the registration record](#tier-a--the-registration-record)
- [Tier B — the club's own teams](#tier-b--the-clubs-own-teams)
- [Tier C — a state named in the team's name](#tier-c--a-state-named-in-the-teams-name)
- [Tier E — a place in the name](#tier-e--a-place-in-the-name)
- [Tier D — TGS tournament participants](#tier-d--tgs-tournament-participants)
- [What outranks the cascade](#what-outranks-the-cascade)
- [What is deliberately not a tier](#what-is-deliberately-not-a-tier)

## The question every tier answers

Where is this team's **club** based. Not where it played, not who it played, not who
sanctioned the fixture. Every tier is a different way of asking that one question, and the
ranking is by how directly each one answers it.

A tier that fires proposes a state. The highest one that fires wins and is recorded in
`teams.state_source`, so a value can always be traced to the reasoning that produced it.

## Tier A — the registration record

Confidence 0.95. GotSport's `team_association`: the state association a team registers with,
per team rather than per club.

**It is an association code, not a postal code.** `CAN` is California North, not Canada;
Canada is `CND`. Four states never emit their postal code at all — California, New York,
Pennsylvania and Texas split by region — so a lookup that only handled the identity cases
would silently drop four of the five largest cohorts. `src/utils/team_association_map.py`
holds the mapping and fails closed: an unseen code returns nothing rather than being treated
as a postal code, which is what would send a Brazilian team to a US state board.

Measured against the club count on 1,572 teams where both answered, they agree 97.1%, and
where they differ the registration record is usually visibly right from the team's own name.

**It is only probed for teams something else already disputes.** One HTTP call per team means
probing all 200,164 to find the ones nobody flagged is not a thing the sweep does. A named
team is always probed — `--team <uuid>` — which is how a uniformly mislabelled club gets
resolved.

## Tier B — the club's own teams

Confidence 0.90. Where the rest of the club sits.

A state is **meaningful** to a club when it holds at least two of its teams *and* at least 5%
of its known-state teams. The tier fires only when exactly one state qualifies, counting the
club's other teams and **excluding the team being decided** — a wrongly-coded team otherwise
votes for the minority bucket it created, and one clubmate sharing the error is enough to
reach the two-team floor and silence the tier on exactly the teams it should correct.

Group clubs on `lower(btrim(club_name))`. Raw `club_name` splits one club across case and
whitespace variants; `normalize_club_name` merges clubs that are not the same club, deleting
the parentheses that are often the only state disambiguator.

**A placeholder club name is not a club, and keys to nothing.** Providers write a literal
dropdown value rather than leaving the field empty, so `club_name` arrives non-null and every
repair path that looks for a *missing* club walks past it. TGS's "No Club Selection" is the
largest single `club_name` in the database — 1,596 teams, more than any real club — spanning
23 states. `src/utils/placeholder_clubs.py` is the one list; `club_key` returns `""` for a
member, which makes Tier B abstain and keeps the name out of Tier E's index. Before that,
the tier abstained only because no single state was meaningful enough to win, which is a
property of the data rather than a rule. `athlete one` is a member for a different reason:
it is the provider AthleteOne's name in `club_name`, and only two of its 23 teams carry a
state — both FL, exactly enough to propose Florida for 21 teams that are not one club.

Where a club has an entry in `src/utils/club_state_registry.py` carrying a `home`, that home
**is** the club's state for every team in it, replacing the computed test. 45 clubs are homed
that way. The other 24 need a person and make this tier queue instead of apply.

## Tier C — a state named in the team's name

Confidence 0.85. Reuses `state_from_name` in `scripts/backfill_state_from_team_name.py`,
which knows the false friends: `SC` is Soccer Club, `GA` is Girls Academy, a name holding two
states is a fixture rather than a home, and an affiliate marker that contradicts the name
("Utah Royals FC-AZ") refuses rather than picks.

## Tier E — a place in the name

Confidence 0.85. Learned rather than curated: for every word appearing in team and club names,
where do the teams carrying that word actually sit. A word earns a state at ten teams and 90%
agreement.

It exists because Tier B has a blind spot it cannot see. "Boise" appears in 173 team names and
95% of them are Idaho, but the six teams of *Boise Timbers | Thorns* said Wyoming — five of
them wrongly — so the club agreed with itself and the sweep wrote Wyoming onto the sixth.
Nothing local disputed it. GotSport says Idaho.

The thresholds are what keep it honest: "Springfield" spans four states and "Portland" three,
and neither reaches 90%. Brand words are excluded outright — "Surf" and "Rush" are national
franchises with a dominant state, which is exactly the shape that reads as a place.

**It is learned from the column being audited**, so it is circular in the strict sense. That
is why its first job is to raise doubt rather than to assert: any two of the club, the name
and the place disagreeing sends the team to review whichever tier would have won. It fills
blanks too, but it never corrects on its own.

## Tier D — TGS tournament participants

Confidence 0.85. The modal state of a gated tournament's participants, gated on the event
being tournament-type, having at least ten participants with a known state, and 90% of them
agreeing.

**It requires the `tgs_events` table**, which is not populated. While that table is empty the
gate cannot be evaluated for any event, so the tier does not fire and the run says so rather
than reporting a silent zero. It was left unbuilt deliberately: of the teams it would serve,
only a handful are ranked and visible on a board.

## What outranks the cascade

Stated pairwise rather than as one ordering, because the intents genuinely differ.

| Rule | Effect | Outranks |
|---|---|---|
| A stored Canadian province | no tier corrects it | everything |
| Two readings disagreeing | queue, cascade not run | the whole cascade, unless Tier A answered |
| A stored `DC` | queue | Tier A's exemption below |
| A curated club | Tiers B, C, E queue | applies when nothing above fired |
| A stored value that was *reported* | a non-A correction queues | Tiers B, C, E |
| The ledger holds a revert away from this value | queue | any auto-apply |

The last two are worth spelling out. A state some writer also spelled into the full-name
`state` column came from a provider payload, a TGS import or an admin form rather than from a
heuristic — counting a club is not evidence enough to overrule it, though a per-team
registration record is. And a value an operator has already reverted must not be re-applied
next week, which is the only thing that makes a revert stick.

## What is deliberately not a tier

**Opponents.** Where a team's opponents are is travel. Its pollution is self-confirming: in a
mislabelled cluster the wrong teams play each other, so "96% of opponents are Illinois"
restates the error rather than testing it. This is the signal that wrote much of the bad data
in the first place, and the weekly step that used it is switched off.

**Venues and competitions.** Same objection, weaker signal.

**`teams.league`.** Not geographic — ECNL RL spans 44 states.
