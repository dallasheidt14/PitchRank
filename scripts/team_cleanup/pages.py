#!/usr/bin/env python3
"""Build the owner's review page for one stage of a weekly team-cleanup run.

Reads the stage's proposals.json and stale.json from the run store and leaves off every proposal
the owner already declined (an active dont_apply in team_cleanup_decisions naming the same new
value), every one the write guard listed as stale, every one whose team is gone or whose field
has moved since, every club change proposing no club, every club change from a tier the scan lists
without approving that the week's review (review_clubs.py) did not reach, and every state
change that a recent GotSport answer or the team's name or club name already answers with the state
the team holds. A pair is left off when either row is gone or merged away, or has changed its age
group, gender, state or club since the scan read it. Teams users follow (watchlisted, report-card or
missing-game teams) are kept inside the caps first and lead their group; past the card cap the rest
are listed and left for next week's scan, which proposes them again. The merges caps keep followed
teams' pairs first, then the cross-provider scan's before the squad-key scan's, each by the fewest
games on the row it retires, and each pair card shows the two rows' shared opponents and same-day
games. A pair neither of whose rows has a game this season is left off unless the scan finds it provably
safe. Once review_merges.py has reviewed the pairs, a pair it cleared goes to the automatic lane turned as the
review chose, one it found to be two teams goes there as Keep separate, one it held is a card giving the
reviewers' reason, and one it did not reach waits past the cap for a later week's review; a cleared pair
whose rows have since played on one day, or each other, is held instead. Once review_clubs.py has reviewed the
club guesses, or review_states.py the state changes, a change it approved goes to the automatic lane, one it found
wrong goes there as declined, and one it held is a card giving the reviewers' reason; a state change it did not
reach is a card as before. The page refuses to build while a review is due and has not been queued.

The changes sure.py finds the evidence already settles go to the stage's automatic lane, with no
card, up to page_caps.auto in config/team_cleanup.json; past it they stay cards, as every one does
while it is 0. A pair the week's review settled that the cap leaves a card carries the reviewers' verdict
(`capped`) and their swap, so the website can merge every cleared one in one click the way they chose.
`collect.py --lane auto` and `apply_stage.py --lane auto` collect and apply that lane.
page_caps.cards caps the cards, and page_caps.<stage> gives a stage caps of its own. The build writes
three files into the stage folder (two for merges), under the run's file lock and only while neither
lane has collected from the page:

  page.html            a self-contained page from assets/stage-page.html, one card per proposal shown;
                       none for merges, whose pair cards only the website shows
  page.manifest.json   which proposal each card shows, which go to the automatic lane, which of
                       either sure.py finds the evidence already settles, and what was left off and
                       why
  page.json            the build: its run, its counts, whether its cards are published, and the
                       hashes of proposals.json, the applier's input and the manifest, which the
                       collector checks first

Publish page.html as an Artifact with the db capability; merges have no such page, so their cards are
decided only on the website. The owner's choices land in the page's own collection, `decisions-<run>`.
A saved choice holds the decision, a note and a timestamp, never team ids: collect.py takes the ids
from the manifest, so a write to the page can decide a proposal the page shows but cannot add one.

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
from dataclasses import dataclass, replace
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
from scripts.fix_band_cohorts import SEASON_START  # noqa: E402
from scripts.review_state_queue_by_name import (  # noqa: E402
    affiliate_contradicts,
    classify,
    name_reading,
    names_a_place,
)
from scripts.team_cleanup.club_changes import CLUB_REVIEW_WORDS, change_choice, change_key  # noqa: E402
from scripts.team_cleanup.collect import fetch_cards  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    CARDS_TABLE,
    DECISIONS_TABLE,
    DONT_APPLY,
    DONT_APPLY_COLS,
    MERGES,
    DecisionsUnavailable,
    card_rows,
    new_page_run,
    resolve_execute,
)
from scripts.team_cleanup.pairs import HOLD, MERGE, REVIEW_WORDS, review_choice, side  # noqa: E402
from scripts.team_cleanup.propose_week import (  # noqa: E402
    AGES,
    APPLIER_INPUTS,
    CLUBS,
    CROSS_PROVIDER_DOORWAY,
    PROPOSED_STAGES,
    REVIEWERS,
    SCAN_COUNTS,
    SQUAD_KEY_DOORWAY,
    STATES,
)
from scripts.team_cleanup.review_page import card_id, fetch_teams, render, team_block  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    AUTO,
    CLEANUP_CONFIG,
    COLLECTED_MARKER,
    LANE_CARDS,
    MANIFEST_FILE,
    OWNER,
    PAGE_MARKER,
    PROPOSALS_FILE,
    REVIEW_DIR,
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
from scripts.team_cleanup.state_changes import STATE_REVIEW_WORDS  # noqa: E402
from scripts.team_cleanup.sure import (  # noqa: E402
    Signals,
    change_reviews,
    keeps_state,
    load_signals,
    merge_reviews,
    provably_safe,
    state_evidence,
    sure_because,
)
from scripts.team_cleanup.vetted import changed_since_vetted  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "assets" / "stage-page.html"
PAGE_FILE = "page.html"
TITLES = {CLUBS: "Club names", STATES: "States", AGES: "Age groups", MERGES: "Duplicate teams"}
# The tiers trusted to apply whole. Every age-plan row (review groups 1-3) is, so ages has no entry.
# A club proposal from any other tier is a guess the scan lists unapproved, which reaches the page only
# through the week's club review.
WHOLE_TIERS = {
    CLUBS: {"provider", "swap", "word", "bracket"},
    STATES: {"B fill"},
}
# A pair's group names the scan that found it; same-name pairs across two providers come first.
PAIR_GROUPS = {CROSS_PROVIDER_DOORWAY: "C identical name", SQUAD_KEY_DOORWAY: "D squad key"}
SHARED_NAMES_SHOWN = 5
IDLE_WHY = "neither team has a game this season"
BLANK_CLUB_WHY = "the scan proposes no club"


@dataclass(frozen=True)
class Caps:
    cards: int
    auto: int
    review: int = 0


def load_caps(path: Path = CLEANUP_CONFIG, stage: str | None = None) -> Caps:
    """The configured caps on a page's cards, on its automatic lane and on what a week's review takes, each a
    whole number from 0: the stage's own caps when page_caps names the stage, else
    the shared ones, which review none."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))["page_caps"]
        spec = spec.get(stage, spec)
        caps = Caps(spec["cards"], spec["auto"], spec.get("review", 0))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path} holds no readable page_caps ({type(exc).__name__}: {exc})") from None
    if not all(type(cap) is int and cap >= 0 for cap in (caps.cards, caps.auto, caps.review)):
        raise ValueError(f"{path}'s page_caps must be whole numbers from 0: {spec}")
    return caps


def group_of(stage: str, proposal: dict) -> str:
    """The card's group on the page. A state change the rules would only queue, and a club change
    the scan left for review, sit apart from the confident ones of their tier."""
    if stage == MERGES:
        return PAIR_GROUPS[proposal["doorway"]]
    tier = proposal["tier"]
    if stage == CLUBS:
        return f"{tier} (needs review)" if proposal["needs_review"] else tier
    if stage == STATES:
        kind = "fill" if proposal["old_value"] is None else "correction"
        return f"{tier} {kind}" + (" (rules unsure)" if proposal["action"] == "queue" else "")
    return tier


def whole(stage: str, group: str) -> bool:
    return stage == AGES or group in WHOLE_TIERS.get(stage, ())


def group_rank(stage: str, proposal: dict) -> tuple:
    """Groups the page offers to apply whole come first."""
    group = group_of(stage, proposal)
    return (not whole(stage, group), group)


def name_key(proposal: dict) -> str:
    return (proposal["team_name"] or "").lower()


def teams_of(proposal: dict) -> tuple[str, ...]:
    return (proposal["merge_id"], proposal["keep_id"]) if "merge_id" in proposal else (proposal["team_id_master"],)


def proposal_key(proposal: dict) -> str:
    """A proposal's key within a build: its pair, else its team, since a stage proposes one change a team."""
    return f"{proposal['merge_id']}_{proposal['keep_id']}" if "merge_id" in proposal else proposal["team_id_master"]


def interested(proposal: dict, interest: set[str]) -> bool:
    return any(team in interest for team in teams_of(proposal))


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


def pair_moved(p: dict, teams: dict, canonical) -> str | None:
    """Why a pair no longer stands as its scan read it: a row gone or merged away, or either row's age
    group, gender, state or club changed since."""
    rows = [teams.get(team) for team in teams_of(p)]
    if any(t is None or t["is_deprecated"] or canonical(t["team_id_master"]) != t["team_id_master"] for t in rows):
        return "no longer two live teams"
    return changed_since_vetted(p, *rows)


def sort_out(stage, proposals, stale, declined, answered, teams, canonical, interest, listed=False):
    """The proposals not left off, interest teams first so the caps keep them, and each one left off
    with why. ``listed`` keeps the club guesses the scan lists without approving, for the week's review."""
    stale_keys = {(s["team_id_master"], s["field"]): s["changed"] for s in stale}
    shown, left_out = [], []
    for p in proposals:
        tid, field = p["team_id_master"], p["field"]
        team = teams.get(tid)
        why = None
        if stage == CLUBS and not (p["new_value"] or "").strip():
            why = BLANK_CLUB_WHY
        elif stage == CLUBS and p["tier"] not in WHOLE_TIERS[CLUBS] and not listed:
            why = listed_why(p)
        elif (tid, field) in stale_keys:
            why = f"changed while the week was proposed: {stale_keys[tid, field]}"
        elif stage == MERGES:
            why = pair_moved(p, teams, canonical)
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
    shown.sort(key=lambda p: (not interested(p, interest), group_rank(stage, p), name_key(p)))
    return shown, left_out


def listed_why(p: dict) -> str:
    return f"the scan lists {p['tier']} guesses without approving them"


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


def name_place(team: dict, locality_index: dict[str, str]) -> tuple[str | None, str]:
    """The state a team's name places it in, as the states skill's name pass reads it, and how (``team``, ``club``,
    ``town``, ``conflict``, ``unplaced`` or ``none``)."""
    state, how = name_reading(team, locality_index)
    # A town word can point outside the US (ON, Ontario), which the name pass reads as no state.
    if state and state not in STATE_CODE_TO_NAME:
        return None, "none"
    # A state word the name pass's own checks set aside (a place called after another state, an affiliate marker
    # naming one) is no reading; shown as one, it would argue against a right card.
    if state and (
        names_a_place(team, state)
        or affiliate_contradicts(team.get("team_name"), state)
        or affiliate_contradicts(team.get("club_name"), state)
    ):
        return None, "unplaced"
    return state, how


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
        state, how = name_place(team, evidence.locality_index)
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
    group = group_of(stage, p)
    return {
        "id": change_id(run, p),
        "group": group,
        "whole": whole(stage, group),
        "alike": alike_key(group, p, team),
        "interest": tid in interest,
        "change": {"field": p["field"], "old": p["old_value"], "new": p["new_value"]},
        "why": change_why(stage, p),
        "team": team_block(team, ev, providers),
        **({"evidence": facts[tid]} if facts and tid in facts else {}),
    }


def change_why(stage: str, p: dict) -> str:
    """What the reviewers found, where the week's club or state review reached the change, else the proposal's
    reason."""
    review = p.get("review")
    if review:
        words = STATE_REVIEW_WORDS if stage == STATES else CLUB_REVIEW_WORDS
        return f"{words[review['verdict']].capitalize()}: {review['reason']}"
    return p.get("reason") or ""


def pair_why(p: dict) -> str:
    """What the reviewers found, else why the scan paired the two rows; neither scan gives a proposed pair a reason
    of its own."""
    review = p.get("review")
    if review and review.get("held"):
        return f"Reviewers cleared it ({review['reason']}), but the page held it: {review['held']}"
    if review:
        return f"{REVIEW_WORDS[review['verdict']].capitalize()}: {review['reason']}"
    if p["doorway"] == CROSS_PROVIDER_DOORWAY:
        return f"Both are named {p['keep_name']!r}, one on gotsport and one on {p['provider']}"
    return f"Both are {p['club']}'s {p['squad_key']!r} squad of one age group, the name written two ways"


def pair_card(run, p, teams, ev, providers, interest, names) -> dict:
    """A pair as the website's pair card reads it. The overlap is measured here rather than taken from the
    scan, whose record reads 0.0 for a row with no opponents, and which the squad-key scan never measures."""
    merge, keep = p["merge_id"], p["keep_id"]
    shared = ev.opponents[merge] & ev.opponents[keep]
    both = ev.opponents[merge] and ev.opponents[keep]
    group = group_of(MERGES, p)
    return {
        "id": card_id(run, proposal_key(p)),
        "group": group,
        "whole": whole(MERGES, group),
        "alike": None,
        "interest": interested(p, interest),
        "why": pair_why(p),
        "merge": side(merge, teams, ev, providers),
        "keep": side(keep, teams, ev, providers),
        "evidence": {
            "doorway": p["doorway"],
            "shared_opponents": len(shared),
            "shared_opponent_names": sorted(names[o] for o in shared if names.get(o))[:SHARED_NAMES_SHOWN],
            "shared_dates": len(ev.dates[merge] & ev.dates[keep]),
            "opponent_overlap": round(len(shared) / len(ev.opponents[merge] | ev.opponents[keep]), 3) if both else None,
        },
    }


def auto_pair(p: dict) -> dict:
    """What an automatic pair's card adds: the review's swap, and whether the lane keeps the two rows separate
    rather than merging them. The table holds every automatic card as Apply, the loop carrying out its call."""
    choice = review_choice(p)
    return {"swap": choice["swap"], "keep_separate": choice["decision"] == DONT_APPLY}


def capped_pair(p: dict) -> dict:
    """What a pair the week's review settled adds when the automatic lane's cap left it a card: the reviewers'
    verdict, by which the website merges every cleared one in one click, and their swap, so a merge keeps the row
    they chose. A pair the rules settled unreviewed adds nothing."""
    review = p.get("review")
    return {"capped": review["verdict"], "swap": review_choice(p)["swap"]} if review else {}


def auto_change(p: dict) -> dict:
    """What an automatic club or state card adds: whether the lane keeps the stored value, the review having found
    the change wrong, rather than writing the new one. The table holds every automatic card as Apply."""
    return {"keep_as_is": change_choice(p)["decision"] == DONT_APPLY}


def read_evidence(sb, team_ids, merge_map, canonical):
    """The teams' games, read under every row merged into them."""
    rows = fetch_games(sb, sorted(merged_into(team_ids, merge_map, canonical)))
    return build_evidence(rows, [], canonical, team_ids)


def shared_opponent_names(sb, pairs, ev) -> dict[str, str]:
    """{opponent: name} for every opponent both rows of a pair played."""
    shared = set().union(*(ev.opponents[p["merge_id"]] & ev.opponents[p["keep_id"]] for p in pairs))
    return {tid: team["team_name"] for tid, team in fetch_teams(sb, sorted(shared)).items()}


def idle(p: dict, ev) -> bool:
    """A pair neither of whose rows has a game this season, played or scheduled: merging it changes nothing this
    season's boards show, and the owner leaves such pairs alone (2026-10-21) unless the scan finds them provably
    safe, which costs no one's time."""
    return not provably_safe(p) and not any(day >= SEASON_START for team in teams_of(p) for day in ev.dates[team])


def pair_cap_order(interest: set[str], ev):
    """The order the merges caps keep pairs in: followed teams', then by group, the row a pair retires
    holding the fewest games first."""
    return lambda p: (not interested(p, interest), group_rank(MERGES, p), ev.games[p["merge_id"]], name_key(p))


def display_order(stage: str, interest: set[str], ev=None):
    """Groups first, followed teams leading their group; a pair's, the row it retires holding the fewest games."""
    if stage == MERGES:
        return lambda p: (group_rank(stage, p), not interested(p, interest), ev.games[p["merge_id"]], name_key(p))
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


@dataclass(frozen=True)
class Selection:
    """A stage's proposals once those the evidence answers are left off: the ones the page shows, a merges page's
    in the order its caps keep them, and what was read to choose them."""

    shown: list
    left_out: list
    teams: dict
    merge_map: dict
    canonical: object
    interest: set
    evidence: object
    ev: object


def select(sb, folder: Path, stage: str, listed: bool = False) -> Selection:
    """The proposals a build starts from, which each review takes too, so it reviews what the page would show;
    ``listed`` keeps the club guesses the scan lists without approving."""
    proposals = read_json(folder / PROPOSALS_FILE)
    stale = read_json(folder / STALE_FILE)
    ids = sorted({team for p in proposals for team in teams_of(p)})
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    declined = load_declined(sb, stage, canonical)
    interest = load_interest(sb, canonical)
    evidence = state_evidence(sb, stage, proposals)
    answered = load_answered(proposals, evidence)
    teams = fetch_teams(sb, ids)
    shown, left_out = sort_out(stage, proposals, stale, declined, answered, teams, canonical, interest, listed)
    ev = None
    if stage == MERGES:
        # The cap orders pairs by their retiring row's games, so the evidence is read before it.
        ev = read_evidence(sb, [team for p in shown for team in teams_of(p)], merge_map, canonical)
        left_out += [{**p, "why": IDLE_WHY} for p in shown if idle(p, ev)]
        shown = sorted((p for p in shown if not idle(p, ev)), key=pair_cap_order(interest, ev))
    return Selection(shown, left_out, teams, merge_map, canonical, interest, evidence, ev)


def merge_signals(sb, folder: Path, chosen: Selection) -> Signals:
    """The merges rules' signals, with each retiring row that has played since the scan, which keeps an
    unreviewed pair out of the automatic lane."""
    signals = load_signals(sb, MERGES, folder, chosen.shown, None, chosen.canonical)
    return replace(signals, held={p["merge_id"] for p in chosen.shown if chosen.ev.games[p["merge_id"]]})


def with_reviews(shown: list[dict], reviews: dict, ev) -> list[dict]:
    """Each pair with its review, where it has one. A pair the reviewers cleared whose two rows now played on one
    day (a game between them among those) is held for the owner instead, its review marked so: the scans refuse
    such a pair as two squads, so the day came after the scan, and it may be one game recorded twice or two squads."""
    reviewed = []
    for p in shown:
        merge, keep = p["merge_id"], p["keep_id"]
        review = reviews.get((merge, keep))
        if review and review["verdict"] == MERGE and ev.dates[merge] & ev.dates[keep]:
            review = {**review, "verdict": HOLD, "swap": False, "held": "the two have since played on the same day"}
        reviewed.append({**p, "review": review} if review else p)
    return reviewed


def with_change_reviews(stage: str, shown: list[dict], reviews: dict) -> tuple[list[dict], list[dict]]:
    """Each club or state change with its review, where it has one; a club guess the review did not reach is left
    off, as it is with no review, and any other change it did not reach routes by the rules alone."""
    kept, left_out = [], []
    for p in shown:
        review = reviews.get(change_key(p))
        if review:
            kept.append({**p, "review": review})
        elif stage != CLUBS or p["tier"] in WHOLE_TIERS[CLUBS]:
            kept.append(p)
        else:
            left_out.append({**p, "why": listed_why(p)})
    return kept, left_out


def build(
    sb, store: Path, run_id: str, stage: str, publish: bool = False, execute: bool = False, dry_run: bool = False
) -> dict:
    """The page's build, its files written unless it is a dry run, and its cards inserted when published."""
    run = read_run(store, run_id)
    folder = buildable(store, run_id, stage)
    caps = load_caps(stage=stage)
    if stage in REVIEWERS and caps.review and not (folder / REVIEW_DIR).exists():
        script, what = REVIEWERS[stage]
        script = Path(script).name
        raise ValueError(f"its {what} are not reviewed yet: run {script} --execute first, as the autopilot does")
    changes = change_reviews(folder) if stage in (CLUBS, STATES) else None
    selection = select(sb, folder, stage, changes is not None)
    shown, left_out, teams, ev = selection.shown, selection.left_out, selection.teams, selection.ev
    interest, evidence, reviews = selection.interest, selection.evidence, None
    if stage == MERGES:
        signals = merge_signals(sb, folder, selection)
        reviews = merge_reviews(folder)
        if reviews is not None:
            shown = with_reviews(shown, reviews, ev)
    else:
        signals = load_signals(sb, stage, folder, shown, evidence, selection.canonical)
        if changes is not None:
            shown, unreached = with_change_reviews(stage, shown, changes)
            left_out = left_out + unreached
    settled = {proposal_key(p): why for p in shown if (why := sure_because(stage, p, signals))}
    auto = [p for p in shown if proposal_key(p) in settled][: caps.auto]
    sent = {proposal_key(p) for p in auto}
    shown = [p for p in shown if proposal_key(p) not in sent]
    # Once the merges review ran, only reviewed pairs are cards (those it held, and any it settled past page_caps.auto);
    # a pair it did not reach waits for a later week's review.
    unreviewed = [p for p in shown if "review" not in p] if reviews is not None else []
    shown = [p for p in shown if reviews is None or "review" in p]
    shown, overflow = shown[: caps.cards], shown[caps.cards :] + unreviewed

    page_ids = [team for p in (*shown, *auto) for team in teams_of(p)]
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    ev = ev or read_evidence(sb, page_ids, selection.merge_map, selection.canonical)
    shown.sort(key=display_order(stage, interest, ev))
    auto.sort(key=display_order(stage, interest, ev))
    facts = state_facts(evidence, ev, teams, page_ids)
    names = shared_opponent_names(sb, (*shown, *auto), ev) if stage == MERGES else {}
    page_run = new_page_run()
    lanes, by_lane = {}, {}
    for lane, chosen in ((OWNER, shown), (AUTO, auto)):
        lanes[lane] = [
            {
                **(
                    pair_card(page_run, p, teams, ev, providers, interest, names)
                    if stage == MERGES
                    else card(stage, page_run, p, teams[p["team_id_master"]], ev, providers, interest, facts)
                ),
                "n": n,
                "sure": settled.get(proposal_key(p)),
                **(auto_pair(p) if stage == MERGES and lane == AUTO else {}),
                **(capped_pair(p) if stage == MERGES and lane == OWNER and proposal_key(p) in settled else {}),
                **(auto_change(p) if stage in (CLUBS, STATES) and lane == AUTO else {}),
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
        **({"scanned": read_json(folder / SCAN_COUNTS)} if stage == MERGES else {}),
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
        if stage != MERGES:
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
    elif args.stage == MERGES:
        print(f"built the {args.stage} page: {marker['cards']} cards, page run {marker['run']}")
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
