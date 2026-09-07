# Writing a new caller of `apply_team_state`

Three obligations the RPC does not discharge for you. The operator path in SKILL.md needs
none of them — `apply_snapshot` already mirrors what it applies — so this is for code that
calls the RPC directly.

## Mirror the value into `rankings_full` yourself

`apply_team_state` writes `teams` and stops there, deliberately. The state boards read
`rankings_full.state_code`, and nothing re-derives that column until Monday's ranking run
pulls it back out of `teams`. So a caller that stops at the RPC leaves its fill — or its
undo — invisible on the board for up to a week, while the team page and every "missing
state" query already show it.

Every caller in the repo carries the value across itself, in `teams` and in `rankings_full`
both. `revert_team_states` got its mirror in a migration of its own
(`20260829210000_revert_mirrors_the_state_board.sql`), written because the undo looked like
it had not worked to the one audience that matters. Read that migration's header before
deciding you are the exception.

**Mirror with an `UPDATE` keyed on `team_id`, never an upsert.** Monday re-derives the
column from `teams`, so an inserted row would be a ranking no run produced. Two tracked
tests pin that property on the SQL side and fail on an `INSERT`:
`tests/unit/test_team_state_provenance_migration.py::test_approving_mirrors_the_board_with_an_update`
and `::test_reverting_puts_the_board_back_too` — the second also asserting the mirror sits
*inside* the branch that writes, since below the `END IF` it would still read as "after the
apply" while firing on a dry run and on skipped teams. Neither test covers a Python caller,
so `mirror_rankings` and any new equivalent are on you.

## Send the prior source and confidence when reverting

The RPC rewrites the state and all three provenance columns unconditionally
(`20260829120000_add_team_state_provenance.sql`, whose own comment calls them "all three of
them"). A revert that passes its own source therefore leaves a team with no state still
claiming that tier put one there. `revert_team_states` reads `old_source` and
`old_confidence` back out of `team_state_audit` for exactly this reason; a caller reverting
from its own log has to carry both values in that log to have them at revert time.

## Stamp the tier, not a new name for it

`teams.state_source` is documented as the tier that produced the value, and
`state_confidence` as that tier's confidence. A caller whose evidence *is* an existing
tier's evidence should emit that tier's vocabulary rather than a fourth spelling of one
signal — GotSport's `team_association` is Tier A, so a fill from it is `tier_a` at
`TIER_CONFIDENCE["A"]`. Keep the actor distinct instead: `revert_team_states` scopes on
`applied_by`, so that is what should identify the tool.
