---
type: plan
status: done
---

# Plan: SincSports Team Discovery

## Context

Seed the `teams` + `team_alias_map` tables with SincSports club teams (Boys/Men +
Girls/Women, U10–U19, all 50 US states + DC) ahead of event scraping. Rich discovery
metadata (`state_code`, `club_name`, `age_group`, `gender` known from the filter inputs)
feeds the existing `SincSportsGameMatcher` so future cross-provider opponent resolution
gets a clean direct_id fast path on the first try. Without this seed, every first-time
opponent scraped from a tournament schedule hits cross-provider fuzzy matching with only
whatever scraps come off a schedule page.

The feature consists of three new files (scraper, driver script, GHA workflow), one
small extraction (`src/utils/us_states.py` for the 50-state mapping duplicated across 5
scripts), one backward-compatible matcher extension (`state_code` parameter on
`_create_new_sincsports_team`), and deletion of the partial non-working prior attempt at
`scripts/search_sincsports_teams.py`. Implementation spec lives at
`docs/superpowers/specs/2026-04-23-sincsports-team-discovery-design.md` (committed on
branch `feat/sincsports-team-discovery`, commit `604c23e5b`).

**Operational precondition:** discovery's enrichment pass (Step 6) is only race-free once
`scripts/match_state_from_club.py:617` UPDATE is made write-time monotonic (that UPDATE
currently filters only by `team_id_master IN (batch)` with no `state_code IS NULL`
re-assertion; a stale snapshot can overwrite discovery's authoritative value). Fixing
`match_state_from_club.py` is a separate change out of this plan's scope. Until it lands,
do not run this discovery workflow concurrently with `data-hygiene-weekly.yml`.

## Pattern Survey

### Analogous Features

- `C:/PitchRank/src/scrapers/sincsports.py:22-112` — `SincSportsScraper` extends `BaseScraper`; canonical session init (`_init_http_session()` with `Retry(total=3, backoff_factor=0.5, status_forcelist=[500,502,503,504])`, browser UA, `delay_min/delay_max` env-driven sleep). Direct reference for session, throttle, and env-var conventions.
- `C:/PitchRank/src/scrapers/template.py:30-99` — `TemplateScraper` — starting point for new scrapers, shows `BaseScraper` subclass shape. New `SincSportsClubsScraper` diverges because its entry point is `discover_teams(filters...)` rather than per-team scraping.
- `C:/PitchRank/src/scrapers/gotsport_event.py:48-88` — `GotSportEventScraper` — closest session/retry shape in the repo for a scraper class that doesn't itself inherit `BaseScraper` (note: it internally wraps `GotSportScraper` which IS a `BaseScraper` subclass, so DB coupling exists through composition). `SincSportsClubsScraper` deliberately removes that coupling — it takes no `supabase_client` and writes no DB state; the driver owns all DB interactions.
- `C:/PitchRank/src/scrapers/gotsport_event.py:34-46` — `EventTeam` module-level `@dataclass`. Precedent for a record-style dataclass co-located with the scraper that produces it.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py:77-277` — Driver script pattern: dedupe-by-key dict, `batch_create_teams_and_aliases` with 100-ID `IN(...)` pre-check (line 148-157), row-by-row fallback on 23505 errors, `rich.progress.track`, summary panel. Near-perfect template.
- `C:/PitchRank/scripts/import_sincsports_teams.py:47-497` — Existing sincsports importer wires `SincSportsScraper` + `SincSportsGameMatcher._match_team` in the same flow the spec envisions. Mirror its match-result handling.
- `C:/PitchRank/scripts/import_sincsports_teams.py:47-68` — `ensure_provider_exists` — the provider-resolution helper the spec calls out.
- `C:/PitchRank/scripts/search_sincsports_teams.py:19-85` — Prior incomplete attempt; captures `__VIEWSTATE` + `__EVENTVALIDATION` (lines 44-54) but never builds the POST body. Superseded; delete.
- No existing ASP.NET viewstate replay scraper in repo. The `__VIEWSTATE`/`__EVENTVALIDATION`/`__EVENTTARGET` replay loop is genuinely new ground.

### Reusable Utilities

- `C:/PitchRank/scripts/import_sincsports_teams.py:47` — `ensure_provider_exists(supabase)` resolves/creates `providers` row for `code='sincsports'`, returns UUID. Currently `async def` — copy as sync module-level helper in the new driver.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py:148-161` — 100-ID-batched `team_alias_map` `IN(...)` pre-check populating `existing_aliases` set. Copy verbatim.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py:228-277` — Batch INSERT with row-by-row fallback on `duplicate key` / `23505`. Copy verbatim.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py:39-44` — `.env.local` → `.env` fallback `load_dotenv` pattern. Copy verbatim.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py:296-303` — Supabase client bootstrap with `SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY` fallback. Copy verbatim.
- `C:/PitchRank/src/models/sincsports_matcher.py:570-672` — `_create_new_sincsports_team()` — the function to extend with a new `state_code` parameter.
- `C:/PitchRank/src/models/sincsports_matcher.py:502-565` — `SincSportsGameMatcher._match_team()` — matcher entry point the driver calls per team.
- `C:/PitchRank/scripts/backfill_state_from_state_code.py:28-80`, `scripts/backfill_missing_state_codes.py:35-87`, `scripts/match_state_from_club.py:37+`, `scripts/match_missing_state_codes.py:41+`, `scripts/update_single_team_state.py:28+` — `STATE_CODE_TO_NAME` dict duplicated across 5 scripts. No shared module exists. This plan extracts it to `src/utils/us_states.py` for new-scraper use only (does not migrate existing 5 scripts — scope control).
- `C:/PitchRank/src/base/__init__.py:9-25` — `GameData` `@dataclass` pattern for module-level record types with `Optional[str]`.
- `C:/PitchRank/src/scrapers/sincsports.py:85-112` — `_init_http_session()`. Clubs scraper reuses the session structure but **does NOT add POST to `allowed_methods`** — viewstate rotates on every postback, so transport-level POST retry would re-send a stale body. Retries happen at the request level with a fresh form-state GET per attempt (see Step 4).

### Convention Anchors

- **Scraper inheritance:** event/discovery scrapers do NOT extend `BaseScraper`; team-games scrapers do. `SincSportsClubsScraper` is discovery → plain class, own session, own `.errors = []`.
- **Record dataclass:** `@dataclass` module-level, `Optional[X]` for nullable fields. No TypedDict usage in scrapers.
- **Scraper config env vars:** `<PROVIDER>_DELAY_MIN|MAX|MAX_RETRIES|TIMEOUT|RETRY_DELAY`. Clubs scraper reuses `SINCSPORTS_*` prefix (same provider).
- **Workflow Supabase env:** top-level `env:` maps single `secrets.SUPABASE_SERVICE_KEY` to FOUR names (`SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL`) per `gotcha_supabase_key_env_mismatch.md`.
- **Workflow input routing:** CLI-flag interpolation via `${{ github.event.inputs.* }}` inside `run:` with branching (see `data-hygiene-weekly.yml:99-112`). Hoist `${{ inputs.* }}` into step `env:` per `gha_inputs_shell_injection.md`.
- **Python setup:** `actions/setup-python@v6`, `python-version: '3.11'`, `cache: 'pip'`. Lean pip install for scraper-only jobs.
- **Artifacts:** `actions/upload-artifact@v5`, `if: always()`, `retention-days: 30`, name includes `${{ github.run_number }}`.
- **Test layout:** No `tests/scrapers/` tree exists. Unit tests live at `tests/unit/test_<name>.py`. Repo convention per `tests/unit/test_scrape_playmetrics.py:1-16` is unit tests for "novel, branch-heavy pure functions" only; HTTP plumbing covered by end-to-end verification, not mocked unit tests.
- **Error surfacing:** `.errors` list on scraper instance, populated during extract loop; per-item failures logged but do not raise; driver reads `.errors` for summary.
- **Gender normalization:** matcher at `src/models/sincsports_matcher.py:616` expects `"Male"`/`"Female"`. `TeamRecord.gender` must hold those values (not SincSports' `"Boys / Men"` filter labels) — normalize at parse time.

### Proposed Alignment

Build on repo scaffolds heavily. Scraper follows `GotSportEventScraper` structural precedent (plain class, own session) but goes further by dropping all DB coupling — discovery writes nothing directly; the driver owns the Supabase client. Reuses `SincSportsScraper._init_http_session` retry shape except POST stays OUT of `allowed_methods` (viewstate safety — see Step 4). Shares `SINCSPORTS_*` env prefix. `TeamRecord` dataclass co-located with the scraper class. Driver structured like `scripts/extract_and_import_tgs_teams.py` (env load → Supabase client → provider resolve → bulk pre-check → match/create loop with 23505 fallback → rich summary), with per-combo manifest replacing row-count checkpoints for reliable `--resume` (see Step 6). Workflow copies `data-hygiene-weekly.yml` shape with `schedule:` removed and `concurrency:` added to prevent parallel triggers of *this* workflow (cross-workflow coordination vs `data-hygiene-weekly.yml` is NOT handled by this group — see the enrichment-pass precondition in Step 6). Deviations from spec: (1) `STATE_CODE_TO_NAME` extracted to `src/utils/us_states.py` (new single-source module) rather than inlined — migration of existing 5 duplicate scripts is OUT of this plan's scope; (2) test placement is `tests/unit/test_sincsports_clubs.py` not `tests/scrapers/...` per repo convention; (3) `TeamRecord.gender` holds normalized `"Male"`/`"Female"` not raw SincSports filter labels; (4) live-capture HTML fixtures (once) and commit to `tests/fixtures/sincsports_clubs/` rather than synthesize by hand; (5) `SincSportsGameMatcher` gets a `discovery_mode=True` switch that suppresses review-queue writes (the base `_match_team` otherwise pollutes `team_match_review_queue` for every sub-0.91 fuzzy result — unwanted when discovery auto-creates a new team for those same rows); (6) `state_code` threads through `_match_team` / `_fuzzy_match_team` / `_create_new_sincsports_team` as a cascading kwarg so discovered teams benefit from location scoring immediately, not via a post-INSERT UPDATE repair — this requires a **minimal base-matcher edit** (adding `state_code` kwarg to `GameHistoryMatcher._match_team` and forwarding to `_fuzzy_match_team`) because the fuzzy call lives in the base, not the subclass; (7) Mode A/B iteration selection driven by Step 3's `observations.json` sidecar (single-state vs multi-state POST), with manifest schema branching on mode for resume safety; (8) matcher return dict extended with `created: bool` (derived from a new `(team_id, was_created)` tuple from `_create_new_sincsports_team`) and `suppressed_review_method` / `suppressed_review_confidence` fields so discovery's low-confidence auto-creates are auditable without polluting the review queue; (9) driver checkpoints via CSV-before-manifest atomic rename sequence with relaxed integrity check that tolerates in-progress combo overlap on resume; (10) scraper classifies transient failures into separate `_consecutive_block_count` (429/403/shape-fail → 3-strike abort) and `_transport_error_count` (5xx/network/exhausted retries → 10-strike abort) to avoid false-positive block detection from sparse 500s; (11) Step 6 enrichment pass is gated by an operational precondition (the unrelated `scripts/match_state_from_club.py:617` UPDATE must be made write-time monotonic to close a lost-update race with `data-hygiene-weekly.yml`) and enforced at runtime by a pre-flight GHA step that aborts if hygiene is in progress.

## Implementation Steps

1. **Extract `src/utils/us_states.py`**
   - New file. Two module-level dicts: `STATE_CODE_TO_NAME` (51 entries: 50 states + DC, e.g. `"AZ": "Arizona"`) and `STATE_NAME_TO_CODE` (inverse mapping). Source dict from `C:/PitchRank/scripts/backfill_state_from_state_code.py:28-80` — copy the content verbatim, add DC if missing.
   - Expose `state_name_to_code(name: str) -> Optional[str]` helper with case-insensitive lookup that handles common variants (e.g. "D.C." → "DC").
   - No other changes in this step. Do NOT migrate the 5 existing duplicate scripts — out of scope.

2. **Extend `SincSportsGameMatcher` in `src/models/sincsports_matcher.py` (three changes, all backward-compatible)**

   **2a. Cascade `state_code` through FOUR methods (one base edit, three subclass edits).** Location scoring (`game_matcher.py:1378-1383` uses `state_code` as a weighted match component) is currently dead for discovery because `_fuzzy_match_team` hardcodes `provider_team["state_code"] = None` at `sincsports_matcher.py:348`. The fuzzy dispatch lives in the BASE matcher (not the subclass), so threading `state_code` requires a minimal base-file edit in addition to the subclass changes:
   - **`_match_team()` at `game_matcher.py:685` (base matcher):** add `state_code: Optional[str] = None` as the last kwarg in the signature. Forward it to the `self._fuzzy_match_team(team_name, age_group, gender, club_name, state_code=state_code)` call at line 740. Default `None` preserves backward compatibility for every existing caller.
   - **`_match_team()` at `sincsports_matcher.py:502` (subclass):** add `state_code: Optional[str] = None` kwarg. Forward to `super()._match_team(..., state_code=state_code)` at line 516 (so the base forwards it to the fuzzy call), AND forward to `self._create_new_sincsports_team(..., state_code=state_code)` at line 525 for the creation branch.
   - **`_fuzzy_match_team()` at `sincsports_matcher.py:283` (subclass override):** add `state_code: Optional[str] = None` kwarg. Replace the hardcoded `"state_code": None` at line 348 with `"state_code": state_code`. The subclass override is the actual dispatch target because `self._fuzzy_match_team(...)` in the base resolves to the subclass method via polymorphism — which means the base forwarding at line 740 actually reaches the subclass's scoring path.
   - **`_create_new_sincsports_team()` at `sincsports_matcher.py:570`:** add `state_code: Optional[str] = None` at the end of the signature. Persist to the `team_data` dict at lines 627-636 as `"state_code": state_code`.
   - All four params default to `None` so existing callers (`scripts/import_sincsports_teams.py` and any game-import pipeline usage) are unaffected.
   - **Rationale for editing the base file:** iter-2's preference for "no base edits" was specific to the `created: bool` field (a subclass-only concern wrapped at subclass return sites — see 2b). `state_code` is different: it must flow through an existing method dispatch chain, and wrapping at the subclass cannot intercept a call made by the base. Minimal base edit (one signature kwarg + one forwarded arg) is the correct fix and is backward-compatible via the `None` default.

   **2b. Add `created: bool` to `_match_team` return dict via dual mechanism (return-site wrapping + `was_created` tuple).** The base `_match_team` has **7** return sites at `game_matcher.py:712, 720, 731, 758, 781, 804, 829` (direct_id, provider_id, alias, fuzzy_auto, fuzzy_review, fuzzy_review_low, final no-match fallback — the earlier plan's cited range "712-786" was wrong; it missed 804 and 829). The base does not know about the subclass's create-on-fail, so `created` must be injected at the subclass boundary without editing the base file. Two-part fix:

   **Part 1 — Refactor `_create_new_sincsports_team` to return `(team_id, was_created: bool)`.** At `sincsports_matcher.py:570`, change the signature's return type annotation from `-> str` to `-> Tuple[str, bool]`. The second element is `True` only when a new row is actually INSERTed. Specifically:
   - Pre-insert lookup at lines 593-612: if `existing.data` found, return `(existing.data["team_id_master"], False)` — NO new row.
   - Main insert path around line 638: return `(team_id_master, True)` after successful insert.
   - 23505 duplicate-key fallback at lines 651-668: if the lookup finds an existing row, return `(existing.data["team_id_master"], False)` — a concurrent insert beat us, no row was created by this call.

   **Part 2 — Subclass `_match_team` wraps every base-result return path with `created=False`.** At `sincsports_matcher.py:516-565`, every path that returns `base_result` (currently `if base_result.get("matched"): return base_result` at line 518, and the final `return base_result` at line 565 when creation fails) wraps as `return {**base_result, "created": False}`. This uniformly covers all 7 base return sites without editing `game_matcher.py`. The creation branch at lines 522-555 sets `created` from the new `was_created` tuple element: `new_team_id, was_created = self._create_new_sincsports_team(...)` then returns `{"matched": True, "team_id": new_team_id, "method": match_method, "confidence": 1.0, "created": was_created}`.

   **Part 3 — Driver (Step 6) uses `created` as authoritative.** Classification buckets key off `created: bool` rather than string-matching on `method`. A `method == "direct_id"` with `created == True` is a brand new discovery insert; `method == "direct_id"` with `created == False` is an existing alias hit that raced past the bulk pre-check.

   **2c. Add `discovery_mode: bool = False` kwarg to `__init__` AND a `suppressed_review_method` field on the return dict.** The inherited base `_match_team` writes `team_match_review_queue` rows at three sites (`game_matcher.py:768` for 0.75–0.91 fuzzy, `:791` for <0.75 with candidate, `:809` for no candidate) BEFORE the SincSports subclass gets a chance to auto-create. Discovery runs therefore pollute the review queue for every sub-0.91 match even though the subclass immediately creates an approved `direct_id` team for the same row. The subclass auto-creation ALSO runs unconditionally when `matched=False`, so the low-confidence signal is silently lost if we only suppress the queue write. Fix is paired:
   - Change signature at `sincsports_matcher.py:99-105`: `def __init__(self, supabase, provider_id=None, alias_cache=None, discovery_mode: bool = False)`. Store as `self.discovery_mode`.
   - Override `_create_review_queue_entry` in the subclass: if `self.discovery_mode`, `return` immediately (no insert, no exception). Otherwise delegate to `super()._create_review_queue_entry(...)`.
   - **Carry the suppressed signal forward (BOTH method and confidence).** In the subclass's creation branch at lines 522-555, BEFORE calling `_create_new_sincsports_team`, inspect `base_result`. Capture `base_result.get("method")` if it equals `"fuzzy_review"` or `"fuzzy_review_low"`, AND capture `base_result.get("confidence")` at the same site (the original fuzzy score before auto-create overrode it). Both become new fields on the final return dict. Final shape on the creation path:
     ```python
     suppressed = base_result.get("method") if base_result.get("method") in ("fuzzy_review", "fuzzy_review_low") else None
     suppressed_conf = base_result.get("confidence") if suppressed else None
     return {
         "matched": True,
         "team_id": new_team_id,
         "method": match_method,
         "confidence": 1.0,                                # direct_id-equivalent for the newly created team
         "created": was_created,
         "suppressed_review_method": suppressed,           # None for direct/fuzzy_auto; set for sub-0.91 matches that would have been review-queued
         "suppressed_review_confidence": suppressed_conf,  # original fuzzy score from base (for audit CSV); None when suppressed_review_method is None
     }
     ```
   - All non-creation paths wrap as `{**base_result, "created": False, "suppressed_review_method": None, "suppressed_review_confidence": None}` so BOTH fields are always present for consistent driver consumption.
   - **Why a separate confidence field:** the creation path returns `confidence: 1.0` (the team is now a direct_id, fully approved) — but the audit CSV needs the ORIGINAL sub-0.91 fuzzy score that triggered review suppression. Overloading `confidence` would force the driver to choose between "matcher result confidence" and "suppressed fuzzy score" semantics. Separate field keeps both meanings unambiguous.
   - Default `discovery_mode=False` — the game-import pipeline in `import_sincsports_teams.py` and event-import flows continue to populate the review queue as they do today.

   **2d. Preserve from existing file:** the full `_match_team` override (502-565), the duplicate-key 23505 fallback block (647-670), all logging calls, the `gender_normalized` logic (616), the `provider_team_id` MD5 deterministic-fallback generator (587-590), and all base-matcher integration via `super()` calls. Do NOT refactor the subclass into a non-inheriting discovery-only matcher — that loses the fuzzy scoring improvements the subclass gets via `super()._calculate_match_score`.

   **Verification for this step alone:** grep `_create_new_sincsports_team(` / `_fuzzy_match_team(` / `_match_team(` / `SincSportsGameMatcher(` across repo (scripts, src, tests). Expected existing callers: `scripts/import_sincsports_teams.py` (passes no new kwargs), matcher internal calls. None should need updating because every new kwarg has a default.

3. **Capture live HTML fixtures AND characterize the form mechanics**
   - Manual one-off during implementation (not a committed script). Using browser devtools (Network tab, Elements tab) against the live page, capture responses and observations. Save HTML under `C:/PitchRank/tests/fixtures/sincsports_clubs/` (new directory) and write observations to a new `tests/fixtures/sincsports_clubs/README.md`.

   **Fixtures to capture (minimum required set):**
   - `search_page_initial.html` — GET `https://soccer.sincsports.com/sicclubs.aspx?sinc=Y`. Tests full form-state extraction (viewstate + every `<input type="hidden">`).
   - `results_page_1.html` — POST for narrow combo (e.g., state=Arizona, age=U12, gender=Boys/Men, type=Team, all ranks checked). Tests row parsing.
   - `results_page_2.html` — the second page of results for a broader combo where pagination is actually exercised. If the narrow combo above has only one page, use a larger combo (e.g., age=U14, California). Tests pagination loop.
   - **`results_empty.html`** — a combo that genuinely returns zero teams (e.g., a rare age/state combination such as U19 Girls in Wyoming). **This is the authoritative reference for distinguishing real empty results from a block/captcha page** — without it, `_validate_response_shape` in Step 4 cannot be tuned correctly and every zero-result combo risks false-positive into the block counter.
   - **`block_page.html`** *(highly recommended; capture if observable)* — if during reconnaissance you ever hit a block/captcha response (rate-limit hammer, suspicious UA, etc.), save it. Often not reproducible on-demand; if not captured, note in README.md that `_validate_response_shape` will need post-deployment tuning from live observation.
   - `results_multi_state.html` *(conditional — only if the State field supports multi-select; see observations below)* — one POST with multiple states selected. Tests the multi-state code path.

   **Observations to document in `README.md` (human narrative) AND `observations.json` (machine-readable sidecar):**

   **Human narrative in `README.md`:**
   - **State field type.** Is it `<select>` (single-value), `<select multiple>` (multi-value), or a custom multi-checkbox UI? Paste the relevant HTML fragment. This gates whether Step 4 collapses 51 state-queries into fewer multi-state queries (potential 50× speedup flagged in the spec's Unknowns), AND which driver iteration mode Step 6 selects (Mode A per-state vs Mode B per-(age,gender) batching).
   - **Pagination mechanism.** Is it `__doPostBack('...$lnkPageN', '')` in anchor `href` attributes (classic ASP.NET postback), AJAX-driven "Show More", a page-size dropdown, or infinite scroll? Paste the relevant pager HTML fragment. Step 4 implementation branches on this.
   - **Exact form field names.** From the Network tab, record the name attributes of each filter control (State, Age, Gender, Type, USA Rank checkboxes, "Search Teams" submit). Field names are `ctl00$ContentPlaceHolder$...$...` style in ASP.NET — capture them verbatim.
   - **Response structure marker — populated vs empty vs block.** Identify THREE distinct DOM selectors: (a) what's present only on populated results pages, (b) what's present on genuinely empty results (using `results_empty.html` as reference), (c) what distinguishes a block/captcha page (using `block_page.html` if captured, or describe what would). Step 4's `_validate_response_shape` branches on these.
   - **Any `Retry-After` header** observed on deliberate rate-limit tests (optional — don't stress-test; note if you observe one organically).

   **REQUIRED machine-readable artifact: `tests/fixtures/sincsports_clubs/observations.json`**

   The README is human-narrative. The driver (Step 6) needs a stable machine-readable config to pick Mode A vs Mode B at startup and to know which form-field names to POST. Fixed schema:
   ```json
   {
     "schema_version": 1,
     "state_field_mode": "single",
     "pagination_mode": "doPostBack",
     "form_fields": {
       "state": "ctl00$ContentPlaceHolder$ddlState",
       "age": "ctl00$ContentPlaceHolder$ddlAge",
       "gender": "ctl00$ContentPlaceHolder$ddlGender",
       "type": "ctl00$ContentPlaceHolder$ddlType",
       "rank_checkboxes": [
         "ctl00$ContentPlaceHolder$chkRankGold",
         "ctl00$ContentPlaceHolder$chkRankSilver"
       ],
       "submit_button": "ctl00$ContentPlaceHolder$btnSearchTeams"
     },
     "response_markers": {
       "populated": "table.results-table tr.team-row",
       "empty": "div.no-results-message",
       "block": null
     },
     "pagination_hint": "a[href*=\"__doPostBack\"][href*=\"lnkPage\"]"
   }
   ```
   Field semantics:
   - `state_field_mode`: `"single"` | `"multi"`. Drives Mode A vs Mode B selection in Step 6.
   - `pagination_mode`: `"doPostBack"` | `"ajax"` | `"page_size"` | `"infinite_scroll"`. Step 4 branches on this.
   - `form_fields`: verbatim ASP.NET field names from the live page's Network tab.
   - `response_markers.block`: CSS or text marker for captcha/block pages. Can be `null` if `block_page.html` wasn't captured during reconnaissance — `_validate_response_shape` then falls back to "populated marker present OR empty marker present = valid response; otherwise suspect block."
   - `pagination_hint`: CSS selector for the pager element (mechanism-specific).

   **File is REQUIRED before Step 4 can begin.** Step 6 aborts at startup if the file is missing, malformed, or missing any required field.

   **Escalation rule — STOP before Step 4 if observations are ambiguous OR `observations.json` cannot be filled:**
   - If after reconnaissance the implementer cannot confidently distinguish (a) successful populated results vs (b) successful empty results vs (c) block/captcha response from DOM markers alone, **do NOT begin Step 4**. Surface the ambiguity to the operator and document every ambiguity in `tests/fixtures/sincsports_clubs/README.md` as a follow-up item. Step 4's `_validate_response_shape` and pagination logic depend on these distinctions.
   - Same rule applies if `results_page_2.html` cannot be reliably replayed (pagination mechanism undiscoverable): STOP — Step 4's pagination loop needs a confirmed replay strategy.
   - **Same rule applies if any REQUIRED field in `observations.json` cannot be determined** — schema_version, state_field_mode, pagination_mode, form_fields.{state,age,gender,type,submit_button}, response_markers.{populated,empty}. `response_markers.block` can be `null` (fallback logic handles it); everything else is mandatory. If you can't fill them in after devtools inspection, STOP.

   **This step gates Step 4** — without real HTML samples AND a fully-populated `observations.json` AND the empty-vs-block distinction validated, the scraper implementation is guessing.

4. **Implement `src/scrapers/sincsports_clubs.py`**
   - New file. Plain class `SincSportsClubsScraper` — no `BaseScraper` ancestry, no `supabase_client`. Driver owns all DB interactions.
   - Canonical structure sketch (neutral pagination naming; actual implementation branches on Step 3 findings):
     ```python
     BASE_URL = "https://soccer.sincsports.com"
     SEARCH_PAGE = "/sicclubs.aspx?sinc=Y"

     @dataclass
     class TeamRecord:
         provider_team_id: str
         team_name: str
         club_name: Optional[str]
         age_group: str           # "u10".."u19"
         gender: str              # "Male" | "Female" (normalized)
         state_code: Optional[str]

     class CaptchaOrBlockError(Exception): ...

     class SincSportsClubsScraper:
         def __init__(self, delay_min=2.0, delay_max=3.0, max_retries=3, timeout=30):
             self.session = self._init_http_session()
             self.errors: List[Dict] = []
             self._consecutive_block_count = 0
         def _init_http_session(self) -> requests.Session: ...   # mirror sincsports.py:85, keep allowed_methods=["GET","HEAD"]
         def _fetch_initial_page(self) -> Tuple[BeautifulSoup, Dict[str, str]]: ...
         def _extract_form_state(self, soup: BeautifulSoup) -> Dict[str, str]: ...
         def _validate_response_shape(self, soup: BeautifulSoup) -> bool: ...
         def _submit_search(self, form_state: Dict, states: List[str], age: str, gender: str) -> Tuple[BeautifulSoup, Dict[str, str]]: ...
         def _parse_result_rows(self, soup: BeautifulSoup, age: str, gender: str, state_lookup: Dict[str, str]) -> List[TeamRecord]: ...
         def _has_more_results(self, soup: BeautifulSoup) -> bool: ...
         def _extract_next_page_postback(self, soup: BeautifulSoup) -> Optional[Tuple[str, str]]: ...
         def _fetch_next_results_batch(self, form_state: Dict, target: str, argument: str) -> Tuple[BeautifulSoup, Dict[str, str]]: ...
         def discover_teams(self, states: List[str], ages: List[str], genders: List[str],
                            usa_ranks: Optional[List[str]] = None) -> Iterator[TeamRecord]: ...
     ```
   - Env vars: `SINCSPORTS_DELAY_MIN`, `SINCSPORTS_DELAY_MAX`, `SINCSPORTS_MAX_RETRIES`, `SINCSPORTS_TIMEOUT`, `SINCSPORTS_RETRY_DELAY` (shared prefix with existing scraper).

   **Form-state handling (critical — viewstate rotates on every postback):**
   - `_extract_form_state(soup)` returns a dict of every `<input type="hidden">` in the main form, keyed by `name` → `value`. Includes `__VIEWSTATE`, `__EVENTVALIDATION`, `__VIEWSTATEGENERATOR`, and any other hidden fields ASP.NET emits. Do NOT hardcode the three well-known names.
   - Every POST returns a response containing an updated form. After parsing results from the response, **call `_extract_form_state` on the response soup and replace the cached `form_state` dict** before the next POST. Failing to refresh means the next postback is against a stale viewstate and silently returns page 1 or an empty shell.
   - POST body = `{**form_state, **filter_overrides, **postback_overrides}` — the hidden fields plus whatever overrides apply (filter submit vs pager click).

   **Pagination (implementation branches on Step 3 findings):**
   - If Step 3 confirms `__doPostBack` pattern: `_extract_next_page_postback(soup)` finds the next-page anchor and parses the exact `__doPostBack('target','arg')` call from its `href`. Never guess `$lnkPageN` patterns. Submit via `_fetch_next_results_batch` with `__EVENTTARGET=target, __EVENTARGUMENT=arg`.
   - If Step 3 confirms AJAX or page-size dropdown: adapt `_has_more_results` / `_fetch_next_results_batch` to that mechanism. Keep method names neutral.
   - **Stale-viewstate detection:** after a pagination POST, if `_has_more_results` still returns True AND the parsed team IDs equal the previous page's team IDs (no new teamid appeared), treat as stale-viewstate → abort the combo with an error. Don't silently record as empty.

   **Multi-state submission (depends on Step 3 State-field observation):**
   - `_submit_search` accepts `states: List[str]` (plural). If Step 3 confirmed `<select multiple>` or multi-checkbox: submit one POST with all states selected; `discover_teams` collapses the 51 state-queries into far fewer multi-state queries.
   - If Step 3 confirmed single-select: `_submit_search` loops internally and submits one POST per state. Caller (`discover_teams`) still passes `List[str]`; adaptation is inside the scraper.
   - Either way, the scraper's public API is stable.

   **Retry and rate-limit handling (manual, not via urllib3 Retry adapter):**
   - POST retries happen per-request in `_submit_search` and `_fetch_next_results_batch`: on failure, re-GET the initial page, re-extract form state, re-attempt the POST. This ensures every retry uses a fresh viewstate.
   - `allowed_methods` on the Retry adapter stays `["GET", "HEAD"]` — HTTP-level POST retry would resend a stale body and is unsafe.
   - **Two-counter classification** — don't conflate "site is blocking us" (403/429/shape-fail) with "site is down" (5xx/network). Each has its own counter with its own threshold.

   **`_consecutive_block_count` (site-is-blocking-us detection):**
   - Increments on HTTP 429, HTTP 403, OR HTTP 200 with `_validate_response_shape` returning False.
   - Resets to 0 on any successful validated response (HTTP 200 + shape check passes).
   - Threshold `≥ 3` consecutive → raise `CaptchaOrBlockError("blocked")` to abort the run.
   - On HTTP 429: read `Retry-After` header via `float(r.headers.get("Retry-After", delay_max))`; sleep that long before the manual retry.

   **`_transport_error_count` (site-is-down detection) — separate counter:**
   - Increments on HTTP 500-series, connection errors (`requests.exceptions.ConnectionError`, `Timeout`), and retry-loop exhaustion for non-block reasons (three transient failures in a row for one POST).
   - Resets to 0 on any successful response (validated or not — even a shape-fail response counts as "transport worked").
   - Threshold `≥ 10` consecutive → raise `CaptchaOrBlockError("transport exhausted")` with a distinct message so the operator can tell outage vs block apart in logs/artifacts.

   **Cross-counter rules — avoid sticky-counter false positives:**
   - 500-series and network errors do **NOT** increment `_consecutive_block_count`. A sequence like `429 → exhausted 500 retries → 429 → 429` does NOT trip the block threshold at the second 429, because the intermediate 500s are neither increments nor resets for the block counter (they only touch the transport counter). This prevents sparse real blocks from falsely aggregating.
   - Per-combo retry exhaustion (all 3 per-request retries fail for non-block reasons) → append `{"combo": (state, age, gender), "error": "transport exhausted"}` to `self.errors`, continue to next combo. Does not raise.

   **`Retry-After` header honor:**
   - On any 429 response (whether or not the block counter trips), parse `r.headers.get("Retry-After")`. If present and numeric, `time.sleep(float(...))`; if present as HTTP-date, parse and sleep until then (RFC 7231 §7.1.3). Cap sleep at some sensible ceiling (e.g. 5 min) to prevent a hostile server from pinning the scraper indefinitely.

   **Row parsing and normalization:**
   - `_parse_result_rows` pulls `<a href=".../teamid=XXX">` links, extracts `provider_team_id`, `team_name`, `club_name` from each result row.
   - `age_group` and `gender` come from the filter inputs (known at call time), not from the row.
   - `state_code` uses `src/utils/us_states.py::STATE_NAME_TO_CODE` to convert the full state name (known at call time via `state_lookup` dict mapping SincSports state label → postal code).
   - `gender` normalization: submit `"Boys / Men"` / `"Girls / Women"` as filter values; store `"Male"` / `"Female"` in `TeamRecord.gender` to match `sincsports_matcher.py:616`.

   **Throttling:**
   - `time.sleep(random.uniform(delay_min, delay_max))` between each HTTP request (both combo-level and pagination-level). Not just between combos.

   **Error surfacing:**
   - `self.errors.append({"combo": (state, age, gender), "error": str(e)})` for per-combo failures. Do not raise on per-combo failure — let the driver continue.
   - Exception to the "don't raise" rule: `CaptchaOrBlockError` DOES propagate up to the driver so the driver can halt the run cleanly.

5. **Write unit tests at `tests/unit/test_sincsports_clubs.py` and `tests/unit/test_sincsports_matcher_extensions.py`**

   **5a. Scraper tests at `tests/unit/test_sincsports_clubs.py`:**
   - New file. Repo convention: unit tests for "novel, branch-heavy pure functions" only — no HTTP mocking. Coverage:
     - `test_extract_form_state_returns_all_hidden_inputs` — parse `search_page_initial.html`, assert the extracted dict includes `__VIEWSTATE`, `__EVENTVALIDATION`, `__VIEWSTATEGENERATOR`, AND every other `<input type="hidden">` in the form (count-check against fixture). Exact names depend on Step 3 findings.
     - `test_parse_result_rows_single_page` — parse `results_page_1.html`, assert ≥1 `TeamRecord` with correct `provider_team_id`, non-empty `team_name`, `age_group="u12"`, `gender="Male"`, `state_code="AZ"`.
     - `test_parse_result_rows_gender_normalized` — fixture row submitted with SincSports `"Boys / Men"` filter value yields `"Male"` on `TeamRecord.gender`.
     - `test_state_name_to_code_round_trip` — `STATE_NAME_TO_CODE["Arizona"] == "AZ"` and inverse. Include case-insensitive variant ("arizona", "ARIZONA") and D.C. → DC normalization.
     - `test_has_more_results_detects_pagination` — fixture `results_page_1.html` (mid-pagination) returns True from `_has_more_results`; fixture `results_page_2.html` (or a last-page fixture) returns False.
     - `test_extract_next_page_postback_parses_doPostBack` — (only if Step 3 confirms `__doPostBack` pagination) given a pager anchor with `href="javascript:__doPostBack('ctl00$...$lnkPageN', '')"`, returns `("ctl00$...$lnkPageN", "")`. Skip if Step 3 finds AJAX/page-size.
     - `test_validate_response_shape_accepts_populated` — `results_page_1.html` returns True.
     - `test_validate_response_shape_accepts_empty` — `results_empty.html` returns True (real empty results are NOT block pages).
     - `test_validate_response_shape_rejects_block` — `block_page.html` (or synthetic stub if real capture unavailable) returns False.
     - `test_multi_state_parse` *(conditional)* — if `results_multi_state.html` fixture exists, assert rows from multiple states are yielded with correct `state_code` per row.
   - Do NOT write HTTP-level integration tests as pytest units. The `RUN_LIVE_SINCSPORTS_TESTS=1` gate mentioned in the spec is superseded by the manual narrow-dry-run in Verification.

   **5b. Matcher extension tests at `tests/unit/test_sincsports_matcher_extensions.py`:**
   - New file. The three matcher extensions from Step 2 (`was_created` tuple, `discovery_mode` suppression, `state_code` threading, `suppressed_review_method` carry-forward) are branch-heavy per the repo's own unit-test convention (see `tests/unit/test_scrape_playmetrics.py:1-16`). Use a mocked `supabase` client; check for existing mock patterns in other matcher tests first (`tests/unit/test_*matcher*.py` if any exist).
   - Required tests:
     - `test_was_created_true_on_fresh_insert` — `_create_new_sincsports_team` with a unique `provider_team_id` and mocked DB where pre-insert lookup returns no row and the insert succeeds returns `(team_id_master, True)`.
     - `test_was_created_false_on_preinsert_lookup_hit` — mock the pre-insert lookup at lines 593-612 to return an existing row; assert returned tuple is `(existing_id, False)` and `self.db.table("teams").insert(...)` was NOT called.
     - `test_was_created_false_on_23505_fallback` — mock the main insert to raise a 23505 duplicate-key error; mock the 23505 fallback lookup (lines 651-668) to return an existing row; assert `(existing_id, False)`.
     - `test_created_flag_false_on_direct_id_path` — full `_match_team` call with a seeded direct_id alias in `team_alias_map` (mocked); assert return dict has `created == False`.
     - `test_created_flag_true_on_create_path` — full `_match_team` call with no existing matches and no alias; assert `created == True` and matches the `was_created` from the underlying `_create_new_sincsports_team`.
     - `test_discovery_mode_suppresses_review_queue_insert` — instantiate `SincSportsGameMatcher(supabase_mock, discovery_mode=True)`, trigger a fuzzy_review path (0.75-0.91 confidence via mocked scoring); assert `self.db.table("team_match_review_queue").insert(...)` was NOT called.
     - `test_discovery_mode_false_preserves_review_queue_insert` — same setup with `discovery_mode=False` (default); assert the review-queue insert WAS called.
     - `test_state_code_reaches_team_data_on_insert` — `_create_new_sincsports_team(..., state_code="AZ")`; assert the dict passed to `self.db.table("teams").insert(...)` contains `"state_code": "AZ"`.
     - `test_state_code_reaches_fuzzy_match_scoring` — `_fuzzy_match_team(team_name=..., age_group=..., gender=..., state_code="AZ")` with a mocked DB returning a candidate with `state_code="AZ"`; assert the provider_team dict passed into `_calculate_match_score` has `"state_code": "AZ"` (spy on the method call, or verify scored result reflects the location_score boost).
     - `test_suppressed_review_method_carried_forward` — `discovery_mode=True` + mocked fuzzy_review base result; assert final return dict has `"suppressed_review_method": "fuzzy_review"` and `created=True`.
     - `test_suppressed_review_method_none_on_auto_approve` — `discovery_mode=True` + mocked fuzzy_auto base result (≥0.91); assert `suppressed_review_method is None` and `created=False` (base returned matched=True so subclass doesn't create).

6. **Implement `scripts/discover_sincsports_teams.py`**
   - New file. Mirror `scripts/extract_and_import_tgs_teams.py` shape for env/Supabase/provider bootstrap and batch-import with 23505 fallback; diverge for scrape-driven input, per-combo manifest, and `discovery_mode` matcher integration.

   **CLI (argparse):**
   - `--states "AZ,CA,..."` — CSV of postal codes. Blank = all 50 + DC.
   - `--ages "u10,u12,..."` — CSV of age groups. Blank = U10–U19.
   - `--genders "male,female"` — CSV. Blank = both.
   - `--resume <prefix>` — resume from a prior run's `<prefix>.csv` + `<prefix>_manifest.json` pair.
   - `--force-resume` — override checkpoint integrity mismatch (see below).
   - `--dry-run` — scrape + print + write CSV, skip all DB writes.
   - `--confirm-full-grid` — required non-interactively (CI) when --states/--ages/--genders are all blank. Skips the TTY confirmation prompt.
   - `--max-combos N` — testing cap; stop after N combos.

   **Startup:**
   - `load_dotenv` with `.env.local` → `.env` fallback (copy pattern from `extract_and_import_tgs_teams.py:39-44`).
   - Supabase client bootstrap with `SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY` (copy from `extract_and_import_tgs_teams.py:296-303`).
   - `ensure_provider_exists(supabase)` — synchronous copy of `scripts/import_sincsports_teams.py:47` (strip `async def` → plain `def`; same select/insert logic for `providers` where `code='sincsports'`).
   - **Compute `run_ts` once at startup** — `run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")`. This single timestamp string is reused verbatim for all three artifact filenames:
     - Main CSV: `data/exports/sincsports_teams_discovery_{run_ts}.csv`
     - Manifest: `data/exports/sincsports_teams_discovery_{run_ts}_manifest.json`
     - Low-confidence audit CSV: `data/exports/sincsports_low_confidence_{run_ts}.csv`
     - Do NOT call `datetime.utcnow()` again at individual write sites — divergent timestamps break `--resume` correlation between CSV, manifest, and audit CSV after a crash.
   - **Load `tests/fixtures/sincsports_clubs/observations.json`** — parse the sidecar produced by Step 3. Abort at startup with a clear error if the file is missing, malformed, or missing any required field (`schema_version`, `state_field_mode`, `pagination_mode`, `form_fields.{state,age,gender,type,submit_button}`, `response_markers.populated`, `response_markers.empty`): `"Cannot start discovery: tests/fixtures/sincsports_clubs/observations.json is missing/malformed. Complete Step 3 reconnaissance first."`
   - **Select iteration mode:** `mode = "B" if observations["state_field_mode"] == "multi" else "A"`. Stored on the driver instance and written into the manifest's `"mode"` field.
   - **Full-grid confirmation gate:** if `--states`, `--ages`, `--genders` are all blank AND `--dry-run` is not set:
     - TTY (`sys.stdin.isatty()`): prompt `⚠ About to scrape full 1,020-combo grid (~45-60 min). Continue? [y/N]`; abort on non-`y`.
     - Non-TTY: require `--confirm-full-grid`; abort with clear error if missing.
   - **`--resume <prefix>` argument semantics:** operator passes the shared prefix excluding all suffixes — e.g., `--resume data/exports/sincsports_teams_discovery_20260423T182211Z`. The driver appends `.csv`, `_manifest.json`, and (if present) looks for the correlated low-confidence audit CSV from the same run.

   **Filter grid build:**
   - `build_filter_grid(states, ages, genders)` → cartesian product. Default: 51 × 10 × 2 = 1,020 combos.
   - Map user-supplied postal-code state args to SincSports full state names via `src/utils/us_states.py::STATE_CODE_TO_NAME`.

   **Manifest file (replaces row-count checkpoint):**
   - Path: `data/exports/sincsports_teams_discovery_<ts>_manifest.json`.
   - Schema (Mode A — per-state combos; see Scrape phase below for Mode B shape):
     ```json
     {
       "schema_version": 1,
       "mode": "A",
       "scope_fingerprint": "<sha256 of sorted (states, ages, genders) submitted this run>",
       "combos": [
         {"state": "AZ", "age": "u12", "gender": "Male", "status": "completed",
          "pages_fetched": 2, "team_count": 47, "completed_at": "2026-04-23T18:22:11Z"}
       ]
     }
     ```
   - Mode B variant: `"mode": "B"` and combos keyed by `(age, gender)` with an extra `"states_scope": ["AZ","CA",...,"WY"]` field recording which states were requested in the single multi-state POST.
   - Status values: `pending` (enqueued), `in_progress` (scraping in flight — only observable if the run crashes mid-combo), `completed` (pagination exited cleanly, ALL pages fetched). Zero-result combos that finished cleanly ARE marked `completed` so they are not re-scraped on next resume.

   **Flush order — strict, CSV before manifest:**
   - At combo start: mark combo `in_progress` in the in-memory manifest. Do NOT flush to disk yet.
   - Scrape the combo; collect `TeamRecord`s into `teams_dict`.
   - On clean pagination exit: mark combo `completed` in the in-memory manifest.
   - **Flush sequence (order matters):**
     1. Write `<prefix>.csv.tmp` with full `teams_dict` contents → `fsync(fd)` → `os.replace(<prefix>.csv.tmp, <prefix>.csv)`.
     2. Only after CSV rename succeeds: write `<prefix>_manifest.json.tmp` → `fsync(fd)` → `os.replace(<prefix>_manifest.json.tmp, <prefix>_manifest.json)`.
   - **Guarantee achieved:** manifest's "completed" claims are always ≤ CSV contents. A crash between renames (or during either write) leaves CSV possibly ahead of manifest but never behind — which the resume integrity check below tolerates.
   - `os.replace()` is per-file atomic on POSIX and Windows NTFS; we do NOT rely on cross-file atomicity.

   **Resume logic — file-presence gate, mode gate, relaxed integrity:**

   **File presence gate (runs before any parsing):**
   - If BOTH `<prefix>.csv` and `<prefix>_manifest.json` present → proceed to mode gate + integrity check (normal flow).
   - If manifest MISSING but CSV present → require `--force-resume`. With `--force-resume`: load CSV into `teams_dict`, treat `completed`-set as empty (every combo will be re-scraped; `teams_dict` dedup by `provider_team_id` absorbs the already-scraped rows). Print: `"Manifest missing; rebuilding from CSV via dedup. All combos will be re-scraped."` Without `--force-resume`: hard error: `"--resume <prefix> requires both <prefix>.csv and <prefix>_manifest.json; manifest missing. Use --force-resume to rebuild from CSV alone, or start a fresh run."`
   - If CSV MISSING (with or without manifest present) → hard error unconditionally: `"--resume <prefix> requires <prefix>.csv; missing. Cannot resume — CSV is the source of truth for scraped team data. Start a fresh run."` `--force-resume` does NOT bypass — the CSV is canonical and cannot be reconstructed from the manifest.

   **Mode gate — HARD FAIL on mismatch, NOT bypassable by `--force-resume`:**
   - First check after parsing manifest: `manifest.mode == current_mode`. If not, abort with: `"Cannot resume: manifest was Mode <X>, current run is Mode <Y>. Mode mismatch indicates Step 3 observations changed; start a fresh run. (--force-resume does NOT bypass this.)"`. Rationale: Mode change means the scraper's iteration shape differs; silently mixing would produce inconsistent manifest entries or skip real work.

   **Mode A scope-subset check:**
   - For each current run's `(state, age, gender)` combo, look it up in manifest.combos by key. Missing combos are fine — they scrape fresh.
   - Skip ONLY manifest combos with `status == "completed"` whose key matches a current-run combo.

   **Mode B scope-subset check (state-aware):**
   - For each current run's `(age, gender)` combo, find the matching manifest combo (same `age, gender`).
   - Skip that combo ONLY if the current run's requested states ⊆ `manifest_combo.states_scope`. If current run requests a strict superset (e.g., previous run's `states_scope=["AZ","CA"]` but current wants `["AZ","CA","NV"]`), DO NOT skip — re-scrape the combo with the full current state list and WARN: `"Mode B combo (age={age}, gender={gender}) was completed with states_scope={prev_scope} but current run requests {current_scope} — re-scraping to cover new states."` The dedup by `provider_team_id` in `teams_dict` absorbs the AZ+CA overlap.

   **Relaxed integrity check (same for both modes):**
   - Compute `manifest_completed_sum = sum(c.team_count for c in manifest.combos if c.status == "completed")`. Require `csv_row_count >= manifest_completed_sum`.
     - If `csv_row_count > manifest_completed_sum`: the excess comes from combos marked `in_progress` at the crash moment. OK to proceed — on re-scrape of those combos, `provider_team_id` dedup in `teams_dict` absorbs the overlap. Print to operator: `"Resuming: <N> combos completed; <M> combos 'in_progress' at crash will be re-scraped (their partial rows will dedupe)."` and list the in-progress combo keys.
     - If `csv_row_count < manifest_completed_sum`: real corruption. Fail with: `"checkpoint integrity mismatch: CSV has <N> rows but manifest claims <M> rows across completed combos. Use --force-resume to override (may skip real data)."`
   - **Scope of the integrity guarantee:** the `csv_row_count >= manifest_completed_sum` check protects against **crash-during-write** scenarios only (interrupted renames, process crashes mid-flush). It does NOT detect **partial CSV corruption** where aggregate row count is preserved but individual rows for a "completed" combo are damaged or missing. Detecting partial corruption would require either per-row checksums or per-combo row-group validation — both out of scope for v1. If an operator suspects CSV damage beyond crash-during-write (disk failure, manual edit), they should start a fresh run rather than rely on `--force-resume`. Document this threat-model boundary in a comment on the resume code.

   **Final skip decision:**
   - After mode gate + scope check pass, skip combos in the current run's grid that correspond to manifest combos with `status == "completed"` (and, for Mode B, where states ⊆ states_scope).
   - Combos marked `pending` or `in_progress` are re-scraped from scratch.

   **Scrape phase — iteration mode chosen from `observations.json`:**
   - Mode selection already happened in Startup: `mode = "B" if observations["state_field_mode"] == "multi" else "A"`. README.md is narrative only; `observations.json` is the authoritative machine-readable input.

   **Mode A (single-select confirmed in Step 3):**
   - Driver iterates per `(state, age, gender)` combo — 1,020 combos total (51 × 10 × 2).
   - Each scraper call: `scraper.discover_teams(states=[state], ages=[age], genders=[gender])`.
   - Manifest entry keyed by `(state, age, gender)`.

   **Mode B (multi-select confirmed in Step 3):**
   - Driver iterates per `(age, gender)` combo — 20 combos total (10 × 2) — and passes ALL 51 requested states in one scraper call.
   - Each scraper call: `scraper.discover_teams(states=<full_state_list>, ages=[age], genders=[gender])`.
   - The scraper's `_submit_search` submits a single POST with all states selected; pagination loops once per combo, not once per state.
   - Manifest entry keyed by `(age, gender)` with `states_scope=<full_state_list>`. No per-state combo entries in Mode B.
   - Mode B reduces wall-clock time by ~50× and reduces rate-limit exposure proportionally.

   **Per-combo scrape (both modes):**
   - Mark combo `in_progress` in manifest.
   - Call `scraper.discover_teams(...)` — every yielded `TeamRecord` → upsert into `teams_dict[provider_team_id]`.
   - On clean pagination exit: mark combo `completed` in manifest, run the strict flush sequence above.
   - On `CaptchaOrBlockError` from scraper: halt the run, report error summary, exit non-zero. Manifest stays in partial state (combo remains `in_progress`) for next resume.
   - On per-combo error (populated in `scraper.errors`): leave combo as `in_progress` in manifest (or promote to a new `failed` status if we want to skip on resume — default keep as `in_progress` so next run retries), continue to next combo.

   **Bulk alias pre-check (copy pattern from `extract_and_import_tgs_teams.py:148-161`):**
   - 100-ID `IN(...)` batches against `team_alias_map.provider_team_id` where `provider_id=sincsports_uuid`.
   - Build `existing_aliases: Dict[provider_team_id, team_id_master]` for teams already aliased.

   **Metadata enrichment pass — for existing aliases:**
   - For every team in `existing_aliases`: check whether the linked `teams` row has `state_code IS NULL`. If so, UPDATE that row to set the discovered `state_code`. Use `.is_("state_code", "null")` filter on the UPDATE so discovery's write never overwrites an existing non-null value (monotonic from this side).
   - Batch these UPDATEs or run per-row with 23505-equivalent error handling; mostly no-ops after the first full run.

   **⚠ Precondition before enrichment is safe to deploy:** `scripts/match_state_from_club.py:617` runs `UPDATE ... .in_("team_id_master", batch)` with NO `state_code IS NULL` re-assertion — the batch is built from a stale snapshot at line 173. If discovery writes `state_code=AZ` between hygiene's snapshot and hygiene's UPDATE, hygiene overwrites AZ with its (less authoritative) club-inferred value. Fix out-of-scope for this plan: add `.is_("state_code", "null")` to the UPDATE filter in `match_state_from_club.py`.

   **Automated pre-run enforcement (Step 8 workflow):** the discovery workflow has a pre-flight step that queries the GitHub Actions API for in-progress runs of `data-hygiene-weekly.yml` and aborts if any are found. This is a best-effort check — a hygiene run that STARTS mid-discovery is NOT caught. The proper fix remains making `match_state_from_club.py:617` write-time monotonic.

   **Operational guidance while the precondition is unmet:** coordinate manually (e.g., discovery Saturday, hygiene Tuesday). Flag as a deployment blocker for any future automated scheduling of discovery.

   **Match phase:**
   - Instantiate matcher: `SincSportsGameMatcher(supabase, provider_id=sincsports_uuid, discovery_mode=True)`. `discovery_mode=True` prevents base `_match_team` from writing review-queue entries for sub-0.91 fuzzy results (which would otherwise pollute `team_match_review_queue` with rows that are about to be auto-created as direct_id teams anyway). The subclass return dict carries `suppressed_review_method` forward so the low-confidence signal is preserved for operator audit even though a team is created.
   - For each team NOT in `existing_aliases`: call `matcher._match_team(provider_id=sincsports_uuid, provider_team_id=team.provider_team_id, team_name=team.team_name, age_group=team.age_group, gender=team.gender, club_name=team.club_name, state_code=team.state_code)`.
   - Classify via the new `created: bool` AND `suppressed_review_method` fields (NOT by string-matching on `method`):
     - `created == False` and `method == "direct_id"` → `direct_alias_hit` (rare; only on race with bulk pre-check).
     - `created == False` and `method == "fuzzy_auto"` → `fuzzy_auto_linked` (linked to existing cross-provider team).
     - `created == True` and `suppressed_review_method is None` → `created_new` (brand new team, high-confidence direct_id or no-fuzzy-candidate path; state_code populated at INSERT time via the cascaded kwarg).
     - `created == True` and `suppressed_review_method in ("fuzzy_review", "fuzzy_review_low")` → `low_confidence_auto_created` (brand new team WAS created, but the underlying fuzzy score was sub-0.91 — operators should spot-check). Driver appends these to a separate audit CSV (see below).
   - Error handling: wrap each per-team `_match_team` call in `try/except`; append failures to errors list; continue.

   **Low-confidence audit CSV (for `low_confidence_auto_created` bucket):**
   - Path: `data/exports/sincsports_low_confidence_{run_ts}.csv` (shares `run_ts` with the main CSV and manifest — computed once at startup).
   - Columns (header row): `provider_team_id, team_name, age_group, gender, state_code, club_name, suppressed_review_method, suppressed_review_confidence`.
   - One row per team that fell into the `low_confidence_auto_created` bucket.
   - **`suppressed_review_confidence` reads from `result["suppressed_review_confidence"]`** — the original fuzzy score the base matcher computed before the subclass auto-created a direct_id team. Do NOT read from `result["confidence"]` (which is always 1.0 on the creation path — direct_id-equivalent for the newly inserted row).
   - Operator reviews this CSV after the run to spot-check ambiguous matches. Empty CSV = nothing needs review.
   - Upload this CSV as a workflow artifact alongside the main CSV and manifest (see Step 8).

   **Monotonic alias writes (Finding 6):**
   - All alias INSERTs use insert-or-ignore semantics (`.insert(...)` with 23505 duplicate-key catch; log as "already exists, skipped"). Never UPDATE an existing `team_alias_map` row — a concurrent run may have set it to `direct_id` and a later `fuzzy_auto` write must not overwrite that decision.
   - The enrichment UPDATE above is the sole exception, and it writes only to `teams.state_code` (not `team_alias_map`) and only when state_code is NULL.

   **Summary:**
   - Rich `Table` with buckets: scraped (total), skipped-existing (pre-check hit), direct_alias_hit, fuzzy_auto_linked, created_new, low_confidence_auto_created, errors.
   - Secondary per-state breakdown table (Mode A) or per-(age, gender) table (Mode B).
   - Manifest path + CSV path + low-confidence audit CSV path (if non-empty) printed at end for `--resume` convenience and operator review.

   **Docstring:** CLI examples and notes explaining `discovery_mode` semantics, Mode A vs Mode B iteration, manifest format, and the low-confidence audit CSV.

7. **Delete `scripts/search_sincsports_teams.py`**
   - Remove the file. Confirm no imports reference it: `grep -r "search_sincsports_teams" C:/PitchRank/scripts C:/PitchRank/src C:/PitchRank/tests C:/PitchRank/.github`. Expected: no references (the spec's own file at `docs/superpowers/specs/2026-04-23-...` mentions it only as superseded).
   - Single commit for the deletion.

8. **Create `.github/workflows/sincsports-team-discovery.yml`**
   - New workflow. Manual-only (`workflow_dispatch`, no `schedule:`). Canonical skeleton:
     ```yaml
     name: SincSports Team Discovery
     on:
       workflow_dispatch:
         inputs:
           dry_run: { type: choice, options: ["false", "true"], default: "false" }
           states:  { type: string, required: false, default: "" }   # CSV of postal codes; blank = all 50+DC
           ages:    { type: string, required: false, default: "" }   # CSV of u10..u19; blank = all
           genders: { type: string, required: false, default: "" }   # CSV of male,female; blank = both
     concurrency:
       group: sincsports-discovery
       cancel-in-progress: false
     env:
       SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
       SUPABASE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
       SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
       SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
       PYTHONUNBUFFERED: "1"
     jobs:
       discover:
         runs-on: ubuntu-latest
         timeout-minutes: 180
         permissions:
           actions: read    # required for the concurrent-hygiene check (gh run list)
           contents: read
         steps:
           - uses: actions/checkout@v5
           - name: Check for concurrent data-hygiene run
             env:
               GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
             run: |
               # Enforcement for the enrichment-pass precondition (see plan Step 6).
               # Until match_state_from_club.py:617 is made write-time monotonic,
               # concurrent hygiene runs risk overwriting discovery's state_code.
               in_progress=$(gh run list \
                 --workflow=data-hygiene-weekly.yml \
                 --status=in_progress \
                 --json databaseId \
                 --jq 'length')
               if [ "$in_progress" != "0" ]; then
                 echo "::error::data-hygiene-weekly.yml is currently running ($in_progress in-progress run(s)). Aborting to prevent state_code lost-update race. Re-run this workflow after hygiene completes, OR land the match_state_from_club.py monotonicity fix first."
                 exit 1
               fi
               echo "No concurrent hygiene runs detected."
           - uses: actions/setup-python@v6
             with: { python-version: '3.11', cache: 'pip' }
           - name: Install deps
             run: pip install supabase python-dotenv requests beautifulsoup4 rich
           - name: Full-grid warning summary
             if: inputs.states == '' && inputs.ages == '' && inputs.genders == ''
             run: |
               echo "🚨 Full-grid run: up to 1,020 combos (Mode A) or 20 combos (Mode B) — ~45-60 min scrape + 10-30 min match expected." >> "$GITHUB_STEP_SUMMARY"
               echo "Concurrency group sincsports-discovery serializes THIS workflow only; it does NOT coordinate with data-hygiene-weekly.yml. Confirm that workflow is not running concurrently." >> "$GITHUB_STEP_SUMMARY"
           - name: Run discovery
             env:
               DRY_RUN_INPUT: ${{ inputs.dry_run }}
               STATES_INPUT:  ${{ inputs.states }}
               AGES_INPUT:    ${{ inputs.ages }}
               GENDERS_INPUT: ${{ inputs.genders }}
             run: |
               FLAGS=()
               [ "$DRY_RUN_INPUT" = "true" ] && FLAGS+=(--dry-run)
               [ -n "$STATES_INPUT"  ] && FLAGS+=(--states "$STATES_INPUT")
               [ -n "$AGES_INPUT"    ] && FLAGS+=(--ages "$AGES_INPUT")
               [ -n "$GENDERS_INPUT" ] && FLAGS+=(--genders "$GENDERS_INPUT")
               # Auto-pass --confirm-full-grid when all scope inputs blank (non-TTY requirement).
               if [ -z "$STATES_INPUT" ] && [ -z "$AGES_INPUT" ] && [ -z "$GENDERS_INPUT" ]; then
                 FLAGS+=(--confirm-full-grid)
               fi
               mkdir -p logs data/exports
               python scripts/discover_sincsports_teams.py "${FLAGS[@]}" 2>&1 | tee logs/discover.log
           - uses: actions/upload-artifact@v5
             if: always()
             with:
               name: sincsports-discovery-${{ github.run_number }}
               path: |
                 logs/discover.log
                 data/exports/sincsports_teams_discovery_*.csv
                 data/exports/sincsports_teams_discovery_*_manifest.json
                 data/exports/sincsports_low_confidence_*.csv
               retention-days: 30
     ```
   - **Concurrency scope (narrow):** `cancel-in-progress: false` so a second manual trigger queues behind the current run rather than canceling it (discovery is long and losing work mid-run is wasteful). The group key prevents parallel manual triggers of THIS workflow. **Cross-workflow coordination (especially vs `data-hygiene-weekly.yml`, which mutates the same `teams` table via `match_state_from_club.py`) is NOT handled by the concurrency group** — the pre-flight "Check for concurrent data-hygiene run" step catches the common case (hygiene currently in progress at startup) but cannot prevent a hygiene run that STARTS mid-discovery. See the enrichment-pass precondition in Step 6.
   - **Pre-flight concurrent-hygiene check (enrichment-race enforcement):** runs BEFORE `Install deps`, so an abort burns <10 seconds of runner time. Uses the default `gh` CLI (pre-installed on `ubuntu-latest`) and `GITHUB_TOKEN` (auto-provided with `actions:read` permission via the job's `permissions:` block — no secret setup required). Aborts with a clear `::error::` annotation and exit-1 if any in-progress `data-hygiene-weekly.yml` run is detected. This upgrades the Step 6 enrichment precondition from manual discipline to automation-enforced.
   - **Bash array, no eval (Finding 4):** `FLAGS=()` + `python ... "${FLAGS[@]}"` is injection-safe when inputs are already hoisted into env. The previous `eval python ... $FLAGS` with inline quoting re-opened the shell-parse window env-hoisting was meant to close. Per `gha_inputs_shell_injection.md`.
   - **Full-grid auto-confirm (Finding 7b):** when all three scope inputs are blank, auto-pass `--confirm-full-grid` so the driver's TTY-prompt check passes in CI. A separate summary step emits a visible warning banner so operators can see at-a-glance whether a run is full-grid.
   - **Step-level `env:` hoisting** per `gha_inputs_shell_injection.md` (no `${{ inputs.* }}` inside `run:` blocks).
   - **Job-level `timeout-minutes: 180`** per `gotcha_gha_workflow_env_and_timeouts.md` (step-level would be ignored).
   - **Quad-name Supabase env** intentional per `gotcha_supabase_key_env_mismatch.md`.
   - **Artifact path includes the manifest JSON** so `--resume` from a failed run can pull both files down together.

## Verification

Sequential; each step gates the next. Do NOT proceed past a failed check.

- **Unit tests:** `cd C:/PitchRank && pytest tests/unit/test_sincsports_clubs.py tests/unit/test_sincsports_matcher_extensions.py -v` → all tests pass. No network required.
- **Matcher backward compatibility:** `cd C:/PitchRank && python scripts/import_sincsports_teams.py --team-ids NCM14762 --dry-run` → runs without error. The existing flow is unaffected since the new `state_code`, `discovery_mode`, and `created` field additions all have safe defaults (None, False, False respectively). Confirmed `teams.state_code` is nullable per the existence and semantics of `scripts/backfill_state_from_state_code.py` (which explicitly fills NULLs); adding `"state_code": None` to `team_data` in Step 2 is safe.
- **Narrow dry-run against live site:** `cd C:/PitchRank && python scripts/discover_sincsports_teams.py --states AZ --ages u12 --genders male --dry-run` → scrapes ~20–100 teams in ~30–60s; prints summary; writes CSV at `data/exports/sincsports_teams_discovery_<ts>.csv`. No DB writes.
- **CSV spot-check:** Open the CSV; assert 10 random rows have:
  - `provider_team_id` matches pattern `[A-Z]{3}\w+` (SincSports ID format).
  - `club_name` non-empty for ≥80% of rows.
  - `age_group == "u12"`, `gender == "Male"`, `state_code == "AZ"` for all rows.
  - `team_name` not leading with raw filter labels (no `"Boys / Men"` substring).
- **Narrow live run:** Remove `--dry-run`: `cd C:/PitchRank && python scripts/discover_sincsports_teams.py --states AZ --ages u12 --genders male` → completes; summary shows non-zero "created" or "fuzzy_auto" count; no errors.
- **DB spot-check:** In Supabase, query `teams WHERE provider_id = <sincsports_uuid> AND state_code = 'AZ' AND age_group = 'u12' AND gender = 'Male'` — should return the count reported by the summary. Spot-check 5 rows for full metadata (team_name, club_name, state_code all populated).
- **Created flag distribution:** driver summary's `created_new` bucket shows non-zero count on the narrow live run (new SincSports teams actually being inserted). If `created_new == 0` on a narrow run against a fresh DB, the `was_created` tuple or classification logic is broken.
- **Review queue unchanged:** `SELECT COUNT(*) FROM team_match_review_queue WHERE provider_id = <sincsports_uuid> AND created_at > <run_start_ts>` returns `0`. This proves `discovery_mode=True` suppressed all three review-queue insert sites (`game_matcher.py:768, 791, 809`) end-to-end. A non-zero count means the override didn't take effect.
- **State code populated at INSERT time (not masked by enrichment UPDATE):** `SELECT COUNT(*) FROM teams WHERE provider_id = <sincsports_uuid> AND created_at > <run_start_ts> AND state_code IS NULL` returns `0`. Every discovery-created team must have state_code at INSERT via the cascaded `state_code` kwarg through `_match_team` → `_create_new_sincsports_team`. A non-zero count means state_code threading silently failed and the enrichment UPDATE is papering over the bug.
- **Alias integrity:** `SELECT match_method, COUNT(*) FROM team_alias_map WHERE provider_id = <sincsports_uuid> GROUP BY match_method` — expect `direct_id` majority + some `fuzzy_auto` / `manual_review` depending on cross-provider overlap. No `NULL` or unknown methods.
- **Workflow trigger:** Trigger via GH UI with inputs `states: AZ, ages: u14, genders: male, dry_run: true`. Expected: job completes ≤5 min, `discover.log` artifact uploaded, CSV artifact uploaded.
- **Resume logic:** Take the narrow live run's CSV + manifest JSON, pass `--resume <prefix>` (where `<prefix>` resolves to `<prefix>.csv` and `<prefix>_manifest.json`) to a second run with a broader scope (`--states AZ,CA`). Expected: AZ combos listed as `completed` in manifest are skipped; CA combos scraped from scratch. Summary distinguishes resumed vs newly-scraped counts. Sanity-check the integrity gate: corrupt the CSV (truncate a few rows) and rerun without `--force-resume` — expect clear "checkpoint integrity mismatch" abort; add `--force-resume` and expect it to proceed with a warning.
- **Full-run smoke (optional, not blocking):** `cd C:/PitchRank && python scripts/discover_sincsports_teams.py` — runs all 50+DC. Expected runtime ~45–60 min scrape + ~10–30 min matching. Monitor for 429/403 sustained blocks. Inspect summary for state-by-state breakdown.

No unit tests cover HTTP plumbing — that's intentional per repo convention. Live dry-runs are the authoritative check.

## Context Files

Read in full before starting implementation:

- `C:/PitchRank/docs/superpowers/specs/2026-04-23-sincsports-team-discovery-design.md` — full design spec with architecture, filter grid, unknowns, and risks.
- `C:/PitchRank/src/scrapers/sincsports.py` — existing scraper; lift `_init_http_session`, retry config, env-var naming.
- `C:/PitchRank/src/scrapers/gotsport_event.py` — precedent for non-`BaseScraper` discovery scrapers + `EventTeam` dataclass placement.
- `C:/PitchRank/scripts/extract_and_import_tgs_teams.py` — template for the driver script (argparse, batch pre-check, 23505 fallback, rich progress, summary).
- `C:/PitchRank/scripts/import_sincsports_teams.py` — source of `ensure_provider_exists` helper, reference for current matcher integration.
- `C:/PitchRank/src/models/sincsports_matcher.py` — the matcher to extend; read `_match_team` (502-565) and `_create_new_sincsports_team` (570-672) before modifying.
- `C:/PitchRank/scripts/backfill_state_from_state_code.py` — source dict for `STATE_CODE_TO_NAME` extraction.
- `C:/PitchRank/.github/workflows/data-hygiene-weekly.yml` — workflow shape reference (env block, input routing, artifacts).
- `C:/PitchRank/.github/workflows/unknown-opponent-hygiene-weekly.yml` — workflow_dispatch input patterns, log-parsing-to-summary technique.
- `C:/PitchRank/scripts/search_sincsports_teams.py` — read before deleting; viewstate extraction code there can inform Step 4's scraper implementation.
- `C:/PitchRank/tests/unit/test_scrape_playmetrics.py` — test style reference (unit tests scope per repo convention).
