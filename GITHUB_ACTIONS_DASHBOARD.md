# GitHub Actions Dashboard

This document provides a comprehensive overview of all GitHub Actions workflows configured for the PitchRank project.

## 📊 Workflow Status Badges

Add these badges to your `README.md` to display the status of your workflows:

```markdown
<!-- CI/CD Pipeline -->
![CI/CD Pipeline](https://github.com/dallasheidt14/PitchRank/actions/workflows/ci.yml/badge.svg)

<!-- Security -->
![CodeQL](https://github.com/dallasheidt14/PitchRank/actions/workflows/codeql.yml/badge.svg)
![Dependency Review](https://github.com/dallasheidt14/PitchRank/actions/workflows/dependency-review.yml/badge.svg)

<!-- Operations -->
![Weekly Update](https://github.com/dallasheidt14/PitchRank/actions/workflows/weekly-update.yml/badge.svg)
![Calculate Rankings](https://github.com/dallasheidt14/PitchRank/actions/workflows/calculate-rankings.yml/badge.svg)
![Process Missing Games](https://github.com/dallasheidt14/PitchRank/actions/workflows/process-missing-games.yml/badge.svg)

<!-- Deployment -->
![Deploy Frontend](https://github.com/dallasheidt14/PitchRank/actions/workflows/deploy-frontend.yml/badge.svg)

<!-- Quality -->
![Database Migrations](https://github.com/dallasheidt14/PitchRank/actions/workflows/validate-migrations.yml/badge.svg)
```

---

## 🔄 Workflow Overview

### 1. **CI/CD Pipeline** (`ci.yml`)
**Status:** ![CI/CD](https://github.com/dallasheidt14/PitchRank/actions/workflows/ci.yml/badge.svg)

**Trigger:** Push to any branch, Pull Requests

**Purpose:** Continuous Integration for code quality and testing

**Jobs:**
- **Python CI:**
  - Code formatting check (Black)
  - Linting (flake8)
  - Unit tests (pytest) with coverage
  - Coverage reporting to Codecov

- **Frontend CI:**
  - ESLint linting
  - TypeScript type checking
  - Next.js build verification
  - Bundle size analysis

**Duration:** ~5-10 minutes

**Required for:** All PRs must pass before merging

---

### 2. **CodeQL Security Analysis** (`codeql.yml`)
**Status:** ![CodeQL](https://github.com/dallasheidt14/PitchRank/actions/workflows/codeql.yml/badge.svg)

**Trigger:**
- Push to main and claude/* branches
- Pull Requests to main
- Scheduled: Every Monday at 6:00 AM UTC

**Purpose:** Automated security vulnerability detection

**Languages Scanned:**
- Python
- JavaScript/TypeScript

**Duration:** ~10-15 minutes

**View Results:** GitHub Security tab → Code scanning alerts

---

### 3. **Dependency Review** (`dependency-review.yml`)
**Status:** ![Dependency Review](https://github.com/dallasheidt14/PitchRank/actions/workflows/dependency-review.yml/badge.svg)

**Trigger:** Pull Requests to main

**Purpose:** Review dependencies for security vulnerabilities and license compliance

**Checks:**
- Security vulnerabilities (moderate+ severity)
- License compliance (blocks GPL-2.0, GPL-3.0)
- Supply chain security

**Duration:** ~2-3 minutes

---

### 4. **Dependabot** (`dependabot.yml`)
**Status:** Automatic (Config file)

**Trigger:** Weekly (Mondays at 9:00 AM Pacific)

**Purpose:** Automated dependency updates

**Monitors:**
- Python packages (pip)
- npm packages (frontend)
- GitHub Actions versions

**Configuration:**
- Groups minor/patch updates together
- Exempts major version updates for Next.js, React
- Auto-labels PRs with `dependencies`, `automated`

---

### 5. **PR Automation** (`pr-labeler.yml`)
**Status:** ![PR Automation](https://github.com/dallasheidt14/PitchRank/actions/workflows/pr-labeler.yml/badge.svg)

**Trigger:** PR opened, updated, or reopened

**Purpose:** Automated PR labeling and management

**Features:**
- Labels PRs by size (XS, S, M, L, XL)
- Labels PRs by files changed (backend, frontend, database, etc.)
- Welcomes first-time contributors
- Validates PR title format (conventional commits)

**Duration:** ~1-2 minutes

---

### 6. **Deploy Frontend** (`deploy-frontend.yml`)
**Status:** ![Deploy Frontend](https://github.com/dallasheidt14/PitchRank/actions/workflows/deploy-frontend.yml/badge.svg)

**Trigger:**
- Push to main (production)
- Pull Requests (preview)
- Manual workflow dispatch

**Purpose:** Automated frontend deployment

**Deployments:**
- **Preview:** For every PR with frontend changes
- **Production:** When merged to main

**Platform:** Vercel (configurable for Netlify)

**Duration:** ~3-5 minutes

**Setup Required:**
1. Create Vercel project
2. Add GitHub secrets:
   - `VERCEL_TOKEN`
   - `VERCEL_ORG_ID`
   - `VERCEL_PROJECT_ID`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`

---

### 7. **Validate Database Migrations** (`validate-migrations.yml`)
**Status:** ![Database Migrations](https://github.com/dallasheidt14/PitchRank/actions/workflows/validate-migrations.yml/badge.svg)

**Trigger:** Changes to `supabase/migrations/**`

**Purpose:** Validate SQL migration files before merge

**Checks:**
- File naming convention (YYYYMMDDHHMMSS_description.sql)
- SQL syntax validation
- Dangerous operations detection (DROP DATABASE, TRUNCATE)
- Migration sequence verification
- Rollback documentation

**Duration:** ~2-3 minutes

---

### 8. **Release Management** (`release.yml`)
**Status:** ![Release](https://github.com/dallasheidt14/PitchRank/actions/workflows/release.yml/badge.svg)

**Trigger:**
- Push of version tags (v*)
- Manual workflow dispatch

**Purpose:** Automated release creation

**Features:**
- Generates changelog from commits
- Groups changes by type (features, fixes, docs, etc.)
- Lists contributors
- Creates GitHub Release with notes
- Auto-tags on version bumps in pyproject.toml

**Duration:** ~2-3 minutes

**Usage:**
```bash
# Manual release
gh workflow run release.yml -f version=2.1.0 -f prerelease=false

# Or bump version in pyproject.toml and push to main
```

---

### 9. **Stale Management** (`stale.yml`)
**Status:** ![Stale](https://github.com/dallasheidt14/PitchRank/actions/workflows/stale.yml/badge.svg)

**Trigger:**
- Scheduled: Daily at 1:00 AM UTC
- Manual workflow dispatch

**Purpose:** Automatic stale issue/PR management

**Configuration:**
- **Issues:** Marked stale after 90 days, closed after 14 days
- **PRs:** Marked stale after 60 days, closed after 7 days

**Exemptions:**
- Issues/PRs with labels: `keep-open`, `bug`, `security`
- Issues/PRs with assignees
- Draft PRs
- Issues/PRs with milestones

**Duration:** ~1-2 minutes

---

### 10. **Weekly Update** (`weekly-update.yml`)
**Status:** ![Weekly Update](https://github.com/dallasheidt14/PitchRank/actions/workflows/weekly-update.yml/badge.svg)

**Trigger:**
- Scheduled: Every Monday at 12:01 AM Pacific
- Manual workflow dispatch

**Purpose:** Automated weekly data scraping, import, and ranking calculation

**Steps:**
1. Scrape games from providers (GotSport, TGS, US Club)
2. Import new games
3. Calculate rankings with ML enhancement

**Duration:** ~30-120 minutes

**Timeout:** 2 hours

---

### 11. **Calculate Rankings** (`calculate-rankings.yml`)
**Status:** ![Calculate Rankings](https://github.com/dallasheidt14/PitchRank/actions/workflows/calculate-rankings.yml/badge.svg)

**Trigger:** Manual workflow dispatch

**Purpose:** On-demand ranking calculation

**Command:** `python scripts/calculate_rankings.py --ml --force-rebuild`

**Duration:** ~10-30 minutes

**Note:** Currently configured to run on a specific branch

---

### 12. **Process Missing Games** (`process-missing-games.yml`)
**Status:** ![Process Missing Games](https://github.com/dallasheidt14/PitchRank/actions/workflows/process-missing-games.yml/badge.svg)

**Trigger:**
- Scheduled: Every 5 minutes
- Manual workflow dispatch

**Purpose:** Continuously process missing games queue

**Limit:** 10 games per run

**Duration:** ~1-3 minutes

**Frequency:** 288 times per day

---

## 🎯 Workflow Categories

### Critical (Must Pass for PR Merge)
- ✅ CI/CD Pipeline
- ✅ CodeQL Security Analysis
- ✅ Dependency Review
- ✅ Database Migration Validation

### Automated Operations
- 🔄 Weekly Update
- 🔄 Process Missing Games
- 🔄 Stale Management
- 🔄 Dependabot

### Deployment
- 🚀 Deploy Frontend
- 🚀 Release Management

### Manual Operations
- 🎮 Calculate Rankings

---

## 📈 Monitoring and Alerts

### GitHub Actions Dashboard
View all workflow runs: https://github.com/dallasheidt14/PitchRank/actions

### Security Dashboard
View security alerts: https://github.com/dallasheidt14/PitchRank/security

### Code Coverage
View coverage reports: Codecov (requires setup)

---

## 🔧 Setup Instructions

### Required GitHub Secrets

Add these secrets in: Settings → Secrets and variables → Actions

**Supabase:**
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

**Vercel (for frontend deployment):**
- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

**Codecov (for code coverage):**
- `CODECOV_TOKEN`

### Branch Protection Rules

Recommended branch protection for `main`:

1. Go to: Settings → Branches → Add rule
2. Branch name pattern: `main`
3. Enable:
   - ✅ Require a pull request before merging
   - ✅ Require approvals (1)
   - ✅ Require status checks to pass before merging
     - ✅ CI/CD Pipeline
     - ✅ CodeQL
     - ✅ Dependency Review
   - ✅ Require branches to be up to date before merging
   - ✅ Require conversation resolution before merging
   - ✅ Do not allow bypassing the above settings

---

## 🚦 Workflow Best Practices

### For Contributors

1. **Before Creating a PR:**
   - Ensure all tests pass locally: `pytest tests/`
   - Format code: `black src/ scripts/ tests/`
   - Lint code: `flake8 src/ scripts/ tests/`
   - Check types: `npx tsc --noEmit` (frontend)

2. **PR Title Format:**
   - Use conventional commits: `feat:`, `fix:`, `docs:`, etc.
   - Example: `feat(rankings): add ML layer to v53e algorithm`

3. **Monitor CI Results:**
   - Fix any failing checks before requesting review
   - Check the "Files changed" tab for automated feedback

### For Maintainers

1. **Workflow Maintenance:**
   - Review Dependabot PRs weekly
   - Monitor CodeQL security alerts
   - Review stale PRs monthly

2. **Release Process:**
   - Bump version in `pyproject.toml`
   - Push to main (triggers auto-tag and release)
   - Or manually trigger release workflow

3. **Deployment:**
   - Frontend deploys automatically on merge to main
   - Preview deployments for all PRs

---

## 📊 Workflow Metrics

Track these metrics to improve your CI/CD:

- **Average CI duration:** Target < 10 minutes
- **Success rate:** Target > 95%
- **Time to deploy:** Target < 5 minutes
- **Security alerts:** Target = 0

View in: Actions → Workflows → Select workflow → Insights

---

## 🐛 Troubleshooting

### CI Pipeline Failing?

**Python CI:**
- Run `black --check src/` locally to see formatting issues
- Run `flake8 src/` to see linting errors
- Run `pytest tests/` to see test failures

**Frontend CI:**
- Run `npm run lint` in frontend/
- Run `npx tsc --noEmit` for type errors
- Run `npm run build` for build errors

### Deployment Failing?

**Check:**
1. All required secrets are set
2. Vercel project is properly configured
3. Environment variables are correct
4. Review workflow logs for specific errors

### Security Alerts?

1. Go to: Security → Code scanning → Alerts
2. Review each alert
3. Fix vulnerabilities
4. Push fix to trigger re-scan

---

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Vercel Deployment Guide](https://vercel.com/docs/deployments/overview)
- [CodeQL Documentation](https://codeql.github.com/docs/)
- [Dependabot Documentation](https://docs.github.com/en/code-security/dependabot)

---

**Last Updated:** January 2025
**Maintained by:** Dallas Heidt (@dallasheidt14)
