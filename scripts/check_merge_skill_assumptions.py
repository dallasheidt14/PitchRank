#!/usr/bin/env python3
"""Assert the claims that .claude/skills/merging-duplicate-teams makes about this repo.

That skill governs a data-destroying write, and most of what it says is a claim about code
behaviour or row counts rather than a judgement. Prose claims cannot fail, so they rot
silently: the skill spent months telling operators the birth-year guard protected them while
the Monday normalizer was disarming it, and three fresh errors were introduced into it in the
hour it took to write the corrections.

This script makes those claims executable. Run it before trusting the skill.

ASSERTIONS fail the run. Each one is a behaviour the skill's guidance depends on, phrased so
that a fix to the underlying bug fails the check and sends you to the skill to update it.
A failure here does not mean the codebase is broken -- it means the skill is now wrong.

MEASUREMENTS never fail. They print current counts and warn when one has drifted far from the
figure the skill quotes, which is the signal to re-measure the prose.

Usage:
    python scripts/check_merge_skill_assumptions.py               # everything
    python scripts/check_merge_skill_assumptions.py --code-only   # no database
    python scripts/check_merge_skill_assumptions.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from supabase import create_client  # noqa: E402

SKILL_DIR = ROOT / ".claude" / "skills" / "merging-duplicate-teams"
WORKFLOW = ROOT / ".github" / "workflows" / "data-hygiene-weekly.yml"
ENQUEUE_MIGRATION = "20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql"

DRIFT_TOLERANCE = 0.20

# Figures quoted in the skill, with the date they were measured. Update both together.
RECORDED = {
    "live_teams": 200161,
    "null_club": 15046,
    "null_team_name_original": 90032,
    "u_label_no_year": 20146,
    "u19_guard_blind": 5848,
    "protected_division_rows": 4823,
    "gender_word_year_rows": 2953,
}
RECORDED_ON = "2026-08-27"


@dataclass
class Result:
    assertions: list[dict] = field(default_factory=list)
    measurements: list[dict] = field(default_factory=list)
    manual: list[dict] = field(default_factory=list)

    def check(self, name, ok, detail):
        self.assertions.append({"name": name, "ok": bool(ok), "detail": detail})

    def needs_human(self, name, detail):
        """A claim this script could not establish either way. Never counts as holding."""
        self.manual.append({"name": name, "detail": detail})

    def measure(self, name, value):
        recorded = RECORDED.get(name)
        drift = None
        if recorded:
            drift = (value - recorded) / recorded
        self.measurements.append({"name": name, "value": value, "recorded": recorded, "drift": drift})

    @property
    def failures(self):
        return [a for a in self.assertions if not a["ok"]]

    @property
    def drifted(self):
        return [m for m in self.measurements if m["drift"] is not None and abs(m["drift"]) > DRIFT_TOLERANCE]


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. Note that "
            "decide_team_merges.py and apply_vetted_team_merges.py read .env.local, which "
            "does not exist here -- the keys live in root .env."
        )
    return create_client(url, key)


def count(sb, table, apply_filters=None) -> int:
    q = sb.table(table).select("team_id_master", count="exact", head=True)
    if apply_filters:
        q = apply_filters(q)
    return q.execute().count or 0


def check_birth_year_guard(r: Result) -> None:
    """The guard the skill leans on, and the three ways it goes silent."""
    from src.utils.team_name_utils import birth_years, birth_years_conflict

    r.check(
        "birth_years reads an explicit four-digit year",
        birth_years("Club 2008 Red") == {2008},
        f"birth_years('Club 2008 Red') -> {sorted(birth_years('Club 2008 Red'))}",
    )
    r.check(
        "birth_years is blind to a U-label (skill: the normalizer creates these weekly)",
        birth_years("Club U19 Red") == set(),
        f"birth_years('Club U19 Red') -> {sorted(birth_years('Club U19 Red'))}",
    )
    r.check(
        "birth_years_conflict stays silent on U-label vs either u19 birth year",
        not birth_years_conflict("Club U19 Red", "Club 2008 Red")
        and not birth_years_conflict("Club U19 Red", "Club 2009 Red"),
        "conflict('Club U19 Red', 'Club 2008 Red') and ..2009 both False",
    )
    r.check(
        "birth_years still reads nothing from the 'NN Boys' form (_GENDER_WORD dead branch)",
        birth_years("Club 12 Boys") == set(),
        f"birth_years('Club 12 Boys') -> {sorted(birth_years('Club 12 Boys'))}",
    )
    r.check(
        "birth_years_conflict fires when both sides state a year",
        birth_years_conflict("EPIC SC 2008 Dash", "EPIC SC 2009 Dash"),
        "conflict('EPIC SC 2008 Dash', 'EPIC SC 2009 Dash') is True",
    )


def check_protected_division(r: Result) -> None:
    """AD/HD/EA are matched as tokens, so East/Eagles names reach the scan (IMP-135)."""
    from scripts.find_queue_matches import has_protected_division

    r.check(
        "EAST/EAGLES names are no longer withheld as a protected division",
        not has_protected_division("FC EAST 2012") and not has_protected_division("SC EAGLES 2013"),
        "has_protected_division('FC EAST 2012') and ('SC EAGLES 2013') both False",
    )
    r.check(
        "the exclusion is no longer position-dependent",
        not has_protected_division("EAST MEADOW 2012"),
        "has_protected_division('EAST MEADOW 2012') is False",
    )
    r.check(
        "a real EA division marker keeps its protection",
        has_protected_division("Club EA 2013") and has_protected_division("Dallas Hornets North U15 AD"),
        "has_protected_division('Club EA 2013') and ('... U15 AD') both True",
    )


def check_normalizer_launders_names(r: Result) -> None:
    """Step 1 of the same weekly job erases the evidence the scan depends on."""
    from scripts.normalize_team_names import normalize_team_name

    older = normalize_team_name("EPIC SC B09/08 Dash", "EPIC SC", "u19")
    younger = normalize_team_name("EPIC SC B08/07 Dash", "EPIC SC", "u19")
    r.check(
        "two different u19 bands normalize to one identical token",
        older == younger,
        f"{older!r} == {younger!r}",
    )

    boys = normalize_team_name("Rush 14B Black", "Rush", "u13")
    girls = normalize_team_name("Rush 14G Black", "Rush", "u13")
    r.check(
        "the gender letter is erased, so two cohorts collide on one name",
        boys == girls,
        f"{boys!r} == {girls!r}",
    )


def check_precondition_compares_raw_strings(r: Result) -> None:
    """basics_disagree treats a NULL club as a value, in both directions."""
    from scripts.decide_team_merges import basics_disagree

    def evidence(club_a, club_b):
        row = {"state_code": "PA", "gender": "Female", "is_deprecated": False, "team_name": "x"}
        return {
            "teams": {
                "a": {**row, "club_name": club_a},
                "b": {**row, "club_name": club_b},
            }
        }

    pair = {"merge_id": "a", "keep_id": "b", "merge_name": "Squad 2012", "keep_name": "Squad 2012"}
    both_null = basics_disagree(pair, evidence(None, None))
    null_vs_named = basics_disagree(pair, evidence(None, "FC Delco"))

    r.check(
        "two NULL clubs compare equal and pass the precondition unchecked",
        both_null is None,
        f"basics_disagree(NULL, NULL) -> {both_null!r}",
    )
    r.check(
        "a NULL club is refused against a named one",
        null_vs_named is not None and "clubs differ" in null_vs_named,
        f"basics_disagree(NULL, 'FC Delco') -> {null_vs_named!r}",
    )


def check_scorer_backend(r: Result) -> None:
    """CI installs neither rapidfuzz nor thefuzz, so SequenceMatcher is the real scorer."""
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()
    r.check(
        "rapidfuzz is absent from requirements.lock, so CI scores with SequenceMatcher",
        "rapidfuzz" not in lock,
        "requirements.lock has no rapidfuzz entry",
    )


def check_workflow_flags(r: Result) -> None:
    """The weekly duplicate scan is off; the skill's re-enabling section assumes so."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for flag, expected in (
        ("FUZZY_AUTO_MERGE_ENABLED", "false"),
        ("AGE_DERIVATION_ENABLED", "false"),
        ("AGE_ROLLOVER_FREEZE", "false"),
    ):
        found = re.search(rf"^\s*{flag}:\s*'([^']*)'", text, re.M)
        value = found.group(1) if found else None
        r.check(
            f"{flag} is still {expected!r}",
            value == expected,
            f"{flag} = {value!r} in data-hygiene-weekly.yml",
        )


def check_enqueue_migration_unapplied(r: Result, sb) -> None:
    """Step 7 may only be skipped once this is applied to the database, not merely on disk."""
    on_disk = (ROOT / "supabase" / "migrations" / ENQUEUE_MIGRATION).exists()
    version = ENQUEUE_MIGRATION.split("_")[0]
    name = "Step 7 is still required (enqueue migration not applied)"
    try:
        rows = (
            sb.schema("supabase_migrations")
            .table("schema_migrations")
            .select("version")
            .eq("version", version)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001 - supabase/config.toml exposes only public schemas
        r.needs_human(
            name,
            f"file on disk: {on_disk}. Applied state UNVERIFIED: supabase_migrations is not "
            f"exposed through PostgREST ({type(exc).__name__}). Query schema_migrations for "
            f"version {version} directly before skipping Step 7.",
        )
        return

    r.check(name, not rows, f"file on disk: {on_disk}; applied: {bool(rows)}")


U_LABEL = re.compile(r"(^|[^a-zA-Z0-9])[uU]-?\d{1,2}([^a-zA-Z0-9]|$)")
FOUR_DIGIT_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
GENDER_WORD_YEAR = re.compile(r"(?<!\d)\d{2}\s+(boys|girls)(?![a-z])|(?<![a-z])(boys|girls)\s+\d{2}(?!\d)", re.I)


def measure_counts(r: Result, sb) -> None:
    """Cheap server-side counts, for the figures a plain operator can express."""
    r.measure("live_teams", count(sb, "teams", lambda q: q.eq("is_deprecated", False)))
    r.measure(
        "null_club",
        count(sb, "teams", lambda q: q.eq("is_deprecated", False).or_("club_name.is.null,club_name.eq.")),
    )
    r.measure(
        "null_team_name_original",
        count(sb, "teams", lambda q: q.eq("is_deprecated", False).is_("team_name_original", "null")),
    )


def measure_names(r: Result, sb) -> None:
    """One pass over every live name, scored with the same predicates the skill cites.

    Deliberately not PostgREST regex filters: these figures are the skill's evidence that a
    guard is blind, so they have to be produced by the guard itself rather than by a pattern
    that only resembles it.

    The .order() is load-bearing. PostgREST leaves row order unspecified without it, so paging
    200k rows silently duplicates and drops some -- which shifted this script's own u19 figure
    by 7% before the clause was added.
    """
    from scripts.find_queue_matches import has_protected_division
    from src.utils.team_name_utils import birth_years

    rows, off = [], 0
    while True:
        page = (
            sb.table("teams")
            .select("team_name,age_group")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(off, off + 999)
            .execute()
            .data
        ) or []
        rows += page
        if len(page) < 1000:
            break
        off += 1000

    names = [(row.get("team_name") or "", row.get("age_group") or "") for row in rows]
    u19 = [n for n, age in names if age == "u19"]

    r.measure("u_label_no_year", sum(1 for n, _ in names if U_LABEL.search(n) and not FOUR_DIGIT_YEAR.search(n)))
    r.measure("protected_division_rows", sum(1 for n, _ in names if has_protected_division(n)))
    r.measure("gender_word_year_rows", sum(1 for n, _ in names if GENDER_WORD_YEAR.search(n)))
    r.measure("u19_guard_blind", sum(1 for n in u19 if not birth_years(n)))
    r.measurements[-1]["of_total"] = len(u19)


def render(result: Result) -> None:
    print("\nASSERTIONS -- a failure means the skill is now wrong, not the code\n")
    for a in result.assertions:
        print(f"  [{'ok ' if a['ok'] else 'FAIL'}] {a['name']}")
        print(f"         {a['detail']}")

    if result.measurements:
        print(f"\nMEASUREMENTS -- skill quotes figures recorded {RECORDED_ON}\n")
        for m in result.measurements:
            line = f"  {m['name']:<26} {m['value']:>8,}"
            if m["recorded"]:
                line += f"   (skill says {m['recorded']:,}"
                line += f", drift {m['drift']:+.0%})" if m["drift"] is not None else ")"
            if "of_total" in m:
                line += f"   of {m['of_total']:,}"
            print(line)

    if result.drifted:
        print(f"\n  WARNING: {len(result.drifted)} figure(s) drifted past {DRIFT_TOLERANCE:.0%}.")
        print("  Re-measure and update the skill prose and RECORDED in this script together.")

    if result.manual:
        print("\nNOT VERIFIED -- this script could not establish these either way\n")
        for m in result.manual:
            print(f"  [??] {m['name']}")
            print(f"         {m['detail']}")

    if result.failures:
        print(f"\n{len(result.failures)} assertion(s) failed. Update the skill before relying on it:")
        for a in result.failures:
            print(f"  - {a['name']}")
    elif result.manual:
        print(
            f"\nEvery assertion checked holds, but {len(result.manual)} claim(s) went unverified. "
            "Confirm those by hand before relying on them."
        )
    else:
        print("\nAll assertions hold. The skill's claims still match the code.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code-only", action="store_true", help="skip every database check")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    result = Result()
    check_birth_year_guard(result)
    check_protected_division(result)
    check_normalizer_launders_names(result)
    check_precondition_compares_raw_strings(result)
    check_scorer_backend(result)
    check_workflow_flags(result)

    if not args.code_only:
        sb = get_client()
        check_enqueue_migration_unapplied(result, sb)
        measure_counts(result, sb)
        measure_names(result, sb)

    if args.json:
        print(
            json.dumps(
                {
                    "assertions": result.assertions,
                    "measurements": result.measurements,
                    "unverified": result.manual,
                },
                indent=2,
            )
        )
    else:
        render(result)

    return 1 if result.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
