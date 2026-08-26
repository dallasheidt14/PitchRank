#!/usr/bin/env python3
"""Wait out a pull request's review window, then hand the merge to GitHub.

A change here spends far more time waiting than working. The seven-job quality
gate takes about 3.1 minutes, and the median PR still sat open for 65 minutes
(40 PRs merged 2026-08-20..25). Nearly all of that gap is a human round trip:
noticing the gate went green, then merging by hand.

Two things must land before a merge is safe, and they finish at different times:

* ci.yml concludes, usually inside 3 minutes.
* The Codex bot posts its review. Over the last 20 merged PRs it reviewed 10 of
  them, between 3.4 and 8.7 minutes after the PR opened, and never later. The
  other 10 got nothing, so waiting for it without a ceiling never returns.

So this polls both, gives Codex until CODEX_WINDOW_MINUTES past the PR's creation
and not a second longer, prints whatever it found, and only then merges. Arming
auto-merge up front would instead merge at the 3-minute mark and outrun every
Codex review that ever arrives -- #1019 shipped a false statement exactly that
way, by reading `gh pr checks` and never reading the review comments.

`--auto` is still the fallback for the case the wait cannot cover: the review
window closes while checks are somehow still running (the slowest observed gate
was 12 minutes). GitHub finishes the merge on its own once they pass.

Which checks count is read from the base branch's ruleset rather than guessed, so
the always-red advisory `claude-review` job never blocks and never needs naming
here.

Usage:
    python scripts/pr_wait.py                  # the PR for the current branch
    python scripts/pr_wait.py --pr 1028
    python scripts/pr_wait.py --dry-run        # report; never merge or arm
    python scripts/pr_wait.py --no-merge       # wait and report only

Exit status: 0 merged or armed, 1 a required check failed or the wait timed out,
2 Codex left findings to read.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time

CODEX_LOGIN = "chatgpt-codex-connector[bot]"

# Measured, not chosen: Codex has never posted later than 8.7 minutes after open.
CODEX_WINDOW_MINUTES = 10
POLL_SECONDS = 20
TIMEOUT_MINUTES = 20

# main's ruleset allows squash only; any other method is rejected at merge time.
MERGE_METHOD = "--squash"


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def gh_json(*args: str):
    return json.loads(gh(*args) or "null")


def gh_pages(endpoint: str) -> list:
    """Every page of a list endpoint, not the first 30.

    A busy PR pushes Codex's review onto a later page, and an unpaginated read
    would then report no review at all and merge. `--slurp` wraps the pages in an
    outer list; it cannot be combined with `--jq`, hence the flatten here.
    """
    pages = json.loads(gh("api", "--paginate", "--slurp", endpoint))
    return [item for page in pages for item in page]


def resolve_pr(explicit: int | None) -> dict:
    fields = "number,title,url,baseRefName,createdAt,isDraft,state,statusCheckRollup"
    args = ["pr", "view", "--json", fields]
    if explicit:
        args.insert(2, str(explicit))
    return gh_json(*args)


def required_contexts(base: str) -> set[str]:
    """Contexts the base branch's ruleset requires, falling back to main's.

    A stacked PR's base carries no ruleset of its own, but the change is still
    bound for main, so main's list is the gate that will actually apply to it.
    """
    for branch in (base, "main"):
        for rule in gh_json("api", f"repos/{{owner}}/{{repo}}/rules/branches/{branch}") or []:
            if rule.get("type") == "required_status_checks":
                checks = rule["parameters"]["required_status_checks"]
                return {c["context"] for c in checks}
    return set()


def check_states(rollup: list[dict], required: set[str]) -> tuple[list[str], list[str]]:
    """Split the required checks into (still running, concluded but not passing)."""
    pending, failing = [], []
    for check in rollup or []:
        name = check.get("name") or check.get("context")
        if name not in required:
            continue
        if check.get("__typename") == "CheckRun":
            if check.get("status") != "COMPLETED":
                pending.append(name)
            elif check.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                failing.append(name)
        elif check.get("state") == "PENDING":
            pending.append(name)
        elif check.get("state") != "SUCCESS":
            failing.append(name)
    missing = required - {c.get("name") or c.get("context") for c in rollup or []}
    return pending + sorted(missing), failing


def codex_findings(number: int) -> list[str] | None:
    """Codex's review body and inline comments, or None if it has not posted.

    `gh pr checks` reports run status only. The findings live on the review and
    its inline comments, which is the half that has been missed before.
    """
    reviews = gh_pages(f"repos/{{owner}}/{{repo}}/pulls/{number}/reviews")
    if not any(r["user"]["login"] == CODEX_LOGIN for r in reviews):
        return None
    found = [r["body"].strip() for r in reviews if r["user"]["login"] == CODEX_LOGIN and r["body"].strip()]
    for c in gh_pages(f"repos/{{owner}}/{{repo}}/pulls/{number}/comments"):
        if c["user"]["login"] == CODEX_LOGIN:
            where = f"{c['path']}:{c.get('line') or c.get('original_line')}"
            found.append(f"{where}\n{c['body'].strip()}")
    return found


def minutes_since(timestamp: str) -> float:
    opened = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - opened).total_seconds() / 60


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pr", type=int, help="PR number (default: the current branch's PR)")
    parser.add_argument("--dry-run", action="store_true", help="Report without merging or arming")
    parser.add_argument("--no-merge", action="store_true", help="Wait and report only")
    parser.add_argument(
        "--timeout", type=int, default=TIMEOUT_MINUTES, help=f"Give up after N minutes (default {TIMEOUT_MINUTES})"
    )
    args = parser.parse_args()

    pr = resolve_pr(args.pr)
    number = pr["number"]
    print(f"#{number} {pr['title']}")
    print(f"  {pr['url']}  -> {pr['baseRefName']}")
    if pr["state"] != "OPEN":
        print(f"  already {pr['state'].lower()}; nothing to wait for")
        return 0

    required = required_contexts(pr["baseRefName"])
    print(f"  {len(required)} required check(s); Codex window closes {CODEX_WINDOW_MINUTES} min after open")

    deadline = time.monotonic() + args.timeout * 60
    findings, pending, failing = None, [], []
    while True:
        rollup = resolve_pr(number)["statusCheckRollup"]
        pending, failing = check_states(rollup, required)
        findings = codex_findings(number)
        window_closed = minutes_since(pr["createdAt"]) >= CODEX_WINDOW_MINUTES
        if failing or (not pending and (findings is not None or window_closed)):
            break
        if time.monotonic() > deadline:
            print(f"  timed out after {args.timeout} min waiting on: {', '.join(pending) or 'Codex'}")
            return 1
        waiting = ", ".join(pending) if pending else "Codex review"
        print(f"  waiting on {waiting}")
        time.sleep(POLL_SECONDS)

    if failing:
        print(f"\nFAILED: {', '.join(sorted(failing))}")
        return 1

    if findings is None:
        print("\nCodex did not review this PR (it reviews about half of them).")
    elif findings:
        print(f"\nCodex left {len(findings)} finding(s):\n")
        for item in findings:
            print(f"  {item}\n")
        print("Read these before merging. Nothing was merged.")
        return 2
    else:
        print("\nCodex reviewed with no findings.")

    if args.no_merge:
        print("--no-merge: stopping here.")
        return 0

    # Checks that are still running only reach here once the review window closed,
    # which is the one case auto-merge is for.
    merge = ["pr", "merge", str(number), MERGE_METHOD] + (["--auto"] if pending else [])
    if args.dry_run:
        print(f"[dry-run] would run: gh {' '.join(merge)}")
        return 0
    gh(*merge)
    print("armed auto-merge" if pending else "merged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
