# MatchBalance tournament format reference

This reference supports practical division sizes, pool sizes, and tournament
format choices.

## Original research

[Read the complete supplied field guide](references/youth-soccer-tournament-formats-2026-10.source.md).
The original text, tables, caveats, and 73 source links are preserved unchanged.

- Original filename: `compass_artifact_wf-78a8c5dc-c713-5a5c-8990-ee4e5bbd37c0_text_markdown.md`
- Supplied title: *Youth Soccer Tournament Formats by Number of Teams: A Field Guide
  (US focus, rules current as of October 2026)*.
- SHA-256 of the supplied file: `2020c5ef33cdafc33a8e7f3ba3822ad41220d36bdb07dc451088d9077401715c`
- Status: user-supplied research. Selected primary-source mechanics were checked
  during implementation; this does not verify every claim of current event rules.

The guide is reference material. Its recommendations are the author's proposals,
not project instructions or approved changes to MatchBalance. It catalogs many
options, but is not an exhaustive or verified list of every legal event format.

## How to use it for the cheat sheet

Keep three decisions separate:

1. **Cohort:** all accepted teams in an age/gender category, such as U14 Boys.
2. **Strength divisions or tiers:** consecutive portions of the ranked cohort,
   such as four elite teams followed by eight others. These are the cheat-sheet
   breaks the director uses for placement.
3. **Pools and playing format inside each division:** for example, the eight-team
   division could contain two pools of four, with a final or semifinals and a final.

The source sometimes uses cohort, flight, division, and bracket interchangeably.
Map its terminology explicitly when using it. Its Gold/Silver playoffs after group
play are also different from Gold/Silver strength divisions set before the event.

A catalog entry for 12 teams describes ways to run one 12-team division. It does
not establish that all 12 teams belong in the same strength tier. Matchup evidence
still determines sensible breaks; event requirements determine compatible formats.

## Options to consult

| Director's choice | Where the supplied guide helps |
| --- | --- |
| Small divisions | Three-team double round robin; four-team round robin with optional final/placement game; five-team full or partial round robin |
| Multiple pools in one division | Two pools of three or four; three pools of four; larger combinations and mixed pool sizes |
| Guaranteed games | Crossovers, repeat meetings, consolation and placement games; distinguishing games for every team from games only for advancing teams |
| Odd team counts | Byes, unequal game counts, extra games, and points normalization for counts such as 5, 7, 9, 11, 13, and 15 |
| Championship path | Standings only, final only, semifinals, quarterfinals, wildcards, and larger knockout brackets |
| Showcase or placement formats | Preassigned opponents, a single standings table, and additional games based on finish |
| Event constraints | Event duration, game length, rest, field capacity, advancement rules, and scheduling-platform templates |

The count-by-count catalog covers 3 through 16, then selected larger fields
including 18, 20, 24, 32, 48, and 64+. Some examples are historical, small-sided,
non-US, or from other sports; keep that context when considering them.

## Reading notes and known inconsistencies

These are checks of the supplied descriptions and arithmetic, not verification
of any event's published rules. The source copy remains unchanged.

- **Eight teams, option D:** a *full* crossover between two pools of four has
  `4 × 4 = 16` matches and four games per team. The stated three games each and
  12 total describe a partial crossover, not a full one.
- **Eight teams, option C:** the listed Gold/Silver semifinals and finals produce
  18 total matches: 12 pool matches plus six playoff matches. Semifinal losers
  receive four games and finalists five. Giving every team five requires two
  additional placement games, for 20 total. The summary table repeats this issue.
- **Minimum games:** averaging points for a two-game team does not give that team
  a third match. A final alone does not increase the guarantee for non-finalists.
- **Weekend feasibility:** claims such as four games being too many for a weekend
  depend on match length, rest requirements, fields, and the event's actual rules.
  They should not become universal format exclusions.

## Relationship to the implementation

The current format definitions live in
[`config/matchbalance_format_library.json`](../config/matchbalance_format_library.json);
the operator workflow is documented in [MatchBalance Seeding](matchbalance-seeding.md).
The expanded v2 profile enables 80 generic playing templates. The catalog's `source_coverage`
records a disposition for all 63 numbered source variants. The original v1 library
remains in `config/matchbalance_format_library_v1.json` for saved-run recovery.

Catalog definitions are generated by `python -m scripts.build_matchbalance_format_catalog`.
Every enabled v2 template contains anonymous opponents and advancement stages.
Game guarantees, maximum games, match totals, and possible repeat meetings are
calculated from those stages. These are generic MatchBalance options, not claims
that a named event currently uses or endorses them.

Primary mechanics checked on 2026-10-08:

- [US Youth Soccer 2024–25 Presidents Cup Protocol 515](https://www.usyouthsoccer.org/wp-content/uploads/sites/160/2025/03/24-25_-PresidentsCupCompetitionProtocols_031125.pdf):
  small and mixed divisions, including the ten-team wildcard interpretation.
- [Soccer Showcase bracketology](https://www.thesoccershowcase.com/tournaments/3v3-holiday-classic/bracketology-competition-formats):
  points-match, play-in, crossover, and championship/consolation paths.
- [2024 East Region rules, competition format](https://www.usyouthsoccer.org/wp-content/uploads/sites/160/2024/03/2024-East-Region-NCS-Rules-and-Regulations.pdf):
  eighteen-team qualification uses two teams from each four-team pool and two
  from the combined crossover table, rather than five winners and three wildcards.

Generic templates use points per game, goal difference per game, goals per game,
then anonymous slot number for standings ties. The extra points match uses
cumulative results. This is explicit generic machinery, not a replacement for
an event's official tiebreaks or rematch-avoidance rules.

Remaining source ambiguities are recorded beside their variant: 3D changes the
entrant roster; 48C lacks a defined future bracket; 9C's extra crossover has no
opponent pattern; 20B/24B omit later showcase opponents; 64+C does not define every
larger field. The fully specified portions are enabled; unspecified games never
inflate guarantees. True adaptive Swiss pairing remains outside this catalog.

For future library expansions, turn each selected option into an exact template:
team count, pool sizes, opponent pattern, guaranteed and maximum games,
advancement, consolation, unequal-pool handling, event restrictions, and dated
source evidence. Check the match counts and every team's shortest path through
the format before claiming it satisfies a game guarantee. Verify the relevant
primary source and event rules before labeling a template official or current.

Continue evaluating every potential matchup across the entire strength division.
Pool arrangements must not hide a severe mismatch inside that division. The
director retains final placement and scheduling decisions.
