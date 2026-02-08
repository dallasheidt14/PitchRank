# Codey Trust Zone — Autonomous Commit Rules

> Codey: Follow these rules. Commit autonomously when in trust zone. Ask when not.

## ✅ COMMIT WITHOUT ASKING

### Bug Fixes
- Fixes with clear error → solution path
- Must include test or verification step
- Commit message: `fix: <description>`

### Performance Optimizations
- No behavior change, just faster
- Must benchmark before/after
- Commit message: `perf: <description>`

### Logging & Monitoring
- Adding logs, metrics, health checks
- No business logic changes
- Commit message: `chore: Add logging for <area>`

### Documentation
- README, docstrings, comments
- LEARNINGS.md, GOTCHAS.md, PATTERNS.md
- Commit message: `docs: <description>`

### Dependencies (Minor)
- Patch and minor version updates
- Must run tests after
- Commit message: `chore: Update <package> to <version>`

### Code Cleanup
- Formatting, linting fixes
- Dead code removal (if clearly dead)
- Commit message: `refactor: <description>`

---

## ⚠️ ASK D H FIRST

### Schema Changes
- Any database migrations
- New tables, columns, indexes
- Changes to existing schema

### Algorithm Changes
- Rankings calculation
- Team matching logic
- Scoring formulas

### New Features
- New endpoints, pages, capabilities
- New scraper targets
- New integrations

### Major Refactors
- Restructuring modules
- Changing core abstractions
- Moving significant code

### Protected Files
```
- scripts/calculate_rankings.py (core algorithm)
- src/etl/enhanced_pipeline.py (data integrity)
- Any migration files
- .env files
- GitHub Actions workflows (create new, don't modify existing)
```

---

## 🔄 Commit Workflow

```
1. Make the fix
2. Run tests: pytest tests/ (if available)
3. Run build check: npm run build (if frontend)
4. If all pass:
   git add -A
   git commit -m "<type>: <description>"
   git push
5. Report what you did to D H
```

---

## 📋 Verification Checklist

Before autonomous commit:
- [ ] Is this in the trust zone? (check lists above)
- [ ] Did I test/verify the change?
- [ ] Does it break anything else?
- [ ] Is the commit message clear?
- [ ] Would D H be surprised? (if yes, ask first)

---

## 🚨 When In Doubt

If unclear whether something is in trust zone:
1. Default to asking
2. But propose the fix, don't just report the problem
3. "I found X. I can fix it by doing Y. Should I proceed?"

---

*D H can expand/restrict this list anytime in WEEKLY_GOALS.md*
