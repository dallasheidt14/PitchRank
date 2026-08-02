"""Every workflow step that writes through the age-derivation scripts is frozen.

The Aug 2026 rollover splits one cutover across two clocks: the scripts derive a
cohort from the wall clock, while the labels are relabelled by hand. Between
those two moments a derived cohort and a stored label differ by one, and any step
that writes on that difference does permanent damage -- merging teams into the
wrong cohort, or creating duplicates of teams that already exist.

The freeze flag exists to hold those steps until both clocks agree. Two separate
review rounds each found a writing step that had been missed, so this pins the
invariant rather than the individual steps: name a new caller, or add a new
writing step to an existing one, and this test fails until it is gated too.
"""

import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"

FREEZE_FLAG = "AGE_ROLLOVER_FREEZE"
FREEZE_GATE = f"env.{FREEZE_FLAG} == 'false'"

# Scripts whose age derivation moves on the wall clock AND which are read-only
# until a flag opts in. A step running one of these writes only via WRITE_MARKERS.
AGE_DERIVING_SCRIPTS = (
    "find_queue_matches.py",
    "auto_match_unknown_opponents.py",
    "discover_teams_from_opponents.py",
)

# Scripts with no safe default: they write unless a flag opts OUT, or they exist
# solely to persist someone else's derivation. Running one at all is a write, so
# these must NOT be gated behind WRITE_MARKERS — keying on flag spelling is
# exactly how the first version of this file missed four live gates.
ALWAYS_WRITING_SCRIPTS = (
    "apply_unknown_opponent_matches.py",
    "fix_team_age_groups.py",
    "find_fuzzy_duplicate_teams.py",
    "extract_and_import_tgs_teams.py",
    # Game importers create unmatched teams through the provider matchers, using
    # an age the ETL pipeline derives from the wall clock. The derivation is not
    # visible in the invocation, so this list is the only thing that catches it.
    "import_games_enhanced.py",
)

# A run block writes when it can reach one of these. EXECUTE_FLAG is the repo's
# shell idiom for "--execute" assembled conditionally.
WRITE_MARKERS = ("--execute", "--yes", "--auto-merge", "EXECUTE_FLAG")

def _has_top_level_or(condition):
    """True when `||` appears outside every bracket and string in the expression.

    A nested `||` is the repo's default-value idiom — `inputs.skip_steps || ''`
    inside `!contains(...)` — and only narrows. A top-level one is an alternative
    path to running the step, which widens past the freeze.
    """
    expr = condition.strip().removeprefix("${{").removesuffix("}}")
    depth = 0
    quote = None
    i = 0
    while i < len(expr):
        char = expr[i]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "|" and expr[i : i + 2] == "||" and depth == 0:
            return True
        i += 1
    return False


# Steps deliberately left ungated, with the reason. Scraping and importing are one
# step here, so gating it would stop collection entirely rather than defer a write,
# and unlike the other importers there is no uploaded artifact to backfill from.
# The accepted risk is a new team created mid-rollover with a cohort one off.
# Exemptions are listed rather than silently skipped: an unlisted ungated step
# still fails, and a listed step that no longer exists fails too.
EXEMPT = {
    ("playmetrics-scrape-import.yml", "Scrape and Import PlayMetrics Leagues"),
}


def _workflow_files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _writing_steps():
    """Yield (workflow, step_name, if_expr) for every writing step, gated or not."""
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                run = step.get("run") or ""
                writes = any(s in run for s in ALWAYS_WRITING_SCRIPTS) or (
                    any(s in run for s in AGE_DERIVING_SCRIPTS)
                    and any(m in run for m in WRITE_MARKERS)
                )
                if not writes:
                    continue
                yield path.name, step.get("name", "<unnamed>"), step.get("if", "")


def test_the_scan_finds_the_known_writing_steps():
    """Guards the guard: a parser that silently matches nothing proves nothing."""
    found = list(_writing_steps())
    assert found, "no writing steps found — the scan is broken, not the workflows"
    workflows = {w for w, _, _ in found}
    assert "data-hygiene-weekly.yml" in workflows
    assert "auto-merge-queue.yml" in workflows


def test_every_exemption_still_exists():
    """A stale exemption is a hole nobody is watching."""
    found = {(w, s) for w, s, _ in _writing_steps()}
    missing = EXEMPT - found
    assert not missing, f"exempted steps no longer exist, drop them from EXEMPT: {missing}"


@pytest.mark.parametrize("workflow,step,condition", list(_writing_steps()))
def test_writing_step_is_gated_on_the_freeze(workflow, step, condition):
    if (workflow, step) in EXEMPT:
        pytest.skip(f"deliberately ungated: {workflow} :: {step}")
    assert FREEZE_GATE in condition, (
        f"{workflow} step {step!r} runs an age-deriving script with a write flag "
        f"but its `if:` does not contain `{FREEZE_GATE}`.\n"
        f"  if: {condition or '<none>'}\n"
        f"Until the relabel is applied and the flag lifted, this step can write "
        f"against labels that are one cohort out of step with what it derives."
    )


@pytest.mark.parametrize("workflow,step,condition", list(_writing_steps()))
def test_gate_is_not_bypassable_by_an_or(workflow, step, condition):
    """Presence of the gate is not the same as the gate controlling the step.

    `env.AGE_ROLLOVER_FREEZE == 'false' || github.event_name == 'schedule'`
    contains the gate and still runs on exactly the schedule the freeze exists
    to stop, so a substring assertion alone would accept it.
    """
    assert not _has_top_level_or(condition), (
        f"{workflow} step {step!r} joins the freeze gate to another condition with "
        f"a top-level `||`, so that condition can run the step while the flag is "
        f"still set.\n  if: {condition}"
    )


@pytest.mark.parametrize(
    "workflow",
    sorted({w for w, s, _ in _writing_steps() if (w, s) not in EXEMPT}),
)
def test_gating_workflow_declares_the_flag(workflow):
    """A gate referencing an undeclared flag reads as '' and silently stays shut.

    Scoped to workflows that actually gate something: one whose only writing step
    is exempt has nothing to declare.
    """
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    assert re.search(rf"^\s*{FREEZE_FLAG}:\s*'(true|false)'\s*$", text, re.MULTILINE), (
        f"{workflow} gates a step on {FREEZE_FLAG} but never declares it in an env: block"
    )
