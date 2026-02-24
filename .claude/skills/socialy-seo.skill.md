# Socialy SEO Skill

Proactive SEO monitoring and optimization for PitchRank.

## Monitoring Schedule

| Check | Frequency | Purpose |
|-------|-----------|---------|
| GSC Quick Check | Daily 7:30am | Impressions, clicks, errors |
| Full SEO Audit | Weekly Wed 9am | Technical, content, opportunities |

## Daily Checks

1. **GSC Health** — New errors? Drops? Quick wins?
2. **Only alert if something changed** — Don't spam

## Weekly Checks (Wednesday)

### Technical SEO
- Core Web Vitals (Lighthouse)
- Sitemap validity
- Robots.txt
- Security headers
- Mobile usability
- Index coverage in GSC

### Content Analysis
- Thin content pages
- Missing meta descriptions
- Duplicate titles
- Schema opportunities
- State pages without content

### Opportunities (ACT ON THESE!)
- Pages ranking #4-10 → push to top 3 (spawn Codey for meta fixes)
- High impressions, low CTR → fix meta descriptions
- New queries appearing → create content targeting them
- Content gaps by state → note for blog posts
- Competitor analysis → what are they ranking for?

## Key Queries to Track

**High Priority:**
- "[state] youth soccer rankings" (CA, FL, TX, AZ, NY, NJ)
- "[state] club soccer rankings"
- "youth soccer rankings [year]"

**Medium Priority:**
- "U[age] soccer rankings [state]"
- "[birth year] boys/girls soccer rankings"
- "best youth soccer teams [state]"

**Long Tail (Blog Opportunities):**
- "how youth soccer rankings work"
- "youth soccer ranking algorithm"
- "[state] soccer tournament rankings"

## Autonomous Actions

✅ **DO immediately:**
- GSC reports + trend analysis
- Spawn Codey for technical fixes
- Spawn Codey for new content pages
- Update SEO_ACTION_PLAN.md with progress
- **SPAWN BLOGY for strategic blog posts** (see below)
- Track ranking improvements
- Alert D H about opportunities

✅ **Can do without asking:**
- Meta description improvements
- Title tag fixes
- Schema additions
- Internal linking suggestions
- Alt text additions

## 🔥 SPAWN BLOGY FOR STRATEGIC OPPORTUNITIES

When you find keyword opportunities during your weekly check, **spawn Blogy immediately**.

### Trigger Conditions (Spawn Blogy If):
1. **Ranking #4-20 for high-value keyword** — Blog post can push us higher
2. **High impressions, no content** — We're showing up but have no dedicated page
3. **Competitor content gap** — They rank, we don't, but we have better data
4. **State with >1000 teams but no blog post** — Easy win

### How to Spawn Blogy:
```
Use sessions_spawn with task like:

"Write a blog post targeting '[keyword]'. 

Research first:
- Run: python3 scripts/blog_research.py --state [XX]
- Search competitors: web_search '[keyword]'
- Check what's ranking and find gaps

Target keyword: [keyword]
GSC position: [current position or 'not ranking']
Our data advantage: [e.g., '15,693 CA teams tracked']

Write the post, add to blog-posts.tsx, commit and push."
```

### Priority Keywords for Blog Posts:
| Keyword | Priority | Why |
|---------|----------|-----|
| california youth soccer rankings | HIGH | 15K teams, huge market |
| texas youth soccer rankings | HIGH | 9K teams |
| florida youth soccer rankings | HIGH | 5K teams |
| how youth soccer rankings work | MEDIUM | Explainer, builds trust |
| youth soccer rankings explained | MEDIUM | Target position #52 |

### After Spawning Blogy:
1. Log the spawn in `docs/BLOG_CONTENT_PLAN.md`
2. Update `docs/SEO_WEEKLY_REPORT.md` with action taken
3. Note expected publish date

❓ **Ask D H first:**
- Major site structure changes
- External link building outreach
- Paid SEO tools

## Content Calendar

Track planned content in `docs/CONTENT_CALENDAR.md`:
- State spotlight blog posts (1/week)
- Age group guides
- Tournament coverage
- Algorithm explainer

## Backlink Opportunities

Track and suggest:
- Youth soccer directories to submit
- Club partnerships (embeddable widget!)
- Local sports news sites
- Reddit/social sharing opportunities

## Success Metrics (Track Weekly)

| Metric | Check |
|--------|-------|
| Total clicks | `gsc_report.py --days 7` |
| Impressions | Trending up? |
| Avg position | Improving? |
| Indexed pages | Growing toward 918? |
| New queries | Opportunities? |

## Reference Docs

- `docs/SEO_ACTION_PLAN.md` — Full strategy
- `docs/SEO_WEEKLY_REPORT.md` — Weekly status
- `docs/CONTENT_CALENDAR.md` — Planned content
