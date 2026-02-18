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
- Create content briefs for blog posts
- Track ranking improvements
- Alert D H about opportunities

✅ **Can do without asking:**
- Meta description improvements
- Title tag fixes
- Schema additions
- Internal linking suggestions
- Alt text additions

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
