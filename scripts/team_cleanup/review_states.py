#!/usr/bin/env python3
"""Review a weekly team-cleanup run's state changes before its states page is built.

The states sweep (the assigning-team-states skill) proposes changes the weekly rules do not apply on their own:
corrections from a club's own count, fills and corrections it only queues for a person, and disagreements that
propose the state a team already holds. Reviewers judge each one by that skill, so the owner sees only the changes
they could not settle. The first run queues the review into <run>/states/review/; each run then reviews up to
RUN_SLICES of the slices still queued, the rest waiting for the next run:

  BRIEF.md, RECHECK.md      the reviewers' briefs, from assets/, with the lookup
  skill/                    the reviewers' rules: the assigning-team-states skill's text as the run's checkout held
                            it, SKILL.md and references/, and VERSION naming which
  slice_NN.json             up to 50 changes, one per team, each labelled (S0001 ...) with what its reviewer may
                            not answer and why
  slice_NN.md               their evidence, read with the full database key, since the public one the reviewers'
                            lookups hold cannot read GotSport's answers, the review queue, the state ledger or the
                            owner's earlier choices
  slice_NN_review.json      each change with its final verdict (apply, hold or reject), which pages.py routes by
  answers/                  a folder per reviewer, the failed attempts, and every reviewer's log

The review takes the changes the page would show as cards: never one the rules settle, nor one an undo reversed,
declined, stale or moved (page_caps.states.review changes a week). By the owner's rule (2026-10-29) a state is
settled unattended only by the owner's own answer or the team's or club's own name, so a reviewer may apply a
change only where the rules would apply it themselves and the name pass places the team there; never one the rules
only queue, whose approval the sweep would read as the owner's; and may not decline a blank state the rules would
fill, which the weekly fill job writes whatever is declined. Any such answer becomes a hold. A reject a second
reviewer with the opposite prior upholds is recorded as declined, so the change stops coming back; anything else
is a hold, the owner's card.

Without --execute it reads the changes and says what it would do, writing nothing.

    python scripts/team_cleanup/review_states.py --run 2026-11-04-all --stage states
    python scripts/team_cleanup/review_states.py --run 2026-11-04-all --stage states --execute
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.assign_team_states import PROBE_LOG_TABLE, club_key, fetch_state_sources  # noqa: E402
from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.hold_unsafe_state_applies import split  # noqa: E402
from scripts.team_cleanup import review_merges as rm  # noqa: E402
from scripts.team_cleanup.apply_stage import AUDIT_COLS, AUDIT_TABLE, QUEUE_TABLE, REVIEW_COLS  # noqa: E402
from scripts.team_cleanup.decisions import APPLY, DECISIONS_TABLE  # noqa: E402
from scripts.team_cleanup.pages import Selection, name_place, select  # noqa: E402
from scripts.team_cleanup.pairs import HOLD, REJECT  # noqa: E402
from scripts.team_cleanup.propose_week import APPLIER_INPUTS, STATES  # noqa: E402
from scripts.team_cleanup.review_lookup import state_label  # noqa: E402
from scripts.team_cleanup.run_store import CHANGE_REVIEW_KEYS, REVIEW_DIR, REVIEW_SUFFIX  # noqa: E402
from scripts.team_cleanup.state_changes import STATE_VERDICTS  # noqa: E402
from scripts.team_cleanup.sure import keeps_state, load_signals, read_state_evidence, sure_because  # noqa: E402
from src.tournaments.storage._io import read_json, write_json  # noqa: E402
from src.utils.club_state_registry import home_state, requires_review  # noqa: E402

BRIEFS = {"BRIEF.md": rm.ASSETS / "state_review_brief.md", "RECHECK.md": rm.ASSETS / "state_recheck_brief.md"}
STATE_SKILL = "assigning-team-states"
SLICE_ITEMS = 50
OWN_NAME = ("team", "club")
HISTORY_SHOWN = 5
DECISION_COLS = "id,team_id_master,proposed_value,decision,source,note,decided_at,superseded_at"
PROBE_COLS = "id,team_id_master,outcome,reported_state_code,probed_at"
NAME_SAYS = {
    "team": "the team name places it in {state}",
    "club": "the club name places it in {state}",
    "town": "only a town word points at {state}",
    "conflict": "its own words point two ways",
    "unplaced": "it names a state the name pass cannot place",
    "none": "nothing in its name places it",
}


# --- choosing the changes ---------------------------------------------------------------------------


def not_allowed(p: dict, reading: tuple[str | None, str]) -> dict[str, str]:
    """{verdict: why the reviewer may not give it} for the change: an apply the owner's rule withholds, and a
    decline the weekly fill job would ignore."""
    state, how = reading
    held_back = {}
    if p["action"] != "apply":
        held_back[APPLY] = "the rules only queued it, and an approval given unattended would count as the owner's"
    elif how not in OWN_NAME or state != p["new_value"]:
        held_back[APPLY] = f"nothing in its own name or its club's name places it in {p['new_value']}"
    if p["action"] == "apply" and not (p["old_value"] or "").strip():
        held_back[REJECT] = "the weekly fill job writes a blank state the rules fill, whatever is declined"
    return held_back


def review_changes(sb, folder: Path, cap: int) -> tuple[list[dict], Selection, object]:
    """The changes the review takes, in the order the page's caps keep them, each labelled with what its reviewer
    may not answer, and the states skill's evidence they were read with. None the rules settle or an undo
    reversed."""
    chosen = select(sb, folder, STATES)
    evidence = chosen.evidence or read_state_evidence(sb)
    signals = load_signals(sb, STATES, folder, chosen.shown, evidence, chosen.canonical)
    rows = []
    for p in chosen.shown:
        if (p["team_id_master"], p["field"], p["new_value"]) in signals.reverted or sure_because(STATES, p, signals):
            continue
        team = evidence.by_id.get(p["team_id_master"]) or chosen.teams[p["team_id_master"]]
        reading = name_place(team, evidence.locality_index)
        rows.append({**p, "item": f"S{len(rows) + 1:04d}", "not_allowed": not_allowed(p, reading)})
    return rows[:cap], chosen, evidence


# --- the evidence pack ------------------------------------------------------------------------------


def _by_team(sb, table: str, cols: str, ids) -> dict[str, list[dict]]:
    found = defaultdict(list)
    for batch in batched(sorted(set(ids))):
        for row in page(lambda b=batch: sb.table(table).select(cols).in_("team_id_master", b), "id"):
            found[row["team_id_master"]].append(row)
    return found


def held_because(sb, folder: Path, ids: set[str]) -> dict[str, str]:
    """{team: why} for each team whose change the hold check would hold, read over the whole snapshot as the
    applier reads it."""
    decisions = read_json(folder / APPLIER_INPUTS[STATES])["decisions"]
    applied = sorted({d["team_id"] for d in decisions if d["action"] == "apply"})
    _, held = split(decisions, fetch_state_sources(sb, applied))
    return {d["team_id"]: d["held_because"] for d in held if d["team_id"] in ids}


def decided_by(source: str) -> str:
    return "the automatic lane" if source.startswith("auto:") else "the owner"


def evidence_blocks(sb, rows: list[dict], chosen: Selection, evidence, folder: Path) -> list[str]:
    """Each change's evidence as a reviewer reads it, in the changes' order, every name written as a JSON string.
    Where the team played is left out: the skill reads it as travel, not as where the club is based."""
    if not rows:
        return []
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    ids = {row["team_id_master"] for row in rows}
    mates = defaultdict(Counter)
    members = defaultdict(set)
    for t in evidence.by_id.values():
        if club := club_key(t.get("club_name")):
            mates[club][(state_label(t.get("state_code")), t.get("state_source") or "unstamped")] += 1
            members[club].add(t["team_id_master"])
    probed = _by_team(sb, PROBE_LOG_TABLE, PROBE_COLS, ids)
    probes = {tid: max(found, key=lambda r: r["id"]) for tid, found in probed.items()}
    queue = _by_team(sb, QUEUE_TABLE, REVIEW_COLS, ids)
    audit = _by_team(sb, AUDIT_TABLE, AUDIT_COLS, ids)
    decisions = defaultdict(list)
    for d in page(lambda: sb.table(DECISIONS_TABLE).select(DECISION_COLS).eq("stage", STATES), "id"):
        if d["superseded_at"] is None:
            decisions[d["team_id_master"]].append(d)
    held = held_because(sb, folder, ids)

    blocks = []
    for row in rows:
        tid = row["team_id_master"]
        team, live = chosen.teams[tid], evidence.by_id.get(tid) or {}
        club = club_key(team.get("club_name"))
        state, how = name_place(live or team, evidence.locality_index)
        reported = (live.get("state") or "").strip()
        itself = (state_label(live.get("state_code")), live.get("state_source") or "unstamped")
        others = mates[club] - Counter({itself: 1})
        by_state = defaultdict(Counter)
        for (code, source), n in others.items():
            by_state[code][source] += n
        owner_on_club = Counter(
            f"{d['decision']} {d['proposed_value']}"
            for mate in members[club] - {tid}
            for d in decisions.get(mate, [])
            if decided_by(d["source"]) == "the owner"
        )
        probe = probes.get(tid)
        allowed = [v for v in STATE_VERDICTS if v not in row["not_allowed"]]
        lines = [
            f"## {row['item']} team_id={tid}",
            f"{json.dumps(team['team_name'])} | registered: {json.dumps(team['team_name_original'])} "
            f"| club: {json.dumps(team['club_name'])} | {providers.get(team['provider_id'], '?')} "
            f"| {team['age_group']} {team['gender']}",
            f"stored: {state_label(row['old_value'])} (written by {live.get('state_source') or 'nothing recorded'}"
            + (f"; a provider or form also reported {json.dumps(reported)}" if reported else "")
            + f") | proposed: {state_label(row['new_value'])}"
            + (" (the state it holds)" if keeps_state(row) else "")
            + f", tier {row['tier']}, the rules would {'apply it' if row['action'] == 'apply' else 'only queue it'}"
            + f" | their reason: {json.dumps(row.get('reason') or '')}",
            f"you may answer: {', '.join(allowed)}"
            + "".join(f"; not {verdict}, since {why}" for verdict, why in row["not_allowed"].items()),
            f"its name: {NAME_SAYS[how].format(state=state)}",
            "GotSport's own record: "
            + (
                f"{probe['reported_state_code'] or 'no state'} ({probe['outcome']}), "
                f"asked {str(probe['probed_at'])[:10]}"
                if probe
                else "never asked"
            ),
            "club registry: "
            + (
                f"home {home_state(team['club_name'])}"
                if home_state(team["club_name"])
                else "needs curation" if requires_review(team["club_name"]) else "not listed"
            ),
            f"club-mates' stored states ({sum(others.values())} teams): "
            + (
                "; ".join(
                    f"{code} {sum(sources.values())} ({', '.join(f'{s} {n}' for s, n in sources.most_common())})"
                    for code, sources in sorted(by_state.items(), key=lambda kv: -sum(kv[1].values()))
                )
                or "none"
            ),
            "the owner's earlier choices on this club's teams: "
            + (", ".join(f"{choice} x{n}" for choice, n in owner_on_club.most_common()) or "none"),
            "earlier choices on this team: "
            + (
                "; ".join(
                    f"{str(d['decided_at'])[:10]} {decided_by(d['source'])}: {d['decision']} {d['proposed_value']}"
                    + (f" {json.dumps(d['note'])}" if d.get("note") else "")
                    for d in sorted(decisions.get(tid, []), key=lambda d: d["id"])[-HISTORY_SHOWN:]
                )
                or "none"
            ),
            "review queue: "
            + (
                "; ".join(
                    f"{q['status']} {state_label(q['proposed_state_code'])} from {state_label(q['current_state_code'])}"
                    + (f" {str(q['reviewed_at'])[:10]}" if q.get("reviewed_at") else "")
                    for q in sorted(queue.get(tid, []), key=lambda q: q["id"])[-HISTORY_SHOWN:]
                )
                or "none"
            ),
            "state history: "
            + (
                "; ".join(
                    f"{str(a['applied_at'])[:10]} {a['applied_by']} {a['action']} "
                    f"{state_label(a['old_state_code'])} -> {state_label(a['new_state_code'])}"
                    + (f" {json.dumps(a['reason'])}" if a.get("reason") else "")
                    for a in sorted(audit.get(tid, []), key=lambda a: a["id"])[-HISTORY_SHOWN:]
                )
                or "none"
            ),
            f"hold check: {'holds it: ' + held[tid] if tid in held else 'passes'}",
        ]
        blocks.append("\n".join(lines) + "\n")
    return blocks


# --- queueing --------------------------------------------------------------------------------------


def render_brief(text: str) -> str:
    return text.replace("{lookup}", rm.LOOKUP)


def queue(sb, folder: Path, cap: int) -> int:
    """Write the review's slices, briefs and skill; the changes queued. A review of no change still leaves the
    folder, so the autopilot moves on to the page, which then has no review to route by."""
    rows, chosen, evidence = review_changes(sb, folder, cap)
    blocks = evidence_blocks(sb, rows, chosen, evidence, folder)
    review = folder / REVIEW_DIR
    (review / rm.ANSWERS_DIR).mkdir(parents=True, exist_ok=True)
    for name, source in BRIEFS.items():
        (review / name).write_text(render_brief(source.read_text(encoding="utf-8")), encoding="utf-8")
    rm.pack_skill(review, STATE_SKILL)
    for n, start in enumerate(range(0, len(rows), SLICE_ITEMS), 1):
        name = rm.slice_name(n)
        (review / f"{name}.md").write_text("\n".join(blocks[start : start + SLICE_ITEMS]), encoding="utf-8")
        write_json(review / f"{name}.json", rows[start : start + SLICE_ITEMS], indent=1)
    return len(rows)


# --- answers ---------------------------------------------------------------------------------------


def read_verdicts(path: Path, rows: list[dict]) -> list[dict]:
    """The reviewer's answer, one valid verdict per change of the slice in its order, or ValueError; a verdict the
    change does not allow comes back a hold, so no second reviewer is asked about it."""
    answers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(answers, list) or len(answers) != len(rows):
        raise ValueError(f"{path.name} does not hold one answer per change of the slice")
    read = []
    for row, answer in zip(rows, answers):
        if not isinstance(answer, dict) or any(answer.get(k) != row[k] for k in ("item", "team_id_master")):
            raise ValueError(f"{path.name} does not answer {row['item']} in its place")
        if answer.get("verdict") not in STATE_VERDICTS:
            raise ValueError(f"{path.name} gives {row['item']} a verdict the brief does not allow")
        reason = answer.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path.name} gives {row['item']} no reason")
        why = row["not_allowed"].get(answer["verdict"])
        if why:
            reason = f"reviewers would {answer['verdict']} it ({reason.strip()}), but {why}"
            answer = {**answer, "verdict": HOLD, "reason": reason}
        read.append(answer)
    return read


def final_rows(rows: list[dict], verdicts: list[dict], seconds: dict[str, dict]) -> list[dict]:
    """Each change with its final verdict: a reject the second reviewer did not uphold is a hold."""
    final = []
    for row, answer in zip(rows, verdicts):
        verdict, reason = answer["verdict"], answer["reason"].strip()
        if verdict == REJECT:
            second = seconds.get(row["item"])
            if second is None or not second["upheld"]:
                answered = f": {second['reason'].strip()}" if second else ""
                reason = f"one reviewer found the stored state right ({reason}), and a second did not agree{answered}"
                verdict = HOLD
        final.append({**row, "verdict": verdict, "reason": reason})
    return final


def held_rows(rows: list[dict], why: str) -> list[dict]:
    return [{**row, "verdict": HOLD, "reason": why} for row in rows]


CHANGES = rm.Kind(CHANGE_REVIEW_KEYS, "item", "changes", read_verdicts, final_rows, held_rows)


def counts(review: Path) -> Counter:
    return Counter(row["verdict"] for path in review.glob(f"*{REVIEW_SUFFIX}") for row in read_json(path))


def main() -> int:
    def plan(folder: Path, cap: int) -> str:
        rows, _, _ = review_changes(get_client(), folder, cap)
        return f"{len(rows)} state change(s) for review, {SLICE_ITEMS} a reviewer"

    def tally(review: Path) -> str:
        found = counts(review)
        rules = rm.skill_version(review) or "the brief alone"
        verdicts = f"{found[APPLY]} apply, {found[HOLD]} hold, {found[REJECT]} reject"
        return f"reviewed state changes: {verdicts}, judged by {rules}"

    def queued(folder: Path, cap: int) -> str:
        return f"{queue(get_client(), folder, cap)} state change(s)"

    return rm.review_main(__doc__, STATES, "the state changes", CHANGES, plan, queued, tally)


if __name__ == "__main__":
    raise SystemExit(main())
