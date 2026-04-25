# Phase A Verification — event 45224 (Phoenix Cup 2026)

**Plan:** `.turbo/plans/matchbalance-backtest-intake-01-scraper-fix-and-abstraction.md` — Step 1 (Phase A)

**Run date:** 2026-04-24
**Event ID:** 45224
**Event URL:** `https://system.gotsport.com/org_event/events/45224`

## Classification

**`PHASE_A_CLASSIFICATION=ua_block,html_drift`**

Primary signal: `ua_block`. `html_drift` is a secondary classification that fires because the 82 KB CAPTCHA challenge page itself is "full-size HTML with no `jsonTeamRegs` and >4 script tags." Fixing the `ua_block` branch first should eliminate the `html_drift` signal on re-run (it will stop being a spurious match once we're past the CAPTCHA wall).

**Recommended Step 2 branch order:** `ua_block` only. Re-run Phase A after the UA-level fix; `html_drift` should clear automatically. If it doesn't, branch into `html_drift` based on the post-fix body.

## Evidence

### Baseline capture

Median body bytes across three known-good completed events:

| event_id | status | bytes | scripts | jsonTeamRegs matches | notes |
|----------|--------|-------|---------|-----------------------|-------|
| 40550 | 200 | 82,216 | 6 | 0 | OK |
| 40610 | 200 | 81,616 | 6 | 0 | OK |
| 41012 | 403 | 75,193 | — | — | **Excluded — 403** |

- Kept samples: `[82216, 81616]`
- Median: **81,916 bytes** — passes `>= 10_000` validation (plan gate: halt if below).
- **Surprise:** event 41012 returned HTTP 403 with a 75 KB body — a bot-detection landing page, not a normal HTML response. gotsport is 403'ing a non-trivial fraction of requests to our UA, not just event 45224.
- `jsonTeamRegs` matches = 0 on all three known-good events is itself notable: the live scraper regex at `src/scrapers/gotsport_event.py:331-380` may already be looking for a JSON blob that the current gotsport pages don't inline. That's a latent `html_drift` signal orthogonal to the CAPTCHA issue — worth a closer look during Step 2 once the UA block is bypassed.

### Warmup

`GET https://system.gotsport.com/` (no event path): **HTTP 403** with 75,193-byte body after a 15s read-timeout retry. The gotsport root page itself is rejecting our requests.

### Three-back-to-back-request protocol on 45224

All three requests to the event URL returned **HTTP 200** of ~82 KB — but each went through a **302 redirect to `/org_event/events/45224/verify_captchas/new`**. The final 200 body is the CAPTCHA challenge page (NewRelic bootstrap script + CAPTCHA form), not the event content.

| attempt | status | length | redirects | jsonTeamRegs | scripts | retry_after | elapsed_ms |
|---------|--------|--------|-----------|--------------|---------|-------------|------------|
| 0 | 200 | 82,730 | `302 → /verify_captchas/new` | 0 | 6 | — | 426 |
| 1 | 200 | 82,502 | `302 → /verify_captchas/new` | 0 | 6 | — | 350 |
| 2 | 200 | 82,502 | `302 → /verify_captchas/new` | 0 | 6 | — | 327 |

Body head (all three responses identical structurally):
```
<!DOCTYPE html>
<html>
<head>
<script type="text/javascript">window.NREUM||(NREUM={});NREUM.info={"beacon":"bam.nr-data.net","errorBeacon":"bam.nr-data.net","licenseKey":"97f1935c44","applicationID":"127462759","transactionName":"IFoNQUpbX1lTEBkJFwRqBkNdWkcaQAdEDwMaagBUSEBQXVcRGQgAFA=="...
```

### `scripts/scrape_specific_event.py 45224 --verbose --no-auto-import`

Ran `SCRAPER_DISABLE_APP_RETRY=1 python scripts/scrape_specific_event.py 45224 --verbose --no-auto-import`. Full output at `scrape_specific_event_run.log`. Key lines:

```
Event: GotSport                                       <- <title> of CAPTCHA page, not actual event name
Scraping games for event 45224
Scraping games from schedule pages for event 45224
Scraping 0 schedule pages                             <- no team schedule URLs extracted
Total games scraped from schedule pages: 0
Team ID resolution: 0 resolved, 0 unresolved (using registration IDs)
Found 0 games from event 45224
✅ Found 0 games                                      <- silent success path; no error surfaced
```

Confirms the "silent failure" described in the plan Context — the scraper returns zero games with no exception because the CAPTCHA page doesn't trigger any of its parser error paths.

## Classification rationale

### Decision-table match

- **`ua_block`** — two independent signals:
  1. **Login/CAPTCHA redirect** — all 3 event-URL requests carry a `302 → /verify_captchas/new` in their history. The plan's decision-table rule is "HTTP 302 with Location containing `/login` or `/users/sign_in`." The diagnostic script extended the regex to also match `/verify_captchas` because a CAPTCHA wall is semantically the same class of signal (server actively challenging non-human traffic). Flagging here so the plan/table can be formally updated.
  2. **Root-domain 403** — `GET https://system.gotsport.com/` returned 403 with a bot-detection body. This is a UA/IP-level block, not event-specific.
- **`html_drift`** — 3/3 requests met the rule literally (HTTP 200 + length ≥ baseline × 0.5 + `jsonTeamRegs` match count = 0 + script count > 4). This is the CAPTCHA page, not drifted HTML. Expected to clear once `ua_block` is resolved.
- **`rate_limited`** — no match. No 429s, no 503s, one warmup timeout (not 2+), no body-length-below-10% signal on the event URL.
- **`js_rendered`** — not a match; script count >4 tipped classification to `html_drift` per the table.
- **`url_change`** — not observable from this standalone diagnostic (requires attempting team-ID resolution on team-schedule pages, which the scraper's 0-schedule-pages result short-circuited before we could evaluate).

### Tag ambiguity note

`html_drift` coexisting with `ua_block` is a **known false-positive pattern** when the UA-rejection response body is itself ~80 KB (CAPTCHA challenge page is HTML with scripts, so it matches drift criteria). Per plan Step 2 multi-tag ordering — "ua_block → rate_limited → html_drift → url_change → js_rendered" — we resolve `ua_block` first and only address `html_drift` if it persists.

## Step 2 — Phase B branch to apply

Start with the plan's **`ua_block`** branch at Step 2 (plan lines 111-117):

> rotate UA at `src/scrapers/gotsport_event.py:112`; add `Accept-Encoding: gzip, deflate, br`, `Sec-Fetch-Dest: document`, `Sec-Fetch-Mode: navigate`; warm cookies via `session.get("https://system.gotsport.com/")` before event URL.

**Complication uncovered:** the plan's prescribed warmup GET to `https://system.gotsport.com/` **itself returned 403**. The prescribed `ua_block` fix will not survive first contact. Likely remediations to try in order (cheapest first):

1. Request full browser-realistic header set (`Accept-Encoding: gzip, deflate, br, zstd`, `Sec-Fetch-*`, `Sec-Ch-Ua-*`, `Upgrade-Insecure-Requests: 1`, `Priority: u=0, i`) with a fresh UA string. Attempt root GET first; if it returns 200, proceed with the event URL through the same session.
2. If #1 fails, add `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8` + `Cache-Control: max-age=0` + a recent Chrome version (currently 131 in the code; try 132/133).
3. If #2 fails, the site now requires JS-rendered CAPTCHA resolution → escalate to the `js_rendered` branch (Playwright MCP fallback behind `GOTSPORT_USE_PLAYWRIGHT=1`). `src/scrapers/gotsport.py:40` shows ZenRows is already wired as a paid fallback; that's another lever if Playwright is too heavy.
4. Rotate source IP (residential proxy) — a code-only fix won't clear an IP-level block. Out of scope for this shell; flag for Dallas.

## Items to flag for plan/spec update

- [ ] **Extend decision-table `ua_block` Location regex** to include `/verify_captchas` (and any other gotsport challenge paths). Current regex is `/(?:login|users/sign_in)`.
- [ ] **`empty_cookies` warmup signal** (plan Step 1, Tag table): explicitly require the warmup GET to have returned a **successful** response before treating an empty cookie jar as a `ua_block` signal. A timed-out/errored warmup produces 0 cookies for an unrelated reason and yields a false positive (caught and fixed in `scripts/phase_a_diagnostic.py` during this run).
- [ ] **`html_drift` false-positive under `ua_block`** — tag description could note that a CAPTCHA/challenge body commonly satisfies the literal `html_drift` rule; multi-tag outputs containing `ua_block` should defer any `html_drift` action until `ua_block` is resolved (this is already implicit in the branch-apply order, but worth flagging as a note on the tag itself).
- [ ] **Warmup URL itself 403s** — plan's `ua_block` branch prescribes a warmup GET to `https://system.gotsport.com/` as part of the fix, which failed under the same UA/IP conditions that caused the original failure. The fix probably needs to either (a) apply the realistic-header bundle *before* the warmup GET, or (b) accept a 403 on the warmup and try the event URL regardless with a more aggressive bot-detection-evasion header set.
- [ ] **Baseline-event 41012 returning 403** — suggests gotsport's bot detection is global, not event-specific. The `baseline-events` default set `[40550, 40610, 41012]` likely needs refresh; consider rotating to a wider pool and keeping the healthiest three. At runtime the baseline function already excludes non-200 samples — this behaves correctly.

## Step 2 attempt 1 — realistic-header bundle (2026-04-24)

**Change applied** (`src/scrapers/gotsport_event.py:_init_http_session`):

- User-Agent bumped `Chrome/131.0.0.0` → `Chrome/133.0.0.0`.
- Added: `Accept-Encoding: gzip, deflate, br`, `Upgrade-Insecure-Requests: 1`, `Sec-Fetch-{Dest,Mode,Site,User}`, `Sec-Ch-Ua*`, `Priority`.
- Expanded `Accept` to the current Chrome default.
- `Accept-Encoding` deliberately omits `zstd` because `zstandard` isn't installed — we only advertise what we can actually decode.
- Mirrored bundle into `scripts/phase_a_diagnostic.py:make_session` for signal parity. Step 3 migration will collapse the two call sites.

**Result — partial success:**

| URL | Before fix | After fix |
|---|---|---|
| `https://system.gotsport.com/` (warmup) | **403** (body 75 KB bot-detection page) | **200** (104 KB) |
| Event 40550 (baseline, known-good) | 200 (82 KB) | 200 (82 KB) |
| Event 41012 (baseline) | **403** | 200 (104 KB — generic page, not event content) |
| Event 42434 (unrelated healthy event, user-supplied control) | n/a | **200 (295 KB) with `jsonTeamRegs=1`** — clean pass |
| **Event 45224 (target)** | 302 → `/verify_captchas/new` | **302 → `/verify_captchas/new`** — still gated |

Also tested on 45224:

- Adding `_gl` Google Analytics tracking param (copied from user's healthy 42434 URL) — **no effect**. 42434 works with or without `_gl`; 45224 CAPTCHAs with or without `_gl`.
- Adding `Referer: https://system.gotsport.com/` + `Sec-Fetch-Site: same-origin` on the event-URL fetch — **no effect**.

**Interpretation:** The header fix resolves gotsport's ambient UA-level bot detection (domain, baseline events, and control event 42434 all went from block to 200). **Event 45224 is individually CAPTCHA-gated** — likely a per-event flag set server-side after prior scraping attempts hammered it, or a volume-based cooldown specific to that URL. A code-only, headers-only fix cannot bypass this.

Final classifications post-fix:

- Event 42434: `PHASE_A_CLASSIFICATION=ok` (new explicit pass state — see plan-gap note below).
- Event 45224: `PHASE_A_CLASSIFICATION=ua_block,html_drift` (unchanged — `html_drift` is still the expected false-positive while `ua_block` persists on this event; see prior section).

## Additional plan/spec items uncovered

Added to the list above:

- [ ] **Decision-table lacks a pass state** — the plan's table only enumerates failure tags and `unknown_html_state`. A healthy event satisfies no rule and falls through to "unknown," which is misleading. The diagnostic script now emits `ok` when `>= 2/3` samples return HTTP 200 with `jsonTeamRegs > 0`. Worth formalizing.
- [ ] **`empty_cookies_after_warmup` rule is noise at gotsport** — the gotsport root page returns 200 with no `Set-Cookie` on a fresh session. Treating that as `ua_block` produces false positives on healthy events (verified 2026-04-24). The diagnostic script now drops this rule. Recommend removing from plan decision table — keep only explicit `403` and login/captcha redirect signals.
- [ ] **Per-event CAPTCHA gating is a failure mode the table doesn't name.** Our current composite tag `ua_block,html_drift` is the closest available mapping, but a dedicated `captcha_challenge` (or `per_event_gate`) tag would be clearer — triggered when the event URL redirects to `/verify_captchas/new` specifically, and would route to a "use a headful browser or wait for cooldown" remediation rather than "rotate UA."

## Next-step decision for 45224

Options to bypass the per-event CAPTCHA on 45224 specifically:

1. **Wait and retry** — if the gate is time-based, it may clear. Cheap; no code changes. Can periodically poll.
2. **Playwright MCP fallback** — plan's `js_rendered` branch (`GOTSPORT_USE_PLAYWRIGHT=1`). Playwright can render the CAPTCHA page and either solve it programmatically (unlikely without a third-party solver) or use a full browser profile that gotsport doesn't challenge.
3. **ZenRows** — already wired at `src/scrapers/gotsport.py:40` in `GotSportScraper`, not in `GotSportEventScraper`. ZenRows advertises CAPTCHA-solving as a paid feature. Shell 01 would need to thread it through `GotSportEventScraper` (or the post-migration `GotsportScraper`).
4. **Change source IP** — residential proxy; out of band for this shell.
5. **Use a different test event** — pick a currently-healthy event to exercise Steps 3–7 end to end; revisit 45224 when it clears or is handled via #2–#4.

## Step 2 attempt 2 — ZenRows routing + CAPTCHA detect-and-skip (2026-04-24)

**Scope.** Headers alone don't unlock gotsport. Per-event reCAPTCHA v2 is widespread (≥ 3/5 events tested served the challenge). ZenRows' premium proxy doesn't auto-solve reCAPTCHA, but it works on healthy events. Pivot:

1. Route event-URL fetches through ZenRows when `ZENROWS_API_KEY` is set (mirrors `src/scrapers/gotsport.py:56`). CAPTCHA'd events still hit the gate but via ZenRows' residential IPs rather than direct.
2. Detect CAPTCHA at fetch time (URL contains `/verify_captchas`, OR redirect chain points there, OR body contains `Please verify to continue`). Fall back to `Zr-Final-Url` response header (set by ZenRows) for the real origin URL rather than the proxy URL.
3. Extract the reCAPTCHA sitekey from the challenge body — 4-shape regex (data-sitekey / `api.js?render=` / `api2/anchor?k=` / JS init) + `6L...` fallback.
4. Raise typed `EventCaptchaGatedError` with sitekey + challenge URL + artifact path.
5. Write `reports/<event_key>/intake/captcha_challenge.json` with full replay payload (sitekey, detected_at, via_zenrows, provider_code, etc.). NO secrets (API key is not written anywhere).
6. `scripts/scrape_specific_event.py` catches the typed error, prints a yellow warning with artifact path, exits 0, does NOT call `save_scraped_event` (so the event is retried next run when the gate clears).

**Files changed:**

- `src/scrapers/gotsport_event.py` — added `EventCaptchaGatedError`, `_extract_captcha_signals`, `_find_sitekey`, `_make_zenrows_request`, `_fetch_event_page`, `_write_captcha_artifact`. Refactored 2 primary event-URL fetch sites in `scrape_games_from_schedule_pages` and `scrape_event_games` to call `_fetch_event_page`. Added `except EventCaptchaGatedError: raise` before bare `except Exception` in those same methods.
- `scripts/scrape_specific_event.py` — imports `EventCaptchaGatedError`; catches it in the main `try/except` around `scrape_event_games` and exits 0 without marking scraped.

**Smoke tests (both pass):**

- **Event 45224 (CAPTCHA-gated):** CAPTCHA detected in ~3 s; artifact written with sitekey `6Lf7TGogAAAAANuN0mBzLOY4T96kSfIB8DHGPsXF` and real gotsport challenge URL (no proxy-URL / API-key leak); process exited 0; event is NOT in `scraped_events.json`, so it'll be retried.
- **Event 42434 (healthy):** routed through ZenRows; event page loaded; scraper found 98 bracket schedule pages (capped to 25 per `GOTSPORT_MAX_SCHEDULE_PAGES`); resolved 137 team IDs through downstream endpoints. Ended with "0 games" — a separate downstream issue (schedule-page parsing / 30-day date window on this specific event), NOT a CAPTCHA or fetch failure. Scraper ran end-to-end without exception.

**Deliberately out of scope for this pivot:**

- Routing the other 6 `self.session.get(event_url, ...)` call sites through ZenRows. They're inside methods that only run if the primary event fetch succeeded — so a CAPTCHA'd event never reaches them. Step 3 migration will consolidate them into a single `_session_get` wrapper.
- Solving the reCAPTCHA. That's a separate sub-project: either (a) 2Captcha/Anti-Captcha integration where the artifact's sitekey is fed to a solver, or (b) a gotsport-authenticated session path if Dallas has an account that sees the gated events.

## Files

- `diagnostic_phase_a.log` — first run (pre-fix baseline).
- `diagnostic_phase_a_rerun.log` — after realistic-header bundle.
- `diagnostic_phase_a_referer.log` — same-origin referer attempt (no effect).
- `diagnostic_phase_a_42434.log` — control test against healthy event.
- `scrape_specific_event_run.log` — pre-fix `scrape_specific_event.py 45224 --verbose --no-auto-import` under `SCRAPER_DISABLE_APP_RETRY=1`.
- `captcha_challenge.json` — artifact written by the detect-and-skip flow (sitekey, challenge URL, provider, timestamp).
- `scrape_verification.md` — this file.
