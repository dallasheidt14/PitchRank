---
status: done
---

# Plan: Install Meta Pixel + Google Ads Remarketing Tag (Audience Capture)

## Context

We want to retarget website visitors who browse PitchRank (rankings, team pages) but never create an account. Retargeting only works if visitors are tagged *now* — the audience starts building the day the pixels go live and cannot be reconstructed retroactively. With traffic approaching ~10k visits/month, the retargetable pool (~7k uniques/month, since ~95%+ leave without signing up) comfortably clears every platform audience minimum (Meta ~100, Google Display ~1,000). So the priority is to get the tags collecting audiences immediately, even though no campaigns run yet.

This change installs the **browser Meta Pixel** (`fbevents.js` / `fbq`) and the **Google Ads remarketing tag** (`gtag('config','AW-…')`), mirroring the existing hand-rolled `GoogleAnalytics.tsx` component pattern. Scope is **audience capture only** — no conversion-event wiring, no server-side Conversions API, no campaign setup.

**Consent decision (resolved):** No cookie-consent banner. Pixels fire for all visitors on load. This is legal for US traffic (no opt-in requirement; CCPA is opt-out and PitchRank is below its thresholds) and fits "start capturing now." The small EU/UK GDPR gap is accepted given a US youth-soccer audience. The privacy policy is updated to disclose Meta/Google advertising regardless.

**Future enhancement (out of scope):** Meta's 2026 best practice pairs the browser pixel with the server-side **Conversions API** (with `eventID` dedup) for reliability against iOS/ad-blocker loss. Note it; do not build it here.

## Pattern Survey

**Baseline note (LOAD-BEARING):** The current working tree (`fix/modular11-events-division-mapping`, a backend ranking change with unrelated staged work) is **behind `origin/main`** on two surveyed files — `components/GoogleAnalytics.tsx` (missing `session_id` sanitization + `page_location` pinning) and `next.config.ts` (missing a redirect entry). **All line anchors below are from `origin/main`.** The implementer MUST branch off `origin/main` and mirror `origin/main`'s `GoogleAnalytics.tsx`, not the working-tree copy. (Branch/setup handled in Step 0.)

### Analogous Features
- `frontend/components/GoogleAnalytics.tsx:85` — `GoogleAnalytics` public component: early-returns `null` when `!measurementId || NODE_ENV === 'development'`, then renders `<Suspense fallback={null}>` wrapping the inner content component. **The exact mirror template** for `MetaPixel` (and the gate/Suspense shape for `GoogleAds`).
- `frontend/components/GoogleAnalytics.tsx:17-41` — `GoogleAnalyticsContent`: reads `usePathname()` + `useSearchParams()`, fires a route-change pageview in `useEffect` (deps `[pathname, searchParams, measurementId]`), guarded again by the same `!id || dev` check. The `useSearchParams` usage is why the Suspense wrapper is required (Next.js rule).
- `frontend/components/GoogleAnalytics.tsx:48-66` — initial-load injection: two `<Script strategy="afterInteractive">` tags — external `googletagmanager.com/gtag/js?id=...` + an inline one that sets `window.dataLayer`, defines `gtag()`, calls `gtag('js', new Date())` then `gtag('config', ...)`.
- `frontend/app/layout.tsx:146` — sole mount point: `<GoogleAnalytics measurementId={process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID} />` inside `<head>` (head block at `layout.tsx:137-147`), imported at `layout.tsx:9`. New components mount as siblings here, env var passed as a prop the same way.
- `GoogleAnalytics.tsx` is the **only** `next/script`-based tracking component. `WebVitalsReporter` (layout.tsx:10) is hook-based — not a template.

### Reusable Utilities
- `frontend/lib/analytics.ts:18` — `gtagEvent(name, params)`: GA4-event-shaped low-level helper (dev-gates, strips null params, pushes to dataLayer). **Convention anchor for the dev-gate+dataLayer guard, NOT a function to call** for `config`/`fbq`.
- `frontend/lib/events.ts:1-308` — ~30 typed `track*()` wrappers. **Audience-capture only → DO NOT touch this file.** Listed so the implementer knows GA events live here and deliberately stays out.
- `frontend/types/gtag.d.ts:4-13` — global `Window.gtag?` + `Window.dataLayer?` augmentation. **`fbq` is NOT typed** anywhere → Meta Pixel needs a new `Window.fbq?` declaration added here. Google Ads reuses existing `gtag` typing (no new type).

### Convention Anchors
- **gtag reuse:** gtag.js is initialized exactly once (GoogleAnalytics.tsx `<Script src=...gtag/js>` at :51 + inline `gtag('js')`/`gtag('config', GA_ID)` at :54-64). Google Ads uses the SAME library → `GoogleAds` renders an inline `<Script>` that re-establishes the `gtag` shim and pushes a second `gtag('config','AW-…')` to the shared `window.dataLayer` (race- and `tsc`-safe — see Step 4), **not** a typed `window.gtag` call and **not** re-injecting the loader when GA is present. Caveat: GA mount is conditional, so if `NEXT_PUBLIC_GA_MEASUREMENT_ID` is unset, gtag.js never loads — `GoogleAds` must additionally render the gtag.js loader + call `gtag('js')` in that case (see Step 4).
- **Component placement:** flat `frontend/components/*.tsx`, PascalCase filename = export name, `'use client'` at top.
- **Dual dev/prod gate:** `!id || process.env.NODE_ENV === 'development'` appears in BOTH the `useEffect` body AND the render early-return (GoogleAnalytics.tsx:23 and :44/:87). Mirror both surfaces.
- **Env var convention:** `NEXT_PUBLIC_*`, read in `layout.tsx` (not the component) and passed as optional prop (`id?: string`). Documented in **two** places: root `.env.example:126-130` (commented block: title, source URL, format, "Leave empty to disable", then `NAME=`) and `frontend/CLAUDE.md` public-env list (~line 326). **There is no `frontend/.env.example`** — the file is at repo root.
- **CSP `script-src`:** `frontend/next.config.ts:103-104`, inside `async headers()` (block :74-110), source `/(.*)`. Current value:
  `default-src 'self'; script-src 'self' 'unsafe-inline'${cspUnsafeEval} https://www.googletagmanager.com https://www.google-analytics.com; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none';`
  Only `https://connect.facebook.net` must be ADDED to `script-src` (Meta loader). Google's `googletagmanager.com` already whitelisted. `img-src 'self' https: data:` covers the `www.facebook.com` tracking pixel; `connect-src 'self' https:` covers `connect.facebook.net` / `googleads.g.doubleclick.net` / `google.com` beacons. **Preserve every other directive unchanged** and the `${cspUnsafeEval}` dev interpolation.
- **Privacy policy:** `frontend/app/privacy-policy/page.tsx`, section `id="data-sharing"` (#4 "Data Sharing") spans :144-158; the `<ul>` opens at line 149 with four `<li>` items at :150-153 and `</ul>` at :154 ("Payment processors (Stripe) / Hosting providers / Analytics providers / Legal authorities"); the "we do not sell" line is at :156. TOC entry at line 31. Extend the `<ul>` with an advertising/remarketing bullet.

### Proposed Alignment
**Mirror `origin/main`'s `GoogleAnalytics.tsx` closely** for `MetaPixel`; mirror its gate/Suspense shape for `GoogleAds`. **Two deliberate deviations:** (1) `MetaPixel` self-injects `connect.facebook.net/en_US/fbevents.js` + `fbq('init')`/`fbq('track','PageView')` and adds a `Window.fbq?` type; (2) `GoogleAds` does NOT re-inject gtag.js when GA is present — it adds a `gtag('config','AW-…')` via an inline `<Script>` pushing to dataLayer (mirroring GA's init block, not a typed `window.gtag` call), additionally rendering the gtag.js loader + `gtag('js')` only when GA's env var is unset. **Do NOT** add to `lib/events.ts`/`lib/analytics.ts`.

## Implementation Steps

0. **Branch/setup — handle the local-state hazard.**
   - The current `C:/PitchRank` checkout is on `fix/modular11-events-division-mapping` with **unrelated staged work in the index** (`config/settings.py`, a staged spec, dirty `.pyc`) and is behind `origin/main` on in-scope frontend files. Branching in place would bundle this change with the modular11 work.
   - Per repo worktree discipline, this is the documented exception: isolate via a **git worktree off `origin/main`** — `cd C:/PitchRank && git fetch origin && git worktree add C:/pitchrank-pixels origin/main -b feat/meta-pixel-google-ads`. (Alternatively, if the modular11 staged work has since been committed/cleared, branch off `origin/main` in place.)
   - Before editing, confirm a clean baseline: `git diff origin/main -- frontend/` returns empty for in-scope files.
   - The worktree lacks `frontend/.env.local` and `node_modules`; copy env (`cp C:/PitchRank/frontend/.env.local C:/pitchrank-pixels/frontend/.env.local`) and run `npm install` (or run the `tsc`/build verification in the main `C:/PitchRank` checkout against identical code). Clean up the worktree after the PR merges.

1. **Add the two env vars (docs only — both default empty/disabled).**
   - In root `C:/PitchRank/.env.example`, after the GA block (~:126-130), add two commented blocks matching the existing style (title, source URL, format, "Leave empty to disable"):
     - `NEXT_PUBLIC_META_PIXEL_ID=` — source `https://business.facebook.com/` (Events Manager → Data Sources).
     - `NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_ID=` — source `https://ads.google.com/` (Audiences/Tag → `AW-XXXXXXXXX`).
   - In `frontend/CLAUDE.md` public-env list (~:326), add both names so the inventory stays complete.

2. **Add the `fbq` global type.**
   - In `frontend/types/gtag.d.ts` (the `declare global { interface Window { … } }` block at :4-13), add `fbq?: (...args: unknown[]) => void;` and `_fbq?: unknown;`. Leave the existing `gtag`/`dataLayer` typings untouched (Google Ads uses the untyped inline-`<Script>` path — see Step 4 — so the `gtag` signature needs no change).

3. **Create `frontend/components/MetaPixel.tsx`** — mirror `GoogleAnalytics.tsx` (origin/main):
   - `'use client'`; export `MetaPixel({ pixelId }: { pixelId?: string })`.
   - Render early-return `null` when `!pixelId || NODE_ENV === 'development'`; wrap inner content in `<Suspense fallback={null}>` (mirrors :85/:87 and the Suspense rationale).
   - Inner content: a single `<Script id="meta-pixel" strategy="afterInteractive">` that injects the standard Meta base code (`fbevents.js` loader + `fbq('init', pixelId)` + `fbq('track','PageView')`).
   - A `useEffect` keyed on `usePathname()` + `useSearchParams()` (deps mirror GA's `[pathname, searchParams, pixelId]`) that fires `window.fbq?.('track','PageView')` on route change, guarded by the same `!pixelId || dev` check (mirror both gate surfaces, GA :23 and :44).
   - *(Exact `fbq` base snippet is provided by Meta's docs at execution time — do not hardcode it from this plan.)*

4. **Create `frontend/components/GoogleAds.tsx`** — minimal remarketing tag (mirror GA's inline-`<Script>` approach, NOT a typed `window.gtag` call):
   - `'use client'`; export `GoogleAds({ conversionId }: { conversionId?: string })`.
   - Early-return `null` when `!conversionId || NODE_ENV === 'development'` (dual dev/prod gate). No route-change handler, no Suspense (no `useSearchParams`).
   - Render an inline `<Script id="google-ads" strategy="afterInteractive">` (mirroring `GoogleAnalytics.tsx:48-66`) whose template-string idempotently sets `window.dataLayer = window.dataLayer || []`, defines the `gtag` shim (`function gtag(){dataLayer.push(arguments);}`), and calls `gtag('config', '${conversionId}')`. **Write this as an inline-`<Script>` template-string, NOT a typed `window.gtag?.('config', …)` TSX call** — doing so is both (a) race-safe: gtag.js replays the `dataLayer` queue when it finishes loading, so the `config` is never dropped on first paint (gating on `window.gtag` truthiness would silently no-op if GA's async inline shim hasn't run yet); and (b) type-safe: the inline string isn't type-checked, so it sidesteps the `types/gtag.d.ts` `gtag` signature whose 2nd param is `string` (a typed `gtag('js', new Date())` would fail the `tsc --noEmit` verification below).
   - **GA-absent path:** branch on `process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID` (a `NEXT_PUBLIC_*` var, statically inlined at build time, so it can be read directly in the component). ONLY when it is unset (GA never loads gtag.js) must GoogleAds ALSO render the loader `<Script src="https://www.googletagmanager.com/gtag/js?id=${conversionId}" strategy="afterInteractive" />` and have its inline script call `gtag('js', new Date())` before the `config` call. When GA *is* present (the normal case — `G-7G1698GM92` is configured), GA already loads the library and calls `gtag('js')`, so GoogleAds emits ONLY the extra `gtag('config', '${conversionId}')` and must NOT re-inject the loader.

5. **Add `connect.facebook.net` to the CSP.**
   - In `frontend/next.config.ts:103-104`, append ` https://connect.facebook.net` to the `script-src` directive only. **Preserve all other directives, the `${cspUnsafeEval}` dev interpolation, and the surrounding `headers()` structure (:74-110) exactly.** No other directive needs changes (verified: `img-src`/`connect-src` already permissive).

6. **Mount both components in the root layout.**
   - In `frontend/app/layout.tsx`: import `MetaPixel` and `GoogleAds` (beside the `GoogleAnalytics` import at :9).
   - In `<head>` (:137-147), add as siblings after `<GoogleAnalytics … />` (:146):
     `<MetaPixel pixelId={process.env.NEXT_PUBLIC_META_PIXEL_ID} />` and
     `<GoogleAds conversionId={process.env.NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_ID} />`.
   - Order GoogleAds after GoogleAnalytics so that, in the GA-present case, GA's gtag.js loader is already rendered and GoogleAds avoids double-injecting it. Correctness does **not** depend on `window.gtag` existing at mount — GoogleAds pushes `config` to the shared `window.dataLayer` queue, which gtag.js replays once it loads.

7. **Update the privacy policy.**
   - In `frontend/app/privacy-policy/page.tsx`, extend the Data Sharing `<ul>` (opens at :149, items :150-153, closes :154; section `id="data-sharing"`) with a bullet naming advertising/remarketing partners, e.g.: "Advertising partners (Meta and Google) — we use the Meta Pixel and Google Ads tags to measure site usage and build remarketing audiences." Keep wording consistent with the existing "we do not sell personal data" stance (:156).

## Verification

- **Build-safe with IDs unset (default state):** in the worktree (or main checkout against identical code) run `cd frontend && npx tsc --noEmit` and `npm run build`. Both pass; with the two new env vars empty, `MetaPixel`/`GoogleAds` return `null` and inject nothing.
- **With test IDs set** — the pixels are gated off in dev (`NODE_ENV === 'development'`), so these checks MUST run against a **production build, not `npm run dev`**. Set the two IDs temporarily in `frontend/.env.local`, then `cd frontend && npm run build && npm run start` (production server). Then:
  - Network tab shows `connect.facebook.net/en_US/fbevents.js` loading and an `fbq` init/PageView request to `www.facebook.com/tr`.
  - Browser **Meta Pixel Helper** extension reports the pixel firing + a `PageView`.
  - **Google Tag Assistant** shows the `AW-…` tag firing a `config`.
  - Navigating between routes fires a **second** Meta `PageView` (SPA route-change handler); Google Ads does not re-fire (expected — config-once).
- **Dev gate:** in `npm run dev` with `NODE_ENV=development`, neither pixel injects or fires.
- **CSP:** no `Content-Security-Policy` violation in the console for `connect.facebook.net`; confirm the response header still contains all original directives plus the new domain.
- **GA-absent path:** temporarily unset `NEXT_PUBLIC_GA_MEASUREMENT_ID` with `NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_ID` set → `GoogleAds` self-loads gtag.js and the `AW-` config still fires.
- **Privacy policy:** `/privacy-policy` renders the new advertising/remarketing bullet under Data Sharing.

## Operational prerequisites (not code — for the user)

To make the tags actually collect, after merge: create the **Meta Pixel** at business.facebook.com (Events Manager) and the **Google Ads remarketing tag** at ads.google.com (Audiences), then set `NEXT_PUBLIC_META_PIXEL_ID` and `NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_ID` in **Vercel → Production env vars** (and local `frontend/.env.local` for testing). The code ships safely before the IDs exist — it simply no-ops until they're set.

## Context Files

Read in full before implementing:
- `frontend/components/GoogleAnalytics.tsx` (**from `origin/main`**) — the mirror template for both new components; copy its gate/Suspense/Script structure.
- `frontend/app/layout.tsx` — `<head>` mount point and env-var-as-prop pattern.
- `frontend/next.config.ts` — the `headers()` CSP block; edit `script-src` only, preserve the rest.
- `frontend/types/gtag.d.ts` — global `Window` augmentation to extend with `fbq`.
- `frontend/app/privacy-policy/page.tsx` — Data Sharing section to extend.
- `C:/PitchRank/.env.example` (root) and `frontend/CLAUDE.md` — the two env-var documentation surfaces.
- `frontend/lib/events.ts` / `frontend/lib/analytics.ts` — read only to confirm scope: these stay untouched (no events in this task).
