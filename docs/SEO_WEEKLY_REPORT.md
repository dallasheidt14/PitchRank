# SEO Weekly Report

*Updated by Socialy every Wednesday*

---

## Latest Report: Feb 18, 2026

### Performance (vs Feb 17)
- **Clicks:** ~10 (-41% 📉)
- **Impressions:** ~63 (-37% 📉)
- **Indexed Pages:** Still 2/918 (CRITICAL GAP)
- **Avg Position:** Mixed (1.5 to 70)

### 🔍 Week-over-Week Analysis

**Traffic Decline:**
- Clicks dropped from ~17 to ~10 (41% down)
- Impressions dropped from ~100 to ~63 (37% down)
- **Possible causes:** Algorithm update, seasonal variance, or indexing issues

**Positive Signals:**
- ✅ Ranking pages ARE being indexed and clicked (NC U11 Female: 3 clicks)
- ✅ Security headers implemented (HSTS, Permissions-Policy, Referrer-Policy, X-Content-Type-Options)
- ✅ No 403 errors for Googlebot
- ✅ Position #4 for "louisiana youth soccer rankings" (high-value query!)

**Concerning Signals:**
- 🔴 Still only 2 pages showing in `site:` search
- 🔴 Traffic declining week-over-week
- 🟡 Strong positions (e.g., #4) getting zero clicks (CTR problem)

### 📊 Top Opportunities

**1. CTR Optimization (HIGH IMPACT)**
Queries with good position but 0 clicks:
- **"louisiana youth soccer rankings"** — Position #4, 1 impression, 0 clicks
  - Action needed: Optimize meta description to drive clicks
- **"az soccer rankings"** — Position #17, 2 impressions, 0 clicks
  - Action needed: Push closer to top 3 with on-page optimization

**2. Security Headers (MEDIUM PRIORITY)**
Still missing:
- X-Frame-Options: DENY
- Content-Security-Policy (full CSP implementation)

**3. Rankings Index SSR (HIGHEST IMPACT - BLOCKED)**
Individual ranking pages ARE appearing in search, suggesting client-side rendering may not be the only issue. However, the main `/rankings` index is likely still invisible to crawlers.

### 🚀 Actions Taken This Week
- ✅ GSC 7-day analysis completed
- ✅ Technical health checks (headers, robots.txt, Googlebot access)
- ✅ Identified CTR optimization opportunities
- ✅ Documented traffic decline for monitoring

### 🔧 Actions Needed (Cannot Execute from Cron Context)
- [ ] Add X-Frame-Options and CSP headers (needs Codey)
- [ ] Optimize meta descriptions for position #4-10 queries (needs Codey)
- [ ] Monitor GSC for indexing progress manually
- [ ] Create blog content for long-tail keywords

### 📈 Query Performance

**Top Queries (Last 7 Days):**
1. **pitchrank** — 2 clicks, 2 impressions, Position 1.5 (brand search)
2. **2013 boys soccer rankings** — Position 10
3. **az soccer rankings** — Position 17
4. **louisiana youth soccer rankings** — Position 4 (OPPORTUNITY!)
5. **louisiana soccer rankings** — Position 32.5

**Top Landing Pages:**
1. `/rankings/nc/u11/female` — 3 clicks (best performer)
2. Homepage — 2 clicks
3. Various state/age/gender ranking pages — 1 click each

### 🎯 Priority Matrix

| Priority | Action | Impact | Effort | Owner |
|----------|--------|--------|--------|-------|
| 🔴 HIGH | Monitor traffic decline | High | Low | Socialy |
| 🔴 HIGH | Meta description optimization | High | Medium | Codey |
| 🟡 MEDIUM | Add missing security headers | Medium | Low | Codey |
| 🟡 MEDIUM | Create blog content for keywords | High | High | D H / Movy |
| 🟢 LOW | Continue monitoring indexing | Medium | Low | Socialy |

### 📝 Notes for D H
- Traffic decline is concerning but could be normal variance (need 2-3 more weeks to confirm trend)
- The fact that individual ranking pages ARE getting clicks suggests indexing is happening, just slowly
- Position #4 for "louisiana youth soccer rankings" is HUGE — we're ranking well, just need better CTR
- Should consider manual GSC check to see if there are crawl errors or coverage issues we're missing

### Next Check
**Wednesday, Feb 25, 2026 @ 9am MST**

---

## Historical Data

### Feb 17, 2026
- Clicks: ~17/week
- Impressions: ~100/week
- Major schema improvements deployed

### Feb 18, 2026
- Clicks: ~10 (↓41%)
- Impressions: ~63 (↓37%)
- Security headers validated, CTR opportunities identified
