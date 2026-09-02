#!/usr/bin/env python3
"""Assert the claims that .claude/skills/assigning-team-states makes about this repo.

That skill governs a write to a column the public state boards read, and most of what it
says is a claim about code behaviour or row counts rather than a judgement. Prose claims
cannot fail, so they rot silently.

This script makes those claims executable. Run it before trusting the skill.

ASSERTIONS fail the run. Each one is a behaviour the skill's guidance depends on, phrased
so that a fix to the underlying rule fails the check and sends you to the skill to update
it. A failure here does not mean the codebase is broken -- it means the skill is now wrong.

MEASUREMENTS never fail. They print current counts and warn when one has drifted far from
the figure the skill quotes, which is the signal to re-measure the prose.

Usage:
    python scripts/check_state_skill_assumptions.py               # everything
    python scripts/check_state_skill_assumptions.py --code-only   # no database
    python scripts/check_state_skill_assumptions.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from supabase import create_client  # noqa: E402

SKILL_DIR = ROOT / ".claude" / "skills" / "assigning-team-states"
WORKFLOW = ROOT / ".github" / "workflows" / "update-missing-club-and-state.yml"

DRIFT_TOLERANCE = 0.20

# Figures quoted in the skill, with the date they were measured. Update both together.
RECORDED = {
    "live_teams": 201032,
    "teams_without_state": 2221,
    "stateless_and_visible": 0,
    "registry_entries": 69,
    "registry_curated": 24,
    "ledger_rows": 8902,
    "queue_pending": 1838,
    # SKILL.md Step 2a is where these are maintained. They fall toward zero as the audit
    # runs in earnest, which is why they need watching at all: prose that can only get more
    # wrong reads exactly like prose that is right.
    "audit_candidates": 1173,
    "audit_candidates_with_alias": 1124,
}
RECORDED_ON = "2026-09-01"

# The four homes the operator confirmed by hand, blind to the analysis, on 2026-08-28.
# The only external ground truth this problem has.
CONFIRMED_HOMES = {
    "arizona arsenal soccer club": "AZ",
    "city sc": "CA",
    "soccer chance academy": "OR",
    "steel city fc": "PA",
}


@dataclass
class Result:
    assertions: list[dict] = field(default_factory=list)
    measurements: list[dict] = field(default_factory=list)

    def check(self, name, ok, detail):
        self.assertions.append({"name": name, "ok": bool(ok), "detail": detail})

    def measure(self, name, value):
        recorded = RECORDED.get(name)
        drift = (value - recorded) / recorded if recorded else None
        self.measurements.append(
            {"name": name, "value": value, "recorded": recorded, "drift": drift}
        )

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
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (root .env).")
    return create_client(url, key)


def _team(**fields):
    base = {"team_id_master": "t", "team_name": "", "club_name": "", "state_code": None, "state": None}
    base.update(fields)
    return base


def check_registry(r: Result) -> None:
    """The curated registry, and the two fields that decide what happens to a club."""
    from src.utils.club_state_registry import CLUBS, home_state, requires_review

    curated = [key for key, entry in CLUBS.items() if entry["curate"]]
    homed = [key for key, entry in CLUBS.items() if entry["home"]]

    r.check(
        "every curated club withholds a home (curate and home are exclusive)",
        all(CLUBS[key]["home"] is None for key in curated),
        f"{len(curated)} curated, none carrying a home",
    )
    r.check(
        "every homed club auto-applies (skill: 45 clubs settle without a person)",
        all(not CLUBS[key]["curate"] for key in homed),
        f"{len(homed)} homed, none marked curate",
    )
    r.check(
        "curated plus homed accounts for every entry",
        len(curated) + len(homed) == len(CLUBS),
        f"{len(curated)} + {len(homed)} == {len(CLUBS)}",
    )
    for club, want in CONFIRMED_HOMES.items():
        r.check(
            f"operator-confirmed home holds: {club} -> {want}",
            home_state(club) == want,
            f"home_state({club!r}) -> {home_state(club)!r}",
        )
    r.check(
        "the key ignores case and surrounding space",
        home_state("  Steel City FC  ") == "PA",
        "home_state('  Steel City FC  ') -> PA",
    )
    r.check(
        "a club with no entry gets no home and no review requirement",
        home_state("a club that does not exist") is None
        and requires_review("a club that does not exist") is False,
        "unknown club -> (None, False)",
    )


def check_association_map(r: Result) -> None:
    """The association is a registration code, not a postal one."""
    from src.utils.team_association_map import to_state_code

    r.check(
        "CAN is California North, not Canada",
        to_state_code("CAN") == "CA",
        f"to_state_code('CAN') -> {to_state_code('CAN')!r}",
    )
    r.check(
        "a Canadian province does not fire the tier",
        to_state_code("ON") is None and to_state_code("CND") is None,
        "to_state_code('ON') and ('CND') -> None",
    )
    r.check(
        "an unseen code fails closed rather than passing itself through",
        to_state_code("ZZ") is None and to_state_code("QQ") is None,
        "to_state_code('ZZ') and ('QQ') -> None",
    )
    r.check(
        "a national body names no state, however often it is seen",
        to_state_code("USA") is None,
        "to_state_code('USA') -> None (a real code, but not a state)",
    )


def check_name_reading(r: Result) -> None:
    """The state-name tier, whose false friends are soccer vocabulary."""
    from scripts.backfill_state_from_team_name import state_from_name

    r.check(
        "SC in a name is Soccer Club, not South Carolina",
        state_from_name("California Athletic SC") == "CA",
        f"state_from_name('California Athletic SC') -> {state_from_name('California Athletic SC')!r}",
    )
    r.check(
        "two states in one name is a fixture, not a home",
        state_from_name("Texas Oklahoma Cup") is None,
        "state_from_name('Texas Oklahoma Cup') -> None",
    )
    r.check(
        "an affiliate marker that contradicts the name refuses rather than picks",
        state_from_name("Utah Royals FC-AZ") is None,
        "state_from_name('Utah Royals FC-AZ') -> None",
    )


def check_decision_rules(r: Result) -> None:
    """The rules the skill tells an operator to rely on, driven through the real code."""
    from scripts.assign_team_states import decide

    # fc stars is curated. Its single meaningful state is the point: the tier fires and
    # the curation is what stops it, rather than the club being undecidable anyway.
    club_index = {"clean club": Counter({"OH": 40}), "fc stars": Counter({"MA": 284})}
    locality = {"boise": "ID"}

    r.check(
        "a stored Canadian province is never corrected",
        decide(_team(state_code="ON", club_name="clean club"), club_index, {}, {}, set()) is None,
        "an ON team in an OH club -> no decision",
    )
    r.check(
        "a fill from the club auto-applies",
        (decide(_team(club_name="clean club"), club_index, {}, {}, set()) or {}).get("action") == "apply",
        "no state, club says OH -> apply",
    )
    r.check(
        "a curated club queues rather than applying",
        (decide(_team(club_name="fc stars"), club_index, {}, {}, set()) or {}).get("action") == "queue",
        "no state, curated club -> queue",
    )
    r.check(
        "a correction from the team's own name never auto-applies",
        (
            decide(_team(state_code="NY", team_name="Michigan Wolves 19"), {}, {}, {}, set()) or {}
        ).get("action")
        == "queue",
        "NY team named Michigan -> queue, not apply",
    )
    r.check(
        "a correction over a reported state queues even from the club",
        (
            decide(
                _team(state_code="RI", state="Rhode Island", club_name="clean club"),
                club_index, {}, {}, set(),
            )
            or {}
        ).get("action")
        == "queue",
        "club says OH but the state was reported -> queue",
    )
    boise = decide(
        _team(state_code="WY", team_name="BTT 17 Boise Timbers", club_name="boise club"),
        {"boise club": Counter({"WY": 5})},
        locality,
        {},
        set(),
    )
    r.check(
        "a place in the name that contradicts the club stops the write",
        (boise or {}).get("action") == "queue" and (boise or {}).get("tier") == "R9",
        f"club says WY, name says Boise -> {(boise or {}).get('action')} at tier {(boise or {}).get('tier')}",
    )
    r.check(
        "the provider record settles that disagreement instead of queueing it",
        (
            decide(
                _team(state_code="WY", team_name="BTT 17 Boise Timbers", club_name="boise club"),
                {"boise club": Counter({"WY": 5})},
                locality,
                {"t": "ID"},
                set(),
            )
            or {}
        ).get("proposed")
        == "ID",
        "same team with an association of ID -> proposes ID",
    )
    r.check(
        "a value the operator already reverted is not re-applied",
        (
            decide(_team(club_name="clean club"), club_index, {}, {}, {("t", "OH")}) or {}
        ).get("action")
        == "queue",
        "club says OH, ledger holds a revert away from OH -> queue",
    )


def check_audit_selection(r: Result) -> None:
    """The audit reaches a team no free tier disputes, which is its whole reason to exist.

    The skill tells an operator this tier is no longer probed only for teams something
    else already flagged. That claim is only true while candidate selection is driven by
    the provider-confirmed anchor rather than by the tiers.
    """
    from scripts.assign_team_states import (
        TIER_A_SOURCE,
        build_anchor_index,
        build_club_index,
        contradiction_candidates,
        decide,
    )

    confirmed = _team(club_name="clean club", state_code="OH", state_source=TIER_A_SOURCE)
    mislabelled = _team(club_name="clean club", state_code="WY", team_id_master="quiet")
    # One population for both halves. Proving "quiet" against a hand-built Counter and
    # "selected" against a different team list would let either half drift into describing
    # a club the other never contained -- which is how the claim reads true while the two
    # facts stop being about the same thing.
    teams = (
        [dict(confirmed, team_id_master=f"a{i}") for i in range(2)]
        + [dict(mislabelled, team_id_master=f"w{i}") for i in range(4)]
        + [mislabelled]
    )

    r.check(
        "no free tier disputes a team its whole club agrees with",
        decide(mislabelled, build_club_index(teams), {}, {}, set()) is None,
        "club of 5 WY against 2 confirmed OH, team WY -> no tier fires",
    )
    r.check(
        "the audit selects that team anyway, from the confirmed club-mate",
        [t for t, _ in contradiction_candidates(teams, build_anchor_index(teams))]
        == ["quiet", "w0", "w1", "w2", "w3"],
        "two club-mates confirmed OH, five WY teams -> all five selected",
    )


def check_workflow_retired(r: Result) -> None:
    """Every state-writing step of the weekly chain is off, or this tool has a rival."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = list(workflow["jobs"].values())[0]["steps"]
    state_steps = {
        name: step.get("if")
        for step in steps
        for name in [step.get("name", "")]
        if "state_code" in name
    }
    off = {name: value for name, value in state_steps.items() if value is False}
    r.check(
        "all four state-writing steps are disabled",
        len(state_steps) == 4 and len(off) == 4,
        f"{len(off)} of {len(state_steps)} off: {sorted(off)}",
    )


def measure(r: Result, sb) -> None:
    from src.utils.club_state_registry import CLUBS

    r.measure("registry_entries", len(CLUBS))
    r.measure("registry_curated", sum(1 for entry in CLUBS.values() if entry["curate"]))

    r.measure(
        "live_teams",
        sb.table("teams").select("team_id_master", count="exact", head=True)
        .eq("is_deprecated", False).execute().count or 0,
    )
    stateless = (
        sb.table("teams").select("team_id_master", count="exact", head=True)
        .eq("is_deprecated", False).is_("state_code", "null").execute().count or 0
    )
    r.measure("teams_without_state", stateless)
    r.measure(
        "ledger_rows",
        sb.table("team_state_audit").select("id", count="exact", head=True).execute().count or 0,
    )
    r.measure(
        "queue_pending",
        sb.table("team_state_review_queue").select("id", count="exact", head=True)
        .eq("status", "pending").execute().count or 0,
    )

    # The count that matters most: teams a visitor sees on a state board with no state.
    ids = []
    offset = 0
    while True:
        page = (
            sb.table("teams").select("team_id_master")
            .eq("is_deprecated", False).is_("state_code", "null")
            .range(offset, offset + 999).execute()
        )
        ids.extend(row["team_id_master"] for row in page.data or [])
        if len(page.data or []) < 1000:
            break
        offset += 1000
    visible = 0
    for start in range(0, len(ids), 100):
        page = (
            sb.table("rankings_full").select("team_id", count="exact", head=True)
            .eq("status", "Active").in_("team_id", ids[start : start + 100]).execute()
        )
        visible += page.count or 0
    r.measure("stateless_and_visible", visible)

    # The audit's own population, measured the way the tool measures it: the real selector
    # over the real table, not a query that reimplements the rule and drifts from it.
    from scripts.assign_team_states import (
        build_anchor_index,
        contradiction_candidates,
        fetch_gotsport_aliases,
        fetch_live_teams,
    )

    teams = fetch_live_teams(sb)
    candidates = [t for t, _ in contradiction_candidates(teams, build_anchor_index(teams))]
    r.measure("audit_candidates", len(candidates))
    r.measure("audit_candidates_with_alias", len(fetch_gotsport_aliases(sb, candidates)))


def render(result: Result) -> None:
    print("\nASSERTIONS -- a failure means the skill is now wrong, not the codebase\n")
    for item in result.assertions:
        print(f"  {'PASS' if item['ok'] else 'FAIL'}  {item['name']}")
        if not item["ok"]:
            print(f"        {item['detail']}")

    if result.measurements:
        print(f"\nMEASUREMENTS -- figures the skill quotes, recorded {RECORDED_ON}\n")
        for item in result.measurements:
            drift = ""
            if item["drift"] is not None:
                marker = "  DRIFTED" if abs(item["drift"]) > DRIFT_TOLERANCE else ""
                drift = f"  (skill says {item['recorded']:,}, {item['drift']:+.0%}){marker}"
            print(f"  {item['name']:26s} {item['value']:>10,}{drift}")

    print()
    if result.failures:
        print(f"{len(result.failures)} assertion(s) failed. Update the skill to match the code.")
    else:
        print("Every assertion holds.")
    if result.drifted:
        print(f"{len(result.drifted)} measurement(s) drifted past {DRIFT_TOLERANCE:.0%}. Re-measure the prose.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the state-assignment skill's claims")
    parser.add_argument("--code-only", action="store_true", help="Skip everything that needs the database")
    parser.add_argument("--json", action="store_true", help="Emit the raw result")
    args = parser.parse_args()

    result = Result()
    check_registry(result)
    check_association_map(result)
    check_name_reading(result)
    check_decision_rules(result)
    check_audit_selection(result)
    check_workflow_retired(result)

    if not args.code_only:
        measure(result, get_client())

    if args.json:
        print(json.dumps({"assertions": result.assertions, "measurements": result.measurements}, indent=1))
    else:
        render(result)
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
