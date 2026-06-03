# Infographic Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bland `@vercel/og` infographics (movers, spotlight, state) with the polished canvas design language, via a shared theme + components, keeping edge rendering / CDN cache / 0-byte smoke test / data guards.

**Architecture:** Extract a shared `_shared/theme.ts` (tokens + score/record helpers), origin-aware `_shared/assets.ts` (fonts + transparent wordmark), and `_shared/components.tsx` (`Frame`, `Header`, `RankRow`, `StatBlock`). Rebuild the three routes on those. Logo is the existing wordmark with its baked green box removed via color-to-alpha → `logo-wordmark.png`.

**Tech Stack:** Next.js 16 App Router edge routes, `next/og` (Satori), Supabase RPCs (`get_state_rankings`, `get_biggest_movers`), Python/Pillow for the one-time asset build.

**Working dir:** worktree `C:/pitchrank-redesign`, branch `redesign/infographics`. Dev server: `cd frontend && NODE_TLS_REJECT_UNAUTHORIZED=0 npm run dev -- --port 3137`.

**Satori invariants (do not regress — see PR #862):** every `<div>` with >1 child sets `display:flex`; every numeric/interpolated child is a single string child (template literal); no SVG in `<img>`; explicit numeric `width`/`height` on `<img>`.

---

## File structure

- Create `frontend/app/api/infographic/_shared/theme.ts` — colors, dims, medal colors, `formatScore`, `formatRecord`, `platformDims`.
- Modify `frontend/app/api/infographic/_shared/assets.ts` — make `loadBrandFonts(origin)` origin-aware; add `wordmarkUrl(origin)`; keep `INFOGRAPHIC_CACHE_CONTROL`.
- Create `frontend/app/api/infographic/_shared/components.tsx` — `Frame`, `Header`, `RankRow`, `StatBlock`.
- Create `frontend/public/logos/logo-wordmark.png` — transparent wordmark (already generated; commit it).
- Create `scripts/make_wordmark.py` — reproducible asset build (color-to-alpha).
- Modify `frontend/app/api/infographic/state/route.tsx` — Top-10 on the shared system.
- Modify `frontend/app/api/infographic/movers/route.tsx` — climbers/fallers on the shared system.
- Modify `frontend/app/api/infographic/spotlight/route.tsx` — team-of-week on the shared system.

No change needed to `scripts/smoke_infographics.py` (byte check is design-agnostic) or `scripts/marketing_pipeline.py` (cohort rotation + deep-state already correct; state graphic stays one-per-state).

---

## Task 1: Commit the transparent wordmark asset + build script

**Files:**
- Create: `scripts/make_wordmark.py`
- Create: `frontend/public/logos/logo-wordmark.png` (already generated in the worktree)

- [ ] **Step 1: Write the build script**

```python
# scripts/make_wordmark.py
"""Strip the baked green box from logo-primary.png via GIMP-style color-to-alpha,
producing a transparent wordmark (white PITCH + yellow RANK) for the infographics.
Run once when the source logo changes: python scripts/make_wordmark.py"""
from PIL import Image

SRC = "frontend/public/logos/logo-primary.png"
OUT = "frontend/public/logos/logo-wordmark.png"
KEY = (5, 46, 39)  # sampled box green

im = Image.open(SRC).convert("RGBA")
px = im.load()
w, h = im.size
kr, kg, kb = KEY

def chan_alpha(p, k):
    if p > k:
        return (p - k) / (255 - k) if k < 255 else 0.0
    if p < k:
        return (k - p) / k if k > 0 else 0.0
    return 0.0

for y in range(h):
    for x in range(w):
        r, g, b, a = px[x, y]
        alpha = max(chan_alpha(r, kr), chan_alpha(g, kg), chan_alpha(b, kb))
        alpha = max(0.0, min(1.0, alpha))
        if alpha < 1 / 255:
            px[x, y] = (0, 0, 0, 0)
            continue
        nr = int(max(0, min(255, (r - kr) / alpha + kr)))
        ng = int(max(0, min(255, (g - kg) / alpha + kg)))
        nb = int(max(0, min(255, (b - kb) / alpha + kb)))
        px[x, y] = (nr, ng, nb, int(alpha * a))

im.save(OUT)
print("wrote", OUT, im.size)
```

- [ ] **Step 2: Generate the asset (idempotent — already present, regenerate to confirm)**

Run: `cd C:/pitchrank-redesign && python scripts/make_wordmark.py`
Expected: `wrote frontend/public/logos/logo-wordmark.png (800, 141)`

- [ ] **Step 3: Confirm it's a transparent PNG**

Run: `python -c "from PIL import Image; im=Image.open('frontend/public/logos/logo-wordmark.png'); print(im.mode, im.size, im.getpixel((2,2)))"`
Expected: `RGBA (800, 141) (...,0)` — corner alpha is 0 (box removed).

- [ ] **Step 4: Commit**

```bash
git add scripts/make_wordmark.py frontend/public/logos/logo-wordmark.png
git commit -m "feat(infographic): transparent wordmark asset + build script"
```

---

## Task 2: Shared theme tokens

**Files:**
- Create: `frontend/app/api/infographic/_shared/theme.ts`

- [ ] **Step 1: Write theme.ts**

```ts
// frontend/app/api/infographic/_shared/theme.ts
// Design tokens for the social infographics — ported from the canvas infographic system.

export const DIMENSIONS = {
  instagram: { width: 1080, height: 1080 },
  story: { width: 1080, height: 1920 },
  twitter: { width: 1200, height: 675 },
} as const;

export type PlatformKey = keyof typeof DIMENSIONS;

export const COLORS = {
  forestGreen: '#0B5345',
  darkGreen: '#052E27',
  electricYellow: '#F4D03F',
  brightWhite: '#FDFEFE',
  date: '#AAB7B2',
  club: '#9FB4AD',
  label: '#7E938C',
  divider: '#0E6552',
  rowDim: 'rgba(255,255,255,0.05)',
  rowTop3: 'rgba(244,208,63,0.16)',
  rowBorderDim: 'rgba(255,255,255,0.18)',
  climber: '#7BE38B',
  faller: '#F1948A',
} as const;

// Gold / silver / bronze for ranks 1-3.
export const MEDAL = ['#F4D03F', '#C0C0C0', '#CD7F32'] as const;

export function platformDims(platform: string) {
  return DIMENSIONS[(platform as PlatformKey)] ?? DIMENSIONS.instagram;
}

// PowerScore is stored 0-1; display on the public 0-100 scale with 2 decimals.
export function formatScore(p: number | null | undefined): string {
  return p == null ? '--' : (p * 100).toFixed(2);
}

export function formatRecord(w?: number, l?: number, d?: number): string {
  return `${w ?? 0}-${l ?? 0}-${d ?? 0}`;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/api/infographic/_shared/theme.ts
git commit -m "feat(infographic): shared theme tokens"
```

---

## Task 3: Origin-aware shared assets (fonts + wordmark)

**Files:**
- Modify: `frontend/app/api/infographic/_shared/assets.ts`

Rationale: the routes must fetch the logo/fonts from the **request origin** so they render against local dev (where the new `logo-wordmark.png` lives) and prod alike — not a hardcoded `NEXT_PUBLIC_SITE_URL`.

- [ ] **Step 1: Rewrite assets.ts**

```ts
// frontend/app/api/infographic/_shared/assets.ts
type SatoriFont = {
  name: 'Oswald' | 'DM Sans';
  data: ArrayBuffer;
  weight: 400 | 700;
  style: 'normal';
};

async function tryLoadFont(url: string, name: SatoriFont['name'], weight: SatoriFont['weight']): Promise<SatoriFont | null> {
  try {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const data = await resp.arrayBuffer();
    return data.byteLength ? { name, data, weight, style: 'normal' } : null;
  } catch {
    return null;
  }
}

// Fetch brand fonts from the request origin so local dev + prod both resolve.
export async function loadBrandFonts(origin: string): Promise<SatoriFont[]> {
  const results = await Promise.all([
    tryLoadFont(`${origin}/fonts/Oswald-Bold.woff`, 'Oswald', 700),
    tryLoadFont(`${origin}/fonts/Oswald-Regular.woff`, 'Oswald', 400),
    tryLoadFont(`${origin}/fonts/DMSans-Bold.woff`, 'DM Sans', 700),
    tryLoadFont(`${origin}/fonts/DMSans-Regular.woff`, 'DM Sans', 400),
  ]);
  return results.filter((f): f is SatoriFont => f !== null);
}

// Transparent wordmark (no baked box); 800x141 source → 5.67:1.
export function wordmarkUrl(origin: string): string {
  return `${origin}/logos/logo-wordmark.png`;
}
export const WORDMARK_ASPECT = 141 / 800;

export const INFOGRAPHIC_CACHE_CONTROL = 'public, s-maxage=3600, stale-while-revalidate=86400';
```

- [ ] **Step 2: Typecheck (expect errors in the 3 routes — they still call the old `loadBrandFonts()` / `LOGO_URL`; fixed in Tasks 5-7)**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors only in `movers/route.tsx`, `spotlight/route.tsx`, `state/route.tsx` (old signatures). No errors in `_shared/`.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/api/infographic/_shared/assets.ts
git commit -m "feat(infographic): origin-aware font loader + wordmark url"
```

---

## Task 4: Shared components (Frame, Header, RankRow, StatBlock)

**Files:**
- Create: `frontend/app/api/infographic/_shared/components.tsx`

- [ ] **Step 1: Write components.tsx**

```tsx
// frontend/app/api/infographic/_shared/components.tsx
import type { ReactNode } from 'react';
import { COLORS } from './theme';
import { wordmarkUrl, WORDMARK_ASPECT } from './assets';

// Root frame: gradient + scan-line texture overlay + footer divider.
export function Frame({ isStory, children }: { isStory: boolean; children: ReactNode }) {
  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        padding: isStory ? 64 : 56,
        background: `linear-gradient(135deg, ${COLORS.forestGreen} 0%, ${COLORS.darkGreen} 100%)`,
        fontFamily: 'DM Sans, sans-serif',
      }}
    >
      {/* Scan-line texture. If this 0-bytes the render (Satori repeating-gradient unsupported),
          delete this overlay div — see Task 4 Step 3 fallback. */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          backgroundImage:
            'repeating-linear-gradient(0deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.02) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 3px)',
        }}
      />
      {children}
    </div>
  );
}

export function Header({
  origin,
  isStory,
  title,
  subtitle,
}: {
  origin: string;
  isStory: boolean;
  title: string;
  subtitle: string;
}) {
  const logoW = isStory ? 380 : 320;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: isStory ? 44 : 30 }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={wordmarkUrl(origin)} width={logoW} height={Math.round(logoW * WORDMARK_ASPECT)} alt="" />
      <div
        style={{
          display: 'flex',
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 60 : 50,
          color: COLORS.electricYellow,
          letterSpacing: 1,
          marginTop: 22,
          textAlign: 'center',
        }}
      >
        {title}
      </div>
      <div style={{ display: 'flex', fontSize: isStory ? 24 : 20, color: COLORS.date, marginTop: 10 }}>{subtitle}</div>
    </div>
  );
}

// One stat column on the right of a row (e.g. W-L-D, SCORE, change).
export function StatBlock({
  value,
  label,
  color,
  isStory,
  width,
}: {
  value: string;
  label: string;
  color: string;
  isStory: boolean;
  width: number;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width }}>
      <div style={{ display: 'flex', fontWeight: 700, fontSize: isStory ? 26 : 22, color }}>{value}</div>
      {label ? (
        <div style={{ display: 'flex', fontSize: isStory ? 13 : 11, color: COLORS.label, letterSpacing: 1, marginTop: 2 }}>
          {label}
        </div>
      ) : null}
    </div>
  );
}

export function RankRow({
  rank,
  accent,
  teamName,
  club,
  isStory,
  children,
}: {
  rank: number;
  accent: string | null;
  teamName: string;
  club: string;
  isStory: boolean;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        flex: 1,
        background: accent ? COLORS.rowTop3 : COLORS.rowDim,
        borderLeft: `5px solid ${accent ?? COLORS.rowBorderDim}`,
        borderRadius: 10,
        padding: isStory ? '0 26px' : '0 22px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          width: isStory ? 64 : 54,
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 40 : 34,
          color: accent ?? COLORS.brightWhite,
        }}
      >
        {`${rank}`}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, marginLeft: 18, overflow: 'hidden' }}>
        <div
          style={{
            display: 'flex',
            fontFamily: 'Oswald',
            fontWeight: 600,
            fontSize: isStory ? 28 : 23,
            color: COLORS.brightWhite,
          }}
        >
          {teamName}
        </div>
        <div style={{ display: 'flex', fontSize: isStory ? 17 : 14, color: COLORS.club, marginTop: 3 }}>{club}</div>
      </div>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: still only the 3 route errors (Tasks 5-7); none in `_shared/`.

- [ ] **Step 3: Scan-line Satori-safety is verified in Task 5 Step 3.** If the first state render returns 0 bytes, delete the texture overlay `<div>` in `Frame` (the gradient alone is the fallback) and re-render. Record which path shipped.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/api/infographic/_shared/components.tsx
git commit -m "feat(infographic): shared Frame/Header/RankRow/StatBlock"
```

---

## Task 5: Rebuild the state route (Top 10) on the shared system

**Files:**
- Modify: `frontend/app/api/infographic/state/route.tsx`

- [ ] **Step 1: Replace the render with the shared system (keep the data layer + STATE_NAMES + cohort/Active guards already on `main`)**

Key changes from the current file:
- imports: `import { ImageResponse } from 'next/og';` `import { createClient } from '@supabase/supabase-js';` `import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';` `import { COLORS, MEDAL, platformDims, formatScore, formatRecord } from '../_shared/theme';` `import { Frame, Header, RankRow, StatBlock } from '../_shared/components';`
- `StateTeam` gains `wins/losses/draws`; `getStateTopTeams` default `limit = 10`, and the `.map` adds `wins: (row.total_wins as number) ?? (row.wins as number) ?? 0` (and losses/draws likewise).
- `GET`: `const { searchParams, origin } = new URL(request.url);` parse state/age/gender as today; `const isStory = platform === 'story';` `const d = platformDims(platform);` `const [teams, fonts] = await Promise.all([getStateTopTeams(state, age, gender), loadBrandFonts(origin)]);`
- JSX:

```tsx
return new ImageResponse(
  (
    <Frame isStory={isStory}>
      <Header
        origin={origin}
        isStory={isStory}
        title={`TOP 10 U${age} ${genderLabel} IN ${stateName}`}
        subtitle={`Rankings as of ${dateStr}`}
      />
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 12 : 8 }}>
        {teams.map((team, i) => (
          <RankRow
            key={i}
            rank={team.rank}
            accent={i < 3 ? MEDAL[i] : null}
            teamName={team.team_name.toUpperCase()}
            club={team.club_name}
            isStory={isStory}
          >
            <StatBlock value={formatRecord(team.wins, team.losses, team.draws)} label="W-L-D" color={COLORS.brightWhite} isStory={isStory} width={isStory ? 130 : 110} />
            <StatBlock value={formatScore(team.power_score)} label="SCORE" color={COLORS.electricYellow} isStory={isStory} width={isStory ? 110 : 92} />
          </RankRow>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', marginTop: isStory ? 28 : 18 }}>
        <div style={{ display: 'flex', height: 2, background: COLORS.divider, marginBottom: 16 }} />
        <div style={{ display: 'flex', justifyContent: 'center', fontSize: isStory ? 20 : 17, color: COLORS.club }}>
          pitchrank.io/rankings
        </div>
      </div>
    </Frame>
  ),
  { width: d.width, height: d.height, fonts, headers: { 'Cache-Control': INFOGRAPHIC_CACHE_CONTROL } }
);
```

`dateStr` uses long month: `new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })`. `genderLabel = isGirls ? 'GIRLS' : 'BOYS'`.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0 except possibly the still-old movers/spotlight (fixed next). state has no errors.

- [ ] **Step 3: Render + verify (this also validates the scan-line texture)**

Run (dev server up on 3137):
`curl -s -o /tmp/s.png -w "%{http_code} %{size_download}\n" "http://localhost:3137/api/infographic/state?state=TX&age=u14&gender=male&platform=instagram"`
Expected: `200` and size > 100000. If size is 0 → apply the Task 4 Step 3 scan-line fallback (remove the texture div) and re-run.
Then view `/tmp/s.png` and confirm: integrated logo, Top-10 medal rows, SCORE like `71.67`, W-L-D present. Also render `&platform=story`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/api/infographic/state/route.tsx frontend/app/api/infographic/_shared/components.tsx
git commit -m "feat(infographic): rebuild state Top-10 on shared design system"
```

---

## Task 6: Rebuild the movers route

**Files:**
- Modify: `frontend/app/api/infographic/movers/route.tsx`

- [ ] **Step 1: Rebuild render on the shared system**

Keep `getMoversData` (the `get_biggest_movers` up/down calls) unchanged. Switch to `const { searchParams, origin } = new URL(request.url);`, `const [{ climbers, fallers }, fonts] = await Promise.all([getMoversData(ageGroup, gender, limit), loadBrandFonts(origin)]);`, `platformDims`, and render with `Frame`/`Header`. Two stacked sections, each a column of `RankRow`s where the single right-side child shows the change:

```tsx
function MoverList({ teams, isStory, climber }: { teams: MoverTeam[]; isStory: boolean; climber: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 10 : 8 }}>
      {teams.map((team, i) => (
        <RankRow
          key={i}
          rank={team.current_rank}
          accent={null}
          teamName={team.team_name.toUpperCase()}
          club={`${team.club_name} • ${team.state_code}`}
          isStory={isStory}
        >
          <StatBlock
            value={`${climber ? '+' : '−'}${Math.abs(team.rank_change)}`}
            label={isStory ? 'THIS WEEK' : ''}
            color={climber ? COLORS.climber : COLORS.faller}
            isStory={isStory}
            width={isStory ? 120 : 96}
          />
        </RankRow>
      ))}
    </div>
  );
}
```

Header `title={`BIGGEST MOVERS`}` and `subtitle={`${ageLabel} ${genderLabel} • Week of ${dateStr}`}`. Between the two lists add small section labels (`🚀 CLIMBERS` / `📉 FALLERS`) as single-child flex divs in `COLORS.climber`/`COLORS.faller`, Oswald. Footer identical to state. `ImageResponse` options identical (fonts + cache header).

Null-safety: `${team.club_name} • ${team.state_code}` — if either can be null, build from non-null parts: `[team.club_name, team.state_code].filter(Boolean).join(' • ')` (PR #862 rule).

- [ ] **Step 2: Typecheck** — `cd frontend && npx tsc --noEmit` → exit 0 (state + movers clean; spotlight may still error until Task 7).

- [ ] **Step 3: Render + verify**
`curl -s -o /tmp/m.png -w "%{http_code} %{size_download}\n" "http://localhost:3137/api/infographic/movers?platform=instagram"` → 200, >100000. View; confirm climbers `+N` green, fallers `−N` red, integrated logo. Render `&platform=story` and `&platform=twitter`.

- [ ] **Step 4: Commit**
```bash
git add frontend/app/api/infographic/movers/route.tsx
git commit -m "feat(infographic): rebuild movers on shared design system"
```

---

## Task 7: Rebuild the spotlight route

**Files:**
- Modify: `frontend/app/api/infographic/spotlight/route.tsx`

- [ ] **Step 1: Rebuild render on the shared system**

Keep `getSpotlightTeam` (`get_biggest_movers` limit 1) + the 404-on-no-data path. Use `origin` + `loadBrandFonts(origin)` + `platformDims` + `Frame`/`Header`. Center a featured card: a large rank badge (electric-yellow circle, `#${current_rank}` single child), team name (Oswald, white), club • state (`[club, state].filter(Boolean).join(' • ')`), a change pill (`↑ ${Math.abs(rank_change)} spots this week`), and a stats row reusing `StatBlock` for RECORD / SCORE (`formatScore`) / WIN %. Header `title={`TEAM OF THE WEEK`}` `subtitle={`Week of ${dateStr}`}`. Footer + ImageResponse options identical.

All multi-child divs `display:flex`; all numbers stringified (template literals).

- [ ] **Step 2: Typecheck** — `cd frontend && npx tsc --noEmit` → exit 0 (all three clean).

- [ ] **Step 3: Render + verify**
`curl -s -o /tmp/sp.png -w "%{http_code} %{size_download}\n" "http://localhost:3137/api/infographic/spotlight?platform=instagram"` → 200, >100000. View; render `&platform=story`.

- [ ] **Step 4: Commit**
```bash
git add frontend/app/api/infographic/spotlight/route.tsx
git commit -m "feat(infographic): rebuild spotlight on shared design system"
```

---

## Task 8: Full verification + ship

- [ ] **Step 1: Typecheck + lint**
Run: `cd frontend && npx tsc --noEmit` (exit 0); `cd .. && python -m ruff check scripts/make_wordmark.py` (exit 0).

- [ ] **Step 2: 0-byte smoke test (local, fixed code)**
Run: `cd C:/pitchrank-redesign && python scripts/smoke_infographics.py --base-url http://localhost:3137`
Expected: all endpoints OK (non-empty). (state's smoke URL already passes age/gender.)

- [ ] **Step 3: Cross-render matrix**
Render movers/spotlight/state across instagram + story (and a deep state like `state=FL&age=u12&gender=male` to compare against the reference). Confirm all > 100 KB and visually correct (logo integrated, no 0-byte, scores `xx.xx`, W-L-D).

- [ ] **Step 4: Push + PR**
```bash
git push -u origin redesign/infographics
gh pr create --base main --title "redesign(infographic): port polished design to the og routes" --body-file <(...)
```
PR body: summarize the redesign (shared theme/components, transparent wordmark, Top-10 state, ×100 2-decimal score, W-L-D, richer palette), link the spec, note the 0-byte smoke + cache + guards preserved.

- [ ] **Step 5: End-to-end Postiz check (optional, creates drafts)**
After merge + deploy, run `python scripts/marketing_pipeline.py --postiz-only` → expect all social drafts succeed with the new look.

---

## Self-review notes

- **Spec coverage:** shared system (T2-4) ✓; transparent logo (T1) ✓; state Top-10 + score + W-L-D (T5) ✓; movers (T6) ✓; spotlight (T7) ✓; preserved edge/cache/smoke/guards/cohort (data layers untouched; cache header retained) ✓; scan-line texture with Satori fallback (T4/T5) ✓; club-only default (state uses `club_name`; movers uses `club • ST` since cross-state) ✓.
- **Numeric children** are all template-literal strings; **multi-child divs** all set `display:flex` (Satori invariant).
- **Origin** is request-derived everywhere so local dev renders the new asset.
