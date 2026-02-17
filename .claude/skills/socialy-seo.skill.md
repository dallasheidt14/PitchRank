# Socialy SEO Skill

Proactive SEO monitoring and optimization for PitchRank.

## Monitoring Schedule

| Check | Frequency | Purpose |
|-------|-----------|---------|
| GSC Quick Check | Daily (7:30am) | Impressions, clicks, errors |
| Technical Audit | Weekly (Wed 9am) | Core Web Vitals, crawl issues |
| Content Gaps | Weekly (Wed 9am) | Missing pages, thin content |
| Competitor Watch | Monthly | Track competitor rankings |

## Daily Checks (7:30am)

1. **GSC Health**
   - New crawl errors?
   - Impressions trending up/down?
   - Any pages dropped from index?

2. **Quick Wins**
   - Pages ranking #4-10 (push to top 3)
   - High impressions, low CTR (fix meta descriptions)
   - New queries appearing

## Weekly Checks (Wednesday 9am)

### Technical SEO
- Core Web Vitals (LCP, INP, CLS)
- Mobile usability issues
- Sitemap validity
- Robots.txt changes
- Security headers

### Content Analysis
- Pages with <300 words (thin content)
- Missing meta descriptions
- Duplicate title tags
- Missing H1s
- Image alt text coverage

### Schema Markup
- Validate existing schema
- Identify missing schema opportunities
- SportsTeam schema for team pages
- BreadcrumbList for navigation

## Monthly Checks

### Competitor Analysis
- Track rankings for key terms
- Identify content gaps
- Backlink opportunities

### Content Planning
- Suggest blog post topics
- State-specific landing pages
- Age group guides

## Key Queries to Track

### High Priority (State + Rankings)
- "[state] youth soccer rankings"
- "[state] club soccer rankings"  
- "best youth soccer teams in [state]"

### Medium Priority (Age Groups)
- "U[age] soccer rankings [state]"
- "[birth year] boys/girls soccer rankings"

### Long Tail
- "[club name] soccer rankings"
- "[team name] PowerScore"

## Autonomous Actions

Socialy can:
✅ Create GSC reports
✅ Identify SEO issues
✅ Write content briefs
✅ Spawn Codey for technical fixes
✅ Update SEO_ACTION_PLAN.md

Socialy should ask first:
❓ Major site structure changes
❓ New page creation
❓ External link building

## Scripts

- `scripts/gsc_report.py --days N` — GSC data
- `scripts/check_core_web_vitals.py` — CWV audit (TODO)
- `scripts/content_audit.py` — Thin content check (TODO)
- `scripts/schema_validator.py` — Schema check (TODO)

## Output Files

- `docs/SEO_ACTION_PLAN.md` — Current priorities
- `docs/SEO_WEEKLY_REPORT.md` — Weekly status
- `docs/CONTENT_CALENDAR.md` — Planned content
