#!/usr/bin/env python3
"""Audit GitHub Actions workflow files against PitchRank's incident catalog.

Outputs a structured markdown report to stdout. Exits non-zero if findings exist
at SEVERITY_FAIL or higher (default: HIGH).

Usage:
    python audit_workflows.py [--workflows-dir PATH] [--repo-root PATH]
                              [--fail-on {critical,high,medium,low,never}]
                              [--format {markdown,json}]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "PyYAML required. Install with: pip install pyyaml\n"
    )
    sys.exit(2)


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Finding:
    check_id: str
    severity: str  # critical|high|medium|low
    workflow: str  # path relative to repo root
    line: int | None
    message: str
    evidence: str
    memory_ref: str = ""  # related MEMORY.md entry

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowFile:
    path: Path
    rel_path: str
    text: str
    lines: list[str]
    data: dict | None  # parsed YAML, None if parse failed
    parse_error: str | None = None


# ---------- helpers ----------


def load_workflows(workflows_dir: Path, repo_root: Path) -> list[WorkflowFile]:
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    out: list[WorkflowFile] = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = str(p.relative_to(repo_root)).replace("\\", "/")
        try:
            data = yaml.safe_load(text)
            err = None
        except yaml.YAMLError as e:
            data = None
            err = str(e)
        out.append(
            WorkflowFile(
                path=p,
                rel_path=rel,
                text=text,
                lines=text.splitlines(),
                data=data if isinstance(data, dict) else None,
                parse_error=err,
            )
        )
    return out


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def iter_jobs(data: dict) -> Iterable[tuple[str, dict]]:
    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for name, job in jobs.items():
        if isinstance(job, dict):
            yield name, job


def iter_steps(job: dict) -> Iterable[dict]:
    steps = job.get("steps") or []
    if not isinstance(steps, list):
        return
    for step in steps:
        if isinstance(step, dict):
            yield step


# ---------- checks ----------


# Check 1: Shell injection via raw ${{ inputs.* }} / github.event.* / needs.*.outputs.*
# Memory: gha_inputs_shell_injection.md
INJECTION_PATTERN = re.compile(
    r"\$\{\{\s*"
    r"(inputs\.[^}\s]+"
    r"|github\.event\.[^}\s]+"
    r"|github\.head_ref"
    r"|github\.ref_name"
    r"|github\.actor"
    r"|needs\.[^}\s]+\.outputs\.[^}\s]+"
    r"|steps\.[^}\s]+\.outputs\.[^}\s]+)"
    r"\s*\}\}"
)


def check_shell_injection(wf: WorkflowFile) -> list[Finding]:
    if not wf.data:
        return []
    findings: list[Finding] = []
    for job_name, job in iter_jobs(wf.data):
        for step in iter_steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for m in INJECTION_PATTERN.finditer(run):
                # Locate line in source by finding the run block + offset
                expr = m.group(0)
                source_idx = wf.text.find(expr)
                line = line_of(wf.text, source_idx) if source_idx >= 0 else None
                findings.append(
                    Finding(
                        check_id="shell-injection",
                        severity="high",
                        workflow=wf.rel_path,
                        line=line,
                        message=(
                            f"Raw `{expr}` interpolated into run: block in job "
                            f"`{job_name}`. Shell injection primitive."
                        ),
                        evidence=expr,
                        memory_ref="gha_inputs_shell_injection.md",
                    )
                )
    return findings


# Check 2: Cron drift — */N patterns drift to 2-3h cadence on shared runners
# Memory: gotcha_gh_actions_scheduled_drift.md
CRON_LINE = re.compile(r"-?\s*cron:\s*['\"]?([^'\"#\n]+)")


def check_cron_drift(wf: WorkflowFile) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(wf.lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        m = CRON_LINE.search(line)
        if not m:
            continue
        expr = m.group(1).strip()
        fields = expr.split()
        if len(fields) < 5:
            continue
        minute = fields[0]
        if re.match(r"^\*/\d+$", minute):
            findings.append(
                Finding(
                    check_id="cron-drift",
                    severity="medium",
                    workflow=wf.rel_path,
                    line=i,
                    message=(
                        f"Cron `{expr}` uses `*/N` minute field. On GitHub-hosted "
                        f"runners this drifts to 2-3h cadence; use explicit minute "
                        f"list (e.g. '7,22,37,52 * * * *') for reliable timing."
                    ),
                    evidence=expr,
                    memory_ref="gotcha_gh_actions_scheduled_drift.md",
                )
            )
    return findings


# Check 3: Env precedence — step-level env: silently wins over $GITHUB_ENV writes
# Memory: gotcha_gha_workflow_env_and_timeouts.md
GITHUB_ENV_WRITE = re.compile(
    r"echo\s+[\"']?([A-Z_][A-Z0-9_]*)\s*=", re.IGNORECASE
)


def check_env_precedence(wf: WorkflowFile) -> list[Finding]:
    if not wf.data:
        return []
    findings: list[Finding] = []
    for job_name, job in iter_jobs(wf.data):
        # Collect names of vars written via $GITHUB_ENV anywhere in this job
        github_env_vars: set[str] = set()
        for step in iter_steps(job):
            run = step.get("run")
            if isinstance(run, str) and "$GITHUB_ENV" in run:
                for line in run.splitlines():
                    if "$GITHUB_ENV" not in line:
                        continue
                    m = GITHUB_ENV_WRITE.search(line)
                    if m:
                        github_env_vars.add(m.group(1))
        if not github_env_vars:
            continue
        # Flag steps that set the same name in step env:
        for step in iter_steps(job):
            step_env = step.get("env")
            if not isinstance(step_env, dict):
                continue
            for var in step_env:
                if var in github_env_vars:
                    # Approximate line: search for "var:" inside the step env block
                    idx = wf.text.find(f"{var}:")
                    line = line_of(wf.text, idx) if idx >= 0 else None
                    findings.append(
                        Finding(
                            check_id="env-precedence",
                            severity="medium",
                            workflow=wf.rel_path,
                            line=line,
                            message=(
                                f"Var `{var}` is set in step env: AND written to "
                                f"$GITHUB_ENV in job `{job_name}`. Step env wins "
                                f"silently — the $GITHUB_ENV write has no effect."
                            ),
                            evidence=f"step env.{var}",
                            memory_ref="gotcha_gha_workflow_env_and_timeouts.md",
                        )
                    )
    return findings


# Check 4: Timeout shielding — continue-on-error doesn't shield runner timeouts
# Memory: gotcha_gha_workflow_env_and_timeouts.md
def check_timeout_shielding(wf: WorkflowFile) -> list[Finding]:
    if not wf.data:
        return []
    findings: list[Finding] = []
    for job_name, job in iter_jobs(wf.data):
        job_timeout = job.get("timeout-minutes")
        for step in iter_steps(job):
            coe = step.get("continue-on-error")
            # GH allows the field to be an expression string; treat truthy literals
            is_coe = coe is True or (isinstance(coe, str) and coe.strip().lower() == "true")
            if not is_coe:
                continue
            step_timeout = step.get("timeout-minutes")
            if step_timeout is None and job_timeout is None:
                step_name = step.get("name") or step.get("id") or "(unnamed)"
                findings.append(
                    Finding(
                        check_id="timeout-shielding",
                        severity="low",
                        workflow=wf.rel_path,
                        line=None,
                        message=(
                            f"Step `{step_name}` in job `{job_name}` sets "
                            f"continue-on-error: true with no timeout-minutes at "
                            f"step or job level. continue-on-error does not shield "
                            f"runner timeouts; long hangs still fail the job."
                        ),
                        evidence=f"job={job_name} step={step_name}",
                        memory_ref="gotcha_gha_workflow_env_and_timeouts.md",
                    )
                )
    return findings


# Check 5: Script existence — run: python scripts/X.py paths must exist
# Memory: gotcha_hygiene_step3_step4_contract.md (broader: don't break script contracts)
SCRIPT_REF = re.compile(
    r"(?:^|[\s;&|`])(?:python3?|node|bash|sh|tsx|ts-node)\s+"
    r"([A-Za-z_][\w./-]*\.(?:py|js|ts|mjs|sh))"
)


CD_PATTERN = re.compile(r"^\s*cd\s+([^\s;&|]+)", re.MULTILINE)


def _resolve_script_candidates(
    repo_root: Path, working_dirs_used_in_run: list[str], rel: str
) -> list[Path]:
    """Build candidate full paths for a script ref, given cd targets in the run block."""
    candidates: list[Path] = [repo_root / rel]
    for cd_target in working_dirs_used_in_run:
        if cd_target.startswith(("/", "${", "$(")) or ".." in cd_target:
            continue
        candidates.append(repo_root / cd_target / rel)
    return candidates


def check_script_existence(wf: WorkflowFile, repo_root: Path) -> list[Finding]:
    if not wf.data:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()  # dedupe (workflow, path)
    for job_name, job in iter_jobs(wf.data):
        # job-level default working directory
        defaults = job.get("defaults") or {}
        run_defaults = defaults.get("run") if isinstance(defaults, dict) else None
        job_wd = (
            run_defaults.get("working-directory")
            if isinstance(run_defaults, dict)
            else None
        )
        for step in iter_steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            # Collect cd targets used in this run block + step working-directory
            cd_targets: list[str] = []
            if job_wd:
                cd_targets.append(job_wd)
            step_wd = step.get("working-directory")
            if isinstance(step_wd, str):
                cd_targets.append(step_wd)
            cd_targets.extend(CD_PATTERN.findall(run))
            for m in SCRIPT_REF.finditer(run):
                rel = m.group(1)
                if rel.startswith(("-", "/", "${")):
                    continue
                if "${" in rel or "$(" in rel:
                    continue
                key = (wf.rel_path, rel)
                if key in seen:
                    continue
                seen.add(key)
                candidates = _resolve_script_candidates(repo_root, cd_targets, rel)
                if not any(c.exists() for c in candidates):
                    idx = wf.text.find(rel)
                    line = line_of(wf.text, idx) if idx >= 0 else None
                    findings.append(
                        Finding(
                            check_id="script-missing",
                            severity="high",
                            workflow=wf.rel_path,
                            line=line,
                            message=(
                                f"Workflow references `{rel}` but the file does "
                                f"not exist under repo root or any `cd` target "
                                f"in this run block."
                            ),
                            evidence=rel,
                            memory_ref="",
                        )
                    )
    return findings


# Check 6: Secret hygiene — hardcoded tokens / JWTs / keys outside ${{ secrets.X }}
SECRET_PATTERNS = [
    # GitHub PAT (classic + fine-grained)
    ("github-pat", re.compile(r"\bgh[ps]_[A-Za-z0-9]{30,}\b"), "critical"),
    # Stripe live/test keys
    ("stripe-key", re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{20,}\b"), "critical"),
    # Supabase service role JWT (signed with eyJ-prefix and very long)
    ("jwt-secret", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"), "critical"),
    # AWS access key
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "critical"),
]

SECRETS_EXPR = re.compile(r"\$\{\{\s*secrets\.[^}]*\}\}")


def check_secret_hygiene(wf: WorkflowFile) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(wf.lines, start=1):
        # Spans inside ${{ secrets.X }} are the correct pattern — skip per-match,
        # not per-line, so a trailing-comment fallback token isn't masked.
        secret_spans = [(m.start(), m.end()) for m in SECRETS_EXPR.finditer(line)]
        for check_id, pat, sev in SECRET_PATTERNS:
            for m in pat.finditer(line):
                if any(s <= m.start() and m.end() <= e for s, e in secret_spans):
                    continue
                hit = m.group(0)
                redacted = hit[:6] + "..." + hit[-4:] if len(hit) > 12 else "***"
                findings.append(
                    Finding(
                        check_id=f"secret-{check_id}",
                        severity=sev,
                        workflow=wf.rel_path,
                        line=i,
                        message=(
                            f"Possible hardcoded {check_id} on this line. "
                            f"Replace with `${{{{ secrets.NAME }}}}`."
                        ),
                        evidence=redacted,
                        memory_ref="",
                    )
                )
    return findings


# Check 7: Matrix sharding over a mutable sort key
# Memory: gotcha_matrix_sharding_with_mutable_sort.md
# Heuristic: matrix has a numeric shard array AND any step run uses OFFSET+LIMIT
# (with no obvious hash-based sharding clause). Flag as suspicious; user judges.
SHARD_KEY_HINT = re.compile(r"^\s*(shard|index|chunk|partition|offset)\b", re.IGNORECASE)


def check_matrix_sharding(wf: WorkflowFile) -> list[Finding]:
    if not wf.data:
        return []
    findings: list[Finding] = []
    for job_name, job in iter_jobs(wf.data):
        strategy = job.get("strategy")
        if not isinstance(strategy, dict):
            continue
        matrix = strategy.get("matrix")
        if not isinstance(matrix, dict):
            continue
        # Detect numeric shard-shaped keys
        shardish_key = None
        for k, v in matrix.items():
            if not isinstance(k, str):
                continue
            if SHARD_KEY_HINT.match(k) and isinstance(v, list) and all(
                isinstance(x, (int, str)) for x in v
            ):
                shardish_key = k
                break
        if not shardish_key:
            continue
        # Scan run blocks for OFFSET + LIMIT pattern (case-insensitive)
        for step in iter_steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            has_offset = re.search(r"\bOFFSET\b", run, re.IGNORECASE) is not None
            has_limit = re.search(r"\bLIMIT\b", run, re.IGNORECASE) is not None
            if has_offset and has_limit:
                # If the shard key is referenced as a hash mod, treat as fine
                if "hashtext" in run.lower() or "% " in run:
                    continue
                findings.append(
                    Finding(
                        check_id="matrix-shard-mutable-sort",
                        severity="medium",
                        workflow=wf.rel_path,
                        line=None,
                        message=(
                            f"Job `{job_name}` shards via matrix key "
                            f"`{shardish_key}` and uses OFFSET+LIMIT. If the "
                            f"underlying sort is mutable (e.g. last_updated), "
                            f"rows shift between shards and get dropped/dupes. "
                            f"Prefer hash sharding on a stable ID."
                        ),
                        evidence=f"matrix.{shardish_key} + OFFSET/LIMIT",
                        memory_ref="gotcha_matrix_sharding_with_mutable_sort.md",
                    )
                )
                break  # one finding per job is enough
    return findings


# ---------- driver ----------


CHECKS = [
    check_shell_injection,
    check_cron_drift,
    check_env_precedence,
    check_timeout_shielding,
    check_secret_hygiene,
    check_matrix_sharding,
]


def run_audit(workflows_dir: Path, repo_root: Path) -> tuple[list[Finding], list[WorkflowFile]]:
    files = load_workflows(workflows_dir, repo_root)
    all_findings: list[Finding] = []
    for wf in files:
        if wf.parse_error:
            all_findings.append(
                Finding(
                    check_id="yaml-parse",
                    severity="high",
                    workflow=wf.rel_path,
                    line=None,
                    message=f"YAML parse error: {wf.parse_error}",
                    evidence=wf.parse_error.splitlines()[0] if wf.parse_error else "",
                    memory_ref="",
                )
            )
            # Line-based checks don't need parsed YAML — run them anyway so
            # security findings (secrets) and obvious drift (cron) still surface
            # on broken files.
            all_findings.extend(check_cron_drift(wf))
            all_findings.extend(check_secret_hygiene(wf))
            continue
        for check in CHECKS:
            all_findings.extend(check(wf))
        all_findings.extend(check_script_existence(wf, repo_root))
    return all_findings, files


def render_markdown(findings: list[Finding], files: list[WorkflowFile]) -> str:
    findings_sorted = sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), f.workflow, f.line or 0),
    )
    counts: dict[str, int] = {}
    for f in findings_sorted:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    lines: list[str] = []
    lines.append("# Workflow Audit\n")
    lines.append(f"Scanned: **{len(files)}** workflow files\n")
    lines.append(f"Findings: **{len(findings_sorted)}** "
                 f"(critical: {counts.get('critical', 0)}, "
                 f"high: {counts.get('high', 0)}, "
                 f"medium: {counts.get('medium', 0)}, "
                 f"low: {counts.get('low', 0)})\n")
    if not findings_sorted:
        lines.append("\nNo findings. All checks passed.\n")
        return "\n".join(lines)
    current_sev: str | None = None
    for f in findings_sorted:
        if f.severity != current_sev:
            current_sev = f.severity
            lines.append(f"\n## {current_sev.upper()}\n")
        loc = f"{f.workflow}" + (f":{f.line}" if f.line else "")
        lines.append(f"### `{f.check_id}` — {loc}\n")
        lines.append(f"{f.message}\n")
        if f.evidence:
            lines.append(f"Evidence: `{f.evidence}`\n")
        if f.memory_ref:
            lines.append(f"Reference: `{f.memory_ref}`\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflows-dir",
        default=None,
        help="Path to .github/workflows directory (default: <repo-root>/.github/workflows)",
    )
    parser.add_argument(
        "--repo-root",
        default=os.getcwd(),
        help="Repo root for resolving script paths (default: cwd)",
    )
    parser.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low", "never"],
        default="high",
        help="Exit non-zero if any finding meets or exceeds this severity (default: high)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    workflows_dir = (
        Path(args.workflows_dir).resolve()
        if args.workflows_dir
        else repo_root / ".github" / "workflows"
    )
    if not workflows_dir.is_dir():
        sys.stderr.write(f"Workflows directory not found: {workflows_dir}\n")
        return 2

    findings, files = run_audit(workflows_dir, repo_root)

    if args.format == "json":
        print(json.dumps([f.to_dict() for f in findings], indent=2))
    else:
        print(render_markdown(findings, files))

    if args.fail_on == "never":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    worst = min(
        (SEVERITY_ORDER.get(f.severity, 99) for f in findings),
        default=99,
    )
    return 1 if worst <= threshold else 0


if __name__ == "__main__":
    sys.exit(main())
