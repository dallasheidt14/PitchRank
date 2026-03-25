# Data Quality Roadmap 🧹

## Philosophy
**Clean at ingestion > Clean after the fact**

As PitchRank scales, reactive cleanup won't cut it. We need proactive systems that:
1. Catch issues BEFORE they enter the database
2. Learn from patterns to prevent future issues
3. Self-heal known problems automatically
4. Surface NEW issues for human review

---

## Cleany's Mandate
**Empowered to explore, test, and propose — but NOT execute changes without D H approval.**

Cleany can:
- ✅ Analyze data quality patterns
- ✅ Run dry-run tests on new cleanup ideas
- ✅ Propose new scripts/rules
- ✅ Identify emerging issues
- ❌ NOT execute changes to production data without approval

---

## Current State (Feb 2026)
- Weekly Cleany job monitors GH Actions
- Scripts exist for club names, team names, duplicates
- Manual review queue for uncertain matches

## Proactive Improvements

### Phase 1: Ingestion Validation (Immediate)
- [ ] Add validation at scrape time — reject/quarantine bad data early
- [ ] Standardize provider data — each source (TGS, GotSport, ECNL) has quirks
- [ ] Age range enforcement — U10-U19 only, filter at source
- [ ] Required fields check — no team without club_name, state_code

### Phase 2: Pattern Learning (Short-term)
- [ ] Club alias auto-detection — "FC Dallas" = "FC Dallas Youth" = "FCD"
- [ ] Coach name extraction — build dictionary from existing data
- [ ] Regional suffix patterns — CTX, NTX, STX, etc.
- [ ] Common misspellings — track and auto-correct

### Phase 3: Quality Scoring (Medium-term)
- [ ] Team completeness score — has club_name, state_code, age, gender?
- [ ] Club health score — consistent naming across teams?
- [ ] Match confidence trending — are auto-matches getting better/worse?
- [ ] Quarantine rate tracking — spike = new issue

### Phase 4: Self-Healing (Long-term)
- [ ] Auto-apply high-confidence fixes — 99%+ matches auto-approve
- [ ] Pattern-based rules engine — "if X then always Y"
- [ ] Feedback loop from manual reviews — learn what humans approve

---

## Metrics to Track Weekly
1. New teams added — volume
2. Quarantine rate — % rejected at ingestion
3. Auto-merge rate — % of duplicates auto-handled
4. Match queue growth — backlog trend
5. Missing field counts — club_name, state_code, etc.

*Last updated: 2026-02-06*
