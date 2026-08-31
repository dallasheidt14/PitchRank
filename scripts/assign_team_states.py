#!/usr/bin/env python3
"""
Assign and correct ``teams.state_code`` from ranked evidence.

A team's state means **where its club is based**, not where it plays. Every tier below
is a way of asking that question; travel-derived signals are not tiers at all.

    Tier A  0.95  the GotSport ``team_association`` the team registers with
    Tier B  0.90  the club's own state: its registry home, else the one state a
                  meaningful share of its other teams sit in
    Tier C  0.85  a US state named in the team's own name
    Tier D  0.85  the modal state of a gated TGS tournament's participants
    Tier E  0.85  a place in the team's or club's name, learned from where teams
                  carrying that word actually sit

The highest tier that fires wins and is recorded as ``state_source``. A team with no
state is a **fill**; a team whose state a tier disputes is a **correction**. Fills
auto-apply from any tier; corrections auto-apply only from A or B. Everything else
writes a review-queue row and changes nothing.

One correction never auto-applies whatever the tier: one that would overwrite a state
some writer also spelled out in the full-name ``state`` column. That column is set by
four writers and by nothing else, so an empty one is hard evidence the state was derived
-- which is the 96% case this tool exists for -- while a filled one means the value came
from a provider payload, a TGS import, or an admin form. Counting a club's other teams is
not evidence enough to overrule that; a per-team provider record is, so Tier A is exempt.

Usage:
    python scripts/assign_team_states.py --out run.json                  # dry run
    python scripts/assign_team_states.py --execute --snapshot run.json [--limit 50]
    python scripts/assign_team_states.py --team <uuid> [--execute]       # one team
    python scripts/assign_team_states.py --team <uuid> --set OH --reason '...' --execute

**The dry run is the only thing that decides.** It snapshots every team's state, writes
its decisions to ``--out``, and ``--execute`` replays that file -- it never recomputes.
Two reasons: a fill written early changes the clubmate distribution a later team's Tier B
reads, and the other weekly writers can turn a recorded fill into an unrecorded
correction between the two commands. Each write carries the snapshotted state as a
predicate, so a team that moved since is skipped and reported rather than overwritten.

Writes go through ``apply_team_state``, which stamps the ledger with actor
``assign_team_states``. To undo a batch:

    revert_team_states('assign_team_states', <from>, <to>, '<you>', NULL, 500, false, '<why>')

Any two of the club, the team name and the place in the name disagreeing stops the
cascade and sends the team to review, whichever tier would have won -- unless the
provider record answered, which settles it. That widened check is what catches a club
whose teams are uniformly mislabelled: it agrees with itself, so nothing local
disputes it, and five of the six Boise Timbers teams said Wyoming.

Two limits, both deliberate and both reported by the run:

* **Tier A is probed for decision candidates only** -- teams with no state, and teams
  another tier disputes. It is one HTTP call per team against GotSport, so probing all
  200,164 live teams to find the ones nothing else disputes is not a thing this tool
  does. A team every other tier agrees with is left alone.
* **Tier D is not implemented.** It would need ``tgs_events``, which is not populated,
  and the per-event participant aggregation behind its gate. Of the teams it would
  serve, four were visible on a state board and none of them needed it. The run says
  the tier did not fire rather than reporting a silent zero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.backfill_state_from_team_name import state_from_name  # noqa: E402
from src.utils.club_state_registry import home_state, requires_review  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402
from src.utils.team_association_map import to_state_code  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

console = Console()

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

ACTOR = "assign_team_states"

# A person's answer is stamped separately from the sweep's, because a revert scopes by
# actor and undoing a sweep must never undo the answers a person gave.
OPERATOR_ACTOR = "operator"

TIER_CONFIDENCE = {"A": 0.95, "B": 0.90, "C": 0.85, "D": 0.85, "E": 0.85, "R9": 0.90}

# Tier E's vocabulary. A place name in a team or club name is a locality claim; these
# words are not, however concentrated they look. "Surf" and "Rush" are national brands
# with a dominant state, which is exactly the shape that would read as a place.
NOT_A_PLACE = frozenset(
    {
        "academy", "athletic", "athletics", "assoc", "association", "club", "cup", "fall",
        "football", "futbol", "inc", "junior", "juniors", "league", "soccer", "spring",
        "summer", "team", "teams", "tournament", "youth",
        "elite", "premier", "select", "classic", "united", "sporting", "rush", "surf",
        "black", "blue", "gold", "gray", "green", "grey", "maroon", "navy", "orange",
        "pink", "purple", "royal", "silver", "teal", "white", "yellow",
        "boys", "girls", "boy", "girl", "next", "usys", "ecnl", "npl", "dpl", "mls",
        "central", "east", "eastern", "north", "northern", "south", "southern", "west",
        "western",
    }
)

# A token earns a state at ten teams and ninety percent. Below that it is a coincidence:
# "springfield" spans four states and "portland" three, and both correctly fail this.
LOCALITY_MIN_TEAMS = 10
LOCALITY_MIN_SHARE = 0.90

# A stored province is legitimate data. No tier corrects it, and it is never counted as
# malformed -- 1,412 teams are Canadian.
CANADIAN_PROVINCES = frozenset(
    {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
)

# A state is meaningful to its club at two or more teams AND a twentieth of the club's
# known-state teams. Tier B fires only when exactly one state clears both.
MEANINGFUL_MIN_TEAMS = 2
MEANINGFUL_MIN_PCT = 5.0

GOTSPORT_TEAM_DETAILS = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

PAGE_SIZE = 1000
IN_BATCH = 100  # URI length caps .in_() lists
DEFAULT_WORKERS = 10


def club_key(club_name: Optional[str]) -> str:
    """The registry's key, and the only grouping key for clubs.

    Raw ``club_name`` splits one club across case and whitespace variants;
    ``normalize_club_name`` merges clubs that are not the same club.

    A placeholder keys to "" so every reader treats it as no club at all. Tier B and
    the locality index both already skip a falsy key, so this is the whole fix: without
    it, TGS's "No Club Selection" is the largest club_name in the database, 1,596 teams
    across 23 states, and the tier abstains only because no single state is meaningful
    enough to win. That is a property of today's distribution, not a rule.
    """
    key = (club_name or "").strip().lower()
    return "" if is_placeholder_club(key) else key


# --------------------------------------------------------------------------- #
# Reading the world
# --------------------------------------------------------------------------- #


def fetch_live_teams(sb) -> List[Dict]:
    """Every non-deprecated team, with the fields the tiers read."""
    teams: List[Dict] = []
    offset = 0
    while True:
        page = (
            sb.table("teams")
            .select("team_id_master,team_name,club_name,state_code,state")
            .eq("is_deprecated", False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        rows = page.data or []
        teams.extend(rows)
        if len(rows) < PAGE_SIZE:
            return teams
        offset += PAGE_SIZE
        if offset % 50000 == 0:
            console.print(f"[dim]  {offset:,} teams read[/dim]")


def fetch_revert_blocks(sb) -> Set[Tuple[str, str]]:
    """``(team, state)`` pairs an operator has already reverted away from (R17).

    Keyed on the ledger's ``old_state_code`` because a revert row records the value being
    undone there. Re-applying it is exactly what the operator rejected, so it queues.
    """
    blocks: Set[Tuple[str, str]] = set()
    offset = 0
    while True:
        page = (
            sb.table("team_state_audit")
            .select("team_id_master,old_state_code")
            .eq("action", "revert")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        rows = page.data or []
        for row in rows:
            if row.get("old_state_code"):
                blocks.add((row["team_id_master"], row["old_state_code"].strip()))
        if len(rows) < PAGE_SIZE:
            return blocks
        offset += PAGE_SIZE


def fetch_queue_rows(sb) -> Dict[Tuple[str, str], Dict]:
    """The newest queue row per ``(team, proposed state)`` -- R24's suppression key."""
    rows_by_key: Dict[Tuple[str, str], Dict] = {}
    offset = 0
    while True:
        page = (
            sb.table("team_state_review_queue")
            .select("id,team_id_master,proposed_state_code,status")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        rows = page.data or []
        for row in rows:
            key = (row["team_id_master"], (row.get("proposed_state_code") or "").strip())
            rows_by_key[key] = row
        if len(rows) < PAGE_SIZE:
            return rows_by_key
        offset += PAGE_SIZE


def fetch_gotsport_aliases(sb, team_ids: List[str]) -> Dict[str, str]:
    """``team_id_master`` → GotSport ``provider_team_id`` for the teams asked about."""
    provider = sb.table("providers").select("id").eq("code", "gotsport").limit(1).execute()
    if not provider.data:
        return {}
    provider_id = provider.data[0]["id"]

    aliases: Dict[str, str] = {}
    for start in range(0, len(team_ids), IN_BATCH):
        batch = team_ids[start : start + IN_BATCH]
        page = (
            sb.table("team_alias_map")
            .select("team_id_master,provider_team_id")
            .eq("provider_id", provider_id)
            .in_("team_id_master", batch)
            .execute()
        )
        for row in page.data or []:
            aliases.setdefault(row["team_id_master"], str(row["provider_team_id"]))
    return aliases


def ranked_and_active(sb, team_ids: List[str]) -> List[str]:
    """Which of these teams a visitor can actually see on a board today."""
    visible: List[str] = []
    for start in range(0, len(team_ids), IN_BATCH):
        page = (
            sb.table("rankings_full")
            .select("team_id")
            .eq("status", "Active")
            .in_("team_id", team_ids[start : start + IN_BATCH])
            .execute()
        )
        visible.extend(row["team_id"] for row in page.data or [])
    return visible


# --------------------------------------------------------------------------- #
# The tiers
# --------------------------------------------------------------------------- #


def build_club_index(teams: List[Dict]) -> Dict[str, Counter]:
    """Per club, how many of its teams sit in each state."""
    index: Dict[str, Counter] = defaultdict(Counter)
    for team in teams:
        key = club_key(team.get("club_name"))
        state = (team.get("state_code") or "").strip()
        if key and state:
            index[key][state] += 1
    return index


def name_tokens(team: Dict):
    """The words in a team's own name and its club's that could name a place.

    A placeholder club contributes none of them. 1,596 teams share "No Club Selection",
    so "selection" would otherwise be offered to the locality index by more teams than
    carry any real town's name -- and NOT_A_PLACE holds "club" but not "selection".
    """
    club = team.get("club_name")
    for text in (team.get("team_name"), None if is_placeholder_club(club) else club):
        for token in re.split(r"[^a-z]+", (text or "").lower()):
            if len(token) >= 4 and token not in NOT_A_PLACE:
                yield token


def build_locality_index(teams: List[Dict]) -> Dict[str, str]:
    """Learn which name tokens mean a state, from the teams that already have one.

    "Boise" appears in 173 team names and 95% of them are Idaho, so the word carries a
    state even though no tier reads it: Tier C looks for the word *Idaho*, and a club
    whose teams are uniformly mislabelled agrees with itself. Both were true of the six
    Boise Timbers teams, five of which said Wyoming.

    Learned from the column being audited, so it is circular in the strict sense and its
    first job is to raise doubt rather than to assert -- see the conflict check in
    ``decide``. The thresholds are what keep it honest: a token needs ten teams and
    ninety percent agreement, which "springfield" (four states) and "portland" (three)
    never reach.
    """
    counts: Dict[str, Counter] = defaultdict(Counter)
    for team in teams:
        state = (team.get("state_code") or "").strip()
        if not state:
            continue
        for token in set(name_tokens(team)):
            counts[token][state] += 1

    index: Dict[str, str] = {}
    for token, states in counts.items():
        total = sum(states.values())
        if total < LOCALITY_MIN_TEAMS:
            continue
        state, hits = states.most_common(1)[0]
        if hits / total >= LOCALITY_MIN_SHARE:
            index[token] = state
    return index


def locality_state(team: Dict, locality_index: Dict[str, str]) -> Optional[str]:
    """The one state this team's own words point at, or None.

    None when they point at two different states -- "Dallas Texans at the Vegas Cup" is
    a fixture, not a home -- for the same reason Tier C refuses a name holding two
    state names.
    """
    states = {locality_index[token] for token in name_tokens(team) if token in locality_index}
    return states.pop() if len(states) == 1 else None


def club_derived_state(team: Dict, club_index: Dict[str, Counter]) -> Optional[str]:
    """Tier B: the club's own state, or None when its teams do not settle one.

    A registry ``home`` replaces the computed test outright (R11). Otherwise the count
    excludes the team being decided, because a wrongly-coded team otherwise votes for
    the minority bucket it created -- and one clubmate sharing the error is enough to
    reach the two-team floor and silence the tier on the very teams it should correct.
    """
    key = club_key(team.get("club_name"))
    if not key:
        return None

    home = home_state(key)
    if home:
        return home

    counts = Counter(club_index.get(key, {}))
    stored = (team.get("state_code") or "").strip()
    if stored:
        counts[stored] -= 1
    others = {state: n for state, n in counts.items() if n > 0}
    known = sum(others.values())
    if not known:
        return None

    meaningful = [
        state
        for state, n in others.items()
        if n >= MEANINGFUL_MIN_TEAMS and 100.0 * n / known >= MEANINGFUL_MIN_PCT
    ]
    return meaningful[0] if len(meaningful) == 1 else None


def probe_associations(
    provider_team_ids: Dict[str, str], workers: int
) -> Tuple[Dict[str, str], Counter]:
    """Tier A: ``team_id_master`` → state, plus a count of what every call did.

    Routed through ``_zenrows_get`` because GotSport blocks a direct burst: probing 6,180
    ids at ten threads earned a 403 on every subsequent call, and the first version of
    this function counted each of those as "team has no association" -- a silenced tier
    that reports zero rather than failing. Hence both the outcome counter and the abort
    below: a blocked probe must look like a blocked probe.

    An unmapped code returns nothing rather than a guess: ``CAN`` is California North,
    not Canada, and treating any two-letter value as a postal code is what sends a
    Brazilian team to a US state board.
    """
    # Imported here, not at module scope. ``src.scrapers.gotsport`` reaches BaseScraper
    # and config.settings, which pull pandas, scipy, sklearn and xgboost -- a chain no
    # tier but this one needs. The scheduled fills-only job runs --no-tier-a and so never
    # arrives here, which lets its runner install five packages instead of requirements.
    # Still at the top of the only function that probes, so a broken install fails before
    # the first call rather than partway through 6,200 of them.
    from src.scrapers.gotsport import _zenrows_get

    session = requests.Session()
    api_key = os.getenv("ZENROWS_API_KEY")
    states: Dict[str, str] = {}
    outcomes: Counter = Counter()

    def probe(item: Tuple[str, str]) -> Tuple[str, Optional[str], str]:
        team_id, provider_team_id = item
        url = f"{GOTSPORT_TEAM_DETAILS}?team_id={provider_team_id}"
        try:
            response = _zenrows_get(session, api_key, url, timeout=15, delay_min=0.1, delay_max=0.3)
        except requests.RequestException as exc:
            return team_id, None, f"request failed ({type(exc).__name__})"
        if response.status_code == 404:
            return team_id, None, "no such team (404)"
        if response.status_code != 200:
            return team_id, None, f"http {response.status_code}"
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            return team_id, None, "unparseable payload"
        if not isinstance(payload, dict):
            return team_id, None, "unparseable payload"

        raw = str(payload.get("team_association") or "").strip()
        if not raw:
            return team_id, None, "no association in payload"
        state = to_state_code(raw)
        return (team_id, state, "mapped") if state else (team_id, None, f"unmapped code {raw}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for team_id, state, outcome in pool.map(probe, provider_team_ids.items()):
            outcomes[outcome.split(" (")[0] if outcome.startswith("request failed") else outcome] += 1
            if state:
                states[team_id] = state
    return states, outcomes


def probe_is_unusable(outcomes: Counter) -> bool:
    """Whether the probe failed often enough that Tier A's silence means nothing."""
    total = sum(outcomes.values())
    if not total:
        return False
    failures = sum(
        count
        for outcome, count in outcomes.items()
        if outcome.startswith(("http", "request failed", "unparseable"))
    )
    return failures > total * 0.2


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #


def decide(
    team: Dict,
    club_index: Dict[str, Counter],
    locality_index: Dict[str, str],
    association_states: Dict[str, str],
    revert_blocks: Set[Tuple[str, str]],
) -> Optional[Dict]:
    """One team's decision, or None when nothing fires or nothing would change."""
    team_id = team["team_id_master"]
    stored = (team.get("state_code") or "").strip() or None

    # R7. A stored province outranks every rule below it, including R9.
    if stored in CANADIAN_PROVINCES:
        return None

    name_state = state_from_name(team.get("team_name"))
    club_state = club_derived_state(team, club_index)
    place_state = locality_state(team, locality_index)

    # R9, widened to three readings of where the club is. Any two of them disagreeing
    # stops the cascade before it resolves: whichever tier would have won, the answer is
    # in doubt. The locality reading is here because a club whose teams are uniformly
    # mislabelled agrees with itself -- five of six Boise Timbers teams said Wyoming, so
    # nothing local disputed the sixth and the sweep wrote Wyoming onto it.
    readings = {
        "team name": name_state,
        "club": club_state,
        "place in the name": place_state,
    }
    voted = {label: state for label, state in readings.items() if state}
    association_state = association_states.get(team_id)
    if len(set(voted.values())) > 1 and not association_state:
        disagreement = ", ".join(f"{label} says {state}" for label, state in sorted(voted.items()))
        return _decision(
            team,
            proposed=club_state or place_state or name_state,
            tier="R9",
            action="queue",
            reason=disagreement,
        )

    for tier, proposed in (
        ("A", association_state),
        ("B", club_state),
        ("C", name_state),
        ("E", place_state),
    ):
        if proposed:
            break
    else:
        return None

    if proposed == stored:
        return None

    is_fill = stored is None
    reason = f"{'fill' if is_fill else f'correct {stored}'} → {proposed} from tier {tier}"

    # R17. An operator has already put this exact value back; do not re-apply it.
    if (team_id, proposed) in revert_blocks:
        return _decision(team, proposed, tier, "queue", f"{reason}; reverted before")

    # R8. Every sampled DC team's association reports MD, so a tier proposing something
    # else would silently relabel the District.
    if stored == "DC":
        return _decision(team, proposed, tier, "queue", f"{reason}; stored DC")

    # R6. Club-level evidence cannot pick a home for a curated club. Tier A is exempt:
    # it reads a per-team record, so the club's ambiguity does not touch it.
    if tier != "A" and requires_review(team.get("club_name")):
        return _decision(team, proposed, tier, "queue", f"{reason}; club needs curation")

    # A stored state that some writer put in the full-name column too is not obviously
    # guessed, and counting the club is not evidence enough to overrule it -- Chariho
    # YSA is a Rhode Island club whose clubmate bucket says New York. Tier A is exempt
    # again: a per-team provider record may overrule a per-team value, a club count
    # may not.
    if not is_fill and tier != "A" and (team.get("state") or "").strip():
        return _decision(team, proposed, tier, "queue", f"{reason}; stored value was reported")

    # R5. Fills auto-apply from any tier; corrections only from A or B.
    if is_fill or tier in ("A", "B"):
        return _decision(team, proposed, tier, "apply", reason)
    return _decision(team, proposed, tier, "queue", f"{reason}; tier {tier} cannot correct")


def _decision(team: Dict, proposed: str, tier: str, action: str, reason: str) -> Dict:
    return {
        "team_id": team["team_id_master"],
        "team_name": team.get("team_name"),
        "club_name": team.get("club_name"),
        "pre_image": (team.get("state_code") or "").strip() or None,
        "proposed": proposed,
        "tier": tier,
        "confidence": TIER_CONFIDENCE[tier],
        "action": action,
        "reason": reason,
    }


def build_snapshot(sb, use_tier_a: bool, workers: int, only_team: Optional[str] = None) -> Dict:
    """Decide every live team against one reading of the database.

    ``only_team`` narrows the decisions and the GotSport probe to one team, and nothing
    else: Tier B still counts that team's clubmates, so the whole table is still read.
    """
    console.print("[bold]Reading teams[/bold]")
    teams = fetch_live_teams(sb)
    console.print(f"  {len(teams):,} live teams")

    club_index = build_club_index(teams)
    console.print(f"  {len(club_index):,} clubs")

    locality_index = build_locality_index(teams)
    console.print(f"  {len(locality_index):,} name tokens that carry a state")

    revert_blocks = fetch_revert_blocks(sb)
    if revert_blocks:
        console.print(f"  {len(revert_blocks):,} reverted (team, state) pairs to respect")

    # Not "is tgs_events populated": the tier has no implementation, so a populated
    # table would silence this warning while changing nothing. Filling the table is the
    # smaller half of building it.
    tier_d_ready = False
    console.print("  [yellow]Tier D is not implemented; it fires for nothing[/yellow]")

    # Two passes. The first finds the teams any tier disputes, which is the only set
    # worth spending a GotSport call on; the second re-decides them with Tier A in hand.
    # One named team is always probed, even when every other tier is content. That is the
    # whole point of asking about one team: a club whose teams are uniformly mislabelled
    # agrees with itself, so nothing local disputes the value and the sweep never looks.
    if only_team:
        candidates = [only_team]
    else:
        disputed = {
            d["team_id"]
            for d in (decide(t, club_index, locality_index, {}, revert_blocks) for t in teams)
            if d
        }
        # Plus every team with no state at all, decided or not. A stateless team no other
        # tier reaches would otherwise never be probed and would be reported undecidable
        # without anyone having asked the one source that could answer.
        stateless = {t["team_id_master"] for t in teams if not (t.get("state_code") or "").strip()}
        candidates = sorted(disputed | stateless)

    association_states: Dict[str, str] = {}
    if use_tier_a and candidates:
        console.print(f"[bold]Probing GotSport[/bold] for {len(candidates):,} candidates")
        aliases = fetch_gotsport_aliases(sb, candidates)
        console.print(f"  {len(aliases):,} have a GotSport id")
        association_states, outcomes = probe_associations(aliases, workers)
        for outcome, count in outcomes.most_common():
            console.print(f"[dim]  {count:>6,}  {outcome}[/dim]")
        if probe_is_unusable(outcomes):
            console.print(
                "[red]Tier A is blocked, not quiet: too many calls failed for its silence to "
                "mean anything. Re-run when GotSport lets us back in, or --no-tier-a to decide "
                "without it deliberately.[/red]"
            )
            sys.exit(1)

    decisions = [
        d
        for d in (
            decide(team, club_index, locality_index, association_states, revert_blocks)
            for team in teams
        )
        if d and only_team in (None, d["team_id"])
    ]
    # Teams no tier can decide never reach the review queue either, because a queue row
    # has to carry a proposal. Most of them are dormant and nobody would notice; the ones
    # ranked Active are on a state board right now with no state, so the run names them
    # rather than leaving them to be silently unfixable.
    decided = {d["team_id"] for d in decisions}
    undecided = [
        t["team_id_master"]
        for t in teams
        if not (t.get("state_code") or "").strip() and t["team_id_master"] not in decided
    ]
    stranded = ranked_and_active(sb, undecided) if undecided else []

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actor": ACTOR,
        "live_teams": len(teams),
        "tier_a_probed": len(association_states),
        "tier_d_available": tier_d_ready,
        "undecidable": len(undecided),
        "undecidable_and_visible": stranded,
        "decisions": decisions,
    }


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


def apply_decision(sb, decision: Dict, reason: str) -> bool:
    """Write one state through the ledgered path. False means the row moved since."""
    result = sb.rpc(
        "apply_team_state",
        {
            "p_team_id": decision["team_id"],
            "p_expected_state_code": decision["pre_image"],
            "p_state_code": decision["proposed"],
            "p_source": f"tier_{decision['tier'].lower()}",
            "p_confidence": decision["confidence"],
            "p_actor": ACTOR,
            "p_action": "fill" if decision["pre_image"] is None else "correct",
            "p_reason": reason,
        },
    ).execute()
    return bool(result.data)


def queue_decision(sb, decision: Dict, existing: Dict[Tuple[str, str], Dict]) -> str:
    """Raise or refresh one review-queue row. Returns what it did.

    Four outcomes, three of which write nothing: a rejected proposal is not re-raised
    (R24), an approved one is not re-raised, and an open one is updated in place rather
    than duplicated -- a queued decision changes nothing, so every sweep recomputes it
    identically and would otherwise insert a fresh row each week.
    """
    key = (decision["team_id"], decision["proposed"])
    row = existing.get(key)
    payload = {
        "team_id_master": decision["team_id"],
        "current_state_code": decision["pre_image"],
        "proposed_state_code": decision["proposed"],
        "tier": decision["tier"],
        "confidence": decision["confidence"],
        "reason": decision["reason"],
    }

    if row is None:
        sb.table("team_state_review_queue").insert(payload).execute()
        return "queued"
    if row["status"] == "rejected":
        return "skipped_rejected"
    if row["status"] == "approved":
        return "skipped_already_approved"
    sb.table("team_state_review_queue").update(payload).eq("id", row["id"]).execute()
    return "deduped_pending"


def state_of(sb, team_id: str) -> Optional[str]:
    """One team's state as it stands right now."""
    found = (
        sb.table("teams").select("state_code").eq("team_id_master", team_id).limit(1).execute()
    )
    return ((found.data[0].get("state_code") if found.data else None) or "").strip() or None


def mirror_rankings(sb, applied: List[Dict]) -> int:
    """Carry applied states into ``rankings_full`` so the boards agree today.

    An UPDATE, never an upsert: Monday's ranking run re-derives the column from ``teams``
    and an inserted row would be a ranking that no run produced.
    """
    mirrored = 0
    by_state: Dict[str, List[str]] = defaultdict(list)
    for decision in applied:
        by_state[decision["proposed"]].append(decision["team_id"])

    for state, team_ids in by_state.items():
        for start in range(0, len(team_ids), IN_BATCH):
            batch = team_ids[start : start + IN_BATCH]
            result = (
                sb.table("rankings_full")
                .update({"state_code": state})
                .in_("team_id", batch)
                .execute()
            )
            mirrored += len(result.data or [])
    return mirrored


def apply_snapshot(
    sb, snapshot: Dict, limit: Optional[int], fills_only: bool = False
) -> None:
    decisions = snapshot["decisions"]
    to_apply = [d for d in decisions if d["action"] == "apply"]
    to_queue = [d for d in decisions if d["action"] == "queue"]

    # A correction is not safe to write unattended, and that is measured rather than
    # cautious. Two consecutive dry runs propose 664 applies, 90 of which overwrite what
    # the first pass just wrote: a fill changes the clubmate distribution Tier B reads
    # next time, so the club count starts overruling per-team records it agreed with an
    # hour ago. Two teams of one club oscillate between NV and WA with no fixed point.
    # A fill cannot do that -- it overwrites nothing, and its worst case is a wrong state
    # on a team that had none, which is visible, logged and reversible. So the scheduled
    # job takes the fills and leaves every correction to an operator running the sweep.
    # Filtered before --limit, so that limit still counts rows this will actually write.
    if fills_only:
        withheld = sum(1 for d in to_apply if d["pre_image"] is not None)
        to_apply = [d for d in to_apply if d["pre_image"] is None]
        console.print(
            f"[yellow]--fills-only: withholding {withheld:,} corrections for an "
            f"operator-run sweep[/yellow]"
        )

    if limit is not None:
        if limit < 0:
            console.print("[red]ERROR: --limit cannot be negative; it would apply all but the last[/red]")
            sys.exit(1)
        to_apply = to_apply[:limit]
        to_queue = to_queue[:limit]

    # Re-read the ledger rather than trusting the snapshot's reading of it. Between a
    # limited batch and the run that finishes it, an operator may have reverted one of the
    # rows already written -- and a revert restores the pre-image, so replaying that
    # decision would find its predicate satisfied and quietly undo the rollback.
    blocked_now = fetch_revert_blocks(sb)
    blocked = [d for d in to_apply if (d["team_id"], d["proposed"]) in blocked_now]
    if blocked:
        to_apply = [d for d in to_apply if (d["team_id"], d["proposed"]) not in blocked_now]
        to_queue = to_queue + [
            dict(d, action="queue", reason=f"{d['reason']}; reverted since the snapshot")
            for d in blocked
        ]
        console.print(
            f"[yellow]{len(blocked):,} decisions reverted since the snapshot; "
            f"queued instead[/yellow]"
        )

    reason = f"snapshot {snapshot['created_at']}"
    applied: List[Dict] = []
    moved: List[Dict] = []
    for decision in to_apply:
        if apply_decision(sb, decision, reason):
            applied.append(decision)
        else:
            moved.append(decision)
    console.print(f"[green]✓[/green] Applied {len(applied):,}, skipped {len(moved):,} that moved")

    # A team already sitting at its proposed state was written by an earlier run of this
    # same snapshot, and that run may have died between the write and the mirror. The
    # write is committed and cannot be replayed -- its pre-image is gone -- so the mirror
    # is the only half left to finish, and nothing else would ever retry it.
    already = [d for d in moved if state_of(sb, d["team_id"]) == d["proposed"]]
    if already:
        console.print(f"[dim]  {len(already):,} were already at their proposed state[/dim]")

    existing = fetch_queue_rows(sb)
    outcomes: Counter = Counter()
    for decision in to_queue:
        outcomes[queue_decision(sb, decision, existing)] += 1
    console.print(
        "[green]✓[/green] Queue: "
        + ", ".join(f"{count:,} {name}" for name, count in sorted(outcomes.items()))
    )

    to_mirror = applied + already
    if to_mirror:
        console.print(f"[green]✓[/green] Mirrored {mirror_rankings(sb, to_mirror):,} ranking rows")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def summarize(snapshot: Dict) -> None:
    decisions = snapshot["decisions"]
    fills = [d for d in decisions if d["pre_image"] is None]
    corrections = [d for d in decisions if d["pre_image"] is not None]

    table = Table(title="Decisions", header_style="bold")
    table.add_column("Tier")
    table.add_column("Fills apply", justify="right")
    table.add_column("Fills queue", justify="right")
    table.add_column("Corrections apply", justify="right")
    table.add_column("Corrections queue", justify="right")
    for tier in ("A", "B", "C", "D", "E", "R9"):
        row = [
            f"{sum(1 for d in fills if d['tier'] == tier and d['action'] == 'apply'):,}",
            f"{sum(1 for d in fills if d['tier'] == tier and d['action'] == 'queue'):,}",
            f"{sum(1 for d in corrections if d['tier'] == tier and d['action'] == 'apply'):,}",
            f"{sum(1 for d in corrections if d['tier'] == tier and d['action'] == 'queue'):,}",
        ]
        if any(value != "0" for value in row):
            table.add_row(tier, *row)
    console.print(table)

    console.print(
        f"[bold]{sum(1 for d in decisions if d['action'] == 'apply'):,}[/bold] to apply, "
        f"[bold]{sum(1 for d in decisions if d['action'] == 'queue'):,}[/bold] to review, "
        f"across {len(fills):,} fills and {len(corrections):,} corrections."
    )
    if not snapshot["tier_d_available"]:
        console.print("[yellow]Tier D did not fire: it is not implemented[/yellow]")

    stranded = snapshot.get("undecidable_and_visible") or []
    console.print(
        f"[dim]{snapshot.get('undecidable', 0):,} teams have no state and no tier that can "
        f"decide them; they cannot be queued either, because a queue row needs a proposal.[/dim]"
    )
    if stranded:
        console.print(
            f"[yellow]{len(stranded)} of them are ranked and Active, so they are on a state "
            f"board today with no state. These need a person:[/yellow]"
        )
        for team_id in stranded[:20]:
            console.print(f"[yellow]  {team_id}[/yellow]")


def assign_by_hand(sb, team_id: str, state: str, reason: Optional[str], execute: bool) -> None:
    """Write the operator's own answer for one team (R21).

    Stamped ``operator`` rather than ``assign_team_states`` so the two are separable
    forever: a revert scopes by actor, and undoing a sweep must not undo the answers a
    person gave. Confidence is 1.0 because a person is not a tier -- no evidence was
    weighed, someone knows.
    """
    state = (state or "").strip().upper()
    if state not in STATE_CODE_TO_NAME and state not in CANADIAN_PROVINCES:
        console.print(f"[red]ERROR: {state!r} is not a US state, DC, or a Canadian province[/red]")
        sys.exit(1)

    found = (
        sb.table("teams")
        .select("team_id_master,team_name,state_code,is_deprecated")
        .eq("team_id_master", team_id)
        .limit(1)
        .execute()
    )
    if not found.data:
        console.print(f"[red]ERROR: no team {team_id}[/red]")
        sys.exit(1)

    team = found.data[0]
    if team.get("is_deprecated"):
        merged = (
            sb.table("team_merge_map")
            .select("canonical_team_id")
            .eq("deprecated_team_id", team_id)
            .limit(1)
            .execute()
        )
        canonical = merged.data[0]["canonical_team_id"] if merged.data else "unknown"
        console.print(
            f"[red]ERROR: {team_id} is deprecated, so nothing reads its state. "
            f"Assign the team it merged into: {canonical}[/red]"
        )
        sys.exit(1)

    current = (team.get("state_code") or "").strip() or None
    decision = {
        "team_id": team_id,
        "pre_image": current,
        "proposed": state,
        "tier": None,
        "confidence": 1.0,
    }
    if current == state:
        # Already there, which is also what a retry looks like after the write committed
        # and the mirror did not. The mirror is the only half left to finish.
        console.print(f"[yellow]{team['team_name']} is already {state}[/yellow]")
        if execute:
            console.print(f"[green]✓[/green] Mirrored {mirror_rankings(sb, [decision]):,} ranking rows")
        return

    if not execute:
        console.print(
            f"[yellow]Would set {team['team_name']}: {current} → {state}. "
            f"Re-run with --execute to write it.[/yellow]"
        )
        return
    applied = sb.rpc(
        "apply_team_state",
        {
            "p_team_id": team_id,
            "p_expected_state_code": current,
            "p_state_code": state,
            "p_source": "operator",
            "p_confidence": 1.0,
            "p_actor": OPERATOR_ACTOR,
            "p_action": "fill" if current is None else "correct",
            "p_reason": reason or "assigned by hand",
        },
    ).execute()
    if not applied.data:
        console.print("[yellow]Skipped: the team's state moved since it was read[/yellow]")
        return
    console.print(f"[green]✓[/green] {team['team_name']}: {current} → {state}")
    console.print(f"[green]✓[/green] Mirrored {mirror_rankings(sb, [decision]):,} ranking rows")


def report_team(sb, snapshot: Dict, team_id: str, execute: bool) -> None:
    """Show one team's decision, and apply it when asked (R21).

    The single-team path needs no snapshot file. A snapshot exists to keep a sweep's
    thousands of decisions consistent with each other and with the database they were
    computed against; one decision applied in the same breath as it was computed has
    neither problem.
    """
    for decision in snapshot["decisions"]:
        if decision["team_id"] != team_id:
            continue
        console.print_json(data=decision)
        if not execute:
            return
        if decision["action"] != "apply":
            console.print(f"[yellow]Not applied: this decision is for review ({decision['reason']})[/yellow]")
            return
        if apply_decision(sb, decision, f"single team, {snapshot['created_at']}"):
            console.print(f"[green]✓[/green] {decision['pre_image']} → {decision['proposed']}")
            console.print(f"[green]✓[/green] Mirrored {mirror_rankings(sb, [decision]):,} ranking rows")
        else:
            console.print("[yellow]Skipped: the team's state moved since it was read[/yellow]")
        return
    console.print(f"[yellow]No decision for {team_id}: no tier fired, or nothing would change[/yellow]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign and correct teams.state_code")
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Default. Decide and report, write nothing"
    )
    parser.add_argument("--execute", action="store_true", help="Apply a snapshot's decisions")
    parser.add_argument("--snapshot", help="Snapshot to apply; required by --execute")
    parser.add_argument("--out", help="Where the dry run writes its decisions")
    parser.add_argument("--limit", type=int, help="Apply at most this many of each outcome")
    parser.add_argument("--team", help="Report the decision for one team_id_master")
    parser.add_argument("--set", dest="set_state", help="Assign this state to --team by hand, no tiers")
    parser.add_argument("--reason", help="Why, recorded in the ledger beside a --set")
    parser.add_argument("--no-tier-a", action="store_true", help="Skip the GotSport probe")
    parser.add_argument(
        "--fills-only",
        action="store_true",
        help="With --execute, apply only decisions that fill a blank; withhold every correction",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help=f"Probe threads (default {DEFAULT_WORKERS})"
    )
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        console.print("[red]ERROR: Missing SUPABASE_URL or SUPABASE_KEY[/red]")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    if args.set_state:
        if not args.team:
            console.print("[red]ERROR: --set needs --team; it assigns one team[/red]")
            sys.exit(1)
        assign_by_hand(sb, args.team, args.set_state, args.reason, execute=args.execute)
        return

    if args.execute and not args.team:
        if not args.snapshot:
            console.print("[red]ERROR: --execute needs --snapshot; a fresh reading is not a decision[/red]")
            sys.exit(1)
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        console.print(f"[bold]Applying[/bold] {args.snapshot} (taken {snapshot['created_at']})")
        apply_snapshot(sb, snapshot, args.limit, fills_only=args.fills_only)
        return

    snapshot = build_snapshot(
        sb, use_tier_a=not args.no_tier_a, workers=args.workers, only_team=args.team
    )

    if args.team:
        report_team(sb, snapshot, args.team, args.execute)
        return

    summarize(snapshot)
    if args.out:
        Path(args.out).write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
        console.print(f"[green]✓[/green] Snapshot written to {args.out}")
    else:
        console.print("[yellow]No --out given, so nothing can be applied from this run[/yellow]")


if __name__ == "__main__":
    main()
