---
status: done
---

# Plan: Keep saved seeding runs safe across imports, view switches and name clashes

## Context

A 2026-09-23 audit of the MatchBalance Seeding intake confirmed four defects in how runs are saved and named:

- A new import autosaves over whichever run is open, under that run's name. This covers a paste, an event walk, the paid cost probe and "Open the saved sample (free)". The original then survives only in `history/`, which no screen reopens.
- The run name lives only in a widget key. Switching Seeding → Backtest → Seeding empties it while the roster stays loaded, so every later autosave silently returns False.
- Messages emitted right before an unconditional `st.rerun()` are erased. "Name and save the current run first", "published no teams" and "Matching paused" all flash and vanish.
- Two run names that slugify to one folder overwrite each other.

The intended outcome is that no import or name choice can overwrite a different run, typed inputs survive a view switch, and every refusal stays on screen.

The owner decided three behaviours on 2026-09-24:

1. When a new roster is imported while a saved run is open, leave the open run untouched and wait for a new name before anything saves. Do not refuse the import and do not auto-suffix.
2. When two different names map to one folder, refuse the save and name the run already there.
3. An edited re-paste into a run that came from a paste counts as the same run and keeps its name. The previous version is archived to `history/` as today. Re-walking the same event also keeps its name.

## Pattern Survey

### Analogous Features

- **Notices carried across a rerun.**
  - `src/tournaments/backtest_intake_ui.py:1787-1791` sets `bt_history_notice_{event_key}` before `st.rerun()` and pops it at `:1715-1717`. The `bt_saved_{generation}` flag works the same way (`:2298-2300`, `:2078-2079`).
  - `tournament_intake.py:772-800` `_render_registry_persist_results` is prior art for the same idea, but nothing calls it.
- **Rerun only after success.** `backtest_intake_ui.py:1632-1686` `_run_reviewed_requests` reruns only when nothing failed. `_run_seeding_resolve` (`tournament_intake.py:3653`) already returns a bool, but its paste caller reruns regardless.
- **Restore before render.** `tournament_intake.py:4679` `_apply_pending_seeding_widgets` copies `_seeding_pending_name` / `_seeding_pending_event_url` into the widget keys before the widgets exist, and clears `seeding_roster_text`. `_autosave_seeding_run` refuses while a pending key is set.
- **Widget mirroring the other way.** Backtest's cohort editor (`backtest_intake_ui.py:1060-1093`, `_save_cohort_field` `:742-754`) uses `on_change` to copy a widget into a plain dict and re-seeds the widget from it.
- **Backtest binds a save to its source by construction.** The event id is the storage key: `write_snapshot` refuses another event (`src/tournaments/backtest_intake_state.py:626-627`). Seeding binds by a free-typed name through `slugify(name)`, and nothing ties the name to a source.
- **Seeding's existing source guard.** `_seeding_context_matches` (`tournament_intake.py:4662`) checks only that the roster in memory matches its own metadata. It never looks at what is saved under the target name.
- **Same-event refresh is deliberate.** `_park_event_roster` carries decisions when `result_event_id == roster.event_id`, and `test_matching_checkpoints_preserve_previous_source_snapshot` (`tests/unit/test_seeding_quote_workflow.py:303-318`) pins that a changed source under the same name archives the previous one.
- **Keep the previous run visible.** `_clear_result_from_other_event` (`tournament_intake.py:5037`) has been unwired since #1174 by design, and should stay unwired.

### Reusable Utilities

- **The single save path:** `_autosave_seeding_run(*, archive_previous=True) -> bool` (`tournament_intake.py:4540`). There are 15+ call sites, so a gate added here covers every one of them.
- **Installing a new source:** `_apply_seeding_transition` (`:4633`) installs it in one step. Only the load path passes `name` / `loaded_slug`.
- **Rebuilding metadata from a saved run:** `_load_seeding_run` (`:4589`) does this, including `event_id`, `fingerprint`, `source_kind` and `source_url`.
- **The run store:** `src/tournaments/seeding_run_store.py`
  - `save_run` (`:140`)
  - `load_run` (`:174`), which reads the stored `name` and `assessment`
  - `list_runs` (`:202`)
  - `slugify` (`:132`)
- **Change callbacks:** `backtest_intake_ui.py:80` `_set_session_value` is a trivial `on_change` setter.

### Convention Anchors

- **Key naming.** Seeding-only session keys are literal `_seeding_*`. Widget keys drop the underscore: `seeding_event_name`, `seeding_event_url`, `seeding_roster_text`. Defaults are seeded in `_init_session_state` (`tournament_intake.py:563-589`).
- **Streamlit's rerun rule.** Streamlit raises a queued rerun from `BaseException` at session-state writes (CLAUDE.md). Write multi-key changes to one pending key and install them on the next render.
- **Test doubles.**
  - `tests/unit/test_seeding_event_intake.py` has `_FakeSt` / `_FakeSessionState` with `arm()`, `spinner_raises`, and the collected `errors` / `warnings` / `infos`.
  - `_FakeSt.text_input` / `text_area` do not model widget state. Test the view-switch behaviour with Streamlit's `AppTest`, as `tests/unit/test_seeding_quote_workflow.py` and `tests/unit/test_seeding_intake_ui.py` do.
- **Run-store tests.** `tests/unit/test_seeding_run_store.py` uses a `tmp_path` base_dir. `test_saving_the_same_name_twice_overwrites_rather_than_duplicating` (`:201-205`) must stay green.

### Proposed Alignment

- **Part 3:** follow Backtest's notice pattern and its rerun-on-success rule.
- **Part 2:** extend `_apply_pending_seeding_widgets` rather than add a new mechanism.
- **Part 1:** gate inside `_autosave_seeding_run`, using the saved run's `assessment` event id and fingerprint, with the event id taking precedence.
- **Part 4:** put the check inside `save_run`.

## Implementation Steps

Work in the worktree `C:/pitchrank-seeding-run-safety` on branch `fix/seeding-run-safety`, created from `origin/main` at `3d646c812`. Before editing, confirm `git -C C:/pitchrank-seeding-run-safety status --short` is empty apart from this plan file. If other files show as modified, another writer is using the tree: stop and ask.

1. **Refuse a name that clashes with a different run (part 4).**
   - In `src/tournaments/seeding_run_store.py` `save_run`, when `root / slugify(run.name) / seeding_run.json` already exists and its stored `name` differs from `run.name`, raise a new `RunNameTaken(ValueError)` carrying the existing name. Check this before archiving or writing anything.
   - The comparison is on the exact stored string. An identical name overwrites as today.
   - A file whose `name` cannot be read, because it is missing or malformed, is treated as the same run, so a damaged save can still be replaced.
   - In `tournament_intake._autosave_seeding_run`, catch `RunNameTaken` and set a visible notice (step 3's key) naming the other run. Return False without saving.

2. **Bind a save to the run already saved under the name (part 1).**
   - Add a helper in `tournament_intake.py`, for example `_saved_run_source(slug) -> Mapping | None`. It returns the `assessment` of the run saved at that slug, or None when there is none or it is unreadable.
   - In `_autosave_seeding_run`, before calling `save_run`, compare the current `_seeding_assessment` with that saved assessment:
     - Both carry an `event_id` → the same event is the same run; a different event is a different run.
     - The saved run came from a paste (no `event_id`) and the current roster is also a paste → the same run, per decision 3.
     - Anything else (event versus paste either way, or a different event) → a different run.
   - When it is a different run, do not save. Set `_seeding_pending_name = ""` and clear `_seeding_loaded_slug`, so step 4's restore empties the name box. Set a notice: "This roster is not the open run '<name>'. Give it a name to save it."
   - This gate sits in the single save path, so the walk, paste, probe, sample and override paths all inherit it.

3. **Carry notices across a rerun and rerun only on success (part 3).**
   - Add a `_seeding_notices` list of `(level, text)` pairs, seeded in `_init_session_state`, plus a small `_add_seeding_notice(level, text)` helper that appends to it.
   - At the top of `_render_seeding_tab`, pop the list and emit each notice with `st.error` / `st.warning` / `st.info`.
   - Route through `_add_seeding_notice` every message that is followed by a rerun:
     - the refusal and "No team rows found" warning in `_run_seeding_resolve`
     - "published no teams" in `_run_event_roster_scrape` (`:3792`)
     - both "Matching paused" infos in `_resolve_seeding_incrementally` (`:4211`, `:4238`)
     - steps 1 and 2's save refusals
   - In `_render_seeding_tab`'s paste branch, call `st.rerun()` only when `_run_seeding_resolve` returns True.
   - Keep the refusals that already `return` without a rerun as direct `st.error` calls.

4. **Keep the run name, event URL and paste box across view switches (part 2).**
   - Give the `seeding_event_name`, `seeding_event_url` and `seeding_roster_text` widgets an `on_change` that mirrors each value into a plain key: `_seeding_kept_name`, `_seeding_kept_event_url`, `_seeding_kept_roster_text`.
   - In `_apply_pending_seeding_widgets`, when a widget key is absent (Streamlit dropped it on the view switch) and no pending handoff applies, restore it from its kept key. A pending handoff still wins, so a loaded run's name and its cleared paste box behave as today.
   - When a pending handoff sets a value, also update the kept key, so a later switch restores the handed-off value rather than a stale one.
   - `_autosave_seeding_run` reads the name from the widget key as today. After a switch the restore has repopulated it, so later saves work.

5. **Leave `_clear_result_from_other_event` unwired.** It is dead code apart from its test. Removing it belongs to the dead-code cleanup, not this change.

## As built (2026-09-24)

The shipped code departs from steps 2 to 4 in seven places. Read this section, not those steps, for what the code does.

- **Both checks live in the store.** `save_run` raises `RunNameTaken` and `RunSourceChanged`, and no intake-side `_saved_run_source` helper exists. Tests that point the store at a temporary folder therefore exercise the real refusals.
- **The source rule has a fourth case.** A partial walk never replaces a saved complete walk of the same event, and the refusal says the walk covers less. An older save with no event id or source URL counts as the event named in its `GotSport Event N` name.
- **A detach uses its own flag.** It uses `_seeding_detach_run`, not `_seeding_pending_name = ""`. A pending name makes every save refuse, which would pause matching. The loaded-run handoff also clears the paste box and resets the source.
  - The next render empties the name and clears the loaded slug.
  - It assigns the resume selector `None`. Removing the key never reached the browser, which sent its old choice back and reopened the old run.
- **An event walk saves once after parking its roster, as a paste does.** A different source is then detached before the matching pass checks for a name.
- **Widget values survive a view switch by being written back each run, not mirrored.** `_init_session_state` writes each key in `_SEEDING_KEPT_WIDGETS` back to itself. This is Streamlit's documented pattern. It also keeps the roster-source radio and the "complete list" checkbox, and a value cleared by a handoff stays cleared.
- **Notices render last and leave the queue only once drawn.** `_render_seeding_tab` draws them into a container at its top after the workspace finishes. A notice raised mid-render therefore shows in the same run, and one interrupted while drawing waits for the next run.
- **A refused paste keeps its message by not rerunning.** `_run_seeding_resolve`'s two refusals stay direct `st.warning` / `st.error` calls, and the paste button reruns only when the import succeeds.

The tests are in `tests/unit/test_seeding_run_safety.py`, not `test_seeding_event_intake.py`. The view-switch `AppTest` drives a two-view stand-in app rather than `main()`, and there are no kept keys to compare against. Line numbers in Context Files are as of `3d646c812`.

## Verification

- `tests/unit/test_seeding_run_store.py`:
  - saving "STX Cup (Boys)", then "STX Cup - Boys", raises `RunNameTaken` naming the first, and leaves the first file byte-identical
  - an identical name still overwrites
  - a malformed existing file can be replaced
- `tests/unit/test_seeding_event_intake.py` with `_FakeSt`:
  - Different run: open saved run A (event 111) → walk event 222 → nothing is written to A's folder, the name is handed off as blank, and the notice text is shown after the rerun.
  - Same event: re-walking event 111 under A saves over A and archives the previous version, so the existing checkpoint test stays green.
  - Paste over paste: a pasted run re-pasted with an edit saves under the same name.
  - Crossing sources: pasting into an event run, or sampling another event, waits for a name.
  - Refusal visible: the refused-paste message and "published no teams" are still in `fake_st.errors` / `warnings` after the rerun.
  - Clashing name: saving under a name whose folder holds a different run shows the notice naming the other run.
- An `AppTest` case using the real `main()` view switch:
  - type a run name, URL and paste, then switch to Backtest and back → all three are still filled
  - an autosave after the switch returns True
  - a loaded run's pending name still wins over a kept name
- Mutate each gate on its own and check that a named new test fails:
  - the source comparison's event branch
  - its paste-over-paste branch
  - the notice pop
  - rerun-on-success
  - the name-clash check
  - each restore
- Run the full CI gate and confirm it passes.

## Context Files

- `tournament_intake.py` — `_autosave_seeding_run` (`:4540`), `_seeding_context_matches` (`:4662`), `_apply_seeding_transition` (`:4633`), `_apply_pending_seeding_widgets` (`:4679`), `_render_seeding_run_controls` (`:4705`), `_render_seeding_tab` (`:5210`), `_run_seeding_resolve` (`:3653`), `_run_event_roster_scrape` (`:3679`), `_resolve_seeding_incrementally` (`:4197`), `_init_session_state` (`:563-589`)
- `src/tournaments/seeding_run_store.py` — `save_run`, `load_run`, `slugify`
- `src/tournaments/backtest_intake_ui.py` — the notice and rerun-on-success patterns (`:1632-1686`, `:1715-1717`, `:1787-1791`)
- `tests/unit/test_seeding_event_intake.py` — the `_FakeSt` double and its rerun modelling
- `tests/unit/test_seeding_quote_workflow.py` — `AppTest` usage and the same-name checkpoint test
- `tests/unit/test_seeding_run_store.py` — the run-store test conventions
