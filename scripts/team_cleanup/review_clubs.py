#!/usr/bin/env python3
"""Review a weekly team-cleanup run's club-name guesses before its clubs page is built.

The club scan lists three kinds of guess it cannot approve on its own (the `Listed` tiers of the
normalizing-club-names skill): a capital the weekly cleanup once lowered (capital), the team name up to its
first age or level word (recased), and a club whose end in the team name the scan could not tell (unclear).
Reviewers judge each distinct change once, however many teams carry it, so the owner sees only the changes they
could not settle. The first run queues the review into <run>/clubs/review/; each run then reviews up to
RUN_SLICES of the slices still queued, the rest waiting for the next run:

  BRIEF.md, RECHECK.md      the reviewers' briefs, from assets/, with the lookup
  skill/                    the reviewers' rules: the normalizing-club-names skill's text as the run's checkout
                            held it, and VERSION naming which
  slice_NN.json             up to 50 changes, one row per team, each labelled with its change (C0001 ...)
  slice_NN.md               their evidence, one block per change
  slice_NN_review.json      each team with its change's final verdict (apply, hold or reject), which pages.py
                            routes by
  answers/                  a folder per reviewer, the failed attempts, and every reviewer's log

The review takes the changes the page would otherwise leave off as guesses, and any change of a trusted tier
the scan left unapproved because two sources disagree; never one proposing no club, nor one declined, stale,
moved or undone (page_caps.clubs.review changes a week). The reviewers are the duplicate review's, run the same
way (review_merges.py): a change they approve applies on its own, a reject a second reviewer with the opposite
prior upholds is recorded as declined, so the scan's guess stops coming back, and anything else is a hold, the
owner's card.

Without --execute it reads the guesses and says what it would do, writing nothing.

    python scripts/team_cleanup/review_clubs.py --run 2026-11-04-all --stage clubs
    python scripts/team_cleanup/review_clubs.py --run 2026-11-04-all --stage clubs --execute
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.team_cleanup import review_merges as rm  # noqa: E402
from scripts.team_cleanup.club_changes import CLUB_VERDICTS  # noqa: E402
from scripts.team_cleanup.decisions import APPLY  # noqa: E402
from scripts.team_cleanup.pages import Selection, select  # noqa: E402
from scripts.team_cleanup.pairs import HOLD, REJECT  # noqa: E402
from scripts.team_cleanup.propose_week import APPLIER_INPUTS, CLUBS, SWAPPED_CLUBS, _read_csv, step_log  # noqa: E402
from scripts.team_cleanup.review_lookup import by_state, state_label  # noqa: E402
from scripts.team_cleanup.run_store import CHANGE_REVIEW_KEYS, REVIEW_DIR, REVIEW_SUFFIX  # noqa: E402
from scripts.team_cleanup.sure import load_signals, sure_because  # noqa: E402
from src.tournaments.storage._io import read_json, write_json  # noqa: E402

BRIEFS = {"BRIEF.md": rm.ASSETS / "club_review_brief.md", "RECHECK.md": rm.ASSETS / "club_recheck_brief.md"}
CLUB_SKILL = "normalizing-club-names"
SLICE_ITEMS = 50
SAMPLE_TEAMS = 8
# Club names run long, so a spelling count asks for a few at a time to keep the URL short.
SPELLING_BATCH = 20
CONFLICT = re.compile(r"^\s*CONFLICT (\S+): (.+) -- left for review, not approved$")
HOW = {
    "capital": "the weekly club cleanup once renamed the proposed spelling to the stored one, changing only its "
    "case, on every team of the state holding it; this restores the spelling it replaced",
    "recased": "the team name up to its first age or level word, where the stored club no longer matches it; "
    "a squad label reads the same way",
    "unclear": "the team name up to where the scan guessed the club ends; it could not tell",
}
TRUSTED_HOW = "a tier the scan trusts, left unapproved because two sources disagree"


# --- choosing the changes ---------------------------------------------------------------------------


def conflicts(folder: Path) -> dict[str, str]:
    """{team: the offers two sources made} for each team the scan left unapproved because they disagree, from the
    club scan's log, the stage's one proposal step; none when the log is gone."""
    path = step_log(folder, 1, SWAPPED_CLUBS)
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := CONFLICT.match(line):
            found[m.group(1)] = m.group(2)
    return found


def review_changes(sb, folder: Path, cap: int) -> tuple[list[dict], Selection]:
    """The team rows the review takes, in the order the page's caps keep them, each labelled with its change:
    every row of one identical change shares a label, a team whose sources disagree has a label of its own, and the
    cap counts changes, so it never cuts one in half. None the rules settle or an undo reversed."""
    chosen = select(sb, folder, CLUBS, True)
    signals = load_signals(sb, CLUBS, folder, chosen.shown, None, chosen.canonical)
    disputed = conflicts(folder)
    items: dict[tuple, list[dict]] = {}
    for p in chosen.shown:
        undone = (p["team_id_master"], p["field"], p["new_value"]) in signals.reverted
        if undone or sure_because(CLUBS, p, signals):
            continue
        key = (p["team_id_master"],) if p["team_id_master"] in disputed else (p["old_value"], p["new_value"])
        items.setdefault(key, []).append(p)
    rows = []
    for n, group in enumerate(list(items.values())[:cap], 1):
        rows += [{**p, "item": f"C{n:04d}"} for p in group]
    return rows, chosen


def items_of(rows: list[dict]) -> list[list[dict]]:
    """The rows grouped by their change, in order."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["item"], []).append(row)
    return list(grouped.values())


# --- the evidence pack ------------------------------------------------------------------------------


def spelling_counts(sb, names) -> dict[str, Counter]:
    """{club name: live teams holding exactly it, by state}. postgrest-py quotes a list value holding a comma, colon
    or bracket but escapes no double quote or backslash inside one, so a name holding either is asked for alone."""
    names = sorted({n for n in names if n})
    counts: dict[str, Counter] = defaultdict(Counter)
    cols = "team_id_master,club_name,state_code"

    def live(query):
        return query.eq("is_deprecated", False)

    plain = [n for n in names if '"' not in n and "\\" not in n]
    rows = []
    for batch in batched(plain, SPELLING_BATCH):
        rows += page(lambda b=batch: live(sb.table("teams").select(cols).in_("club_name", b)), "team_id_master")
    for name in (n for n in names if '"' in n or "\\" in n):
        rows += page(lambda n=name: live(sb.table("teams").select(cols).eq("club_name", n)), "team_id_master")
    for row in rows:
        counts[row["club_name"]][state_label(row["state_code"])] += 1
    return counts


def evidence_blocks(sb, rows: list[dict], chosen: Selection, folder: Path) -> list[str]:
    """Each change's evidence as a reviewer reads it, in the changes' order, each name the reviewer copies into
    its answer written as a JSON string. A scan that proposed nothing leaves no applier input to read notes from."""
    if not rows:
        return []
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    groups = items_of(rows)
    spellings = spelling_counts(sb, [v for g in groups for v in (g[0]["old_value"], g[0]["new_value"])])
    notes = {
        row["team_id_master"]: row["state_note"]
        for row in _read_csv(folder / APPLIER_INPUTS[CLUBS])
        if row.get("state_note")
    }
    disputed = conflicts(folder)
    blocks = []
    for group in groups:
        first = group[0]
        old, new = first["old_value"], first["new_value"]
        teams = [chosen.teams[p["team_id_master"]] for p in group]
        states = Counter(state_label(t["state_code"]) for t in teams)
        tiers = Counter(f"{p['tier']} ({p['source']})" for p in group)
        lines = [
            f"## {first['item']} {json.dumps(old)} -> {json.dumps(new)}",
            f"{len(group)} team(s): {by_state(states)} | tier {', '.join(f'{t} x{n}' for t, n in tiers.items())} "
            f"| needs review: {'yes' if any(p['needs_review'] for p in group) else 'no'}",
            f"how it was proposed: {HOW.get(first['tier'], TRUSTED_HOW)}",
            f"live teams holding {json.dumps(old)}: {by_state(spellings.get(old, Counter()))} "
            f"(this change covers {len(group)} of {sum(spellings.get(old, Counter()).values())})",
            f"live teams already holding {json.dumps(new)}: {by_state(spellings.get(new, Counter()))}",
        ]
        for p in group:
            if p["team_id_master"] in disputed:
                lines.append(f"two sources disagree on {p['team_id_master']}: {disputed[p['team_id_master']]}")
        noted = sorted({notes[p["team_id_master"]] for p in group if p["team_id_master"] in notes})
        if noted:
            lines.append(f"state notes (not fixed here): {'; '.join(noted)}")
        lines.append(f"teams ({min(len(group), SAMPLE_TEAMS)} of {len(group)}):")
        for t in teams[:SAMPLE_TEAMS]:
            lines.append(
                f"   {providers.get(t['provider_id'], '?')} {state_label(t['state_code'])} {t['age_group']} "
                f"{t['gender']} | {t['team_name']!r} | registered: {t['team_name_original']!r}"
            )
        blocks.append("\n".join(lines) + "\n")
    return blocks


# --- queueing --------------------------------------------------------------------------------------


def render_brief(text: str) -> str:
    return text.replace("{lookup}", rm.LOOKUP)


def queue(sb, folder: Path, cap: int) -> tuple[int, int]:
    """Write the review's slices and briefs; (changes queued, their teams). A review of no change still leaves
    the folder, so the autopilot moves on to the page, which then has no review to route by. A change never
    splits across slices."""
    rows, chosen = review_changes(sb, folder, cap)
    groups = items_of(rows)
    blocks = evidence_blocks(sb, rows, chosen, folder)
    review = folder / REVIEW_DIR
    (review / rm.ANSWERS_DIR).mkdir(parents=True, exist_ok=True)
    for name, source in BRIEFS.items():
        (review / name).write_text(render_brief(source.read_text(encoding="utf-8")), encoding="utf-8")
    rm.pack_skill(review, CLUB_SKILL)
    for n, start in enumerate(range(0, len(groups), SLICE_ITEMS), 1):
        name = rm.slice_name(n)
        (review / f"{name}.md").write_text("\n".join(blocks[start : start + SLICE_ITEMS]), encoding="utf-8")
        write_json(review / f"{name}.json", [row for g in groups[start : start + SLICE_ITEMS] for row in g], indent=1)
    return len(groups), len(rows)


# --- answers ---------------------------------------------------------------------------------------


def read_verdicts(path: Path, rows: list[dict]) -> list[dict]:
    """The reviewer's answer, one valid verdict per change of the slice in its order, or ValueError."""
    answers = json.loads(path.read_text(encoding="utf-8"))
    groups = items_of(rows)
    if not isinstance(answers, list) or len(answers) != len(groups):
        raise ValueError(f"{path.name} does not hold one answer per change of the slice")
    for group, answer in zip(groups, answers):
        first = group[0]
        if not isinstance(answer, dict) or any(answer.get(k) != first[k] for k in ("item", "old_value", "new_value")):
            raise ValueError(f"{path.name} does not answer {first['item']} in its place")
        if answer.get("verdict") not in CLUB_VERDICTS:
            raise ValueError(f"{path.name} gives {first['item']} a verdict the brief does not allow")
        reason = answer.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path.name} gives {first['item']} no reason")
    return answers


def final_rows(rows: list[dict], verdicts: list[dict], recheck: dict[str, dict]) -> list[dict]:
    """Each team with its change's final verdict: a reject the second reviewer did not uphold is a hold."""
    final = {}
    for answer in verdicts:
        verdict, reason = answer["verdict"], answer["reason"].strip()
        if verdict == REJECT:
            second = recheck.get(answer["item"])
            if second is None or not second["upheld"]:
                verdict = HOLD
                answered = f": {second['reason'].strip()}" if second else ""
                reason = f"one reviewer found the stored club right ({reason}), and a second did not uphold it"
                reason += answered
        final[answer["item"]] = (verdict, reason)
    return [{**row, "verdict": final[row["item"]][0], "reason": final[row["item"]][1]} for row in rows]


def held_rows(rows: list[dict], why: str) -> list[dict]:
    return [{**row, "verdict": HOLD, "reason": why} for row in rows]


ITEMS = rm.Kind(CHANGE_REVIEW_KEYS, "item", "changes", read_verdicts, final_rows, held_rows)


def counts(review: Path) -> Counter:
    """How many changes the review gave each verdict, counting a change once however many teams it holds."""
    verdicts = {}
    for path in review.glob(f"*{REVIEW_SUFFIX}"):
        for row in read_json(path):
            verdicts[path.name, row["item"]] = row["verdict"]
    return Counter(verdicts.values())


def main() -> int:
    def plan(folder: Path, cap: int) -> str:
        rows, _ = review_changes(get_client(), folder, cap)
        return f"{len(items_of(rows))} change(s) of {len(rows)} team(s) for review, {SLICE_ITEMS} changes a reviewer"

    def tally(review: Path) -> str:
        found = counts(review)
        rules = rm.skill_version(review) or "the brief alone"
        return f"reviewed changes: {found[APPLY]} apply, {found[HOLD]} hold, {found[REJECT]} reject, judged by {rules}"

    def queued(folder: Path, cap: int) -> str:
        changes, teams = queue(get_client(), folder, cap)
        return f"{changes} change(s) of {teams} team(s)"

    return rm.review_main(__doc__, CLUBS, "the club-name guesses", ITEMS, plan, queued, tally)


if __name__ == "__main__":
    raise SystemExit(main())
