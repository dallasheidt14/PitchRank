---
status: done
---

# Plan: Gotsport Direct-Match Fix

## Context

The `auto-gotsport-event-scrape.yml` workflow is silently shipping registration
IDs as `provider_team_id` for 10–75% of teams per event, with ~25% of events
fully blocked by gotsport's reCAPTCHA v3 (rolled out April 2026). Downstream,
`team_alias_map` is being polluted with `match_method='fuzzy_auto'` rows keyed
on registration IDs, which means the "direct ID" path in
`src/models/game_matcher.py:_match_by_provider_id` is never the matching tier
that fires — fuzzy fallback matches the right team most of the time but locks
those reg IDs into the alias map, exposing the system to cross-event reg-ID
collisions in future runs.

Live ZenRows testing during planning (2026‑05‑01) proved the original
fix direction wrong: ZenRows premium proxy + JS rendering does **not** bypass
gotsport's reCAPTCHA challenge on the HTML schedule pages, and even on
non-blocked events the per-team profile pages no longer contain the "View
Rankings" links that `_resolve_api_team_id_from_event_page` parses for. The
gotsport public JSON API at `/api/v1/teams/{id}/matches?past=true` is, however,
**not** CAPTCHA-protected: it returns canonical `homeTeam.team_id` and
`awayTeam.team_id` in the response body, and a 200-vs-404 status check on the
queried ID is a deterministic registration-ID-vs-API-ID classifier.

The fix bundle: (1) refuse to ship registration IDs as `provider_team_id`,
dropping affected games with a per-event counter; (2) replace the HTML-scraping
resolver with a direct ZenRows-routed gotsport API call; (3) audit and quarantine
historical polluted alias-map rows. Change #4 (play-up age validation) is
explicitly deferred — a measure-first follow-up that does not ship in this plan.

## Pattern Survey

### Analogous Features

**ZenRows HTTP wiring**
- `src/scrapers/gotsport.py:1282-1298` — `GotsportScraper._make_zenrows_request(self, url)` is the canonical wrapper. Hits `https://api.zenrows.com/v1/` with `apikey`, `url`, `js_render="false"`, `premium_proxy="true"`, `proxy_country="us"`. Returns the raw `requests.Response`; caller handles `.text` / `.raise_for_status()` / CAPTCHA detection.
- `src/scrapers/gotsport.py:1300-1323` — `_fetch_event_page(event_id)` is the consumer that mirrors the right pattern: `if self.use_zenrows: _make_zenrows_request(event_url) else self.session.get(event_url, timeout=self.timeout)`, then `_extract_captcha_signals(response, fallback_target_url=event_url)` before `raise_for_status()`. CAPTCHA writes `reports/<event_key>/intake/captcha_challenge.json` and raises `EventCaptchaGatedError`.
- `src/scrapers/gotsport.py:3031-3044` — `_subpage_fetcher` closure: third in-tree mirror of the same idiom with `time.sleep(random.uniform(self.delay_min, self.delay_max))` jitter. Established convention.
- `src/scrapers/gotsport.py:1820-1931` — Target site `_resolve_api_team_id_from_event_page` currently uses raw `self.session.get()` at line 1843 and 1914 — bypasses ZenRows entirely. This is what the plan replaces.
- `src/scrapers/gotsport.py:1202-1203, 93-94` — Init-time `self.zenrows_api_key = os.getenv("ZENROWS_API_KEY")`, `self.use_zenrows = bool(self.zenrows_api_key)`.

**Per-run scraper telemetry artifacts**
- `scripts/scrape_new_gotsport_events.py:1043-1059` — Emits `data/raw/new_events_<timestamp>_summary.json` next to the JSONL output. Schema: `{scrape_date, days_back, lookback_days, total_events, total_games, events: [{event_id, event_name, teams_count, games_count, status, error?}, ...]}`.
- `scripts/scrape_new_gotsport_events.py:929-955` — Per-event row construction (`event_results.append({...})`). New per-event fields belong here.
- `.github/workflows/auto-gotsport-event-scrape.yml:65-75` — `actions/upload-artifact@v5` already picks up `data/raw/new_events_*_summary.json`. No workflow change needed for new fields in the summary schema.
- `src/scrapers/gotsport.py:3068-3149` — Existing per-team accumulator pattern (`dropped_out_of_scope_count`) surfaced via structured `logger.info`. Counter-only; no payload sidecar.

**One-off audit/cleanup scripts**
- `scripts/maintain_gotsport_direct_id_aliases.py:1-176` — Closest direct precedent. Conventions: `load_dotenv(".env.local"); load_dotenv(".env", override=True)` at lines 30-34; `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY)` at line 36; paginated read with `page_size=1000`, `offset += page_size`, `.range(offset, offset + page_size - 1)`, break on empty/short page (lines 62-82); per-row `.update(...).eq("id", ...).execute()` mutation (lines 110-119); `--dry-run` argparse (line 172) with early return at lines 102-103; verification re-read after writes.
- `scripts/auto_match_unknown_opponents.py:539-557` — CSV-report writer pattern: `csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))`, `writeheader()`, per-row `writerow`, output path `data/exports/unknown_opponent_match_report_<timestamp>.csv`, `mkdir(parents=True, exist_ok=True)`.
- `scripts/discover_sincsports_via_tournament.py:54-128` — CSV writer with explicit `CSV_COLUMNS` constants, atomic `tmp + os.replace` write at lines 110-128, `--dry-run` at line 134.
- Memory `gotcha_supabase_key_env_mismatch.md` — bridge `os.environ.setdefault("SUPABASE_KEY", os.environ["SUPABASE_SERVICE_ROLE_KEY"])` if any helper reads `SUPABASE_KEY`.

**Dropped-game / needs-review routing**
- No existing `data/raw/needs_review_*.jsonl` convention found anywhere in tree. The two existing sinks for "couldn't trust this record" are: (a) the Supabase `team_match_review_queue` via `src/tournaments/alias_writer.py:281` with `Decimal("0.89")` confidence clamp (memory `gotcha_review_queue_decimal_clamp.md`), and (b) per-event `reports/<event_key>/intake/raw_scrape.jsonl` via `src/scrapers/intake_journal.py`. Neither applies here — the chosen design is a counter-only drop, surfaced in the existing per-event summary row.
- `src/scrapers/gotsport.py:2283, 2329` — Current silent fallback site (`if not home_team_id: home_team_id = reg_id`). This is the leak the plan plugs.

### Reusable Utilities

- `src/scrapers/gotsport.py:1282` — `GotsportScraper._make_zenrows_request(self, url)` — single-arg wrapper. New API-resolver method calls it directly.
- `src/scrapers/gotsport.py:621, 711-720` — `_CAPTCHA_BODY_MARKER` + `_extract_captcha_signals(response, fallback_target_url=...)`. Optional defensive use; the API endpoint is not CAPTCHA-protected per live verification, but a CAPTCHA-shaped response from the API would indicate an upstream regression worth surfacing.
- `scripts/maintain_gotsport_direct_id_aliases.py:39-44` — `get_gotsport_provider_id()` — reusable `providers` lookup helper for the audit script.
- `scripts/maintain_gotsport_direct_id_aliases.py:62-82` — paginated `team_alias_map` read pattern, reusable verbatim.

### Convention Anchors

- ZenRows wrapping is per-class private method; no shared base. Each call site does an inline `if self.use_zenrows: ... else self.session.get(...)` switch. CAPTCHA detection happens at the call site, not inside `_make_zenrows_request`.
- Per-event sidecar artifacts under `reports/<event_key>/intake/` use `event_key = f"gotsport__{event_id}__unknown"`. Per-run scraper artifacts live under `data/raw/<prefix>_<...>_summary.json`, picked up by `actions/upload-artifact@v5` with glob patterns + `if-no-files-found: warn` + `retention-days: 30`.
- Summary JSON shape uses `events: [...]` rows; new per-event metrics belong inside each row, not at the top level.
- Audit/cleanup scripts use `#!/usr/bin/env python3`, `dotenv` loads `.env.local` then `.env` with `override=True`, `argparse` with `--dry-run` (`action="store_true"`), `csv.DictWriter` for reports, output under `data/exports/`.
- Paginated Supabase reads: `page_size = 1000; offset = 0; while True: ...range(offset, offset + page_size - 1).execute(); ...; if len(result.data) < page_size: break; offset += page_size`.

### Proposed Alignment

- The new API-based resolver mirrors `_subpage_fetcher`'s inline ZenRows-or-direct switch pattern (gotsport.py:3031-3044), but the helper is **module-level** (`_zenrows_get`) rather than per-class. This is a deliberate deviation: the audit script in Step 6 needs the helper without instantiating `GotsportScraper` (whose `__init__` does heavyweight Supabase + provider-row work). The class still exposes a thin `_fetch_json_via_zenrows` shim that forwards to the module-level helper. Existing `_make_zenrows_request` is left untouched to preserve `_fetch_event_page`'s well-tested HTML path.
- New per-event resolution fields (`teams_resolved`, `teams_unresolved`, `games_dropped_unresolved`) extend the existing per-event dicts in BOTH `scripts/scrape_new_gotsport_events.py:929-955` AND `scripts/scrape_upcoming_gotsport_events.py` (around the equivalent per-event-row block near line 945). Both workflows' existing artifact globs pick them up automatically. Source-of-truth is `self._last_resolution_metrics` on `GotsportScraper`, populated immediately before each `return games` site in `scrape_games_from_schedule_pages` — non-breaking for callers that ignore it.
- The audit script clones `maintain_gotsport_direct_id_aliases.py`'s skeleton (paginated reads, affirmative `--apply` gate, verify-after-write) and adds `csv.DictWriter` reporting with the explicit-`CSV_COLUMNS`-constant convention from `discover_sincsports_via_tournament.py:54-128` (handles zero-row runs cleanly). Output to `data/exports/audit_polluted_gotsport_aliases_<timestamp>.csv`. HTTP calls go through `_zenrows_get` (no `GotsportScraper` instance needed).

## Prerequisites (must complete before /implement-plan)

1. **Add `ZENROWS_API_KEY` GitHub Actions secret.** Repo Settings → Secrets and variables → Actions → New repository secret. Name: `ZENROWS_API_KEY`. Value: the user's ZenRows API key (already known out of band; do NOT commit it). Without this, the workflow ships unchanged behavior because `self.use_zenrows = bool(os.getenv("ZENROWS_API_KEY"))` will be False.
2. **Verify ZenRows credit budget.** A normal run resolves ~150 unresolved teams across 25 events. At 1 credit/request (basic proxy on a JSON endpoint, no JS render) that is ~150 credits/run × 2 runs/week ≈ 300 credits/week. Audit script (Step 6) is one-off but adds a one-time burst proportional to gotsport+fuzzy_auto row count in `team_alias_map`.

## Implementation Steps

1. **Add a module-level `_zenrows_get` helper and a class shim.**
   - In `src/scrapers/gotsport.py`, add a new module-level (NOT class method) function near the top of the file alongside other module-level helpers (e.g., near `_extract_captcha_signals` at line 711-720): `def _zenrows_get(session: requests.Session, api_key: Optional[str], url: str, *, timeout: int, delay_min: float = 0.0, delay_max: float = 0.0) -> requests.Response`.
   - Body of `_zenrows_get`:
     - If `api_key`: build `zenrows_params = {"apikey": api_key, "url": url, "js_render": "false", "premium_proxy": "true", "proxy_country": "us"}`, then `response = session.get("https://api.zenrows.com/v1/", params=zenrows_params, timeout=timeout)`.
     - Else: `response = session.get(url, timeout=timeout)`.
     - **Post-call jitter**, matching `_subpage_fetcher:3037-3038` (NOT before the request — the original plan inverted this; live verification on 2026-05-01 confirmed `_subpage_fetcher` sleeps AFTER the response): `if delay_min > 0 or delay_max > 0: time.sleep(random.uniform(delay_min, delay_max))`.
     - Return `response`.
   - Add a class-method shim on `GotsportScraper`: `def _fetch_json_via_zenrows(self, url: str, *, timeout: Optional[int] = None) -> requests.Response`. Body: `return _zenrows_get(self.session, self.zenrows_api_key, url, timeout=timeout if timeout is not None else self.timeout, delay_min=self.delay_min, delay_max=self.delay_max)`.
   - Why module-level + shim: the audit script (Step 6) needs `_zenrows_get` callable WITHOUT instantiating `GotsportScraper`, whose `__init__` (gotsport.py:1170-1233) performs a Supabase `providers.select().single().execute()` round-trip and raises `UnsupportedProviderError` on miss, plus nested `GotSportScraper` init. Module-level keeps the audit script's bootstrap to a 5-line session.
   - **Timeout contract:** `_zenrows_get` honors the caller's `timeout` argument because it builds the `session.get(...)` call with the explicit param. This fixes the existing `_make_zenrows_request:1298` issue where `timeout=self.timeout` is hard-coded and ignores caller intent. The plan's documented 10-second budget for the API path (Step 2) actually applies under this shape.
   - This is the "extract-first" step — no callers yet. Step 2 introduces the first caller (the resolver). Step 6 introduces the second (the audit script). `_make_zenrows_request` is left untouched for now to avoid touching `_fetch_event_page`'s well-tested HTML path; future cleanup can re-route it through `_zenrows_get`.

2. **Replace `_resolve_api_team_id_from_event_page` body with API-first resolution.**
   - Target: `src/scrapers/gotsport.py:1820-1931`. Keep the method signature `(self, event_id: str, registration_id: str, team_name: Optional[str] = None) -> Optional[str]`.
   - New body, in this order:
     1. Build URL: `api_url = f"https://system.gotsport.com/api/v1/teams/{registration_id}/matches?past=true"`.
     2. Call `response = self._fetch_json_via_zenrows(api_url, timeout=10)`.
     3. If `response.status_code == 404`: this is a registration ID, not an API team ID. Return `None`. Log at DEBUG with the team_name + reg_id for traceability.
     4. If `response.status_code != 200`: log at WARNING (status, team_name, reg_id), return `None`. Treat 5xx and timeouts as "unknown" — don't promote the reg_id to an API ID on uncertainty.
     5. Parse `response.json()`. The schema is a list of match objects with `homeTeam: {team_id, full_name}`, `awayTeam: {team_id, full_name}`, `home_team_reg_id`, `away_team_reg_id` (verified live 2026-05-01).
     6. Iterate matches and find the one where `str(match.get("home_team_reg_id")) == str(registration_id)` or `str(match.get("away_team_reg_id")) == str(registration_id)`. **Both sides coerced to str** to avoid TypeErrors when API fields are None on a partial-write match record, and to avoid ValueError if `registration_id` is non-numeric. Pull the corresponding `homeTeam.team_id` or `awayTeam.team_id`. That is the canonical API team ID. Return it as a string (`str(...)` defensively — gotsport sometimes returns numeric `team_id`).
     7. **If no match has a matching reg_id, return `None`** (NOT the queried registration_id). Live testing on 2026-05-01 verified the schema but did NOT verify the invariant "endpoint only returns matches for the team queried." Without that proof, promoting the queried ID to an API ID on no-self-match risks re-creating the bug we're fixing — re-injecting a registration ID into `team_alias_map` as if it were canonical. Log at WARNING ("API returned matches but none reference queried reg_id; treating as unresolved") with the first match's home/away reg_ids for diagnostic context.
     8. If response is an empty list: ambiguous. Could be a brand-new team with no matches, or a stale/invalid ID. Return `None`. Log at INFO.
   - Wrap the whole body in `try/except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as e:` — logs at WARNING and returns `None`. The original code's bare `except Exception` at lines 1929-1931 was overly broad, but a too-narrow clause loses coverage of `AttributeError` (e.g., `response.json()` returning a dict instead of a list, then `.get("home_team_reg_id")` is on a non-dict iter element) and `TypeError` (None-arithmetic on missing API fields). The expanded tuple covers the realistic failure surface without re-introducing bare-except.
   - Delete the four legacy strategies (rankings link parse, `/teams/{id}` link parse, JS `team_id` parse, plain `requests.get` API call). They are dead code on the new gotsport pages per live verification.
   - Preserve from the original method: the docstring header convention (rewrite the docstring to describe the new API-first behavior, including the 200/404/empty-list contract AND the conservative no-self-match-→-None policy), `team_name` parameter (used only for logging, do not drop), and the return type contract `Optional[str]`.
   - **Invariant verification step (planning-time only — do not embed in production code):** before merging, run `curl --ssl-no-revoke "https://api.zenrows.com/v1/?apikey=$KEY&url=https%3A%2F%2Fsystem.gotsport.com%2Fapi%2Fv1%2Fteams%2F255164%2Fmatches%3Fpast%3Dtrue&premium_proxy=true&proxy_country=us"` and confirm that every match in the response has `255164` as either `homeTeam.team_id` or `awayTeam.team_id`. If the invariant holds, the conservative no-self-match policy in sub-step 7 is paranoid-but-safe; if it doesn't hold, the policy is load-bearing. Either way the policy is correct; the curl exists so the implementer understands which case they're in.

3. **Refuse registration IDs at the schedule-page parser fallback.**
   - Target: `src/scrapers/gotsport.py:2240-2330` inside `_parse_games_from_schedule_page`. Two near-identical fallback blocks at lines 2277-2284 (home) and 2323-2330 (away).
   - Current behavior: `if not home_team_id: home_team_id = reg_id` (last resort).
   - New behavior: if `_resolve_api_team_id_from_event_page` returns `None` AND the name-based `teams_by_name` lookup also returns nothing, set `home_team_id = None` (NOT the reg_id) and mark the row for drop. Do NOT assign `home_team_id = reg_id` anywhere.
   - Add to the function's local scope: a `dropped_unresolved_count = 0` accumulator. Increment it once per game where either home OR away resolved to `None` after all priorities ran.
   - When either side is None after resolution: `continue` past the `games.append(...)` for that row. The game does not get emitted.
   - Return shape (preferred — see Step 4 for why): keep `_parse_games_from_schedule_page`'s return as `List[GameData]` UNCHANGED. Stash the per-call drop count via a closure-scoped `nonlocal` increment into a parser-level accumulator that the caller (`scrape_games_from_schedule_pages`) owns. Concretely: `_parse_games_from_schedule_page` accepts a new optional kwarg `drop_counter: Optional[List[int]] = None` (single-element list as a poor-man's mutable int — Python idiom). When provided, `drop_counter[0] += 1` for each dropped row. Callers in `scrape_games_from_schedule_pages` create one shared `[0]` list at the top and pass it to every parser invocation. This avoids changing the parser's tuple return contract that the in-tree callers (per-team walk loop at 2108-2125 and per-group walk at 2063-2082) currently bind only to `games`.
   - Preserve from existing parser: the entire happy path (`/teams/{id}` direct match still wins immediately), the `registration_to_api` Priority 1 lookup, the cache Priority 2, the `skip_team_id_resolution` Priority 3 (these all set `home_team_id` to a real value). The Priority 4 resolver call still happens; only its None-fallback to reg_id changes. Per-team walk loop and per-group walk loop both call this parser — keep both code paths.
   - **Per-team walk regression mitigation (CRITICAL — flagged by review):** the per-team walk at gotsport.py:2092-2129 seeds itself from `set(api_team_id_cache.keys())` populated during the per-group walk. The cache is keyed by `reg_id` (line 2275 sets `api_team_id_cache[reg_id] = home_team_id` even when `home_team_id` is None). After this step's edit, any team whose Priority 4 resolver returned None will: (a) still be iterated by the per-team walk (cache key exists), (b) hit `/schedules?team={reg_id}` (correct URL — registration_to_api per scraper-patterns skill), but (c) every game on that page will have unresolvable home/away IDs and be dropped. For league/season events (NPL, ECNL, CCL season brackets) the per-team walk is the **only** source of played history per `.claude/skills/scraper-patterns.skill.md:67-72`. **Mitigation — concrete edit site:** at the Priority-4 success branches in `_parse_games_from_schedule_page` (gotsport.py:2275 for home, 2321 for away), where `api_team_id_cache[reg_id] = home_team_id` (or `away_team_id`) is already written, ALSO write `if home_team_id: registration_to_api[reg_id] = home_team_id` (and the away mirror). Same parser is invoked from BOTH the per-group walk (gotsport.py:2065) and the per-team walk (gotsport.py:2111), so resolved pairs landing in `registration_to_api` from EITHER walk become available to the OTHER's Priority-1 lookup at gotsport.py:2259/2305 on subsequent rows. This means the per-team walk parsing a page for an unresolved team can still resolve that page's *opponent* rows via the populated `registration_to_api`. The team-being-walked is itself still unresolvable (we already failed in the per-group pass) — those rows still drop. Net effect: we lose only games where the queried team is unresolvable (irreparable in this run); we keep games where opponents resolved cleanly.
   - **Verification of the regression mitigation:** add to the unit-test block (Step 3 of Verification): synthesize a per-team walk page with two games — game 1's opponent has a resolvable reg_id in `registration_to_api`, game 2's opponent doesn't. Under the new behavior, both games should still drop because the queried team itself is unresolvable. This proves the regression is bounded to the queried-team failures, not the opponent failures.
   - **Acceptable regression scope:** even with the mitigation, league/season events where the resolver can't identify the queried team will lose that team's played history for this run. This is an explicit trade — the alternative is keeping the prior behavior of writing reg-IDs into `team_alias_map`, which causes wrong-team merges in *future* runs. The plan accepts the trade and surfaces it via `games_dropped_unresolved` in the per-event summary so operators can see the cost.

4. **Aggregate dropped-game counts at the event level.**
   - Target: `src/scrapers/gotsport.py:1933-2149` `scrape_games_from_schedule_pages`.
   - **Return shape: keep `List[GameData]` UNCHANGED.** Stash metrics on `self._last_resolution_metrics: dict[str, int]` immediately before each `return games` site in the function. The decision is non-breaking; the alternative (tuple return) requires updating three callers, two of which are outside the file and the third is in this same class. Caller enumeration (verified via grep on 2026-05-01):
     - `scripts/scrape_new_gotsport_events.py:916` — captures `games = scraper.scrape_games_from_schedule_pages(event_id, ...)`. Updated by Step 5.
     - `scripts/scrape_upcoming_gotsport_events.py:945` — captures `games = scraper.scrape_games_from_schedule_pages(event_id, event_name=event_name, since_date=since_date)`. Reads `self._last_resolution_metrics` post-call to populate the upcoming-event summary file.
     - `src/scrapers/gotsport.py:2571` — `scrape_event_games` calls it internally with `games = self.scrape_games_from_schedule_pages(event_id, event_name, since_date)`. Reads `self._last_resolution_metrics` and includes it in its own return surface (see body at 2571 — currently passes `games` through; add metrics passthrough as needed).
   - Add a class-level `self._last_resolution_metrics: dict[str, int] = {}` initialization in `__init__` (around gotsport.py:1227 alongside `self._matcher_cache`). Default empty dict so callers reading after a never-called path get a sane shape.
   - Inside `scrape_games_from_schedule_pages`, maintain three accumulators across the per-group walk and the per-team walk: `total_resolved`, `total_unresolved`, `total_dropped_unresolved`. The shared `drop_counter = [0]` list (Step 3) provides `total_dropped_unresolved`. Resolved/unresolved counts come from the existing logic at gotsport.py:2132-2141.
   - Before each `return games` (including the early-exit and exception paths), set `self._last_resolution_metrics = {"resolved": total_resolved, "unresolved": total_unresolved, "dropped_unresolved": total_dropped_unresolved}`. Set on the exception path too — `_last_resolution_metrics` should never be stale-from-a-prior-event when a caller reads it.
   - At the bottom of the function (alongside the existing `Team ID resolution: X resolved, Y unresolved` log at gotsport.py:2135-2137), log `Games dropped (unresolved teams): {total_dropped_unresolved}`.
   - **Atomicity note:** `_last_resolution_metrics` is per-instance, not per-call. If a future caller invokes `scrape_games_from_schedule_pages` concurrently from multiple threads on a single `GotsportScraper`, the stash race is unsafe. Today no caller does this (verified via grep — all three callers are sequential per-event loops), but document the invariant in the docstring so a future maintainer adding parallelism doesn't silently corrupt metrics.

5. **Surface drop metrics in the per-event summary JSON (all three callers).**
   - **Caller A — `scripts/scrape_new_gotsport_events.py`:**
     - The script calls `scraper.scrape_games_from_schedule_pages(event_id, ...)` at line 916. Immediately after the call, read `metrics = scraper._last_resolution_metrics or {}` (handle the empty-dict default).
     - **Update all three `event_results.append(...)` sites** (verified via grep 2026-05-01):
       - Success path: line 930
       - No-games path: line 946
       - Error path: line 959
     - Each site's dict gains three new keys, default 0 if metric absent (defensive — the error path's `_last_resolution_metrics` may be stale from a prior event since exceptions can fire before the stash is updated):
       - `teams_resolved: int = metrics.get("resolved", 0)`
       - `teams_unresolved: int = metrics.get("unresolved", 0)`
       - `games_dropped_unresolved: int = metrics.get("dropped_unresolved", 0)`
     - All other per-event fields (`event_id`, `event_name`, `teams_count`, `games_count`, `status`, `error?`) preserved.
     - The console summary table at scripts/scrape_new_gotsport_events.py:985-998 may optionally gain a "Dropped" column. Skip if it makes the table too wide; the JSON summary is the source of truth.
   - **Caller B — `scripts/scrape_upcoming_gotsport_events.py`:**
     - Same pattern as caller A. Calls `scraper.scrape_games_from_schedule_pages(...)` at line 945; read `scraper._last_resolution_metrics` immediately after.
     - **All three `event_results.append(...)` sites** (verified via grep 2026-05-01):
       - Success path: line 960
       - No-games path: line 976
       - Error path: line 991
     - Same three new keys with the same defensive defaults as caller A.
   - **Caller C — `src/scrapers/gotsport.py:2571` (`scrape_event_games`):**
     - This is an internal class method that wraps `scrape_games_from_schedule_pages`. Read its body fully (likely 2560-2620) before editing. Currently returns just the games list per the original contract.
     - If `scrape_event_games` is called by external scripts that don't go through `_last_resolution_metrics`, those scripts won't get the new metrics. Audit `scrape_event_games`'s callers via grep before adding pass-through. If it's only called from `process_event_workflow` or similar internal methods that already have access to `self._last_resolution_metrics`, no change needed beyond the `self._last_resolution_metrics` stash from Step 4 (the metric is on `self`, accessible to anything in the same instance).
   - No workflow changes required: `.github/workflows/auto-gotsport-event-scrape.yml:65-75` and `.github/workflows/auto-gotsport-upcoming-event-scrape.yml:78-88` both already upload `data/raw/<prefix>_*_summary.json` as artifacts via glob — schema additions ride along.

6. **Build the audit-and-quarantine script for polluted alias rows.**
   - New file: `scripts/audit_polluted_gotsport_aliases.py`.
   - Skeleton cloned from `scripts/maintain_gotsport_direct_id_aliases.py`. Mirror its module-level setup (the template uses inline initialization, not helper functions): inline dotenv loading at template lines 30-34 (`load_dotenv(".env.local"); load_dotenv(".env", override=True)`); inline `supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY"))` at template line 36. Reuse the only actual function from the template: `get_gotsport_provider_id()` at template line 39 (import or copy it; it's a simple `providers` lookup). Do NOT invent `load_env()` or `get_supabase()` helper wrappers — they don't exist in the template, and adding them is gratuitous indirection for a one-off script.
   - **HTTP calls use the module-level `_zenrows_get` helper from Step 1**, NOT a `GotsportScraper(...)` instance. Import: `from src.scrapers.gotsport import _zenrows_get`. Construct a 5-line session: `session = requests.Session()`, optional `session.headers.update({"User-Agent": "..."})` if matching the production UA helps. Read `api_key = os.getenv("ZENROWS_API_KEY")`. This avoids the heavyweight `GotsportScraper.__init__` side effects (Supabase `providers.select().single().execute()` round-trip, nested `GotSportScraper` init, `UnsupportedProviderError` raise on missing provider row) which are irrelevant to a read-only audit.
   - Argparse: `--apply` (default `False` — script is dry-run unless explicitly told to mutate), `--limit N` for testing on a subset, `--output PATH` for the CSV (default `data/exports/audit_polluted_gotsport_aliases_<timestamp>.csv`). Note: drop the explicit `--dry-run` flag — `--apply` is the affirmative gate, and `--dry-run` as a redundant flag invites the "I added both, now they conflict" anti-pattern.
   - Read pass: paginated select on `team_alias_map` filtered by `provider_id = <gotsport_provider_id>` AND `match_method = 'fuzzy_auto'` AND `review_status = 'approved'`. Pagination per the convention (page_size=1000, offset += page_size).
   - Validate pass: for each row, call `https://system.gotsport.com/api/v1/teams/{provider_team_id}/matches?past=true` via `_zenrows_get(session, api_key, url, timeout=10, delay_min=0.1, delay_max=0.3)` (jitter built into the helper — no separate sleep needed). Status-based classification mirrors the resolver's branches in Step 2 to keep the audit and the resolver in lockstep:
     - `200` + non-empty list + `provider_team_id` IS in `home_team_reg_id`/`away_team_reg_id` of any match → `verdict='valid_api_id_self_match'` (keep — proven canonical).
     - `200` + non-empty list + NO self-match in any match → `verdict='valid_api_id_no_self_match'` (suspect — same uncertainty the resolver hedges on; default action: quarantine via `review_status='needs_review'`, with the operator-overridable `--keep-no-self-match` flag below).
     - `200` + empty list → `verdict='ambiguous'` (don't quarantine, log for manual review).
     - `404` → `verdict='registration_id'` (quarantine candidate).
     - 5xx / network error / non-list JSON → `verdict='unknown_<reason>'` (skip; do not classify on partial information).
   - **Optional `--keep-no-self-match` flag**: when set, treats the `valid_api_id_no_self_match` bucket the same as `valid_api_id_self_match` (no quarantine). Off by default — quarantine is the conservative action.
   - CSV output columns: define an explicit module-level `CSV_COLUMNS` constant — `("id", "provider_id", "provider_team_id", "team_id_master", "match_method", "review_status", "api_status_code", "api_match_count", "self_match_found", "verdict", "decision_at")`. Use this constant as `fieldnames` for `csv.DictWriter` (mirrors `discover_sincsports_via_tournament.py:54-128` pattern). This avoids the `report_rows[0].keys()` IndexError on empty result sets — explicit columns work for zero rows.
   - Quarantine pass (only when `--apply`): for each row with `verdict='registration_id'` OR (`verdict='valid_api_id_no_self_match'` AND not `--keep-no-self-match`), `.update({"review_status": "needs_review"}).eq("id", row_id).execute()`. Do NOT delete. Do NOT change `team_id_master` (preserves audit trail and lets a future operator merge).
   - Verification pass: re-read the rows the script just updated, confirm `review_status='needs_review'`. Mirror lines 132-152 of `maintain_gotsport_direct_id_aliases.py`.
   - Print rich-console summary at end: total rows audited, verdict counts (one row per verdict), dry-run vs apply mode, output CSV path. The summary should make `valid_api_id_no_self_match` count visible so the operator can decide whether to re-run with `--keep-no-self-match`.

7. **Wire `ZENROWS_API_KEY` through the workflow.**
   - Target: `.github/workflows/auto-gotsport-event-scrape.yml`, the `Run GotSport Event Scraper` step's `env:` block at lines 40-54.
   - Add: `ZENROWS_API_KEY: ${{ secrets.ZENROWS_API_KEY }}`.
   - **Preserve the existing SUPABASE env aliasing — DO NOT "fix" the apparent duplication.** The current block at lines 41-43 maps the single GitHub secret `SUPABASE_SERVICE_KEY` to BOTH env vars `SUPABASE_SERVICE_KEY` and `SUPABASE_SERVICE_ROLE_KEY`:
     ```yaml
     SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
     SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
     SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
     ```
     This is intentional (memory `gotcha_supabase_key_env_mismatch.md`) — different scripts read different env-var names for the same key. Removing the duplicate would break callers reading `SUPABASE_KEY`/`SUPABASE_SERVICE_ROLE_KEY` at runtime.
   - Also preserve: `PYTHONPATH`, all `GOTSPORT_*` tuning env vars (DELAY_MIN/MAX, MAX_RETRIES, TIMEOUT, MAX_SCHEDULE_PAGES, PAGE_DELAY, EVENT_TIMEOUT). Do NOT remove or reorder these.
   - Mirror change in `.github/workflows/auto-gotsport-upcoming-event-scrape.yml` env block at lines 50-65 — the upcoming-event scraper goes through the same `GotsportScraper` class and the same `_resolve_api_team_id_from_event_page` resolver. Apply the same `ZENROWS_API_KEY` add and the same SUPABASE-aliasing preservation.

8. **Update CLAUDE.md / scraper-patterns skill to reflect the new resolver.**
   - Target: `C:/PitchRank/.claude/skills/scraper-patterns.skill.md` "GotSport Endpoint Quirks" section (around lines 49-79).
   - Add a subsection: "**API endpoint `/api/v1/teams/{id}/matches?past=true`** for canonical team_id resolution. Not CAPTCHA-protected (verified 2026-05-01). 200 = valid API team ID; 404 = registration ID. Resolver lives at `src/scrapers/gotsport.py:_resolve_api_team_id_from_event_page` and routes through ZenRows via `_zenrows_get`."
   - **Distinguish HTML-CAPTCHA failure from API-resolution failure** so future maintainers don't look for a sidecar artifact when an API call fails:
     - HTML pages (event main page, per-team schedule page): CAPTCHA-blocked events raise `EventCaptchaGatedError` and write `reports/<event_key>/intake/captcha_challenge.json` via `_write_captcha_artifact`. Operators can replay these.
     - API path (the new resolver): 4xx/5xx/timeout returns `None` from `_resolve_api_team_id_from_event_page`, increments `dropped_unresolved` counter, surfaces in the per-event summary JSON. **No `captcha_challenge.json` is written for API failures** — the API isn't CAPTCHA-protected, so a non-200 means a different class of failure (registration ID vs API ID, gotsport API outage, ZenRows budget exhausted). Look at `_last_resolution_metrics["dropped_unresolved"]` and the workflow logs, not at `reports/<event_key>/intake/`.
   - Update the "Per-team page" paragraph to note that the HTML page no longer reliably exposes `rankings.gotsport.com/teams/{id}` links — the API is now the source of truth. Preserve the existing warning about `/schedules?team={api_id}` redirecting to login.

## Verification

End-to-end verification, in order:

1. **Static checks** (always):
   - `python -m py_compile src/scrapers/gotsport.py scripts/scrape_new_gotsport_events.py scripts/audit_polluted_gotsport_aliases.py` — must exit 0.
   - `ruff check src/scrapers/gotsport.py scripts/scrape_new_gotsport_events.py scripts/audit_polluted_gotsport_aliases.py` — clean.
   - `mypy src/scrapers/gotsport.py` — preserves baseline; no new errors.

2. **Unit tests for the resolver:**
   - Add `tests/unit/test_resolve_api_team_id_from_event_page.py`. Cases — these MUST match Step 2 sub-step 7's conservative "no-self-match → None" contract; do not weaken any case to "returns the queried id":
     - 200 + match list with `away_team_reg_id == queried_id` → returns `awayTeam.team_id`.
     - 200 + match list with `home_team_reg_id == queried_id` → returns `homeTeam.team_id`.
     - 200 + non-empty list with NO matching reg_id → returns `None` (per Step 2 sub-step 7's no-self-match policy — does NOT promote the queried id to an API team ID).
     - 200 + empty list → returns `None`.
     - 404 → returns `None`.
     - 500 → returns `None`.
     - Network error (`requests.ConnectionError`) → returns `None`.
     - Malformed JSON (`response.json()` raises `JSONDecodeError`) → returns `None`.
     - Match record with `home_team_reg_id == None` (defensive — exercises the TypeError path covered by the expanded exception tuple) → returns `None`.
   - Mock `_fetch_json_via_zenrows` to return canned `requests.Response` objects.

3. **Unit tests for the parser drop counter:**
   - Add to `tests/unit/test_gotsport_scraper.py` (or whichever test file covers `_parse_games_from_schedule_page`): synthesize an HTML schedule page with 3 games where exactly 1 game has both teams resolvable, 1 has home unresolvable, 1 has both unresolvable. Assert `len(games) == 1` (only fully resolved ships) and `dropped_unresolved_count == 2`.

4. **ZenRows JSON-mode response shape verification** (runs before any other smoke — fail fast if ZenRows wraps/modifies the gotsport JSON body):
   - Python snippet (run from a Python REPL or `python -c` with the project root on `PYTHONPATH`):
     ```python
     import os
     import requests
     from dotenv import load_dotenv
     from src.scrapers.gotsport import _zenrows_get

     load_dotenv(".env.local")
     load_dotenv(".env", override=False)

     api_key = os.getenv("ZENROWS_API_KEY")
     assert api_key, "ZENROWS_API_KEY not set in environment or .env.local"

     r = _zenrows_get(
         requests.Session(),
         api_key,
         "https://system.gotsport.com/api/v1/teams/255164/matches?past=true",
         timeout=15,
     )
     assert r.status_code == 200, r.status_code
     data = r.json()
     assert isinstance(data, list), type(data)
     assert len(data) > 0, "empty list — picked a stale team_id?"
     m0 = data[0]
     assert "homeTeam" in m0 and "awayTeam" in m0, m0.keys()
     assert "team_id" in m0["homeTeam"], m0["homeTeam"].keys()
     assert "home_team_reg_id" in m0 and "away_team_reg_id" in m0, m0.keys()
     print("OK", len(data), "matches; sample team_id:", m0["homeTeam"]["team_id"])
     ```
   - If this fails, the rest of the smoke is meaningless. Most likely failure: ZenRows account misconfigured (missing `system.gotsport.com` allowlist), or ZenRows returns a wrapper envelope (in which case `data` is a dict, not a list). Either way the resolver would silently return None for every team in production.

5. **Local manual smoke against a real event** (post-prerequisite, post-ZenRows shape check):
   - Set `ZENROWS_API_KEY` in `.env.local`.
   - `python scripts/scrape_new_gotsport_events.py --max-events 2 --max-runtime 10 --days-back 7` against an event known to have unresolved teams in prior runs (event 47258 was CAPTCHA-blocked Apr 2026 — try a successor).
   - Inspect the resulting `data/raw/new_events_<ts>_summary.json`. Each event row should now have `teams_resolved`, `teams_unresolved`, `games_dropped_unresolved` keys.
   - Inspect the JSONL: no record's `team_id` or `opponent_id` should equal a registration ID (cross-reference against the API for sampled rows).

6. **Audit script smoke:**
   - `python scripts/audit_polluted_gotsport_aliases.py --limit 50` (dry-run, since `--apply` is the affirmative gate) — produces a CSV with verdict counts. No DB mutations.
   - `python scripts/audit_polluted_gotsport_aliases.py --apply --limit 50` — flips up to 50 rows' `review_status` to `needs_review` (only those classified `registration_id` or `valid_api_id_no_self_match`), prints verification re-read confirming the change.

7. **Production verification (after workflow run):**
   - Trigger the workflow manually via `gh workflow run auto-gotsport-event-scrape.yml`.
   - Download the `gotsport-events-<run_number>` artifact. The summary JSON should show `games_dropped_unresolved > 0` for events that previously had high unresolved counts.
   - Query Supabase: `SELECT COUNT(*) FROM team_alias_map WHERE provider_id = '<gotsport_id>' AND match_method = 'fuzzy_auto' AND created_at > NOW() - INTERVAL '1 day';` — should be 0 or near-0 for the post-fix run (no new fuzzy_auto aliases keyed on reg IDs).

## Context Files

Files to read in full before starting implementation:

- `src/scrapers/gotsport.py` — the surgery happens here. Specifically read `_make_zenrows_request` (1282-1298), `_fetch_event_page` (1300-1323), `_subpage_fetcher` (3031-3044), `_resolve_api_team_id_from_event_page` (1820-1931), `scrape_games_from_schedule_pages` (1933-2149), and `_parse_games_from_schedule_page` (2151-2330).
- `scripts/scrape_new_gotsport_events.py` — the workflow entrypoint. Read the per-event loop (897-998) and summary-write block (1043-1059) to understand where the new metrics fields plug in.
- `scripts/maintain_gotsport_direct_id_aliases.py` — the audit-script template. Clone its skeleton.
- `scripts/auto_match_unknown_opponents.py:539-557` — the CSV writer convention.
- `.github/workflows/auto-gotsport-event-scrape.yml` — the workflow. Note the existing `env:` block and the `actions/upload-artifact@v5` glob.
- `src/models/game_matcher.py:847-988` — read-only context for understanding what consumes `provider_team_id` downstream and why pollution matters.
- `.claude/skills/scraper-patterns.skill.md` — gotsport endpoint quirks; document update target in Step 8.
- Memory `gotcha_gotsport_per_event_captcha.md` — the prior knowledge that informed the pivot from HTML scraping to API.
