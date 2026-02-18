# PitchRank.io — SEO Action Plan

**Generated:** 2026-02-17
**Current Score:** 72/100
**Target Score:** 88/100

---

## Critical Priority (Fix Immediately)

These issues block indexing or could cause penalties.

### 1. Investigate & Fix the Indexing Gap
**Impact:** 918 sitemap URLs, only 2 indexed
**Files:** `app/rankings/page.tsx`, `app/rankings/[region]/[ageGroup]/[gender]/page.tsx`
**Action:**
- Check Google Search Console for crawl errors and coverage reports
- Verify the sitemap is accessible at `https://pitchrank.io/sitemap.xml`
- Submit sitemap manually in GSC if not already done
- Check if Googlebot can render the ranking pages (use GSC URL Inspection tool)
- If ranking detail pages render empty to Googlebot, the ISR content may need investigation

### 2. Fix 403 for Automated Fetchers
**Impact:** May block Googlebot, Bingbot, AI crawlers
**Action:**
- Check Vercel/Cloudflare bot protection settings
- Ensure Googlebot, Bingbot, and known crawlers are allowlisted
- Test with `curl -A "Googlebot" https://pitchrank.io` to verify
- Review Vercel Edge Middleware for any bot-blocking logic

### 3. Convert Rankings Index to Server Component
**Impact:** Most important SEO page is invisible to crawlers when client-rendered
**File:** `app/rankings/page.tsx`
**Action:**
- Remove `'use client'` directive
- Move data fetching to server-side (use `fetch` with ISR revalidation)
- Keep interactive filters as separate client components
- Pattern: Server component wrapper → Client component for interactivity
- This alone could unlock indexing of the rankings section

### 4. Add Security Headers
**Impact:** Trust signals, prevents clickjacking/XSS
**File:** `next.config.ts`
**Action:** Add `headers()` export:
```js
async headers() {
  return [{
    source: '/(.*)',
    headers: [
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
      { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
    ],
  }]
}
```

---

## High Priority (Fix Within 1 Week)

Significantly impacts rankings.

### 5. Add `llms.txt` for AI Search Engines
**Impact:** Makes site visible to Perplexity, ChatGPT, Claude
**File:** Create `frontend/public/llms.txt`
**Action:**
```
# PitchRank
> Data-powered youth soccer team rankings and performance analytics

## About
PitchRank provides the most accurate youth soccer rankings in the United States, covering U10-U18 boys and girls teams across all 50 states.

## Key Pages
- [Rankings](https://pitchrank.io/rankings): Browse national and state-level rankings
- [Methodology](https://pitchrank.io/methodology): How we calculate rankings
- [Blog](https://pitchrank.io/blog): Youth soccer insights and analysis

## Data
- Rankings updated daily
- Covers 50 states + national rankings
- Age groups: U10 through U18
- Both boys and girls divisions
```

### 6. Add AI Crawler Directives to robots.txt
**File:** `frontend/public/robots.txt`
**Action:** Add explicit rules:
```
User-agent: GPTBot
Allow: /
Disallow: /api/
Disallow: /auth/

User-agent: ClaudeBot
Allow: /
Disallow: /api/
Disallow: /auth/

User-agent: PerplexityBot
Allow: /
Disallow: /api/
Disallow: /auth/
```

### 7. Add BlogPosting Schema to Blog Posts
**Impact:** Enables rich results for blog content
**File:** Create `frontend/components/BlogPostSchema.tsx`
**Action:**
- Add `BlogPosting` JSON-LD with headline, author, datePublished, dateModified, image, description
- Include publisher (Organization reference)
- Add `articleBody` or `wordCount` for content signals

### 8. Fix OG Images — Use Raster Format
**Impact:** Social sharing previews currently broken (SVG not supported by Facebook/Twitter)
**Files:** `app/layout.tsx`, page-specific metadata
**Action:**
- Generate PNG OG images at 1200×630px
- Use Next.js `opengraph-image.tsx` convention for dynamic OG image generation
- Create branded template with PitchRank logo + page-specific text

### 9. Add BreadcrumbList Schema
**Impact:** Enables breadcrumb rich results in Google
**Action:**
- Create `BreadcrumbSchema.tsx` component
- Implement for ranking pages: Home > Rankings > [Region] > [Age Group] > [Gender]
- Implement for team pages: Home > Rankings > [Team Name]
- Implement for blog: Home > Blog > [Post Title]

---

## Medium Priority (Fix Within 1 Month)

Optimization opportunities.

### 10. Fix Heading Hierarchy
**Files:** Various components
**Action:**
- Ensure H2 exists between H1 and H3 on all pages
- Change footer H3 "PitchRank" to `<p>` or `<span>`
- Add H2 section headers on methodology page
- Validate with browser extension or accessibility checker

### 11. Add Alt Text to All Images
**Files:** Components using `<img>` or `<Image>`
**Action:**
- Audit all image elements across components
- Add descriptive alt text (not just "image" or "logo")
- For decorative images, use `alt=""` with `role="presentation"`
- Priority: team logos, blog post images, infographic images

### 12. Fix Infographics Page
**File:** `app/infographics/page.tsx`
**Action:**
- Add `generateMetadata()` export with title, description, OG tags
- Consider converting from `'use client'` to server component if possible
- Or add `noindex` if the page is not intended for search

### 13. Implement Core Web Vitals Monitoring
**Action:**
- Add `reportWebVitals` in `app/layout.tsx` or create `instrumentation.ts`
- Send CWV data to analytics (LCP, INP, CLS, FCP, TTFB)
- Set up alerts for regressions
- Target: LCP < 2.5s, INP < 200ms, CLS < 0.1

### 14. Add Preload Hints for Critical Resources
**File:** `app/layout.tsx`
**Action:**
- Preload critical fonts
- Preload hero image (if any)
- Use `<link rel="preconnect">` for Supabase and analytics domains
- Consider `<link rel="dns-prefetch">` for third-party scripts

### 15. Expand Internal Linking
**Action:**
- Add "Related Rankings" links on team pages (e.g., same age group, same state)
- Add "Related Posts" section at bottom of blog posts
- Add contextual links from blog posts to relevant ranking pages
- Create a hub page linking to all state rankings (improves crawl depth)

---

## Low Priority (Backlog)

Nice to have improvements.

### 16. Create State-Level Landing Pages
**Action:**
- Build `/rankings/[state]` hub pages (e.g., "/rankings/texas")
- Include all age groups and genders for that state
- Add state-specific content (top clubs, trends, tournament info)
- Target long-tail keywords: "Texas youth soccer rankings", "California U14 boys soccer rankings"

### 17. Add FAQ Schema to More Pages
**Action:**
- Add page-specific FAQs to ranking pages ("How are U14 boys ranked?")
- Add FAQs to state landing pages ("What leagues are tracked in Texas?")
- Each FAQ should target real search queries

### 18. Implement Open Search Description
**File:** Create `frontend/public/opensearch.xml`
**Action:**
- Enable browser search bar integration
- Point to `/rankings?q={searchTerms}`

### 19. Build Backlink Strategy
**Action:**
- Get listed on youth soccer resource roundup posts
- Partner with soccer blogs for guest posts / data citations
- Submit to sports analytics directories
- Create shareable, embeddable ranking widgets for club websites

### 20. Consider AMP or Partial Hydration
**Action:**
- Evaluate if ranking pages benefit from Partial Prerendering (PPR) in Next.js 15
- Would allow static shell with streamed dynamic content
- Best of both worlds: fast FCP + fresh data

---

## Score Improvement Projection

| Action | Category Impact | Points Gained |
|--------|----------------|---------------|
| Fix indexing gap (#1-3) | Technical +20 | +5.0 |
| Security headers (#4) | Technical +10 | +2.5 |
| llms.txt + AI directives (#5-6) | AI Readiness +50 | +2.5 |
| BlogPosting schema (#7) | Schema +5 | +0.5 |
| Fix OG images (#8) | Images +15 | +0.75 |
| BreadcrumbList schema (#9) | Schema +5 | +0.5 |
| Alt text (#11) | Images +30 | +1.5 |
| CWV monitoring (#13) | Performance +20 | +2.0 |
| Preload hints (#14) | Performance +10 | +1.0 |
| **Total potential gain** | | **+16.25** |
| **Projected score** | | **≈ 88/100** |

---

## Quick Reference: Priority Matrix

```
                    HIGH IMPACT
                        │
         ┌──────────────┼──────────────┐
         │  #1 Indexing  │  #3 SSR      │
   EASY  │  #5 llms.txt │  Rankings    │  HARD
         │  #6 robots   │  #2 403 Fix  │
         │  #4 Headers  │              │
         ├──────────────┼──────────────┤
         │  #8 OG imgs  │  #16 State   │
         │  #11 Alt txt │  Pages       │
         │  #12 Infog.  │  #19 Links   │
         │  #7 Blog LD  │  #20 PPR     │
         └──────────────┼──────────────┘
                        │
                    LOW IMPACT
```

Focus on the top-left quadrant first: easy wins with high impact.
