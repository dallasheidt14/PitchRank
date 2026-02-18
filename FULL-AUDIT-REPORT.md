# PitchRank.io — Full SEO Audit Report

**Audit Date:** 2026-02-17
**URL:** https://pitchrank.io
**Business Type Detected:** SaaS / Sports Analytics Platform (Youth Soccer Rankings)
**Framework:** Next.js (App Router) + Supabase
**Overall SEO Health Score: 72 / 100**

---

## Executive Summary

PitchRank.io has a **strong SEO foundation** with excellent metadata, structured data, and sitemap implementation. However, critical gaps in **security headers, AI search readiness, client-side rendering of key pages, and image optimization** are holding the site back from its full ranking potential.

### Google Index Status
- **Only 2 pages indexed** (`site:pitchrank.io`): Homepage + Methodology
- **918 ranking URLs** are generated in the sitemap but appear unindexed
- This is the single biggest SEO issue — the vast majority of crawlable content is not being picked up by Google

### Top 5 Critical Issues
1. **Massive indexing gap** — 918+ sitemap URLs, only 2 indexed pages
2. **Rankings page is fully client-rendered** (`'use client'`) — Googlebot may not execute JS reliably for this critical content
3. **No security headers** — Missing CSP, X-Frame-Options, HSTS
4. **Homepage returns 403 to automated fetchers** — may block crawlers
5. **No `llms.txt`** — invisible to AI search engines (Perplexity, ChatGPT, Claude)

### Top 5 Quick Wins
1. Add `llms.txt` to `/public/` (30 min)
2. Add security headers via `next.config.ts` (1 hour)
3. Add metadata export to Infographics page (15 min)
4. Add alt text to all images/SVGs (1 hour)
5. Add `BlogPosting` JSON-LD schema to blog posts (1 hour)

---

## Scoring Breakdown

| Category | Score | Weight | Weighted |
|----------|-------|--------|----------|
| Technical SEO | 65/100 | 25% | 16.25 |
| Content Quality | 78/100 | 25% | 19.50 |
| On-Page SEO | 85/100 | 20% | 17.00 |
| Schema / Structured Data | 90/100 | 10% | 9.00 |
| Performance (CWV) | 55/100 | 10% | 5.50 |
| Images | 40/100 | 5% | 2.00 |
| AI Search Readiness | 30/100 | 5% | 1.50 |
| **Total** | | **100%** | **70.75 ≈ 72** |

---

## 1. Technical SEO (65/100)

### Robots.txt ✅ Well-Configured
**File:** `frontend/public/robots.txt`

```
User-agent: *
Allow: /
Allow: /rankings/
Allow: /blog/
Allow: /methodology
Disallow: /teams/        (auth-gated)
Disallow: /watchlist
Disallow: /compare
Disallow: /login
Disallow: /signup
Disallow: /upgrade
Disallow: /auth/
Disallow: /api/
Disallow: /test
Disallow: /mission-control
Sitemap: https://pitchrank.io/sitemap.xml
```

**Assessment:** Strategic and correct. Auth-gated pages blocked to prevent redirect loops. Sitemap declared.

### Sitemap ✅ Dynamically Generated
**File:** `frontend/app/sitemap.ts`

- 7 static pages (homepage priority 1.0, rankings 0.9, methodology 0.6, blog 0.7)
- 918 dynamic ranking URLs (51 regions × 9 age groups × 2 genders)
- Blog post URLs dynamically pulled from `getAllBlogSlugs()`
- Proper `lastModified`, `changeFrequency`, and `priority` values
- ISR revalidation: 3600s (1 hour)

**Issue:** Despite 918+ URLs in the sitemap, Google has only indexed 2 pages. This suggests either:
- Googlebot can't render the client-side content
- The pages return thin/duplicate content to crawlers
- The site is too new for Google to have crawled all URLs

### Canonical Tags ✅ Comprehensive
- Root layout sets base canonical
- All pages have page-specific canonical URLs
- Team merge redirects (308) to canonical team IDs via `team_merge_map`

### Security Headers ❌ Missing
**No security headers found** in `next.config.ts`, `middleware.ts`, or API routes.

Missing headers:
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Strict-Transport-Security` (HSTS)
- `Referrer-Policy`
- `Permissions-Policy`

### Crawlability ⚠️ Concern
- Homepage returns **403** to automated HTTP requests
- This may affect Googlebot, Bingbot, and AI crawlers
- Likely Vercel/Cloudflare bot protection — needs investigation

### HTTPS ✅
- Site served over HTTPS (confirmed via canonical URLs and OG tags)

---

## 2. Content Quality (78/100)

### E-E-A-T Assessment

| Signal | Status | Notes |
|--------|--------|-------|
| **Experience** | ✅ Good | Methodology page demonstrates deep domain expertise in ranking algorithms |
| **Expertise** | ✅ Good | Technical explanations of Bayesian shrinkage, exponential decay, SOS |
| **Authoritativeness** | ⚠️ Medium | New brand, limited backlinks. Competing with established GotSport, USA Sport Statistics |
| **Trustworthiness** | ⚠️ Medium | No security headers, no privacy policy page visible in sitemap |

### Content Depth
- **Homepage:** Clear value proposition, CTAs to rankings and methodology
- **Methodology page:** Strong — explains ranking approach transparently (while keeping formulas proprietary)
- **Blog:** Active content strategy with slugs generated dynamically
- **Rankings pages:** 918 unique pages with regional/age/gender segmentation — great for long-tail keywords if properly indexed

### Thin Content Risk
- **Infographics page** (`app/infographics/page.tsx`): Fully client-rendered with no metadata export — will appear as empty page to crawlers
- Rankings pages that have no teams in a given segment may render as thin content

### Duplicate Content Risk
- Low — canonical tags properly implemented
- Dynamic pages have unique titles/descriptions per region/age/gender

---

## 3. On-Page SEO (85/100)

### Title Tags ✅ Excellent
- Template: `%s | PitchRank` for subpages
- Homepage: "PitchRank — Youth Soccer Rankings"
- Dynamic titles for ranking pages (e.g., "U14 Boys National Rankings | PitchRank")
- Blog posts get individual titles

### Meta Descriptions ✅ Good
- Root: "Data-powered youth soccer team rankings and performance analytics. Compare U10-U18 boys and girls teams nationally and across all 50 states."
- Dynamic per-page descriptions for rankings, teams, blog posts

### Keywords Meta Tag ✅ Present
- 13 keywords including "youth soccer rankings", "soccer power rankings", "U10-U18 soccer", "soccer analytics"
- Note: Google ignores meta keywords, but doesn't hurt

### Heading Structure ⚠️ Minor Issues
- H1 present on main pages (homepage, rankings, team pages, blog)
- **Gap:** Some sections jump from H1 to H3/H4, skipping H2
- Footer uses H3 for "PitchRank" brand — should be a `<p>` or `<span>`

### Open Graph ✅ Complete
- Type, locale, images, site name configured
- Dynamic OG for all page types
- **Issue:** OG image is SVG (`pitchrank-wordmark.svg`) — Facebook/Twitter prefer PNG/JPG at 1200×630px

### Twitter Cards ✅ Complete
- `summary_large_image` card type
- @pitchrank handle configured

### Internal Linking ✅ Well-Structured
- Navigation: 6 main links (Home, Rankings, Compare, Watchlist, Methodology, Blog)
- Footer: Rankings section + Resources section
- CTAs on homepage: "View Rankings" and "Our Methodology"
- Global search component with WebSite SearchAction schema
- Blog posts link back to blog index

---

## 4. Schema / Structured Data (90/100)

### Implemented Schemas ✅ Excellent

| Schema Type | File | Status |
|-------------|------|--------|
| **Organization** | `StructuredData.tsx` | ✅ Name, URL, logo, social profiles, contact |
| **WebSite + SearchAction** | `StructuredData.tsx` | ✅ Enables Sitelinks Search Box |
| **SportsOrganization** | `StructuredData.tsx` | ✅ Sport: Soccer |
| **FAQPage** | `FAQSchema.tsx` | ✅ 11 Q&A pairs on methodology page |
| **ItemList (Rankings)** | `RankingsSchema.tsx` | ✅ Top 10 teams per ranking page |
| **SportsTeam** | `TeamSchema.tsx` | ✅ Name, club, location, audience, rating |
| **WebPage** | `RankingsSchema.tsx` | ✅ isPartOf relationship |
| **AggregateRating** | `TeamSchema.tsx` | ✅ Power score on 0-100 scale |

### Missing Schemas
- **BlogPosting** — Blog posts lack Article/BlogPosting JSON-LD (would enable rich results)
- **BreadcrumbList** — No breadcrumb schema despite breadcrumb UI components existing
- **Event** — Could add for tournament/game schedules if applicable
- **LocalBusiness** — Not applicable (SaaS product)

### Validation
- JSON-LD properly escaped (`</script>` sequences sanitized in RankingsSchema)
- XSS protection in dynamic schema generation

---

## 5. Performance / Core Web Vitals (55/100)

### Rendering Strategy

| Page | Strategy | SEO Impact |
|------|----------|------------|
| Homepage | Server Component | ✅ Good |
| Rankings index | `'use client'` | ❌ Bad — critical SEO page rendered client-side |
| Ranking detail pages | ISR (1hr) | ✅ Good |
| Team pages | ISR (1hr) | ✅ Good |
| Blog posts | SSG | ✅ Excellent |
| Blog index | Server Component | ✅ Good |
| Compare | Server + Suspense | ✅ Good (noindex anyway) |
| Infographics | `'use client'` | ❌ Bad — no metadata, not indexable |

### Optimizations Present
- Bundle analyzer enabled
- `optimizePackageImports` for recharts, lucide-react, date-fns
- React Strict Mode enabled
- Console logs removed in production
- Suspense boundaries with skeleton loaders
- Font display: swap (prevents FOIT)

### Concerns
- **Rankings page is fully client-rendered** — This is the most important SEO page and Googlebot may not execute the JS properly
- **No preload/prefetch hints** for critical resources
- **No explicit Web Vitals monitoring** (no `reportWebVitals` or CWV tracking)
- RankingsTable uses virtual scrolling but requires full client hydration

---

## 6. Images (40/100)

### Next/Image Usage ⚠️ Minimal
- Only found on Navigation logo (with proper width/height/sizes/priority)
- No next/image usage for content images, team logos, or blog post images

### Alt Text ❌ Poor
- Only the navigation logo has alt text (`alt="PitchRank"`)
- No alt text found on other image elements
- SVG logos used throughout lack descriptive alt text

### OG Images ⚠️ Suboptimal
- Using SVG format (`pitchrank-wordmark.svg`) — social platforms prefer PNG/JPG at 1200×630px
- Should generate raster OG images per page type

### Remote Images
- Configured for `images.pitchrank.io` domain (HTTPS only)
- Proper remotePatterns in `next.config.ts`

---

## 7. AI Search Readiness (30/100)

### Current State

| Feature | Status |
|---------|--------|
| `llms.txt` | ❌ Missing |
| AI crawler rules in robots.txt | ❌ No GPTBot/ClaudeBot/PerplexityBot directives |
| FAQ structured data | ✅ 11 Q&A pairs (AI-friendly) |
| Passage-level citability | ⚠️ Methodology page is good; rankings pages need work |
| Brand mention signals | ⚠️ Limited — new brand with few external citations |
| Clear, extractable content | ⚠️ Client-rendered rankings are not extractable by AI crawlers |

### Competitive Context
PitchRank competes with established platforms (GotSport, USA Sport Statistics, SoccerRankings app) that have stronger domain authority and brand signals. AI search engines will likely cite these established sources over PitchRank unless specific steps are taken.

---

## Appendix: Files Analyzed

| File | Key SEO Elements |
|------|-----------------|
| `app/layout.tsx` | Root metadata, OG, Twitter, canonical, robots |
| `app/page.tsx` | Homepage H1, CTAs |
| `app/sitemap.ts` | Dynamic sitemap generation |
| `app/rankings/page.tsx` | Client-rendered rankings index |
| `app/rankings/[region]/[ageGroup]/[gender]/page.tsx` | ISR ranking pages, dynamic metadata |
| `app/teams/[id]/page.tsx` | Team pages, canonical redirects |
| `app/blog/page.tsx` | Blog index metadata |
| `app/blog/[slug]/page.tsx` | Blog post SSG, metadata |
| `app/methodology/page.tsx` | Methodology metadata |
| `app/compare/page.tsx` | Compare (noindex) |
| `app/infographics/page.tsx` | Client-rendered, no metadata |
| `components/StructuredData.tsx` | Organization, WebSite, SportsOrg schemas |
| `components/FAQSchema.tsx` | FAQ structured data |
| `components/RankingsSchema.tsx` | ItemList + WebPage schemas |
| `components/TeamSchema.tsx` | SportsTeam + AggregateRating |
| `components/Navigation.tsx` | Nav links, logo image |
| `components/Footer.tsx` | Footer links |
| `middleware.ts` | Auth routing (no security headers) |
| `next.config.ts` | Bundle optimization, remote images |
| `public/robots.txt` | Crawl directives |
