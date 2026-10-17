#!/usr/bin/env python3
"""Build the owner's review page for one stage of a weekly team-cleanup run.

Reads the stage's proposals.json and stale.json from the run store and leaves off every proposal
the owner already declined (an active dont_apply in team_cleanup_decisions naming the same new
value), every one the write guard listed as stale, every one whose team is gone or whose field
has moved since, every club change from a tier the scan lists without approving, and every state
change that a recent GotSport answer or the team's name or club name already answers with the state
the team holds. Teams users follow (watchlisted, report-card or missing-game teams) are kept inside the
caps first and lead their group; past the card cap the rest are listed and left for next week's scan,
which proposes them again.

The changes sure.py finds the evidence already settles go to the stage's automatic lane, with no
card, up to page_caps.auto in config/team_cleanup.json; past it they stay cards, as every one does
while it is 0. `collect.py --lane auto` and `apply_stage.py --lane auto` collect and apply that lane.
page_caps.cards caps the cards. The build writes three files into the stage folder, under the run's
file lock and only while neither lane has collected from the page:

  page.html            a self-contained page from assets/stage-page.html, one card per proposal shown
  page.manifest.json   which proposal each card shows, which go to the automatic lane, which of
                       either sure.py finds the evidence already settles, and what was left off and
                       why
  page.json            the build: its run, its counts, and the hashes of proposals.json, the
                       applier's input and the manifest, which the collector checks first

Publish page.html as an Artifact with the db capability. The owner's choices land in the page's
own collection, `decisions-<run>`. A saved choice holds the decision, a note and a timestamp, never
team ids: collect.py takes the ids from the manifest, so a write to the page can decide a proposal
the page shows but cannot add one.

Read-only: it never writes to the database.

    python scripts/team_cleanup/pages.py --run 2026-10-14-nv --stage states
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.assign_team_states import club_key  # noqa: E402
from scripts.enqueue_user_interest_teams import (  # noqa: E402
    collect_report_card_teams,
    collect_user_requested_teams,
    collect_watchlisted_teams,
)
from scripts.find_cross_provider_duplicates import (  # noqa: E402
    build_evidence,
    fetch_games,
    get_client,
    load_merge_map,
    merged_into,
    page,
    resolver,
)
from scripts.review_state_queue_by_name import classify  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    DECISIONS_TABLE,
    DONT_APPLY,
    DONT_APPLY_COLS,
    DecisionsUnavailable,
    new_page_run,
)
from scripts.team_cleanup.propose_week import AGES, APPLIER_INPUTS, CLUBS, PROPOSED_STAGES, STATES  # noqa: E402
from scripts.team_cleanup.review_page import card_id, fetch_teams, render  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    AUTO,
    CLEANUP_CONFIG,
    COLLECTED_MARKER,
    LANE_CARDS,
    MANIFEST_FILE,
    OWNER,
    PAGE_MARKER,
    PROPOSALS_FILE,
    STALE_FILE,
    ApplyLockError,
    Busy,
    RunBusy,
    file_hash,
    hold_apply_file,
    lane_dir,
    lane_name,
    read_run,
    reporting_busy,
    stage_dir,
    stage_due,
    store_dir,
)
from scripts.team_cleanup.sure import keeps_state, load_signals, state_evidence, sure_because  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "assets" / "stage-page.html"
PAGE_FILE = "page.html"
TITLES = {CLUBS: "Club names", STATES: "States", AGES: "Age groups"}
# The tiers trusted to apply whole. Every age-plan row (review groups 1-3) is, so ages has no entry.
# A club proposal from any other tier is a guess the scan lists unapproved, and gets no card.
WHOLE_TIERS = {
    CLUBS: {"provider", "swap", "word", "bracket"},
    STATES: {"B fill"},
}


@dataclass(frozen=True)
class Caps:
    cards: int
    auto: int


def load_caps(path: Path = CLEANUP_CONFIG) -> Caps:
    """The configured caps on a page's cards and on its automatic lane, each a whole number from 0."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))["page_caps"]
        caps = Caps(spec["cards"], spec["auto"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path} holds no readable page_caps ({type(exc).__name__}: {exc})") from None
    if not all(type(cap) is int and cap >= 0 for cap in (caps.cards, caps.auto)):
        raise ValueError(f"{path}'s page_caps must be whole numbers from 0: {spec}")
    return caps


def group_of(stage: str, proposal: dict) -> str:
    """The card's group on the page. A state change the rules would only queue, and a club change
    the scan left for review, sit apart from the confident ones of their tier."""
    tier = proposal["tier"]
    if stage == CLUBS:
        return f"{tier} (needs review)" if proposal["needs_review"] else tier
    if stage == STATES:
        kind = "fill" if proposal["old_value"] is None else "correction"
        return f"{tier} {kind}" + (" (rules unsure)" if proposal["action"] == "queue" else "")
    return tier


def whole(stage: str, group: str) -> bool:
    return stage == AGES or group in WHOLE_TIERS[stage]


def group_rank(stage: str, proposal: dict) -> tuple:
    """Groups the page offers to apply whole come first."""
    group = group_of(stage, proposal)
    return (not whole(stage, group), group)


def name_key(proposal: dict) -> str:
    return (proposal["team_name"] or "").lower()


def load_declined(sb, stage: str, canonical) -> dict[tuple, str]:
    """{(team, field, proposed value): decided_at} for the stage's active dont_apply decisions, keyed
    on each team's surviving row, since a decision outlives a merge of its team.

    Any failure to read raises: an empty answer would put every declined change back on the page.
    """
    try:
        rows = page(
            lambda: sb.table(DECISIONS_TABLE).select(DONT_APPLY_COLS).eq("stage", stage).eq("decision", DONT_APPLY),
            "id",
        )
    except Exception as exc:
        raise DecisionsUnavailable(f"could not read {DECISIONS_TABLE}: {exc}") from exc
    return {
        (canonical(r["team_id_master"]), r["field"], r["proposed_value"]): r["decided_at"]
        for r in rows
        if r["superseded_at"] is None
    }


def load_interest(sb, canonical) -> set[str]:
    teams = collect_watchlisted_teams(sb) | collect_report_card_teams(sb) | collect_user_requested_teams(sb)
    return {canonical(t) for t in teams}


def load_answered(proposals, evidence) -> dict[str, str]:
    """{team: why} for each state change the states skill's own evidence already answers with the
    state the team holds: a recent GotSport answer, or the team's name or club name as its name
    pass reads it. A proposal that keeps the held state changes nothing and is never answered."""
    if evidence is None:
        return {}
    answered = {}
    for p in proposals:
        if keeps_state(p):
            continue
        tid, held = p["team_id_master"], (p["old_value"] or "").strip() or None
        answer = evidence.answers.get(tid)
        if answer and answer == held:
            answered[tid] = f"GotSport's record says {held}"
            continue
        row = {"current_state_code": held, "proposed_state_code": p["new_value"]}
        # The approved and reverted ledgers are left out: classify rejects before it reads them.
        if classify(row, evidence.by_id.get(tid), evidence.locality_index, answer)[0] == "reject":
            answered[tid] = f"its name or club name places it in {held}"
    return answered


def unmoved(field: str, now, then) -> bool:
    """Each applier's own test of a team's value against the one proposed from: the club applier
    ignores case, and state_code is CHAR(2), so a state reads back padded."""
    if field == "club_name":
        return (now or "").lower() == (then or "").lower()
    if field == "state_code":
        return (now or "").strip() == (then or "").strip()
    return now == then


def sort_out(stage, proposals, stale, declined, answered, teams, canonical, interest):
    """The proposals not left off, interest teams first so the caps keep them, and each one left off
    with why."""
    stale_keys = {(s["team_id_master"], s["field"]): s["changed"] for s in stale}
    shown, left_out = [], []
    for p in proposals:
        tid, field = p["team_id_master"], p["field"]
        team = teams.get(tid)
        why = None
        if stage == CLUBS and p["tier"] not in WHOLE_TIERS[CLUBS]:
            why = f"the scan lists {p['tier']} guesses without approving them"
        elif (tid, field) in stale_keys:
            why = f"changed while the week was proposed: {stale_keys[tid, field]}"
        elif team is None or team["is_deprecated"] or canonical(tid) != tid:
            why = "no longer a live team"
        elif not unmoved(field, team[field], p["old_value"]):
            why = f"{field} is now {team[field]!r}, not {p['old_value']!r}"
        elif (tid, field, p["new_value"]) in declined:
            why = f"declined on {declined[tid, field, p['new_value']][:10]}"
        elif tid in answered:
            why = answered[tid]
        if why:
            left_out.append({**p, "why": why})
        else:
            shown.append(p)
    shown.sort(key=lambda p: (p["team_id_master"] not in interest, group_rank(stage, p), name_key(p)))
    return shown, left_out


def alike_key(group: str, p, team) -> str | None:
    """Cards in one group from one club proposing the same change share this key, so the page can
    decide them together. A placeholder club joins unrelated teams, so it shares nothing."""
    club = club_key(team["club_name"])
    if not club:
        return None
    return json.dumps([club, group, p["field"], p["old_value"], p["new_value"]])


def change_id(run: str, p: dict) -> str:
    return card_id(run, f"{p['team_id_master']}|{p['field']}|{p['new_value']}")


def card(stage, run, p, team, ev, providers, interest) -> dict:
    tid = p["team_id_master"]
    dates = ev.dates[tid]
    group = group_of(stage, p)
    return {
        "id": change_id(run, p),
        "group": group,
        "whole": whole(stage, group),
        "alike": alike_key(group, p, team),
        "interest": tid in interest,
        "change": {"field": p["field"], "old": p["old_value"], "new": p["new_value"]},
        "why": p.get("reason") or "",
        "team": {
            "name": team["team_name"],
            "original": team["team_name_original"],
            "club": team["club_name"],
            "state": (team["state_code"] or "").strip() or None,
            "age": team["age_group"],
            "gender": team["gender"],
            "provider": providers.get(team["provider_id"]),
            "games": ev.games[tid],
            "excluded": ev.excluded[tid],
            "first": min(dates, default=None),
            "last": max(dates, default=None),
        },
    }


def display_order(stage: str, interest: set[str]):
    return lambda p: (group_rank(stage, p), p["team_id_master"] not in interest, name_key(p))


def buildable(store: Path, run_id: str, stage: str) -> Path:
    """The stage folder, while neither lane has collected from the page as built."""
    folder = stage_due(store, read_run(store, run_id), stage, ("page", "collect"))
    if (lane_dir(store, run_id, stage, AUTO) / COLLECTED_MARKER).exists():
        raise ValueError(f"{lane_name(stage, AUTO)} is collected from the page as built, so the page stays as it is")
    return folder


def build(sb, store: Path, run_id: str, stage: str) -> dict:
    run = read_run(store, run_id)
    folder = buildable(store, run_id, stage)
    caps = load_caps()
    proposals = read_json(folder / PROPOSALS_FILE)
    stale = read_json(folder / STALE_FILE)
    ids = sorted({p["team_id_master"] for p in proposals})
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    declined = load_declined(sb, stage, canonical)
    interest = load_interest(sb, canonical)
    evidence = state_evidence(sb, stage, proposals)
    answered = load_answered(proposals, evidence)
    teams = fetch_teams(sb, ids)
    shown, left_out = sort_out(stage, proposals, stale, declined, answered, teams, canonical, interest)
    signals = load_signals(sb, stage, folder, shown, evidence, canonical)
    settled = {p["team_id_master"]: why for p in shown if (why := sure_because(stage, p, signals))}
    auto = [p for p in shown if p["team_id_master"] in settled][: caps.auto]
    sent = {p["team_id_master"] for p in auto}
    shown = [p for p in shown if p["team_id_master"] not in sent]
    shown, overflow = shown[: caps.cards], shown[caps.cards :]
    shown.sort(key=display_order(stage, interest))
    auto.sort(key=display_order(stage, interest))

    page_ids = [p["team_id_master"] for p in shown]
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    ev = build_evidence(fetch_games(sb, sorted(merged_into(page_ids, merge_map, canonical))), [], canonical, page_ids)
    page_run = new_page_run()
    cards = [card(stage, page_run, p, teams[p["team_id_master"]], ev, providers, interest) for p in shown]
    for n, c in enumerate(cards, 1):
        c["n"] = n
    by_id = {c["id"]: p for c, p in zip(cards, shown)}
    auto_by_id = {change_id(page_run, p): p for p in auto}
    sure = {
        cid: settled[p["team_id_master"]]
        for cid, p in {**by_id, **auto_by_id}.items()
        if p["team_id_master"] in settled
    }
    title = f"{TITLES[stage]}: {', '.join(run['scope']['states'])} ({run_id})"
    manifest = {
        "run": page_run,
        "cleanup_run": run_id,
        "stage": stage,
        "title": title,
        LANE_CARDS[OWNER]: by_id,
        LANE_CARDS[AUTO]: auto_by_id,
        "sure": sure,
        "left_out": left_out,
        "overflow": overflow,
    }

    # A lane may have been collected while the evidence was read; the collector holds this lock too.
    with hold_apply_file(store, run_id):
        buildable(store, run_id, stage)
        (folder / PAGE_FILE).write_text(render(TEMPLATE, cards, title, page_run), encoding="utf-8")
        write_json(folder / MANIFEST_FILE, manifest, indent=1)
        marker = {
            "run": page_run,
            "built_at": utc_now_iso(),
            "cards": len(cards),
            AUTO: len(auto_by_id),
            "sure": len(sure),
            "left_out": len(left_out),
            "overflow": len(overflow),
            "hashes": {
                name: file_hash(folder / name) for name in (PROPOSALS_FILE, APPLIER_INPUTS[stage], MANIFEST_FILE)
            },
        }
        write_json(folder / PAGE_MARKER, marker, indent=1)
    return marker


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="The run id, e.g. 2026-10-14-nv")
    ap.add_argument("--stage", required=True, choices=PROPOSED_STAGES)
    ap.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = ap.parse_args()
    with reporting_busy():
        try:
            store = store_dir(args.store)
            marker = build(get_client(), store, args.run, args.stage)
        except DecisionsUnavailable as exc:
            raise SystemExit(
                f"{exc}\nThe page waits until the owner's earlier decisions and undos can be read."
            ) from exc
        except RunBusy as exc:
            raise Busy(f"Cannot build the {args.stage} page for {args.run}: {exc}") from None
        except (OSError, ValueError, ApplyLockError) as exc:
            raise SystemExit(f"Cannot build the {args.stage} page for {args.run}: {exc}") from None
    folder = stage_dir(store, args.run, args.stage)
    sent = marker[AUTO]
    print(f"wrote {folder / PAGE_FILE}: {marker['cards']} cards, page run {marker['run']}")
    print(f"  the evidence already settles {marker['sure']}: {sent} go to the automatic lane, the rest stay cards")
    print(f"  left off {marker['left_out']}, past the cap {marker['overflow']}; see {folder / MANIFEST_FILE}")
    if sent:
        lane = f"--run {args.run} --stage {args.stage} --lane auto"
        print(f"  the automatic lane: collect.py {lane}, then apply_stage.py {lane}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
