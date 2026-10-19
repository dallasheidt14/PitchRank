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
  page.json            the build: its run, its counts, whether its cards are published, and the
                       hashes of proposals.json, the applier's input and the manifest, which the
                       collector checks first

Publish page.html as an Artifact with the db capability. The owner's choices land in the page's
own collection, `decisions-<run>`. A saved choice holds the decision, a note and a timestamp, never
team ids: collect.py takes the ids from the manifest, so a write to the page can decide a proposal
the page shows but cannot add one.

With --publish --execute it also writes each card of either lane to team_cleanup_cards (published to
the website, as opposed to an Artifact), the automatic lane's already decided Apply; the website is to
show the build the table saved last for the run (its created_at, not its page run, which is stamped
when the build starts) and save the owner's choices on it, and `collect.py --from-db` reads them back.
That insert is its only database write, made before the files so a refused one leaves the page on disk
as it was; page.json records `published`. --publish alone writes nothing, not even the files, and nor
does --dry-run, with or without it. Once the stage has published cards for the run, every new build is
published too and must carry a card, since a build with none publishes no row to replace them; once the
owner has decided a card of any of them, or marked the run's review done, the page is not built again,
since a new build's cards start undecided.

    python scripts/team_cleanup/pages.py --run 2026-10-14-nv --stage states
    python scripts/team_cleanup/pages.py --run 2026-10-14-nv --stage states --publish --execute
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
from postgrest.exceptions import APIError
from postgrest.types import ReturnMethod

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.assign_team_states import build_club_index, club_key  # noqa: E402
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
from scripts.review_state_queue_by_name import (  # noqa: E402
    affiliate_contradicts,
    classify,
    name_reading,
    names_a_place,
)
from scripts.team_cleanup.collect import fetch_cards  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    CARDS_TABLE,
    DECISIONS_TABLE,
    DONT_APPLY,
    DONT_APPLY_COLS,
    DecisionsUnavailable,
    card_rows,
    new_page_run,
    resolve_execute,
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
    RUNS_TABLE,
    STALE_FILE,
    ApplyLockError,
    Busy,
    RunBusy,
    file_hash,
    hold_apply_file,
    lane_dir,
    lane_name,
    read_run,
    refused,
    reporting_busy,
    stage_dir,
    stage_due,
    store_dir,
)
from scripts.team_cleanup.sure import keeps_state, load_signals, state_evidence, sure_because  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

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


def held_state(team: dict) -> str | None:
    """A team's stored state; state_code is CHAR(2), so it reads back padded."""
    return (team.get("state_code") or "").strip() or None


def state_facts(evidence, ev, teams, team_ids) -> dict[str, dict]:
    """What the states skill reads beside each state card's proposal, for the owner to see and never to decide
    it: its opponents' and club-mates' stored states, GotSport's recent answer, and the state its name points
    at. Opponents who agree prove nothing inside a mislabelled cluster, and club-mates are what proposed a
    Tier B correction. None of it is read for a page with no state change (``evidence`` None)."""
    if evidence is None:
        return {}
    clubs = build_club_index(evidence.by_id.values())
    facts = {}
    for tid in team_ids:
        team = teams[tid]
        opponents = [held_state(evidence.by_id.get(o) or {}) for o in ev.opponents[tid]]
        live = evidence.by_id.get(tid) or {}
        mates = Counter(clubs.get(club_key(live.get("club_name")), {}))
        if held_state(live):
            mates[held_state(live)] -= 1
        state, how = name_reading(team, evidence.locality_index)
        # A town word can point outside the US (ON, Ontario), which the name pass reads as no state.
        if state and state not in STATE_CODE_TO_NAME:
            state, how = None, "none"
        # A state word the name pass's own checks set aside (a place called after another state, an
        # affiliate marker naming one) is no reading; shown as one, it would argue against a right card.
        if state and (
            names_a_place(team, state)
            or affiliate_contradicts(team.get("team_name"), state)
            or affiliate_contradicts(team.get("club_name"), state)
        ):
            state, how = None, "unplaced"
        facts[tid] = {
            "opponents": dict(Counter(s for s in opponents if s).most_common()),
            "opponents_total": len(opponents),
            "club": dict(Counter({s: n for s, n in mates.items() if n > 0}).most_common()),
            "gotsport": evidence.answers.get(tid),
            "name": {"state": state, "how": how},
        }
    return facts


def card(stage, run, p, team, ev, providers, interest, facts=None) -> dict:
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
        **({"evidence": facts[tid]} if facts and tid in facts else {}),
    }


def display_order(stage: str, interest: set[str]):
    return lambda p: (group_rank(stage, p), p["team_id_master"] not in interest, name_key(p))


def buildable(store: Path, run_id: str, stage: str) -> Path:
    """The stage folder, while neither lane has collected from the page as built."""
    folder = stage_due(store, read_run(store, run_id), stage, ("page", "collect"))
    if (lane_dir(store, run_id, stage, AUTO) / COLLECTED_MARKER).exists():
        raise ValueError(f"{lane_name(stage, AUTO)} is collected from the page as built, so the page stays as it is")
    return folder


def check_undecided(sb, run_id: str, stage: str, publish: bool, empty: bool) -> None:
    """Refuse a new build of a published page once the run's review is marked done, whose new cards would be
    collected without the owner seeing them, or once the owner has decided a card of any build of it published
    for the run, and refuse one that would not replace a published page on the website: one that does not
    publish, or one with no card, which publishes no row. The website is to show the newest build published,
    so the page on disk must be that build. A stage with nothing published may still be built after Done,
    so the run can finish: the owner saw none of its cards, which stay undecided and come back next week."""
    rows = fetch_cards(sb, run_id=run_id, stage=stage)
    done = sb.table(RUNS_TABLE).select("owner_done_at").eq("run_id", run_id).execute().data
    if rows and done and done[0]["owner_done_at"] is not None:
        raise ValueError(f"the review of run {run_id} is marked done, so its published pages stay as they are")
    decided = sorted({row["page_run"] for row in rows if row["lane"] == OWNER and row["decision"] is not None})
    if decided:
        raise ValueError(
            f"the owner has decided cards of the published page {', '.join(decided)}, so the page stays as it is; "
            "collect the choices with collect.py --from-db"
        )
    if rows and not publish:
        raise ValueError("the page is published, so a new build of it is published too: pass --publish")
    if rows and empty:
        raise ValueError(
            "the new build has no cards, so publishing it would leave the website showing the published page "
            f"{', '.join(sorted({row['page_run'] for row in rows}))}; the page stays as it is"
        )


def build(
    sb, store: Path, run_id: str, stage: str, publish: bool = False, execute: bool = False, dry_run: bool = False
) -> dict:
    """The page's build, its files written unless it is a dry run, and its cards inserted when published."""
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

    page_ids = [p["team_id_master"] for p in (*shown, *auto)]
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    ev = build_evidence(fetch_games(sb, sorted(merged_into(page_ids, merge_map, canonical))), [], canonical, page_ids)
    facts = state_facts(evidence, ev, teams, page_ids)
    page_run = new_page_run()
    lanes, by_lane = {}, {}
    for lane, chosen in ((OWNER, shown), (AUTO, auto)):
        lanes[lane] = [
            {
                **card(stage, page_run, p, teams[p["team_id_master"]], ev, providers, interest, facts),
                "n": n,
                "sure": settled.get(p["team_id_master"]),
            }
            for n, p in enumerate(chosen, 1)
        ]
        by_lane[lane] = {c["id"]: p for c, p in zip(lanes[lane], chosen)}
    cards = lanes[OWNER]
    sure = {c["id"]: c["sure"] for lane_cards in lanes.values() for c in lane_cards if c["sure"]}
    title = f"{TITLES[stage]}: {', '.join(run['scope']['states'])} ({run_id})"
    manifest = {
        "run": page_run,
        "cleanup_run": run_id,
        "stage": stage,
        "title": title,
        **{LANE_CARDS[lane]: by_lane[lane] for lane in (OWNER, AUTO)},
        "sure": sure,
        "left_out": left_out,
        "overflow": overflow,
    }
    built_at = utc_now_iso()
    marker = {
        "run": page_run,
        "built_at": built_at,
        "published": publish and execute,
        "cards": len(cards),
        AUTO: len(by_lane[AUTO]),
        "sure": len(sure),
        "left_out": len(left_out),
        "overflow": len(overflow),
    }

    # A lane may have been collected, or a published page decided, while the evidence was read; the collector
    # holds this lock too. The cards go in one insert, so a build is published whole or not at all, and before
    # the files, so a failed publish leaves the page on disk as it was.
    with hold_apply_file(store, run_id):
        buildable(store, run_id, stage)
        rows = card_rows(run_id, stage, page_run, built_at, lanes)
        check_undecided(sb, run_id, stage, publish, empty=not rows)
        if dry_run or (publish and not execute):
            return marker
        if publish and rows:
            sb.table(CARDS_TABLE).insert(rows, returning=ReturnMethod.minimal).execute()
        (folder / PAGE_FILE).write_text(render(TEMPLATE, cards, title, page_run), encoding="utf-8")
        write_json(folder / MANIFEST_FILE, manifest, indent=1)
        hashed = (PROPOSALS_FILE, APPLIER_INPUTS[stage], MANIFEST_FILE)
        marker["hashes"] = {name: file_hash(folder / name) for name in hashed}
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
    ap.add_argument("--publish", action="store_true", help=f"Write the cards to {CARDS_TABLE}")
    ap.add_argument("--execute", action="store_true", help="With --publish, write them (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true", help="Write nothing, not even the page; wins over --execute")
    args = ap.parse_args()
    if args.execute and not args.publish:
        ap.error("--execute writes only the cards --publish names")
    execute = resolve_execute(args.execute, args.dry_run)
    dry_run = args.dry_run or (args.publish and not execute)
    what = f"Cannot build the {args.stage} page for {args.run}"
    with reporting_busy():
        try:
            store = store_dir(args.store)
            marker = build(get_client(), store, args.run, args.stage, args.publish, execute, dry_run)
        except DecisionsUnavailable as exc:
            raise SystemExit(
                f"{exc}\nThe page waits until the owner's earlier decisions and undos can be read."
            ) from exc
        except RunBusy as exc:
            raise Busy(f"{what}: {exc}") from None
        except (OSError, ValueError, ApplyLockError) as exc:
            raise SystemExit(f"{what}: {exc}") from None
        except (APIError, httpx.HTTPError) as exc:
            raise SystemExit(refused(what, exc, shlex.join(["python", *sys.argv]))) from None
    folder = stage_dir(store, args.run, args.stage)
    sent = marker[AUTO]
    if dry_run and args.publish:
        print(f"DRY RUN -- would build page run {marker['run']} and publish its {marker['cards'] + sent} cards to")
        print(f"  {CARDS_TABLE}, writing no file; add --execute")
    elif dry_run:
        print(f"DRY RUN -- would build page run {marker['run']} with {marker['cards']} cards, writing no file")
    else:
        print(f"wrote {folder / PAGE_FILE}: {marker['cards']} cards, page run {marker['run']}")
    if marker["published"]:
        print(f"  published its {marker['cards'] + sent} cards, both lanes, to {CARDS_TABLE}")
    print(f"  the evidence already settles {marker['sure']}: {sent} go to the automatic lane, the rest stay cards")
    print(f"  left off {marker['left_out']}, past the cap {marker['overflow']}; see {folder / MANIFEST_FILE}")
    if sent:
        lane = f"--run {args.run} --stage {args.stage} --lane auto"
        print(f"  the automatic lane: collect.py {lane}, then apply_stage.py {lane}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
