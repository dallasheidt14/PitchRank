---
name: review-workflows
description: "Audits GitHub Actions workflow files in .github/workflows/ for shell injection, cron drift, env precedence conflicts, timeout shielding gaps, missing script references, hardcoded secrets, and mutable-sort matrix sharding. Outputs structured findings to .turbo/workflow-audit.md. Use when the user asks to 'review workflows', 'audit workflows', 'check GitHub Actions', 'review CI workflows', 'workflow audit', or 'check workflow safety'. Also folded into /audit as the workflow leg."
---

# Review Workflows

Detect known GHA failure patterns in workflow YAML before they cause incidents. Findings, not fixes — the user decides what to act on.

## Step 1: Run the Audit Script

From the repo root:

```bash
mkdir -p .turbo
python .claude/skills/review-workflows/scripts/audit_workflows.py \
    --repo-root . \
    --fail-on never \
    --format markdown \
    > .turbo/workflow-audit.md
```

Flags:
- `--repo-root` — defaults to cwd; explicit form makes the path resolution unambiguous.
- `--workflows-dir` — defaults to `<repo-root>/.github/workflows`; override only if scanning a different location.
- `--fail-on` — exit-code threshold. Use `never` for interactive runs so the report still writes; use `high` when wiring into CI.
- `--format` — `markdown` (default) or `json` for downstream consumers.

The script requires PyYAML. If it errors with "PyYAML required", run `pip install pyyaml` and retry.

## Step 2: Read the Report

Read `.turbo/workflow-audit.md`. Findings are sorted by severity (critical → high → medium → low) and grouped by section.

Each finding has:
- **Check ID** — e.g. `shell-injection`, `cron-drift`
- **Location** — `<workflow-file>:<line>`
- **Message** — what's wrong and why
- **Evidence** — the offending snippet (secrets are redacted)
- **Reference** — related MEMORY.md entry, when applicable

For check-specific detail, the script's behavior, severity rationale, and known false positives, consult [references/checks.md](references/checks.md).

## Step 3: Triage and Report

Group findings into three buckets and present them to the user:

- **Confirmed** — clear true positives the user should fix. State the file, the fix pattern, and link to the relevant check in `references/checks.md`.
- **Probable false positives** — findings where the check fired but the code is correct in context. State why and ask if the user wants to confirm before dismissing.
- **Needs investigation** — findings where the call requires reading more code than the check inspected.

Then use `AskUserQuestion` to ask whether to:
- Fix confirmed findings now
- Defer all findings to a follow-up session
- Open a tracking note via `/note-improvement`

Do not edit workflow files without explicit approval. The skill detects; the user decides.

## Step 4: Re-Run on Fixes (Optional)

If the user opts to fix findings in this session, run the audit again after edits to verify findings are resolved. Skip this step if no edits were made.

## Adding New Checks

When a new GHA gotcha enters MEMORY.md:
1. Add a new check function in `scripts/audit_workflows.py`. Pick the signature that matches what the check needs:
   - **`(wf: WorkflowFile) -> list[Finding]`** — append to the `CHECKS` list near the bottom; the driver loops over it automatically.
   - **Requires extra context** (e.g. `repo_root` for path resolution) — wire it directly into `run_audit` after the `CHECKS` loop. Follow `check_script_existence` as the pattern.
2. Document it in [references/checks.md](references/checks.md) with severity, memory ref, detected pattern, fix pattern, and known false positives.
3. Run the audit against the current workflows and verify the new check fires on at least one real example (or document why no current workflow trips it).
