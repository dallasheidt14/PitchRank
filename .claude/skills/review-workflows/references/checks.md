# Workflow Audit Checks

Detailed reference for each check the audit script performs. Each check derives from a real incident captured in MEMORY.md.

## Contents
- shell-injection — raw `${{ inputs.* }}` in run blocks
- cron-drift — `*/N` minute fields
- env-precedence — step env vs `$GITHUB_ENV` conflicts
- timeout-shielding — continue-on-error without timeout
- script-missing — referenced scripts that don't exist
- secret-* — hardcoded tokens
- matrix-shard-mutable-sort — OFFSET sharding heuristic
- Tuning false positives

## shell-injection

**Severity:** HIGH
**Memory:** `gha_inputs_shell_injection.md`

Detects raw interpolation of attacker-influenceable expressions into `run:` blocks. The actor can craft a value containing shell metacharacters (`$()`, backticks, `;`, newlines) that execute on the runner.

**Detected expressions:**
- `${{ inputs.X }}` — workflow_dispatch / workflow_call inputs
- `${{ github.event.X }}` — event payload fields (issue title, PR body, comment, etc.)
- `${{ needs.X.outputs.Y }}` — outputs from prior jobs (only attacker-controlled if the prior job processes untrusted input)

**Fix pattern:**
```yaml
- name: Use input safely
  env:
    INPUT_VALUE: ${{ inputs.value }}
  run: |
    echo "Processing: $INPUT_VALUE"
```

The shell variable `$INPUT_VALUE` is not subject to template expansion — the shell handles quoting.

**Known false positive:** The check flags `needs.X.outputs.Y` even when the upstream output is hardcoded (e.g. a version string). Triage per finding.

## cron-drift

**Severity:** MEDIUM
**Memory:** `gotcha_gh_actions_scheduled_drift.md`

GitHub-hosted runner cron uses a shared queue. `*/15 * * * *` does not fire every 15 minutes — observed cadence is every 2-3 hours under load. Explicit minute lists fire reliably.

**Detected pattern:** First cron field matches `^\*/\d+$`.

**Fix pattern:**
```yaml
on:
  schedule:
    - cron: "7,22,37,52 * * * *"   # offset minutes, fires reliably
```

Offset minutes (7, 22, 37, 52 — not 0, 15, 30, 45) reduce queue contention.

## env-precedence

**Severity:** MEDIUM
**Memory:** `gotcha_gha_workflow_env_and_timeouts.md`

Step-level `env:` beats vars written to `$GITHUB_ENV` in a prior step. The `$GITHUB_ENV` write succeeds, the var appears in the job environment, then the step's own `env:` silently overrides it for that step's process.

**Detected pattern:** Within a job, the same variable name appears both in a step's `env:` and in an `echo X=... >> $GITHUB_ENV` somewhere in any step's `run:`.

**Fix patterns:**
- If the step `env:` value is correct, remove the `$GITHUB_ENV` write (it's dead).
- If the `$GITHUB_ENV` write is correct, remove the step `env:` entry.

**Known false positive:** A step intentionally overrides a global var for one step only. Triage per finding.

## timeout-shielding

**Severity:** LOW
**Memory:** `gotcha_gha_workflow_env_and_timeouts.md`

`continue-on-error: true` marks a step's failure as non-fatal but does **not** apply when the step exceeds the runner's default 360-minute timeout. A hung process still kills the job after 6 hours; the `continue-on-error` flag is irrelevant at that point.

**Detected pattern:** Step has `continue-on-error: true` and no `timeout-minutes` at either step or job level.

**Fix pattern:**
```yaml
- name: Best-effort scrape
  continue-on-error: true
  timeout-minutes: 30          # explicit bound; failure marked non-fatal
  run: python scripts/scrape.py
```

## script-missing

**Severity:** HIGH

Workflows that reference `python scripts/X.py`, `node scripts/X.js`, `bash scripts/X.sh`, etc., where the file does not exist at repo root. Catches: scripts deleted without updating workflows, scripts renamed, typos.

**Detection:** Regex scans `run:` blocks for `(python|node|bash|sh|tsx|ts-node) <path>` where `<path>` matches `*.py|js|ts|mjs|sh`. Skips paths containing `${...}` or `$(...)`.

**Known false positives:**
- Cd targets that contain GitHub Actions context expressions like `${{ github.workspace }}` are excluded from candidate resolution. A workflow using `cd ${{ github.workspace }}/scripts` reports a missing script even when the file exists. Triage per finding.
- Steps that use job-level or step-level `working-directory` are resolved; ad-hoc `pushd`/`popd` is not. Triage per finding.

## secret-github-pat / secret-stripe-key / secret-jwt-secret / secret-aws-key

**Severity:** CRITICAL

Hardcoded credentials in workflow YAML. Workflow files are public on public repos and visible to all repo collaborators on private repos. Any credential here must be rotated immediately if exposed.

**Detected patterns:**
- GitHub PAT: `ghp_*` / `ghs_*` (30+ chars)
- Stripe keys: `sk_live_*` / `sk_test_*` (20+ chars)
- JWTs (Supabase service role keys): `eyJ...eyJ...sig` three-segment base64
- AWS access keys: `AKIA[0-9A-Z]{16}`

The check skips lines containing `${{ secrets.` to avoid flagging the correct usage pattern.

**Evidence is redacted** in output: first 6 + last 4 chars only. The full match is in the source file but not in `.turbo/workflow-audit.md`.

**Fix:**
1. Rotate the exposed credential immediately.
2. Add to GitHub Actions secrets.
3. Reference as `${{ secrets.NAME }}`.

## matrix-shard-mutable-sort

**Severity:** MEDIUM
**Memory:** `gotcha_matrix_sharding_with_mutable_sort.md`

Heuristic check for the sharding bug pattern: matrix-based parallel jobs that partition work by OFFSET+LIMIT over a mutable sort key (e.g. `ORDER BY last_updated`). As rows update during the run, they shift across shard boundaries — some rows get processed twice, others not at all.

**Detected pattern:**
- Job has `strategy.matrix.<key>` where `<key>` matches `shard|index|chunk|partition|offset` and the value is a numeric/string array.
- Any step in the job runs SQL containing both `OFFSET` and `LIMIT`.
- The run block does not contain a hash-based clause (`hashtext`, `% `).

**Fix pattern:** Shard by hash of a stable ID:
```sql
WHERE ((hashtext(team_id) % :total_shards) + :total_shards) % :total_shards = :shard
```

Note the double-modulo: Postgres `%` preserves dividend sign and drops ~48% of rows on naive `hashtext(x) % N`. See `gotcha_postgres_signed_modulo.md`.

**Known false positive:** OFFSET+LIMIT used for pagination within a single shard (not for sharding). Triage per finding.

## Tuning false positives

When a finding is a confirmed false positive, the right fix depends on the check:

| Check | Tune by |
|-------|---------|
| shell-injection | Tighten `INJECTION_PATTERN` to exclude specific safe contexts |
| cron-drift | No tuning — `*/N` is always drift on shared runners |
| env-precedence | Add a per-workflow allowlist constant; this case is rare |
| timeout-shielding | Add a per-job allowlist; some jobs intentionally have no upper bound |
| script-missing | Tighten `SCRIPT_REF` regex to exclude `cd subdir &&` patterns |
| secret-* | Pattern is conservative; FP usually means a non-secret token shaped like one (e.g. a sample) — move sample to a comment with `# pragma: not-a-secret` and add a guard |
| matrix-shard-mutable-sort | The check already exits when hash-mod is present. If OFFSET+LIMIT is intentional for pagination, the finding is informational |

When a new GHA gotcha enters MEMORY.md, add a new check function to `audit_workflows.py` and append it to the `CHECKS` list.
