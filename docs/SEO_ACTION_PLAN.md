# SEO Action Plan for PitchRank 📈

**Created:** Feb 17, 2026  
**Status:** Active  
**Owner:** Socialy 📱 + Codey 🤖

---

## 📊 Current State (30-Day GSC Analysis)

### What's Working
- ✅ **#2 for "pitchrank"** (branded)
- ✅ **#4 for "louisiana youth soccer rankings"** (non-branded!)
- ✅ **Getting impressions on state ranking pages** (11 states showing)
- ✅ **Sitemap is good** (consistent www, all ranking pages included)

### Critical Issues
- 🚨 **www vs non-www split** - `pitchrank.io` AND `www.pitchrank.io` both showing in GSC
  - Homepage split: 4 clicks vs 1 click
  - Ranking pages mixed between both versions
  - **This is diluting our authority!**
- 🚨 **Zero-click impressions** - 17 clicks total, but appearing for dozens of queries
- 🚨 **Low CTR on ranking pages** - Showing up but not getting clicks (need better meta)
- 🚨 **Weak positions** - Most state queries ranking 20-90 (page 3-9)

### Quick Wins
| Query | Position | Opportunity |
|-------|----------|-------------|
| louisiana youth soccer rankings | #4 | Push to #1-3 with content |
| louisiana soccer rankings | #24 | Optimize existing page |
| az soccer rankings | #17 | Add AZ-specific content |
| 2013 boys soccer rankings | #10 | Good! Need meta optimization |

---

## 🎯 PHASE 1: Quick Wins (This Week)

### 1A. Canonical URL Fix (CRITICAL - Day 1)
**Problem:** Both `pitchrank.io` and `www.pitchrank.io` indexed  
**Solution:** Implement 301 redirects + canonical tags

**Codey's Task:**
```javascript
// In next.config.js or middleware
async redirects() {
  return [
    {
      source: '/:path*',
      has: [{ type: 'host', value: 'pitchrank.io' }],
      destination: 'https://www.pitchrank.io/:path*',
      permanent: true,
    },
  ]
}
```

**Add to all pages:**
```html
<link rel="canonical" href="https://www.pitchrank.io/[current-path]" />
```

**Then:** Submit updated sitemap to GSC and request re-indexing of key pages

---

### 1B. Meta Description Optimization (Day 2-3)

**Current Problem:** Generic or missing meta descriptions = low CTR

**Template for State Ranking Pages:**
```
[State] Youth Soccer Rankings | Updated [Frequency] | PitchRank

Official [State] youth soccer team rankings for boys and girls (U10-U18). See how your team ranks against [#] teams statewide. Updated [weekly/daily] with live game results.
```

**Example for Louisiana:**
```
Louisiana Youth Soccer Rankings | Updated Weekly | PitchRank

Official Louisiana youth soccer team rankings for boys and girls (U10-U18). See how your team ranks against 247 teams statewide. Updated weekly with live game results.
```

**Codey's Implementation:**
- Add dynamic meta descriptions to `/rankings/[state]/[age]/[gender]` pages
- Include team count dynamically
- Add "Updated [date]" for freshness signal

---

### 1C. Title Tag Optimization (Day 3-4)

**Current Format:** Likely generic  
**New Format:** `[State] U[Age] [Gender] Soccer Rankings | PitchRank`

**Examples:**
- `Louisiana U15 Boys Soccer Rankings | PitchRank`
- `Arizona U13 Girls Soccer Rankings | PitchRank`

**Homepage Title:**
- Current: Unknown
- **New:** `Youth Soccer Rankings | Live Team Rankings by State | PitchRank`

---

## 🎯 PHASE 2: Content Strategy (Next 2 Weeks)

### 2A. Priority State Landing Pages

**Target States (highest search volume):**
1. **California** - Currently #88 (huge opportunity)
2. **Florida** - Currently #49
3. **Texas** - Not yet appearing
4. **New York** - Not yet appearing
5. **New Jersey** - Good impressions already
6. **Arizona** - Currently #17 (push higher)

**Create:** `/rankings/[state]` overview pages (not just age/gender breakdowns)

**Template Structure:**
```markdown
# [State] Youth Soccer Rankings

## Overview
[State] has [X] ranked teams across [Y] age groups and both genders.

## Top Teams
- #1 U15 Boys: [Team Name]
- #1 U13 Girls: [Team Name]
[...]

## How Rankings Work
Brief explanation + link to methodology

## Browse by Age & Gender
[Grid of links to age/gender pages]
```

**SEO Benefits:**
- Captures broad "[state] soccer rankings" queries
- Internal linking hub to specific age/gender pages
- More content = better chances to rank

---

### 2B. Blog Content (SEO-Focused)

**Article Ideas (target long-tail keywords):**

1. **"Best Youth Soccer Teams in [State] - 2026 Rankings"**
   - Target: "[state] youth soccer teams"
   - Include top 10 teams per age group
   - Link to full ranking pages

2. **"How Youth Soccer Rankings Work: Understanding the Algorithm"**
   - Target: "youth soccer rankings explained"
   - Great for backlinks (coaches want to understand)

3. **"U13 vs U15 Soccer: Key Differences in Rankings"**
   - Target: age-specific searches
   - Educational content

4. **"State-by-State Guide to Youth Soccer Rankings"**
   - Target: "youth soccer rankings by state"
   - Mega-guide with links to all state pages

**Publishing Schedule:**
- Week 1: California + Florida posts
- Week 2: Texas + Arizona posts
- Week 3: New York + New Jersey posts
- Week 4: Algorithm explanation post

---

### 2C. Age Group Landing Pages

**Create:** `/rankings/u13`, `/rankings/u15`, etc. (national overviews)

**Why:** Capturing queries like "2013 boys soccer rankings" (currently #10!)

**Structure:**
```
# U13 Soccer Rankings - 2026

## National Top 25 U13 Boys Teams
[Table with team, state, rating]

## National Top 25 U13 Girls Teams
[Table with team, state, rating]

## Browse U13 Rankings by State
[50 state links]
```

---

## 🎯 PHASE 3: Technical SEO (Weeks 3-4)

### 3A. Schema Markup (Structured Data)

**Implement on ranking pages:**
```json
{
  "@context": "https://schema.org",
  "@type": "SportsTeam",
  "name": "[Team Name]",
  "sport": "Soccer",
  "memberOf": {
    "@type": "SportsOrganization",
    "name": "[Club Name]"
  },
  "location": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "addressRegion": "[State]"
    }
  }
}
```

**Also add:** BreadcrumbList schema for navigation

**Why:** Rich snippets in search results = higher CTR

---

### 3B. Internal Linking Structure

**Current Issue:** Likely weak internal linking

**Implement:**
1. **Breadcrumbs on all ranking pages:**
   ```
   Home > Rankings > [State] > U13 > Boys
   ```

2. **Related Rankings sidebar:**
   ```
   Related Rankings:
   - [State] U12 Boys
   - [State] U14 Boys
   - National U13 Boys
   ```

3. **"Top Movers" widget** (link to teams with biggest ranking changes)

4. **Footer links** to all state overview pages

**Goal:** Keep users on site longer, pass PageRank internally

---

### 3C. Page Speed Optimization

**Action Items:**
1. Run Lighthouse audit on key pages
2. Optimize images (WebP format, lazy loading)
3. Minimize JavaScript bundles
4. Implement proper caching headers
5. Consider CDN for static assets

**Target:** Core Web Vitals in "Good" range (ranking factor!)

---

## 🎯 PHASE 4: Backlink Strategy (Ongoing)

### 4A. Youth Soccer Directories

**Submit to:**
1. **YouthSoccerRankings.us** (if exists - check competitors)
2. **US Youth Soccer state associations** (50 submissions)
3. **MaxPreps** (see if they'll link to us)
4. **Local sports news sites** (per state)

**Template Pitch:**
```
Hi [Name],

I'm reaching out from PitchRank.io, a live youth soccer ranking platform covering [State]. We provide real-time rankings for U10-U18 teams based on game results.

Would you be open to adding us to your resources page? We'd be happy to link back to [your site] as well.

Our [State] rankings: https://www.pitchrank.io/rankings/[state]

Best,
[Your Name]
```

---

### 4B. Club Partnerships

**Target:** Top 100 clubs in our database

**Offer:**
1. **Free embeddable widget** showing their team's ranking
2. **Direct links** to their team pages
3. **Featured club status** (if they link back)

**Code for clubs to embed:**
```html
<iframe src="https://www.pitchrank.io/embed/club/[club-id]" width="300" height="400"></iframe>
```

**Benefit:** Natural backlinks from club websites

---

### 4C. Content Outreach

**Once blog posts are live:**
1. Share on Reddit r/bootroom, r/SoccerCoaching
2. Email to youth soccer podcasts (guest appearance?)
3. Submit to Hacker News (the algorithm post could do well)
4. Youth soccer Facebook groups (50k+ members in many states)

---

## 🎯 PHASE 5: Local SEO (Month 2)

### 5A. Google Business Profile

**Create listing:**
- Category: "Sports Website" or "Sports Information Service"
- Include link to site
- Post weekly updates ("New rankings posted!")

---

### 5B. State-Specific Content

**Per priority state, create:**
1. **"Top 10 Soccer Clubs in [State]"** blog post
2. **"[State] Soccer Tournament Calendar 2026"**
3. **"Best Cities for Youth Soccer in [State]"**

**Link to:** Relevant team pages, club pages

---

## 📋 Codey's Priority Implementation List

### Week 1 (CRITICAL)
1. ✅ Canonical URL fix (301 redirects from non-www)
2. ✅ Add canonical tags to all pages
3. ✅ Dynamic meta descriptions for ranking pages
4. ✅ Title tag optimization
5. ✅ Submit updated sitemap to GSC

### Week 2
6. ✅ Create state overview pages (CA, FL, TX, AZ, NY, NJ)
7. ✅ Add breadcrumb navigation
8. ✅ Implement Schema.org markup for teams

### Week 3
9. ✅ Create age group landing pages (U10-U18)
10. ✅ Build "Related Rankings" sidebar component
11. ✅ Write 2 blog posts (California + Florida focus)

### Week 4
12. ✅ Page speed audit + optimizations
13. ✅ Internal linking improvements
14. ✅ Embeddable widget for clubs

---

## 📊 Success Metrics (Track Monthly)

| Metric | Baseline (30d) | 1-Month Goal | 3-Month Goal |
|--------|----------------|--------------|--------------|
| **Total Clicks** | 17 | 100+ | 500+ |
| **Total Impressions** | ~100 | 1,000+ | 10,000+ |
| **Avg Position** | 35-40 | 25 | 15 |
| **Indexed Pages** | ~200? | 300+ | 500+ |
| **Backlinks** | Unknown | 10+ | 50+ |
| **Organic Traffic** | ~50/mo | 300/mo | 1,500/mo |

---

## 🚀 Quick Command Reference

### Check GSC
```bash
cd /Projects/PitchRank && python3 scripts/gsc_report.py --days 7
```

### Check Sitemap
```bash
curl -sL https://www.pitchrank.io/sitemap.xml | grep -c "<loc>"
```

### Submit to Google
1. GSC → Sitemaps → Submit `https://www.pitchrank.io/sitemap.xml`
2. Request indexing for priority pages

---

## 📝 Notes for Socialy

### Weekly Tasks
- Run GSC report every Monday
- Check Google Search Console for crawl errors
- Monitor new queries appearing in GSC
- Update this doc with progress

### Monthly Tasks
- Full competitive analysis (who's ranking for our keywords?)
- Backlink audit (who's linking to competitors?)
- Content gap analysis
- Review and update strategy based on results

---

## 🎯 The Big Picture

**Goal:** Own the youth soccer rankings space in Google

**Strategy:**
1. **Technical foundation** (canonicalization, meta, schema) → Week 1
2. **Content expansion** (state pages, blog posts) → Weeks 2-4
3. **Link building** (directories, clubs, partnerships) → Ongoing
4. **Optimization** (based on GSC data) → Continuous

**Why it'll work:**
- We have unique data (live rankings)
- Low competition (niche space)
- Clear user intent (parents/coaches want rankings)
- Technical SEO is fixable quickly
- Content strategy targets long-tail keywords

---

**Last Updated:** Feb 17, 2026  
**Next Review:** Feb 24, 2026
