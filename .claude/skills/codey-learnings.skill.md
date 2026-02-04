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
