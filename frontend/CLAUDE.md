# CLAUDE.md — PitchRank Frontend

> Next.js 16 + React 19 + TypeScript 5.9 + Tailwind v4

---

## Quick Reference

| Item | Value |
|------|-------|
| **Framework** | Next.js 16.2.1 (App Router) |
| **React** | 19.2.1 (Server Components by default) |
| **TypeScript** | 5.9.3 (strict mode) |
| **Styling** | Tailwind CSS v4, shadcn/ui (Radix), CVA |
| **State** | TanStack React Query v5 |
| **Auth** | Supabase Auth (SSR cookies) |
| **Payments** | Stripe (checkout + portal) |
| **Charts** | Recharts v3 |
| **Search** | Fuse.js (client-side fuzzy) |
| **Virtualization** | @tanstack/react-virtual |
| **Unit Tests** | Vitest (happy-dom) |
| **E2E Tests** | Playwright v1.58 |
| **Path alias** | `@/*` → project root |
| **Domain** | www.pitchrank.io |

---

## Commands

```bash
npm run dev          # Dev server
npm run build        # Production build
npm run lint         # ESLint
npm run format       # Prettier (write)
npm run format:check # Prettier (check only, used in CI)
npm run analyze      # Bundle analysis (set ANALYZE=true)
npm run test         # Unit tests (Vitest, run once)
npm run test:watch   # Unit tests (watch mode)
npm run test:coverage # Unit tests (with coverage)
npm run test:e2e     # All Playwright E2E tests
npm run test:e2e:smoke  # Smoke tests only
npm run test:e2e:api    # API tests only
```

---

## Directory Structure

```
frontend/
├── app/                    # App Router pages
│   ├── layout.tsx          # Root layout (Providers, Nav, Footer)
│   ├── providers.tsx       # React Query + Tooltip providers
│   ├── page.tsx            # Home page
│   ├── rankings/           # Rankings routes
│   │   ├── page.tsx        # National rankings
│   │   ├── [region]/       # State rankings
│   │   └── [region]/[ageGroup]/[gender]/  # Filtered
│   ├── teams/[id]/         # Team detail (ISR, revalidate: 3600)
│   ├── compare/            # Team comparison (premium)
│   ├── watchlist/          # Watched teams (premium)
│   ├── blog/[slug]/        # Blog posts
│   ├── mission-control/    # Admin dashboard
│   ├── upgrade/            # Premium upgrade funnel
│   ├── embed/club/[clubId]/ # Embeddable widget
│   ├── login/ signup/ forgot-password/ reset-password/
│   ├── sitemap.ts          # Dynamic sitemap
│   └── api/                # API routes (see below)
├── components/             # React components
│   ├── ui/                 # shadcn/ui primitives
│   ├── mission-control/    # Admin panel components
│   ├── agent-hq/           # AI agent interface
│   ├── infographics/       # Canvas-rendered infographics
│   ├── insights/           # AI insights (premium)
│   ├── subscription/       # Paywall/upgrade UI
│   └── skeletons/          # Loading states
├── hooks/                  # Custom React hooks
├── lib/                    # Utilities, API client, types
│   ├── api/                # Shared route utilities (requirePremium, validatePagination, parseJsonBody, rateLimit)
│   ├── agents/             # Agent config (schedules, roles) + utils (formatRelativeTime, calculateNextRun)
│   ├── supabase/           # Supabase client (client.ts, server.ts, admin.ts)
│   ├── stripe/             # Stripe client + server
│   ├── insights/           # AI insight generators
│   ├── email/              # Resend email templates
│   ├── api.ts              # Core API functions (50KB+)
│   ├── types.ts            # Domain TypeScript types
│   ├── hooks.ts            # React Query hooks
│   ├── utils.ts            # cn(), formatPowerScore(), etc.
│   ├── errors.ts           # AppError, isNetworkError()
│   ├── constants.ts        # US_STATES, etc.
│   ├── analytics.ts        # GA4 helpers
│   └── events.ts           # 100+ domain event trackers
├── types/                  # Specialized TypeScript types
├── e2e/                    # Playwright test specs
└── middleware.ts           # Auth guard + session refresh
```

---

## API Routes

### Public
- `GET /api/rankings/national?age=12&gender=M&limit=1000&offset=0`
- `GET /api/rankings/state?state=CA&age=12&gender=M&limit=1000&offset=0`
- `GET /api/teams/search?q=FC%20Dallas`

### Auth
- `GET /api/auth/callback` — OAuth/email link handler
- `POST /api/logout`

### Premium
- `GET /api/watchlist` / `POST /api/watchlist/add` / `POST /api/watchlist/remove`
- `GET /api/insights/[teamId]`
- `POST /api/stripe/checkout` / `POST /api/stripe/portal` / `POST /api/stripe/webhook`

### Admin (requireAdmin)
- `GET|POST /api/mission-control/*`
- `GET|POST|PUT|DELETE /api/tasks/*`
- `POST /api/chat`
- `GET /api/agent-status` / `GET|POST /api/agent-activity`
- `GET /api/team-aliases/[teamId]`
- `GET|POST|DELETE /api/team-merge/*`

### Data Operations (requireAdmin)
- `POST /api/link-opponent` / `POST /api/unlink-opponent`
- `POST /api/create-team`
- `POST /api/scrape-missing-game` / `GET /api/process-missing-games` (CRON_SECRET)

### Public
- `GET /api/announcements` (intentionally public, limit clamped to 50)
- `POST /api/newsletter` (rate limited: 5 req/min per IP)

---

## Key Patterns

### Supabase Client

```typescript
// Browser (singleton) — use in client components
import { createBrowserClient } from '@/lib/supabase/client'
const supabase = createBrowserClient()

// Server — use in API routes and server components
import { createServerSupabase } from '@/lib/supabase/server'
const supabase = await createServerSupabase()
```

### API Route Auth

```typescript
// Admin-only routes (mission control, tasks, agent endpoints)
import { requireAdmin } from '@/lib/supabase/admin';
const auth = await requireAdmin();
if (auth.error) return auth.error;

// Premium routes (watchlist, insights) — also returns authenticated supabase client
import { requirePremium } from '@/lib/api/requirePremium';
const auth = await requirePremium();
if (auth.error) return auth.error;
const { user, supabase } = auth;
```

### React Query

```typescript
// Default config (providers.tsx)
staleTime: 5 * 60 * 1000    // 5 min (rankings update weekly)
gcTime: 10 * 60 * 1000      // 10 min
refetchOnWindowFocus: false
retry: network errors 3x, others 1x (exponential backoff)

// Query keys
['rankings', region, ageGroup, gender]
['team', id]
['team-trajectory', id, periodDays]
['team-games', id, limit]
['rank-history', id]
['team-search']
```

### Custom Hooks

| Hook | Purpose |
|------|---------|
| `useUser()` | Auth state, profile, session, `hasPremiumAccess()` |
| `useRankings()` | Paginated rankings via API routes |
| `useTeamSearch()` | All teams with searchable_name field |
| `usePerformance()` | Performance metrics |

### Component Patterns

```typescript
// Client component (interactive)
'use client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

// shadcn/ui with CVA variants
<Button variant="default" size="sm">Click</Button>

// Memoize expensive components
export default memo(RankingsTable)

// Virtual scrolling for large lists
import { useVirtualizer } from '@tanstack/react-virtual'
```

### Error Handling

```typescript
import { isNetworkError, getErrorMessage } from '@/lib/errors'

// Section-level error boundaries (don't crash entire page)
<SectionErrorBoundary fallback={<ErrorDisplay />}>
  <RankingsTable />
</SectionErrorBoundary>
```

---

## Design System

### Colors (OKLch)
- **Primary**: Forest Green `oklch(0.38 0.1 163)` / `#0B5345`
- **Accent**: Electric Yellow `oklch(0.88 0.18 90)` / `#F4D03F`
- **Background**: Pure White
- **Win**: Green | **Loss**: Red | **Draw**: Yellow

### Fonts
- **Display**: Oswald (athletic headlines)
- **Body**: DM Sans
- **Mono**: JetBrains Mono (stats/data)

### Utility
```typescript
import { cn } from '@/lib/utils'   // clsx + tailwind-merge
cn('base-class', condition && 'conditional-class')
```

---

## Naming Conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Components | PascalCase | `RankingsTable.tsx` |
| Files | kebab-case (except components) | `lib/utils.ts` |
| Functions | camelCase | `formatPowerScore()` |
| Constants | UPPER_SNAKE | `US_STATES` |
| DB columns | snake_case | `team_name` |
| Age groups | Integer | `10`, `12`, `14` (not 'u10') |
| Gender | Single letter | `'M'`, `'F'`, `'B'`, `'G'` |
| States | 2-letter lowercase | `'ca'`, `'ny'` |
| Events | snake_case | `rankings_viewed` |

---

## Middleware (Auth Flow)

1. Redirect non-www → www.pitchrank.io (301)
2. Catch OAuth `?code=` / `?token_hash=` → `/auth/callback`
3. Refresh Supabase session cookie
4. Protected routes (`/watchlist`, `/compare`, `/teams`) → check auth
5. Premium routes → check `user_profiles.plan` = `premium` or `admin`
6. Redirect logged-in users away from `/login`, `/signup`

---

## SEO

- Dynamic OG images: `opengraph-image.tsx`, `twitter-image.tsx`
- Structured data components: `RankingsSchema`, `TeamSchema`, `BlogPostSchema`, `FAQSchema`, `BreadcrumbSchema`
- Dynamic sitemap: `app/sitemap.ts`
- Canonical URLs in page metadata
- `robots.noindex` for auth-gated pages

---

## Performance

- ISR for team pages (revalidate: 3600s)
- Virtual scrolling for rankings table
- `React.memo()` on expensive components
- Optimized imports: recharts, lucide-react, date-fns
- Brand icons (Twitter, Facebook, Instagram, LinkedIn): use `components/ui/brand-icons.tsx` (removed from lucide-react v1)
- Bundle analysis: `ANALYZE=true npm run build`
- Core Web Vitals tracking via `WebVitalsReporter`

---

## Environment Variables

### Public (browser-visible)
```
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
NEXT_PUBLIC_GA_MEASUREMENT_ID
NEXT_PUBLIC_SITE_URL          # defaults to pitchrank.io
NEXT_PUBLIC_STRIPE_PRICE_MONTHLY
NEXT_PUBLIC_STRIPE_PRICE_YEARLY
```

### Server-only
```
SUPABASE_SERVICE_KEY
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
RESEND_API_KEY
```

---

## Testing

### Unit Tests (Vitest)

- Config: `vitest.config.ts` (happy-dom environment, `@` path alias)
- Test location: `__tests__/` dirs next to route files (e.g., `app/api/stripe/webhook/__tests__/route.test.ts`)
- Mock Stripe/Supabase with `vi.mock()` and `vi.hoisted()` for hoisted mock refs
- CI: `frontend-test` job in `.github/workflows/ci.yml`

### E2E Tests (Playwright)

- Base URL: `https://pitchrank.io` (live site)
- Tags: `@smoke` (quick regression), `@api` (no browser)
- Selectors: prefer `data-testid` attributes
- Retry helper for transient network failures
- Projects: chromium (desktop), mobile-chrome (Pixel 5), api (request-only)

---

## Common Pitfalls

1. **`'use client'` only when needed** — Server components are default, only add directive for interactivity
2. **Age groups are integers in frontend** — `12` not `'u12'` or `'U12'`
3. **Gender is single letter** — `'M'`/`'F'` not `'Male'`/`'Female'`
4. **Supabase client singleton** — Never create multiple browser clients (auth state duplication)
5. **API routes over direct Supabase** — Prefer `/api/rankings/*` over direct Supabase in browser for caching
6. **1000-row pagination** — All Supabase queries must paginate
7. **Premium gating** — Check `hasPremiumAccess()` before rendering premium features
8. **ISR revalidation** — Team pages cache for 1 hour; don't expect instant updates
