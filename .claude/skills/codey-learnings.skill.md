# Codey Learnings 💻

## Date: 2026-02-03

### What Worked Well
- **GitHub Action workflow creation:** Successfully converted queue auto-merge script to GH Action (`.github/workflows/auto-merge-queue.yml`)
- **Cleany integration:** Seamlessly added workflow trigger to weekly cleanup script as Step 0
- **Cost optimization:** Moved compute from local API calls to free GitHub Actions infrastructure

### Patterns for Future Use
1. **Convert long-running local scripts → GH Actions** when they use external APIs (saves credits)
2. **Async workflows in cron jobs:** Scripts can trigger GH Actions via `gh workflow run` — workflow runs independently
3. **Database secrets:** Existing `DATABASE_URL` secret works in workflows without reconfiguration

### Gotchas Discovered
- **Async execution timing:** When Cleany triggers the workflow, it won't block or report results immediately
- **gh CLI requirement:** Machine must have `gh` installed for workflow triggering

### For Next Time
- Consider creating more GitHub Actions for long-running computations
- Document GH Action trigger patterns for other scripts

## Date: 2026-02-04

### What Worked Well
- **Iterative GitHub Actions debugging:** Successfully diagnosed and fixed IPv6/pooler connection issue through 5 successive commits (`a7482b6` → `890404f` → `9f65930` → `d7030c9` → final pooler fix)
- **Blog platform implementation:** Built full CMS with routes, newsletter form, Supabase integration from scratch in single session
- **Algorithm deep dive documentation:** Created comprehensive 6,000-word technical analysis with validation of SOS accuracy advantage
- **Team unmerge automation:** Script to separate legitimate HD/AD divisions executed cleanly (79 teams)

### Patterns for Future Use
1. **Supabase connection strategies:**
   - **Direct connection:** `postgresql://postgres:pass@db.REGION.supabase.co:5432/postgres` (IPv6, local/CLI only)
   - **Pooler connection:** `postgresql://postgres.REGION:pass@aws-1-us-west-1.pooler.supabase.com:5432/postgres` (IPv4, GitHub Actions compatible)
   - **When to use:** Direct for local scripts (fast), Pooler for GH Actions/CI/remote (reliable, IPv4-only)

2. **Iterative fix pattern for CI/CD issues:**
   - Try simple fix first (add env var)
   - If fails, try workaround (different port/URL format)
   - If persists, diagnose root cause (IPv6 vs IPv4)
   - Document the actual solution for others
   - **Key**: Each iteration teaches you something about the system

3. **Newsletter forms in TypeScript/React:**
   - Use `useTransition()` for loading state without reloading page
   - Store to database table + trigger email queue job
   - Validate email client-side before submit
   - Disable button during submission

4. **Full-stack blog features:**
   - RLS policies on Supabase tables for public read, authenticated write
   - Metadata extraction from markdown (frontmatter + first paragraph)
   - SEO: sitemap generation, og:tags in metadata
   - Content recycling: Each post → 5 social formats (newsletter email, Twitter thread, Instagram carousel, TikTok caption, YouTube Shorts)

### Gotchas Discovered
- **Supabase pooler hostname differs by region:** Don't assume `aws-1-us-west-1.pooler.supabase.com` — check Supabase dashboard for actual pooler URL for your region/instance
- **GitHub Actions only have IPv4:** Direct Supabase connections fail silently in GH Actions (look for connection timeouts with no error message)
- **GitHub secrets not visible in logs:** DATABASE_URL updates to secrets require re-running workflow to pick up changes
- **HD vs AD are legitimate divisions:** Teams with both HD and AD aliases shouldn't be merged — they represent different squad levels in same club

### For Next Time
- When GitHub Actions workflow fails silently → first check network protocol (IPv4 vs IPv6)
- Document pooler hostname immediately when setting up new Supabase projects
- Newsletter forms should have rate limiting to prevent spam submissions
- Blog content should auto-generate social media captions from markdown frontmatter
