---
status: done
---

# Plan: A Seeding rebuild keeps every cohort's notes, and an interrupted build can be restored

## Context

Line numbers in Context, Pattern Survey and Implementation Steps refer to the tree before this change.

The 2026-09-23 audit confirmed two ways the Seeding tab loses operator work without saying so:

- **C2, notes dropped on a narrowed rebuild.** `src/tournaments/seeding_intake_ui.py:330-343` copies `operator_notes` and `placement_reviews` into the rebuilt pack only for the cohorts selected now, then saves (`:443-446`). A note written for a cohort that is deselected for one rebuild is deleted, and reselecting the cohort does not bring it back. The only surviving copy is an archived history file the UI never lists. The screen says the opposite at `:316`: "Rebuilding reads fresh data while preserving director notes and roster decisions." The UI filter is forced by the pack validator, `src/tournaments/seeding_pack.py:228-230`, which requires `operator_notes` keys to be a subset of the selected cohorts.
- **C3, a build lost to a click.** The rebuilt pack lives in a local (`pack = candidate`, `:345`) until `st.session_state[_PACK_KEY] = pack` at `:444`. A widget click during the build (up to about 300 s) queues a rerun. Streamlit raises it as a `BaseException` at the spinner's exit or inside the next session-state write, and `except Exception` at `:347` cannot catch it. The paid predictions are discarded, the previous pack stays exportable with its old timestamp, and no error shows.

The audit's fixes:

- C2: carry notes and reviews for unselected cohorts forward, and filter by selection only at render and export.
- C3: write the validated candidate to a recovery file right after `analyze_pack`, the same approach the paid event walk uses (`_write_recovery`, `tournament_intake.py:3832`), and offer it back.

## Pattern Survey

- **Notes consumers already look up by sheet key.** `seeding_sheet.py:604`, `seeding_workbook.py:86`, `seeding_content.py:137`, `seeding_pack.py:401` and `seeding_intake_ui.py:154,190` all call `.get(key)` for a rendered cohort. So an extra key for an unselected cohort never reaches a sheet, a workbook or the export fingerprint.
- **Placement reviews are fingerprint-bound.** `needs_placement_review` (`seeding_pack.py:406`) honours a stored review only when it matches the current evidence, seed order and notes. Carrying a review forward for a reselected cohort is safe: it counts only if nothing it reviewed has changed.
- **Run storage.** `seeding_run_store.save_run` writes `<base>/<slugify(name)>/seeding_run.json` with `write_json`, and refuses a folder that holds a different run's name. The recovery file sits beside it in the same folder.
- **Tests.** `tests/unit/test_seeding_intake_ui.py` drives `render_seeding_pack` through `AppTest` with the `operator` fixture. `test_narrowing_cohorts_preserves_only_selected_notes_and_policy` (`:281`) currently pins the C2 defect. `tests/unit/test_seeding_pack.py:124-125` (the "notes" corruption case) pins the validator's subset check.

## Implementation Steps

1. **Validator (`seeding_pack.py:228-232`).** Drop `operator_notes` from the subset-of-request check. Keep the check for `manual_groups` and `unavailable_codes`. `operator_notes` must still be a dict of string keys to string values.
2. **Rebuild carry-forward (`seeding_intake_ui.py:334-340`).** Copy every `operator_notes` entry and every `placement_reviews` entry from the previous pack, not only the selected ones.
3. **Recovery store (`seeding_run_store.py`).** Add `PACK_RECOVERY_FILENAME = "pack_recovery.json"` and a small frozen `PackRecovery(name, base_dir=None)` with three methods:
   - `write(pack) -> bool` writes `{"name", "saved_at", "pack"}` with `write_json`. It returns False and logs a warning on `OSError`/`ValueError`/`TypeError`, and it refuses (returns False) when the folder's `seeding_run.json` names a different run.
   - `load() -> dict | None` returns the pack only when the file parses and its `name` equals this run's name.
   - `clear() -> None` removes the file, ignoring a missing one.
   Export it in `__all__`.
4. **UI wiring (`render_seeding_pack`).** Add a keyword argument `recovery: PackRecovery | None = None`. `None` disables recovery, so existing callers and tests write nothing.
   - **Write.** Right after `analyze_pack(candidate, ...)` succeeds, and inside the spinner, call `recovery.write(candidate)`. This is before any session-state write.
   - **Offer.** Before `_selected_cohorts(...)`, load the recovery. Offer it only when it passes `snapshot_matches_roster` for the current rows, resolved and overrides, and its `generated_at` is newer than the saved pack's (ISO strings compare correctly).
     - Show `st.warning("A build finished but was interrupted before it was saved.")` with two buttons, "Restore the interrupted build" and "Discard it".
     - Restore sets the scope and cohort widget keys to the recovered pack's `selected_cohorts` and hands the pack to the normal adoption path (see As built).
     - Discard clears the file and reruns.
     - A recovery that fails the roster check, or is not newer, is cleared silently.
   - **Clear on adoption.** When `pending_replacement` is adopted at `:443`, clear the recovery. When the export step fails for a candidate (`:433`), also clear it, so a build that cannot export is never offered back. (Both clears are conditional on the pack being saved; see As built.)
5. **Caller (`tournament_intake.py` `_render_seeding_sheet`).** Pass `recovery=PackRecovery(_seeding_run_name())` when the run is named, else `None`.
6. **Screen copy (`:316`).** Keep "Rebuilding reads fresh data while preserving director notes and roster decisions." Carrying every cohort's notes forward makes it true.

## As built (2026-09-24)

- **Restore goes through the normal adoption path.** `_offer_interrupted_build` returns the recovered pack, and `render_seeding_pack` treats it like a fresh build: export checks, then the save, then the clear. A restored build whose sheets fail is dropped and the saved pack stays.
- **Restore keeps notes and reviews saved while the build ran.** The current pack's `operator_notes` and `placement_reviews` are merged over the recovered pack's copy.
- **Restore sets both cohort pickers.** A keyed `st.multiselect` in Streamlit 1.50 leaves `default` out of its identity, so a real browser keeps and resends its old value when only the default changes. The keys are set before the pickers render.
- **The recovery file is cleared only after a save lands.** Adoption marks `_seeding_pack_unsaved` before storing the pack and clears the file only when the save succeeds. The offer check keeps a not-newer file while the pack is unsaved, so a failed save, or a rerun between storing and saving, still leaves it on disk behind the retry banner.
- **A failing rebuild hands the file back.** When a new build's sheets fail while the pack in memory is still unsaved, the recovery is rewritten with that pack instead of being cleared.
- **Streamlit's widget-state duplication warning is off** (`[global] disableWidgetStateDuplicationWarning` in `.streamlit/config.toml`): Restore sets the pickers through session state while they keep a default for a fresh page.
- **In a real browser the offer appears on the next rerun.** The interrupting click starts a new script run while the old one is still finishing, so the page that follows has no file yet. The build is kept, and any click or a reload offers it. The owner accepted this in the 2026-09-24 preview rather than adding a timer. AppTest reruns on the same thread, so its tests see the offer at once.
- **The caller passes `default_seeding_base_dir()`** to `PackRecovery`, so tests that point that name at a scratch folder keep the file there too. `test_seeding_quote_workflow.py`'s `operator` fixture redirects it too.

## Tests

- Re-pin `test_narrowing_cohorts_preserves_only_selected_notes_and_policy` and rename it `..._keeps_every_cohorts_notes...`. After narrowing to u14 and rebuilding, `operator_notes` keeps both literals. The workbook and HTML hold the boys' note and not the girls'. Reselecting both cohorts and rebuilding shows "Girls placement notes" in the HTML again.
- A placement review stored for a deselected cohort survives the narrowed rebuild, keyed by the same fingerprint literal.
- Replace the `test_seeding_pack.py` "notes" corruption case with a non-mapping `operator_notes`, and add `test_a_note_for_a_cohort_outside_the_selection_survives_an_upgrade`. A non-string note value is already covered by the existing "invalid placement notes" case.
- `PackRecovery` unit tests on `tmp_path`: write then load round-trip; a folder whose run file names another run refuses the write; a recovery written under another name loads as None; clear on a missing file is a no-op; an unwritable path returns False.
- The C3 AppTest reproduces the real mechanism. The patched `load_seeding_predictions` calls `get_script_run_ctx().script_requests.request_rerun(...)` during the build. Assert the recovery file then holds the new pack, and that after the rerun the restore warning shows. Clicking "Restore the interrupted build" makes `_seeding_pack["generated_at"]` the new snapshot and removes the file. A second test covers "Discard it". A third checks that a completed, uninterrupted build leaves no recovery file.
- Mutation-check each guard on its own: the carry-forward, the validator relaxation, the write placement, the name check, the newer-than check, clear on adoption, and clear on export failure. Each must be killed by a named new test.

## Verification

- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`
- A browser smoke test on a scratch app (port not 8503, `MATCHBALANCE_SEEDING_DIR` set to a scratch store, no paid calls) covering three things. First, narrow, rebuild, reselect, and check the girls' note is back. Second, start a build, click another widget mid-build, and check the restore warning appears and restores the new snapshot. Third, run a normal build and check no warning appears.
