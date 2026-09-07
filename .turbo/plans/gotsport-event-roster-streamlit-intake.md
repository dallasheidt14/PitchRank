---
status: done
---

# Plan: Scrape a GotSport event URL from the Seeding tab

## Context

The Seeding tab has one intake today: paste an accepted-teams list and the app resolves each
row to a PitchRank team. PR #1090 merged the engine for a second one — give it a GotSport
event URL and it walks the event, harvesting each team's GotSport provider id from the
"View Rankings" hop. A provider id resolves by direct lookup at full confidence, so it links
teams that name matching would miss, and it clears the AWS WAF challenge that stops the
older `GotsportScraper` on `/org_event/*`.

That engine has no way into the app. Its CLI writes `reports/seeding/gotsport_<id>/roster.json`,
and a grep across `*.py`, `*.md` and `*.yml` finds no production reader — only the writer
(`scripts/scrape_event_roster.py:291` builds the path, `:352` writes it) and twelve
`tmp_path / "roster.json"` uses in its own tests. A reviewer filed this as a P1: the second
intake never places its teams into the seeding run, queue or cohort sheet.

This plan closes that **for the UI path** by converting the scraper's rows into the exact pair
the Seeding tab already runs on — `(ParsedRoster, tuple[ResolvedTeam, ...])` — so a scraped
event lands in the same table, the same override rows, the same queue button and the same
cohort sheet as a pasted one. No new artifact, no new reader, no third row type.

**Scope limit, stated honestly:** the CLI is unchanged, so after this ships it still writes a
`roster.json` that nothing reads. That is a deliberate narrowing — step 8 records it so the
next reader does not re-file the reviewer's P1 as live.

The stakes on the conversion choice are concrete. This repo has just discovered it shipped
**two** GotSport event walkers by not asking the equivalent question:
`src/scrapers/gotsport.py:1466` and `src/tournaments/gotsport_event_roster.py:65` define the
identical `EVENT_BASE`, walk the identical `.../schedules?group=` URL, and share no code.
IMP-172 already records the first drift between the two seeding paths. A third parallel path
would compound both.

**Operator goal, verbatim:** "I just want to link as many teams to teams in our database as
possible." Cohort metadata is secondary, and a division is never dropped for an unreadable label.

## Decisions

Resolved with the operator:

1. **Placement — the Seeding tab, beside the paste box.** Not the backtest Intake card.
2. **Unreadable division labels — keep the teams, flag the blank cohort.** Never drop a division.
3. **Cost — probe two divisions, then offer the rest.**
4. **The scrape does not autosave.** It fills the results table and stops; the operator names the
   run and saves it with the controls already there, exactly as for a pasted roster.
   **This is the decision that keeps the feature simple.** An earlier draft auto-saved, and two
   review rounds found four separate defects that all lived in that one choice: the run name is
   widget-backed and only applies on the *next* script run, so the first scrape of a session saved
   nothing; a later two-division probe silently replaced a completed full walk on disk; scraping a
   second event while the first event's name sat in the box overwrote the first; and the marker
   that tracks which saved run is open interacts with the resume selector in a way that reloads the
   old run over the new scrape. Not saving automatically removes all four, because none of the
   naming, overwrite-protection or run-mode machinery is needed. The cost is one extra click and
   that an unsaved scrape is lost if the tab closes — accepted deliberately.
5. **Progress is a spinner, not a bar.** See step 5.

## Pattern Survey

### Analogous Features

- **`tournament_intake.py:3470` `_run_seeding_resolve(text, supabase_client) -> None`** — the
  function this plan mirrors. `parse_roster(text)` → clears `st.session_state._seeding_overrides`
  → guards an empty roster at `:3474-3477` → opens `requests.Session()` at `:3479` →
  `st.progress(0.0, ...)` at `:3480` → `resolve_roster(..., on_progress=...)` → catches
  `requests.RequestException` at `:3496` → `finally: progress.empty()` and `session.close()`
  (`:3501`) → sets `st.session_state._seeding_result = (parsed, resolved)` at `:3503`.
- **`tournament_intake.py:3789` `_render_seeding_tab(supabase_client)`** — the tab body, and
  **where the paste box lives**: `st.text_area(key="seeding_roster_text")` at `:3802`, the
  "Resolve teams" button at `:3808`, `_run_seeding_resolve(...)` at `:3813` and
  `_autosave_seeding_run()` at `:3814`. Note it calls `_render_seeding_run_controls()` first, at
  `:3801`. `supabase_client` is in scope here.
  Reached from `main()` via `st.segmented_control("View", options=_VIEWS)` where
  `_VIEWS = ("Backtest", "Seeding")` (`:3448`), branch at `:3932-3935`. **The Seeding tab is live.**
  The `_DISABLED_MODES = ("seeding",)` / `_resolve_intake_mode` gate at `:173`/`:194` governs a
  vestigial *Mode radio inside the backtest Intake card* (`:613-627`), not this tab.
- **`tournament_intake.py:3659` `_render_seeding_run_controls()`** — renders **only** the
  "Event name" `st.text_input` (key `seeding_event_name`, `:3665`) and the "Reopen a saved run"
  `st.selectbox`. Takes **no** Supabase client and **returns early at `:3673`** when
  `list_seeding_runs()` (`:3670`) is empty. It runs `_apply_pending_seeding_widgets()` (`:3644`)
  before creating the name widget — which is why a name set from inside a button branch only takes
  effect on the following script run, and why this plan does not try to set one.
  Its resume selector reloads whenever the chosen slug differs from `_seeding_loaded_slug`
  (`:3683`).
- **`tournament_intake.py:3606` `_autosave_seeding_run()`** — **not called by this feature.**
  Named here only so an implementer does not add it by symmetry with `:3814`.
- **`tournament_intake.py:3745` `_render_seeding_enqueue(parsed: ParsedRoster, resolved, supabase)`** —
  takes a `ParsedRoster`, which is why the converter must return one.
- **`tournament_intake.py:755` `_run_scrape(url, supabase_client)`** — the *backtest* intake spine
  and the source of the lock idiom: `with _acquire_scrape_lock(key):`,
  `_scrape_in_progress = True` inside, cleared at `:786` in a `finally`, `_ScrapeLockContended`
  handled at `:788`.

### Reusable Utilities

- **`src/tournaments/gotsport_event_roster.py:600` `scrape_event_roster(event_id, *, fetch, delay_min=0.0, delay_max=0.0, limit_groups=None, max_workers=1, on_progress=None) -> EventRoster`.**
  `EventRoster` (`:138`): `event_id, teams, warnings, divisions_found, divisions_walked, divisions_unreadable, teams_unreadable` + `is_complete` (`:148`).
  `EventRosterTeam` (`:124`): `source_index, group_id, division_label, age_group, gender, team_name, registration_id, provider_team_id`.
  **`max_workers` defaults to 1 (serial).** It must be passed explicitly.
- **`:457` `make_zenrows_fetcher(api_key, ...)`** — the WAF-clearing fetcher. **ZenRows bills every
  attempt** (`attempts=3`). `WafChallengeError` is at **`:447`** and **subclasses `RuntimeError`**.
- **`scripts/scrape_event_roster.py:147` `_resolve_master_ids(teams, *, enabled, client_factory=create_client, resolver_factory=MergeResolver, lookup_factory=make_provider_id_lookup) -> tuple[dict[str, str], list[str]]`** —
  injectable, never raises, returns `(provider_team_id -> team_id_master, warnings)`. **It reads
  `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the environment before touching
  `client_factory`** and returns `({}, [...])` when either is missing, and **discards all
  accumulated mappings on any exception** — so an empty mapping does not mean "unmapped".
- **`scripts/scrape_event_roster.py:64` `_printable(text)`** — strips `Cc/Cf/Co/Cs/Zl/Zp`, keeping
  tab and newline. Applied to provider text at `:229`, `:326`, `:336`, `:340`, `:341`. Covered by
  `tests/unit/test_gotsport_event_roster.py:1225`.
- **`src/tournaments/roster_paste.py:41` `RosterRow`** (frozen): `source_index, club_raw, team_name_raw, state, section_age_group, section_gender, team_name_stripped, has_star_marker, has_c_marker`. **`:56` `ParsedRoster`**: `rows`, `warnings`.
- **`src/tournaments/roster_resolver.py:72` `ResolvedTeam`** (frozen): `source_index, status, team_id_master=None, provider_team_id=None, matched_name=None, candidates=()`. `status ∈ {gotsport_id, exact_name, review, unresolved}`.
- **`:151` `resolve_row(row, *, gotsport_search, lookup_provider_id, lookup_exact_name)`** —
  **derives a provider id from `gotsport_search(name, age, gender)`, a name search.** `RosterRow`
  carries no provider-id field, so `resolve_row` cannot use an id we already hold.
- **`:359` `make_provider_id_lookup(supabase_client, merge_resolver=None)`** → `lookup(provider_team_id) -> str | None`.
- **`:419` `make_exact_name_lookup(supabase_client, merge_resolver=None)`** → `lookup(team_name, age_group, gender) -> list[str]`. Returns `[]` on no match; `.eq("age_group", "")` returns nothing rather than raising.
- **`:87` `build_search_params(team_name, age_group, gender)`** — raises `ValueError` on a blank age
  and `KeyError` on a blank gender, independently. Only the **search** branch is exposed to this.

### Convention Anchors

- **Session-state contract:** `st.session_state._seeding_result = (parsed, resolved)` and
  `st.session_state._seeding_overrides = {}`. Producing that pair is the whole integration.
- **Threading:** none. Neither app imports `threading` or `concurrent.futures`, and
  `add_script_run_ctx` has zero occurrences repo-wide.
- **Importing from `scripts/` is established** (`tournament_intake.py:35`,
  `src/tournaments/event_team_matcher.py:15-16`, `scripts/__init__.py` exists) — but
  `scripts/scrape_event_roster.py` runs `load_dotenv(_ENV_LOCAL, override=True)` at module scope
  (`:45-49`), which the existing precedent does not. See step 5.
- **`ZENROWS_API_KEY`:** read via `os.getenv` directly. Neither Streamlit app reads it today.
- **Streamlit-touching tests** replace the module's `st` wholesale:
  `monkeypatch.setattr(tournament_intake, "st", fake_st)` at `tests/unit/test_division_render.py:88`
  and `tests/unit/test_recompute_medians.py:176`.
  **`tests/unit/test_tournament_intake_helpers.py` is NOT this idiom** — zero `monkeypatch.setattr`.

## Implementation Steps

> **Order:** step 6 before step 5, which calls the function step 6 creates.

1. **Add the pure converter module `src/tournaments/event_roster_intake.py`**
   - No Streamlit import.
   - `to_seeding_rows(roster: EventRoster, master_ids: Mapping[str, str], extra_warnings: Sequence[str] = ()) -> tuple[ParsedRoster, tuple[ResolvedTeam, ...]]`:
     - One `RosterRow` per `EventRosterTeam`, preserving `source_index`.
     - `team_name_raw = team_name_stripped = _printable(team.team_name)`; `club_raw = ""`;
       `state = ""`. **Sanitize here** — this is the boundary where provider-authored text enters
       the seeding path, and the sibling CLI writer already sanitizes at exactly this point
       (`scripts/scrape_event_roster.py:64`, applied at `:340-341`). Import `_printable` or lift it
       into this module; either way apply the same `Cc/Cf/Co/Cs/Zl/Zp` semantics, keeping ordinary
       Unicode. Apply it to warnings too.
     - `section_age_group = team.age_group` (may be `""`), `section_gender = team.gender` (may be `""`).
     - `has_star_marker = has_c_marker = False`.
     - Per team, the `ResolvedTeam`:
       - pid present **and** in `master_ids` → `status="gotsport_id"`, `team_id_master=master_ids[pid]`, `provider_team_id=pid`.
       - pid present, **not** in `master_ids` → `status="unresolved"`, `provider_team_id=pid`.
         **Not `review`** — a `review` row with no candidates is inert downstream
         (`src/tournaments/seeding_enqueue.py:57-61` returns `None` without a `team_id_master`,
         and `_seeding_team_ids` at `tournament_intake.py:3693-3703` drops it).
       - no pid → `status="unresolved"`.
     - Warnings: `extra_warnings` **first**, then the two cohort-count lines, then `roster.warnings`
       **capped at the first 10 with an "and N more" line**. The order is load-bearing:
       `extra_warnings` carries the only signal that credentials or the merge map failed, and the
       scenario the cap exists for — a systematic `_TargetRefused` 403 yielding one warning per
       team — is exactly what would push that signal past position 10.
       Append a cohort-count line **only when its count is non-zero**, so a clean scrape shows no
       warning boxes.
   - `needs_name_lookup(parsed, resolved) -> tuple[int, ...]` — every `unresolved` index. Both the
     known-pid and no-pid cases go to step 2; step 2 decides which branch each takes.

2. **Add `resolve_unlinked(...)` to the same module**
   - `resolve_unlinked(parsed, resolved, *, indices, gotsport_search, lookup_provider_id, lookup_exact_name, delay_seconds=0.0) -> tuple[ResolvedTeam, ...]`
   - **Branch on whether we already hold a provider id**, because `resolve_row` cannot use one:
     - **Known pid** (the `ResolvedTeam` carries `provider_team_id`): first retry
       `lookup_provider_id(pid)` — `_resolve_master_ids` returns `{}` wholesale on a credentials
       or exception path, so absence from `master_ids` does **not** prove the id is unmapped. On a
       hit, `status="gotsport_id"` with the id preserved. On a miss, call
       `lookup_exact_name(team_name_stripped, section_age_group, section_gender)` and, on a single
       hit, `status="exact_name"` **keeping `provider_team_id`**. Never send this row to
       `gotsport_search`: we already hold the authoritative id, a name search costs a request and
       could return a *different* id, and `resolve_row` would drop the id we hold.
       A blank cohort is safe on this branch — `lookup_exact_name` filters on `""` and returns
       nothing rather than raising.
     - **No pid:** call `roster_resolver.resolve_row(...)` unchanged — but only when
       `section_age_group` **and** `section_gender` are both non-empty, because that path reaches
       `build_search_params`, which raises `ValueError` on a blank age and `KeyError` on a blank
       gender. A row failing that test stays `unresolved`.
   - Splice results by `source_index`; leave every other entry untouched.
   - **Docstring must state:** linkless teams get **exact-name recovery only**. The club-aware
     fuzzy scorer in `event_team_matcher` is a different path and is not called here.

3. **Add tests `tests/unit/test_event_roster_intake.py`**
   - Import directly — no Streamlit dependency.
   - `to_seeding_rows`: a mapped pid → `gotsport_id` with the `team_id_master`; an unmapped pid →
     `unresolved` **carrying `provider_team_id`** and selected by `needs_name_lookup`; no pid →
     `unresolved`; `source_index` order preserved; a name containing a control character comes back
     stripped while accented text survives.
   - Warning order: `extra_warnings` appear before capped `roster.warnings` and survive a
     20-warning roster; a zero-count cohort line is absent; a non-zero one is present.
   - `resolve_unlinked` branching, each arm asserted by which collaborators were called:
     - known pid + `lookup_provider_id` hit → `gotsport_id`, **`gotsport_search` never called**;
     - known pid + miss + single exact-name hit → `exact_name` **with `provider_team_id` retained**;
     - no pid + populated cohort → `resolve_row` path exercised;
     - no pid + blank age → stays `unresolved`, `gotsport_search` never called, **and**
       `build_search_params("X", "", "Male")` raises `ValueError`;
     - no pid + blank gender → same, **and** `build_search_params("X", "u14", "")` raises `KeyError`.
     Pin each blank arm separately; they raise different exceptions, so one mutation cannot cover both.

4. **Wire the controls into `_render_seeding_tab` (`tournament_intake.py:3789`), beside the paste box at `:3802-3814`**
   - **Not** `_render_seeding_run_controls` — no Supabase client, and it returns early at `:3673`.
   - `st.text_input` keyed `seeding_event_url`, placeholder
     `https://system.gotsport.com/org_event/events/52975`.
   - Two buttons:
     - `Check 2 divisions (~$0.05)` → `_run_event_roster_scrape(url, supabase_client, limit_groups=2)`
     - `Scrape the whole event` → `_run_event_roster_scrape(url, supabase_client, limit_groups=None)`,
       `disabled` unless `st.session_state.get("_seeding_event_probe", {}).get("url") == url`
       **and** that probe recorded at least one successfully walked division.
   - **Do not call `_autosave_seeding_run()` here.** The paste path does at `:3814`; this path
     deliberately does not (Decision 4). After a scrape, show a
     `st.caption("Name this run above and press Save to keep it.")` so the operator knows the step
     is theirs.
   - After a probe, render a `st.caption` with divisions walked, teams seen, and how many linked,
     plus a **range** estimate — see the cost note in step 5. **When the probe walked zero
     divisions, show no estimate and leave the full-run button disabled**; an event that publishes
     no divisions, or whose every division failed, is not a sample.
   - As a courtesy, `st.info` naming `ZENROWS_API_KEY` when `os.getenv` returns nothing. The
     authoritative guard is in the runner (step 5), because a widget's `disabled` state is not
     unit-testable.
   - Gate both buttons on `st.session_state._scrape_in_progress`, as `_render_intake_section:566`
     does at `:569`.

5. **Add `_run_event_roster_scrape(url: str, supabase_client: Any, *, limit_groups: int | None) -> None` to `tournament_intake.py`**
   - Place it beside `_run_seeding_resolve` (`:3470`).
   - **Import `_resolve_master_ids` inside this function, not at module scope.**
     `scripts/scrape_event_roster.py` runs `load_dotenv(_ENV_LOCAL, override=True)` at import
     (`:45-49`); a module-scope import would let `.env.local` override the running process's
     environment for the whole app, after `config/settings.py` has already captured
     `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` as module constants — so `get_database()` and the
     Backtest tab could end up on different credentials from this path. The existing `scripts/`
     import at `tournament_intake.py:35` has no such side effect.
   - **Key guard first.** `api_key = os.getenv("ZENROWS_API_KEY")`; absent → `st.error` naming the
     variable, return, before `make_zenrows_fetcher` is constructed.
   - `event_id = event_id_from(url)` (step 6; returns `None` rather than raising). `None` →
     `st.error` naming the URL, return.
   - **Lock:** `with _acquire_scrape_lock(event_key("gotsport", event_id, None)):`, setting
     `_scrape_in_progress = True` inside and clearing it in a `finally` (as `:786` does).
     - Catch **`_ScrapeLockContended` before `RuntimeError`** — it subclasses `RuntimeError`
       (`:290`), so a bare handler would swallow it. Use the wording at `:788`.
     - **Sharing that lock with a Backtest scrape of the same event is correct and deliberate** —
       both hit the same paid provider for the same event, so serializing prevents double spend.
       The Backtest tab already produces the same `__unknown` key, because
       `GotsportScraper.fetch_event_metadata` returns `event_start_date=None` and never sets
       `season_year`; `reports/` already contains `gotsport__42434__unknown/` and
       `gotsport__45224__unknown/`. Do not "fix" this.
     - `_acquire_scrape_lock` does `lock_path.parent.mkdir(parents=True, exist_ok=True)`, creating
       `reports/gotsport__<id>__unknown/intake/`. `_resume_options()` skips it correctly, but
       `_render_rekey_banner` (`:550-563`) names it in a per-session warning. **Accept the nag.**
   - **Progress is a single spinner, not a bar.** Wrap the whole call in
     `st.spinner("Walking the event…")` and pass **no** `on_progress`.
     Reason, to be stated inline so nobody reinstates a bar: `scrape_event_roster` is one opaque
     call and both its phases run off the script thread via `_in_pool` (`:707` division reading,
     `:783` team pages), `on_progress` is handed only to the pooled `_provider_ids_for` (`:646`),
     and `_report_progress` (`:787`) swallows every callback exception — so a `st.progress` driven
     from there no-ops silently and the bar sits frozen. `_in_pool` runs on the calling thread only
     at `max_workers <= 1`, which would make the walk serial. `st.status` has the same problem.
   - Call `scrape_event_roster(event_id, fetch=make_zenrows_fetcher(api_key), limit_groups=limit_groups, max_workers=8)`.
     **Pass `max_workers` explicitly** — it defaults to 1 (serial).
     Catch `WafChallengeError` → `st.error` explaining GotSport blocked the walk; then
     `RuntimeError` → `st.error` with the message. Neither raises into the UI.
   - **Guard an empty roster** as `_run_seeding_resolve` does at `:3474-3477`: when
     `roster.teams` is empty, `st.warning` naming the event and return **without** setting
     `_seeding_result`. Otherwise the tab renders four zero metrics and then the green
     `st.success("Every team on the list is resolved.")` at `:3864` after a paid walk that found
     nothing.
   - `master_ids, resolve_warnings = _resolve_master_ids(roster.teams, enabled=True, client_factory=lambda *_: supabase_client)`.
     It never raises; pass `resolve_warnings` into `to_seeding_rows` as `extra_warnings`.
   - `parsed, resolved = to_seeding_rows(roster, master_ids, resolve_warnings)`.
   - **Park the result immediately:** set `_seeding_overrides = {}` and
     `_seeding_result = (parsed, resolved)` **before** the free lookup phase, so a failure there
     cannot cost the paid walk. `_resolve_master_ids`' own docstring states the principle: "A
     database failure here must not cost the walk: the roster is the paid artifact, and re-running
     resolution is free where re-running the scrape is not."
   - **Then** run `resolve_unlinked` for `needs_name_lookup(parsed, resolved)`, in its own `try`,
     with a `requests.Session()` closed in a `finally` (mirroring `:3479`/`:3501`), reusing
     `make_provider_id_lookup(supabase_client)`, `make_exact_name_lookup(supabase_client)`,
     `search_gotsport_teams` and `_SEEDING_LOOKUP_DELAY_SECONDS` as the paste path does.
     **Catch `Exception`, not a named list.** `requests.RequestException`, `ValueError` and
     `KeyError` do not cover the Supabase transport and API errors that
     `make_provider_id_lookup`/`make_exact_name_lookup` can raise, and anything escaping here
     discards the paid roster. Record the failure in `st.session_state._seeding_resolution_failed`,
     `st.warning` that name matching was incomplete, and leave the parked result standing.
     On success, update `_seeding_result` with the spliced tuple.
   - **Offer a free retry.** When `_seeding_resolution_failed` is set, step 4 renders a
     `Retry name matching` button that re-runs only `resolve_unlinked` against the parked pair —
     recovering without a second paid walk.
   - **Clear `_seeding_sheet_html` only.** `_render_seeding_sheet` serves a cached
     `_seeding_sheet_html` to `st.download_button` without regenerating, so a stale one hands the
     operator the previous event's sheet under the new event's filename.
     **Do NOT clear `_seeding_loaded_slug`.** It is the guard that stops the resume selector
     reloading: `_render_seeding_run_controls` reloads whenever the selected slug differs from it
     (`:3683`), so clearing it while a saved run is still selected makes the *next* script run
     reload that run over the freshly scraped result.
   - Store `st.session_state._seeding_event_probe = {"url": url, "limit_groups": limit_groups, "divisions_found": ..., "divisions_walked": ..., "teams": ..., "linked": ...}` for step 4's caption and gate.
   - **Cost, for the step-4 caption.** Pages = 1 landing + one per **walked** division + one per
     **unique** registration id, and ZenRows bills every retry (up to 3). Measured on the 8
     captured events, unique regids equalled the raw sum every time, so de-duplication saves
     nothing; across 39 real divisions there were 201 teams, 5.15 per division with a 3-8 spread,
     so team pages are ~83% of the bill and scale with **teams**, not divisions. Extrapolate as
     `divisions_found × (teams seen ÷ divisions_walked)` and present a **range**, not a point — a
     2-division sample of a 3-8 spread carries roughly ±50% — noting retries can bill up to 3×.
     Guard `divisions_walked == 0` (no estimate). The `~$0.05` probe label is sound
     (1 + 2 + ~10 ≈ 13 pages against ~405 for ~$1.70).

6. **Extract a reusable event-id parser into the engine module** *(before step 5)*
   - An **extraction, not a move.** `scripts/scrape_event_roster.py:130`
     `_event_id_from(args: argparse.Namespace) -> str` is argparse-coupled and raises `SystemExit`.
   - Add to `src/tournaments/gotsport_event_roster.py`:
     - `event_id_from(url_or_id: str) -> str | None` — permissive, accepts either form, returns
       `None` instead of raising. **Serves the Streamlit caller only.**
     - The two patterns moved and exported: `_EVENT_ID_IN_URL` (`:54`, whose `(?![0-9])` lookahead
       refuses an overlong token rather than truncating it to a different event) and `_EVENT_ID`
       (`:55`, whose `\Z` anchor rejects a trailing newline).
   - **Keep `_event_id_from`'s two-branch dispatch and both `SystemExit` messages.** A single
     permissive helper would change CLI behaviour: today `--event-id "https://…/events/52975"` and
     `--event-url "52975"` both exit, and combined both would succeed.
   - **Preserve the security property in the docstring:** the id becomes a path segment under
     `reports/`, so an unvalidated value lets `../` escape. Both callers build paths from it.

7. **Add tests `tests/unit/test_seeding_event_intake.py`**
   - Use the real idiom: `monkeypatch.setattr(tournament_intake, "st", fake_st)` as at
     `tests/unit/test_division_render.py:88` and `tests/unit/test_recompute_medians.py:176`. **Not**
     `test_tournament_intake_helpers.py`. The fake needs `session_state`, `spinner`, `button`,
     `text_input`, `caption`, `error`, `warning`, `info`, `success` — **no `progress`**, since this
     path has no bar.
   - `monkeypatch.setattr(tournament_intake, "scrape_event_roster", <recording fake>)`, and
     **patch `_acquire_scrape_lock` to a no-op or repoint the lock path at `tmp_path`** — the real
     one creates `reports/gotsport__<id>__unknown/intake/.scrape.lock` and would mutate operator
     storage or contend with a live scrape. Assert `reports/` is untouched.
   - **Assert the paid mode at both boundaries:** the probe button passes `limit_groups=2` and the
     full button `limit_groups=None`; the runner forwards `limit_groups` unchanged **and**
     `max_workers=8`. A swapped argument would otherwise spend the full budget while every other
     assertion passed, and omitting `max_workers` silently selects the serial default.
   - **A positive case exercising `resolve_unlinked`:** a row with no provider id and a populated
     cohort. Record all three collaborators, assert each was called, assert the splice landed at
     the right `source_index`. Without it, an always-empty selector passes everything else — an
     empty `ParsedRoster` is valid (`roster_paste.py:56-59`) and the outer pair stays truthy
     (`:3816-3833`).
   - **Paid-walk preservation, able to fail:** make a resolver collaborator raise a `TypeError`
     (outside any named set) and assert `_seeding_result` is already parked and survives. Asserting
     against a caught exception cannot detect the ordering, because the `except` branch leaves the
     same value either way.
   - Pin that **`_autosave_seeding_run` is never called** by this path, and that
     `_seeding_loaded_slug` is **not** cleared while `_seeding_sheet_html` is.
   - **Separate `WafChallengeError` and generic `RuntimeError` cases**, asserting message
     **content** — `WafChallengeError` subclasses `RuntimeError` (`:447`), so "some `st.error`"
     cannot detect a generic handler swallowing the blocked-run explanation. Both must assert the
     spinner exited and `_scrape_in_progress` is `False`.
   - Pin that a missing `ZENROWS_API_KEY` returns before `make_zenrows_fetcher` is called, and that
     an empty roster warns and does **not** set `_seeding_result`.
   - **Render-boundary spend-gate tests:** no probe, a probe for a *different* URL, a probe that
     walked zero divisions, and a matching valid probe — asserting the full-run button's `disabled`
     value and whether the runner was called.
   - In `tests/unit/test_gotsport_event_roster.py`, cover `event_id_from` with a bare id, a URL, an
     overlong bare id, an overlong URL, a newline-terminated id and a `../` attempt; plus CLI
     wrapper tests asserting **each of the two exact `SystemExit` messages**, including that
     `--event-id <url>` still exits. Existing coverage (`:838-846`) only exercises agreeing cases.

8. **Record the deferred items in `.turbo/improvements.md`**
   - **The CLI still writes an unread `roster.json`.** This plan fixes the UI path only. The option
     not taken: have the CLI call the same converter and the `SeedingRun` writer.
   - A WAF challenge does not cancel already-queued `ThreadPoolExecutor.map` page fetches
     (`gotsport_event_roster.py:804`), so a blocked run can still spend the full event budget.
   - The group page header names gender for 5 of 39 captured divisions where the fixture-table
     label does not, but its U-age is season-stamped and disagrees with the durable birth year on
     3 others.
   - Two GotSport event walkers now exist; folding the WAF-clearing fetch mode into
     `GotsportScraper` would leave one.
   - `EventRosterTeam` carries no club name, so `_seeding_result_frame`'s "Club" column is blank
     for every scraped row and `_render_seeding_override`'s heading renders as `" · Team Name"`
     (`:3551`). This is a **legibility** cost, not a matching one — the seeding path's
     `search_gotsport_teams` and `make_exact_name_lookup` never read a club name.
   - A scraped run must be saved by hand (Decision 4). If that proves annoying, the safe way to
     automate it is a save that refuses to replace a more complete run of the same event, mirroring
     `_write_roster`'s guard at `scripts/scrape_event_roster.py:238`.

## Verification

- `PYTHONPATH=<worktree> python -m pytest tests/unit/test_event_roster_intake.py tests/unit/test_seeding_event_intake.py tests/unit/test_gotsport_event_roster.py tests/unit/test_tournament_intake_helpers.py -q` — all green.
- Full gate: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
  and `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.
- **Guard check, one arm at a time.** Delete `resolve_unlinked`'s **age** condition and confirm a
  test fails; restore, delete its **gender** condition, confirm a *different* test fails. The two
  blanks raise different exceptions, so one mutation leaves the other arm unguarded.
- **Second guard check.** Remove the known-pid branch from `resolve_unlinked` so those rows fall to
  `resolve_row`, and confirm a test fails on `gotsport_search` having been called.
- **Manual smoke, paid — probe first.** `streamlit run tournament_intake.py`, View → Seeding, paste
  `https://system.gotsport.com/org_event/events/52975`, press *Check 2 divisions*. Expect: a
  spinner while it runs, two divisions reported with a cost range, teams in the table with
  `gotsport_id` status on those carrying a provider id, and the full-run button becoming enabled.
  Confirm **no** file appears under `reports/seeding/`. Then type a name, press Save, and confirm
  the run appears in the Reopen dropdown.
- Then run the full event and confirm it replaces the table without touching the saved probe.
- Spot-check that a division whose label did not parse still contributes its teams, with the blank
  cohort counted in a warning rather than the division missing.
- Confirm a team with a blank cohort and no provider id is listed and does **not** trigger a
  GotSport search.

## Context Files

- `tournament_intake.py` — `_run_seeding_resolve` (:3470, empty guard :3474, session :3479),
  `_render_seeding_tab` (:3789, run controls :3801, paste box :3802, autosave :3814),
  `_render_seeding_run_controls` (:3659, early return :3673, name widget :3665, resume reload
  :3683), `_apply_pending_seeding_widgets` (:3644), `_render_seeding_enqueue` (:3745),
  `_acquire_scrape_lock` (:295), `_ScrapeLockContended` (:290), `_run_scrape` (:755, :786-788).
- `src/tournaments/roster_paste.py` — `RosterRow` (:41), `ParsedRoster` (:56).
- `src/tournaments/roster_resolver.py` — `ResolvedTeam` (:72), `resolve_row` (:151, why it cannot
  use a known id), `build_search_params` (:87), `make_provider_id_lookup` (:359),
  `make_exact_name_lookup` (:419).
- `src/tournaments/gotsport_event_roster.py` — `EventRosterTeam` (:124), `EventRoster` (:138),
  `WafChallengeError` (:447), `make_zenrows_fetcher` (:457), `scrape_event_roster` (:600, its
  `on_progress` hand-off :646), `_in_pool` (:707, :783, :800-804), `_report_progress` (:787).
- `scripts/scrape_event_roster.py` — `_printable` (:64), `_resolve_master_ids` (:147),
  `_event_id_from` (:130, **retained as a wrapper**), the import-time `load_dotenv` (:45-49).
- `tests/unit/test_division_render.py` (:88) and `tests/unit/test_recompute_medians.py` (:176) —
  the real idiom for testing this app's Streamlit-touching helpers.

## Baseline and Working-Tree Hazards

- Branch from `origin/main`. The worktree `C:\pitchrank-seeding-intake` is on
  `gotsport-roster-intake-ui`, created from and level with `origin/main`; PR #1090 is merged
  (`25e669fcc`).
- Before editing: `git fetch origin main && git status -sb && git diff origin/main --stat`.
- **`reports/seeding/` is untracked and holds the operator's own earlier runs, and this checkout is
  shared with other live agent sessions.** Never stage, revert or delete it; never `git add -A`.
- The repo is public. Never commit `.env` or `.env.local`.
- `ZENROWS_API_KEY` must be present in the environment Streamlit is launched from; it is read from
  the root `.env`.
