"""Which of a stage's proposed changes the evidence already settles.

A sure change is one the weekly loop could apply without asking the owner. Each rule but the merges
review reuses evidence the stage's own code already reads, and replay_sure.py checks those against how the
owner decided past pages; the review's verdicts are its reviewers' own:

  clubs   a change the scan approves (a provider, swap, word or bracket tier)
  states  a blank state the rules would apply from the team's club (tier B), which the hold check does
          not hold, whose latest recent GotSport answer, if there is one, names the same state, and
          which neither its name nor its club name places elsewhere, points two ways, or names a
          state it cannot place
  ages    a move to the band in the team's own name, or to a U-age label the review's opponents
          confirmed (never a play-up) when the league's division, its opponents' bands or GotSport say
          that age too, or the move is two groups or fewer
  merges  a pair the week's review cleared or found to be two teams (review_merges.py), the second as
          Keep separate, unless the page held a cleared pair because its rows have since played on the same
          day (pages.with_reviews); or, unreviewed, a pair the cross-provider scan finds provably safe: the
          row it retires holds no games, still none when the page is built, and that row's provider alias
          already points at the row it keeps

Everything else is a conflict, every state correction included: a club count can move a team out of
its own state. A change the loop applied and an undo reversed is never sure again, nor is a merge of
the same two rows the other way round, either row read as the one it has since been merged into.

Reading is all it does; nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.assign_team_states import build_locality_index, fetch_live_teams, fetch_state_sources
from scripts.find_cross_provider_duplicates import page
from scripts.fix_band_cohorts import age_num
from scripts.hold_unsafe_state_applies import split
from scripts.review_state_queue_by_name import name_reading, provider_states
from scripts.team_cleanup.decisions import CHANGES_TABLE, MERGES, DecisionsUnavailable
from scripts.team_cleanup.pairs import MERGE, REJECT, REVIEW_WORDS, VERDICTS
from scripts.team_cleanup.propose_week import (
    AGES,
    APPLIER_INPUTS,
    CLUBS,
    CROSS_PROVIDER_DOORWAY,
    FIELDS,
    PROVABLY_SAFE,
    STATES,
)
from scripts.team_cleanup.run_store import REVIEW_DIR, REVIEW_SUFFIX
from src.tournaments.storage._io import read_json

BAND_TIER = "A_own_name_band"
# What a review settles without the owner: a merge, and two teams kept separate; a hold is a card.
REVIEW_SETTLES = (MERGE, REJECT)
ULABEL_TIER = "U_own_name_ulabel_opponent_confirmed"
NEAR_GROUPS = 2


@dataclass(frozen=True)
class StateEvidence:
    """What the states skill reads about a team beyond its proposal: GotSport's recent answers, and
    every live team with the place index its name pass reads."""

    answers: dict[str, str]
    by_id: dict[str, dict]
    locality_index: dict[str, str]


@dataclass(frozen=True)
class Signals:
    """What a stage's rules read beyond each proposal: the changes an undo reversed, the teams held back
    (a state fill the hold check holds, a pair's retiring row that has played since its scan), and the
    states skill's evidence."""

    reverted: set[tuple] = field(default_factory=set)
    held: set[str] = field(default_factory=set)
    evidence: StateEvidence | None = None


def keeps_state(proposal: dict) -> bool:
    """Whether a state proposal names the state the team holds: a lock card, which changes nothing."""
    return proposal["new_value"] == ((proposal["old_value"] or "").strip() or None)


def state_evidence(sb, stage: str, proposals) -> StateEvidence | None:
    """The states skill's evidence, read once for every use a page makes of it; none when no
    proposal changes a state, so a page of lock cards skips these reads."""
    if stage != STATES or all(keeps_state(p) for p in proposals):
        return None
    answers = provider_states(sb)
    live = fetch_live_teams(sb)
    return StateEvidence(answers, {t["team_id_master"]: t for t in live}, build_locality_index(live))


def reverted_changes(sb, stage: str, canonical) -> set[tuple]:
    """{(team, field, new value)} for each change this loop applied and an undo reversed, keyed on
    each team's surviving row, since an undo outlives a merge of its team; a merge's new value is a
    team too, read the same way.

    Any failure to read raises: an empty answer would make every undone change sure again.
    """
    try:
        rows = page(
            lambda: sb.table(CHANGES_TABLE).select("id,team_id_master,field,new_value,reverted_at").eq("stage", stage),
            "id",
        )
    except Exception as exc:
        raise DecisionsUnavailable(f"could not read {CHANGES_TABLE}: {exc}") from exc
    merged_into = FIELDS[MERGES]
    return {
        (
            canonical(r["team_id_master"]),
            r["field"],
            canonical(r["new_value"]) if r["field"] == merged_into else r["new_value"],
        )
        for r in rows
        if r["reverted_at"]
    }


def held_fills(sb, folder: Path, proposals) -> set[str]:
    """The teams whose state fill the hold check would hold before it is written."""
    fills = {p["team_id_master"] for p in proposals if p["old_value"] is None}
    if not fills:
        return set()
    decisions = [d for d in read_json(folder / APPLIER_INPUTS[STATES])["decisions"] if d["team_id"] in fills]
    _, held = split(decisions, fetch_state_sources(sb, sorted(fills)))
    return {d["team_id"] for d in held}


def merge_reviews(folder: Path) -> dict[tuple[str, str], dict] | None:
    """{(merge row, keep row): its review's verdict, swap and reason} for each pair the week's review reached;
    None when the review queued no pair, and each pair then routes by the rules alone: a provably safe pair to the
    automatic lane, the rest as cards."""
    review = folder / REVIEW_DIR
    if not any(review.glob("slice_*.json")):
        return None
    reviews = {}
    for path in sorted(review.glob(f"*{REVIEW_SUFFIX}")):
        for row in read_json(path):
            if row["verdict"] not in VERDICTS or not isinstance(row["swap"], bool):
                raise ValueError(f"{path.name} gives {row['merge_id']} a verdict or swap the review never writes")
            reviews[row["merge_id"], row["keep_id"]] = {k: row[k] for k in ("verdict", "swap", "reason")}
    return reviews


def load_signals(sb, stage: str, folder: Path, proposals, evidence: StateEvidence | None, canonical) -> Signals:
    held = held_fills(sb, folder, proposals) if stage == STATES else set()
    return Signals(reverted_changes(sb, stage, canonical), held, evidence)


def sure_because(stage: str, proposal: dict, signals: Signals) -> str | None:
    """Why the evidence settles the change, or None when the owner decides it."""
    if (proposal["team_id_master"], proposal["field"], proposal["new_value"]) in signals.reverted:
        return None
    if stage == CLUBS:
        return _sure_club(proposal)
    if stage == STATES:
        return _sure_state(proposal, signals)
    if stage == AGES:
        return _sure_age(proposal)
    if stage == MERGES:
        return _sure_merge(proposal, signals)
    return None


def _sure_club(p: dict) -> str | None:
    if p["approved"]:  # the scan unapproves a team two sources propose different clubs for
        return f"the scan approves its {p['tier']} reading"
    return None


def _sure_state(p: dict, signals: Signals) -> str | None:
    tid, new = p["team_id_master"], p["new_value"]
    if p["old_value"] is not None or p["tier"] != "B" or p["action"] != "apply" or tid in signals.held:
        return None
    answer = signals.evidence.answers.get(tid)
    if answer and answer != new:
        return None
    team = signals.evidence.by_id.get(tid)
    if team is None:
        return None
    state, how = name_reading(team, signals.evidence.locality_index)
    if how in ("conflict", "unplaced") or (state and state != new):
        return None
    return "a blank state filled from its club, which nothing disputes"


def _sure_merge(p: dict, signals: Signals) -> str | None:
    if (p["keep_id"], FIELDS[MERGES], p["merge_id"]) in signals.reverted:
        return None
    review = p.get("review")
    if review:
        settled = review["verdict"] in REVIEW_SETTLES
        return f"{REVIEW_WORDS[review['verdict']]}: {review['reason']}" if settled else None
    if provably_safe(p) and p["merge_id"] not in signals.held:
        return "the row it retires holds no games, and its provider alias already points at the row it keeps"
    return None


def provably_safe(p: dict) -> bool:
    """Whether the pair is in the cross-provider scan's provably safe tier, which merges unreviewed while its
    retiring row still holds no games (Signals.held says whether it does)."""
    return p["doorway"] == CROSS_PROVIDER_DOORWAY and p["tier"] == PROVABLY_SAFE


def _sure_age(p: dict) -> str | None:
    if p["tier"] == BAND_TIER:
        return "the age band in its own name"
    if p["tier"] != ULABEL_TIER:
        return None
    new = p["new_value"]
    if new in (p.get("div_says"), p.get("band_opps_say"), p.get("gotsport_age")):
        return "its U-age label, which a second source confirms"
    try:
        gap = abs(age_num(new) - age_num(p["old_value"]))
    except ValueError:  # a team stored with no age group has no distance to measure
        return None
    if gap <= NEAR_GROUPS:
        return f"its U-age label, {NEAR_GROUPS} groups or fewer from where it is"
    return None
