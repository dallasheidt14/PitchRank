"""A command substitution under `set -o pipefail` must not be able to kill its step.

GitHub runs a `run:` block under `bash -e`. Inside a step that has enabled
`pipefail`, a pipeline whose grep finds nothing exits 1, the pipeline takes that
status, and `bash -e` ends the step **at the assignment** — so the `${VAR:-0}`
default on the next line never runs, the `$GITHUB_OUTPUT` write is skipped, and a
run that actually succeeded is reported as a failure.

That is not hypothetical: `data-hygiene-weekly.yml` Step 1b went red whenever its
backfill had nothing to report, and `refresh-team-scrape-activity.yml` carries the
fix and the reasoning in a comment.

Either `|| true` or `|| echo "0"` closes it, and both are in use here. `||` binds
looser than `|`, so `cmd1 | cmd2 || echo 0` is `(cmd1 | cmd2) || echo 0` and the
or-else runs on the whole pipeline's status. The two differ only in what the
variable then holds, which is why the `|| true` sites pair with a `${VAR:-0}`
default. What strands a step is a piped substitution with no or-else at all.

The file list is derived by globbing, never enumerated, so a workflow added
tomorrow is covered without anyone remembering to list it.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

_SUBSTITUTION = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)=\$\((.+)\)\s*$", re.M)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def _steps(text: str) -> list[str]:
    """The workflow split into steps, so pipefail is attributed to the step that sets it."""
    return re.split(r"\n(?=      - name:)", text)


def has_fallback(body: str) -> bool:
    """True when an or-else catches the pipeline's status before `bash -e` sees it.

    `||` binds looser than `|`, so `cmd1 | cmd2 || echo 0` is
    `(cmd1 | cmd2) || echo 0` -- the or-else runs on the pipeline's non-zero
    status and the substitution ends at 0 either way. So `|| echo "0"` is as
    sound a guard as `|| true` here; the difference is only what the variable
    then holds, which is why the `|| true` sites pair with a `${VAR:-0}` default
    and the `|| echo "0"` sites do not need one.
    """
    return "||" in _QUOTED.sub("", body)


def has_shell_pipe(body: str) -> bool:
    """True when `body` pipes one command into another.

    Two things that look like pipes and are not, both live in this repo's
    workflows: a `|` inside a quoted grep pattern (`'(Would update|Updated)'`),
    and the `||` of an or-else. Counting either would condemn assignments that
    are already correct -- a bare `grep ... || echo 0` cannot strand its step,
    because there is no pipeline for pipefail to take a status from.
    """
    bare = _QUOTED.sub("", body).replace("||", "")
    return "|" in bare


def _unguarded() -> list[str]:
    findings = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for step in _steps(text):
            if "set -o pipefail" not in step:
                continue
            for match in _SUBSTITUTION.finditer(step):
                variable, body = match.group(1), match.group(2)
                if not has_shell_pipe(body) or has_fallback(body):
                    continue
                findings.append(f"{path.name}: {variable}=$({body.strip()})")
    return findings


def test_no_piped_substitution_under_pipefail_is_left_unguarded():
    unguarded = _unguarded()

    assert unguarded == [], (
        "these assignments end their step when the pipeline finds nothing, "
        "skipping the $GITHUB_OUTPUT write that follows:\n  " + "\n  ".join(unguarded)
    )


def test_the_scan_actually_sees_the_shape_it_is_guarding():
    """Without this the test above passes for a regex that matches nothing."""
    sample = """      - name: Step
        run: |
          set -o pipefail
          python thing.py 2>&1 | tee logs/x.log
          COUNT=$(grep -oP 'x: \\K\\d+' logs/x.log | tail -1)
          echo "count=${COUNT:-0}" >> $GITHUB_OUTPUT
"""
    match = _SUBSTITUTION.search(_steps(sample)[-1])

    assert match is not None, "the substitution regex no longer matches the shape it guards"
    assert has_shell_pipe(match.group(2))
    assert "|| true" not in match.group(2)


def test_either_fallback_form_is_accepted():
    """Both are in use across these workflows and both are sound."""
    for body in (
        "grep -oP 'x: \\K\\d+' logs/x.log | tail -1 || true",
        "grep -oP 'x: \\K\\d+' logs/x.log | tr -d ',' || echo \"0\"",
    ):
        assert has_shell_pipe(body), body
        assert has_fallback(body), body


def test_an_alternation_inside_a_quoted_pattern_is_not_a_pipe():
    """`grep -oP '(Would update|Updated): ...' log || echo 0` is already correct.

    Reading that `|` as a pipe would condemn eight assignments across two
    workflows that cannot strand their step, because no pipeline exists for
    pipefail to take a status from.
    """
    assert not has_shell_pipe("grep -oP '(Would update|Updated): \\K\\d+' logs/x.log || echo \"0\"")


def test_an_or_else_is_not_a_pipe():
    assert not has_shell_pipe("grep -oP 'a' x.log || grep -oP 'b' x.log || echo \"0\"")


def test_a_pipe_after_a_quoted_alternation_is_still_seen():
    """The exclusions must not blind the scan to a real pipe beside them."""
    assert has_shell_pipe("grep -oP '(a|b)' x.log | tr -d ',' || echo \"0\"")
