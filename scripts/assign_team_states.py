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
    python scripts/assign_team_states.py --audit-contradictions [--probe-limit 50] --out audit.json

**The dry run is the only thing that decides.** It snapshots every team's state, writes
its decisions to ``--out``, and ``--execute`` replays that file -- it never recomputes.
Two reasons: a fill written early changes the clubmate distribution a later team's Tier B
reads, and the other weekly writers can turn a recorded fill into an unrecorded
correction between the two commands. Each write carries the snapshotted state as a
predicate, so a team that moved since is skipped and reported rather than overwritten.

A dry run makes **no team-state and no review-queue writes, but it does persist
paid-probe observations** to ``team_state_probe_log`` -- one row per probe, agreements
included. The GotSport call is paid for whether or not its answer is recorded, and an
agreement is visible nowhere else: it changes no state, so it fires no ledger trigger.

Writes go through ``apply_team_state``, which stamps the ledger with actor
``assign_team_states``. To undo a batch:

    revert_team_states('assign_team_states', <from>, <to>, '<you>', NULL, 500, false, '<why>')

Any two of the club, the team name and the place in the name disagreeing stops the
cascade and sends the team to review, whichever tier would have won -- unless the
provider record answered, which settles it. That widened check is what catches a club
whose teams are uniformly mislabelled: it agrees with itself, so nothing local
disputes it, and five of the six Boise Timbers teams said Wyoming.

Two limits, both deliberate and both reported by the run:

* **Tier A is never probed for every team.** It is one paid HTTP call each, so asking every
  live team is not on the table. A sweep asks about the teams a tier disputes and the teams
  with no state at all; ``--audit-contradictions`` asks instead about the teams whose state
  contradicts a club-mate a provider record already confirmed, which is how a club that
  agrees with itself gets caught; and ``--team`` always asks, whatever the tiers think.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from supabase import create_client

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.backfill_state_from_team_name import affiliate_contradicts, state_from_name  # noqa: E402
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

# The state Tier A proposes when GotSport has no association on file, which is also the
# state it proposes when the association really is Alabama. R8b in ``decide`` is what the
# ambiguity costs; the evidence for it is there. Alabama teams still reach Alabama.
UNSET_DEFAULT_ASSOCIATION = "AL"

# A state is meaningful to its club at two or more teams AND a twentieth of the club's
# known-state teams. Tier B fires only when exactly one state clears both.
MEANINGFUL_MIN_TEAMS = 2
MEANINGFUL_MIN_PCT = 5.0

GOTSPORT_TEAM_DETAILS = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

PAGE_SIZE = 1000
IN_BATCH = 100  # URI length caps .in_() lists

# Rows travel in the request body, where the URI cap on IN_BATCH does not apply.
INSERT_BATCH = 1000

# Deliberately smaller than INSERT_BATCH: these are paid observations, and the sweep runs
# for tens of minutes under an operator who may interrupt it. Ten times fewer at risk, for
# a few more round trips on a run already dominated by one paid HTTP call per team.
FLUSH_EVERY = 100

DEFAULT_WORKERS = 10

PROBE_LOG_TABLE = "team_state_probe_log"

NO_ALIAS_OUTCOME = "no gotsport alias"


def state_source_for(tier: str) -> str:
    """The provenance a write of `tier`'s answer records."""
    return f"tier_{tier.lower()}"


# The outcome a probe records when the provider named a state we recognise, and the
# provenance ``apply_team_state`` stamps for a Tier A write. Both are written in one place
# and read in another, and a mismatch is silent: the audit simply finds no anchors and
# reports a clean zero. So the provenance is derived from the writer above rather than
# spelled again beside it -- two literals held equal by nothing is how that silence gets in.
# ``approve_team_state`` builds the same format independently in SQL, and nothing checks
# the two against each other.
MAPPED_OUTCOME = "mapped"
TIER_A_SOURCE = state_source_for("A")


# An outcome that says something about the run rather than about the team. These are the
# only ones worth retrying, and the only ones that must never suppress a later probe: a
# blocked run stamps every id in its batch, so treating those as answers would skip
# exactly the teams it failed on. Every other outcome is durable.
TRANSIENT_OUTCOMES = ("http", "request failed", "unparseable")

# What the abort counts, which is deliberately wider than what a run retries. A 404 for a
# team we hold a live alias for is a statement about the provider, not about the team, so
# it belongs here -- but it stays out of ``TRANSIENT_OUTCOMES`` because re-buying it every
# run is exactly the waste the durability rule exists to stop. ``no association in payload``
# is the reverse: a legitimate and common per-team answer, so counting it as a failure would
# abort healthy runs. The mapped-share arm below is what catches an outage made of them.
PROVIDER_FAILURE_OUTCOMES = TRANSIENT_OUTCOMES + ("no such team (404)",)

# The mapped-share arm of the abort, and the batch it needs to mean anything. Below the
# floor a run of empty answers is a fact about a few teams; above it, against a healthy
# run where the large majority map, it is the provider having stopped answering.
MIN_BATCH_FOR_SHARE = 20
MIN_MAPPED_SHARE = 0.2

# How long a durable outcome stands before the team is asked again. A registration moves
# at a season boundary at most, and the backlog drains in one uncapped run, so this only
# has to outlast the gap between capped runs.
REPROBE_AFTER_DAYS = 90


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


def stored_state(team: Dict) -> Optional[str]:
    """The state this team currently holds, blank normalised to None.

    One definition, because two readings of it have to agree exactly: the decision's
    ``pre_image`` and the probe ledger's ``stored_state_code`` describe the same value
    for the same team, and a ledger row whose idea of "before" differs from the
    snapshot's cannot be checked against anything.
    """
    return (team.get("state_code") or "").strip() or None


# --------------------------------------------------------------------------- #
# Reading the world
# --------------------------------------------------------------------------- #


def fetch_live_teams(sb) -> List[Dict]:
    """Every non-deprecated team, with the fields the tiers read.

    ``state_source`` is read by the contradiction audit alone, to find the teams a
    provider record has already confirmed. No tier consults it: a tier decides what a
    state should be, and this says where the current one came from.
    """
    teams: List[Dict] = []
    offset = 0
    while True:
        page = (
            sb.table("teams")
            .select("team_id_master,team_name,club_name,state_code,state,state_source")
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


def fetch_recent_probes(sb, cutoff: datetime) -> Dict[str, Tuple[str, Optional[str]]]:
    """``team_id_master`` → the latest ``(outcome, reported state)`` since ``cutoff``.

    Ordered by ``id`` and kept last-write-wins, like ``fetch_queue_rows``: this builds a
    dict of the newest row per team, so it needs a deterministic "latest" on top of the
    stable paging every one of these readers wants.

    Only durable outcomes are returned. A transient one -- a WAF block, a timeout, an
    unparseable body -- says nothing about the team, and letting it suppress a re-probe
    would skip exactly the teams a blocked run failed on, for the whole window, and report
    a smaller candidate set instead of an error.
    """
    latest: Dict[str, Tuple[str, Optional[str]]] = {}
    offset = 0
    while True:
        page = (
            sb.table(PROBE_LOG_TABLE)
            .select("id,team_id_master,outcome,reported_state_code")
            .gte("probed_at", cutoff.isoformat())
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        rows = page.data or []
        for row in rows:
            outcome = row.get("outcome") or ""
            if outcome.startswith(TRANSIENT_OUTCOMES):
                continue
            latest[row["team_id_master"]] = (outcome, row.get("reported_state_code"))
        if len(rows) < PAGE_SIZE:
            return latest
        offset += PAGE_SIZE


def fetch_gotsport_aliases(sb, team_ids: List[str]) -> Dict[str, str]:
    """``team_id_master`` → GotSport ``provider_team_id`` for the teams asked about.

    An empty result means these teams have no alias. A missing provider row means the
    lookup itself is broken, and the two must not arrive as the same value: the caller
    stamps a durable ``no gotsport alias`` on everything it asked about, so returning
    ``{}`` here would file one configuration fault as a per-team fact about the whole
    population and suppress the lot for the re-probe window, without a single call made
    and with nothing for the abort to count.
    """
    provider = sb.table("providers").select("id").eq("code", "gotsport").limit(1).execute()
    if not provider.data:
        raise RuntimeError(
            "No 'gotsport' row in providers: the alias lookup cannot run. Refusing rather "
            "than recording every team as alias-less."
        )
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


def build_anchor_index(teams: List[Dict]) -> Dict[str, Tuple[str, int]]:
    """Per club, the one state its provider-confirmed teams agree on, and how many agree.

    The sibling of ``build_club_index``, and deliberately not the same thing: that one
    counts every team's stored state, which is the column being audited, so a club whose
    teams are uniformly wrong agrees with itself. This counts only states a provider
    record confirmed, which is evidence from outside the column.

    A club whose confirmed teams disagree is omitted rather than resolved by majority.
    Two confirmed states in one club means the name covers two clubs, and that is the
    shape that produces false positives, not a vote to be won.
    """
    confirmed: Dict[str, Counter] = defaultdict(Counter)
    for team in teams:
        key = club_key(team.get("club_name"))
        state = stored_state(team)
        if key and state and team.get("state_source") == TIER_A_SOURCE:
            confirmed[key][state] += 1

    index: Dict[str, Tuple[str, int]] = {}
    for key, states in confirmed.items():
        if len(states) == 1:
            state, count = next(iter(states.items()))
            index[key] = (state, count)
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

    None too when an affiliate marker on the **club name** names a different state, which
    Tier C has always done and this tier did not: "Utah Royals FC - AZ" holds the word
    "utah", so this tier read 22 Arizona teams as Utah while Tier C refused them.

    The club name only, deliberately. Team names carry coach and squad initials in the
    same position -- SoCal Reds FC fields "- AV", "- RK", "- JW", "- JM" and "- AR", all
    of them California -- and 7,496 team names hold a marker of that shape against 1,624
    club names, which are almost all genuine disambiguators: "FC Premier (CA)",
    "Spartans FC (AZ)", "Eastside FC (WA)". Reading initials as a state would suppress
    this tier on teams whose club cannot answer, which is exactly when it is needed.
    Tier C keeps checking the team name: it fires only when a state is named outright,
    so a stray "- MD" there has a state word to contradict rather than a learned one.
    """
    states = {locality_index[token] for token in name_tokens(team) if token in locality_index}
    if len(states) != 1:
        return None
    state = states.pop()
    return None if affiliate_contradicts(team.get("club_name"), state) else state


def contradiction_candidates(
    teams: List[Dict], anchor_index: Dict[str, Tuple[str, int]]
) -> List[Tuple[str, int]]:
    """Teams whose state contradicts a club-mate a provider record already confirmed.

    ``(team_id_master, anchor count)``, strongest evidence first and deterministic on the
    id, so a budget can take a prefix and the next run continues where this one stopped.

    This is the population, not the spend: recency is not consulted here. A team already
    answered is still a candidate, because the answer it produced still belongs in this
    run's decisions. Filtering it out here instead is what silently drops corrections
    already paid for.

    A stored Canadian province is excluded because no tier corrects one, so the call
    would buy nothing. A stored ``DC`` is kept: that one queues rather than applies, and
    a review row carrying the provider's answer is worth the call.
    """
    candidates = []
    for team in teams:
        # A placeholder club keys to "", and a team with no club at all keys the same.
        # Neither can anchor anything, so neither can contradict one.
        key = club_key(team.get("club_name"))
        anchor = anchor_index.get(key) if key else None
        state = stored_state(team)
        if (
            anchor
            and state
            and state != anchor[0]
            and state not in CANADIAN_PROVINCES
            and team.get("state_source") != TIER_A_SOURCE
        ):
            candidates.append((team["team_id_master"], anchor[1]))
    return sorted(candidates, key=lambda pair: (-pair[1], pair[0]))


def probe_list(
    candidates: List[Tuple[str, int]],
    recent: Dict[str, Tuple[str, Optional[str]]],
    probe_limit: Optional[int],
) -> List[str]:
    """The candidates worth paying for, in order, bounded by the budget.

    A team with a recent durable outcome is dropped: it was asked, it answered, and the
    answer is still good. Only what survives that is sliced, so the budget bounds new
    calls rather than the decisions a run can reach -- a cached answer costs nothing and
    is used whether or not the budget would have covered it.
    """
    due = [team_id for team_id, _ in candidates if team_id not in recent]
    return due if probe_limit is None else due[:probe_limit]


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
    provider_team_ids: Dict[str, str],
    workers: int,
    sb,
    stored_states: Dict[str, Optional[str]],
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

    ``sb`` and ``stored_states`` (``{team_id_master: stored state}``) record every call in
    ``team_state_probe_log``, agreements included -- the outcome no other table can hold,
    because a probe that agrees writes nothing. Neither is defaulted: a caller that omitted
    them would pay for its probes and record none.
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
        return (
            (team_id, state, MAPPED_OUTCOME) if state else (team_id, None, f"unmapped code {raw}")
        )

    # The ledger is written here, on the main thread, never inside ``probe``. This loop
    # already consumes the iterator and does every mutation; supabase-py publishes no
    # thread-safety guarantee, and every other pool in this repo resolves in the workers
    # and writes sequentially.
    pending: List[Dict] = []

    def flush() -> None:
        """Write the buffer and clear it, in that order and only once per row.

        ``pending`` is detached before the insert, not after: a write that fails *after*
        PostgREST committed would otherwise leave its rows buffered for the next flush to
        send again, and the ledger has no unique key to absorb the duplicate.
        """
        nonlocal pending
        batch, pending = pending, []
        write_probe_log(sb, batch)

    # Flushed on both exit paths, because this runs for tens of minutes under an operator
    # who may interrupt it and the buffer holds calls already paid for. Not one ``finally``:
    # the failing path's flush is guarded so it cannot replace the exception on its way out,
    # while the normal path's stays fatal.
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for team_id, state, outcome in pool.map(probe, provider_team_ids.items()):
                outcomes[
                    outcome.split(" (")[0] if outcome.startswith("request failed") else outcome
                ] += 1
                if state:
                    states[team_id] = state
                # The raw outcome, not the counter's key: the line above collapses
                # 'request failed (Timeout)' to 'request failed' for the histogram.
                pending.append(
                    probe_log_row(
                        team_id,
                        provider_team_ids[team_id],
                        outcome,
                        state,
                        stored_states.get(team_id),
                    )
                )
                if len(pending) >= FLUSH_EVERY:
                    flush()
    except BaseException:
        # The tail write on the failing path, guarded: a raise in here would replace the
        # exception on its way out, so an interrupt would surface as a Postgrest error and
        # the operator would debug the wrong thing. The rows are lost either way at that
        # point; the diagnosis is not.
        try:
            flush()
        except Exception:
            console.print("[red]Could not flush the final probe observations[/red]")
        raise
    # The normal exit path, unguarded, so the caller's blocked-probe abort still leaves this
    # run's observations on disk and a failure here is still fatal.
    flush()
    return states, outcomes


def probe_is_unusable(outcomes: Counter) -> bool:
    """Whether the probe failed often enough that Tier A's silence means nothing.

    Two arms, because there are two ways a provider stops answering, and they need
    different tests.

    **The failure ratio** catches a provider that refuses the call: a WAF block, a timeout,
    an unparseable body, or a 404 for a team we hold a live alias for. Ungated by batch
    size, deliberately -- one refused call in a one-team run says nothing was learned, and
    a named team that aborts is a team the operator can ask about again.

    **The mapped share** catches the opposite shape: a provider answering every call with a
    well-formed nothing. That needs a batch to mean anything, so it is gated two ways. A
    floor, because a small minority of teams legitimately carry no association and a single
    such answer is a fact about one team, not about the provider. And a share rather than a
    presence test, because one mapped answer in a large batch is still an outage; presence
    alone would let a batch that is almost entirely empty replies pass as healthy and
    durably retire every team in it.
    """
    total = sum(outcomes.values())
    if not total:
        return False
    failures = sum(
        count
        for outcome, count in outcomes.items()
        if outcome.startswith(PROVIDER_FAILURE_OUTCOMES)
    )
    if failures > total * 0.2:
        return True
    return total >= MIN_BATCH_FOR_SHARE and outcomes[MAPPED_OUTCOME] < total * MIN_MAPPED_SHARE


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
    stored = stored_state(team)

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

    # R8b. ``AL`` is the one association code that is also GotSport's value for a team
    # whose association was never set, and the payload cannot tell the two apart. Of the
    # 86 teams this tier had written to AL by 2026-09-02, 65 belong to clubs that really
    # are in Alabama and 19 to clubs in NY, IN, PA, MI, MO, IL, OK, GA, UT, WI and CO --
    # the four Cold Spring Harbor Huntington (LIJSL) teams among them, and IFA's
    # "Hammarby - Sweden" carries the same code. Each payload was confirmed to be that
    # team's own record, so this is the field and not a mis-matched alias. AL still fills
    # a blank and still wins where nothing disputes it; what it may no longer do is settle
    # a disagreement, which is the shape all 19 have and none of the 65 does.
    if proposed == UNSET_DEFAULT_ASSOCIATION:
        disputing = sorted({s for s in (club_state, name_state, place_state) if s and s != proposed})
        if disputing:
            return _decision(
                team,
                proposed,
                tier,
                "queue",
                f"{reason}; AL is also GotSport's unset default, and {'/'.join(disputing)} disputes it",
            )

    # R5. Fills auto-apply from any tier; corrections only from A or B.
    if is_fill or tier in ("A", "B"):
        return _decision(team, proposed, tier, "apply", reason)
    return _decision(team, proposed, tier, "queue", f"{reason}; tier {tier} cannot correct")


def _decision(team: Dict, proposed: str, tier: str, action: str, reason: str) -> Dict:
    return {
        "team_id": team["team_id_master"],
        "team_name": team.get("team_name"),
        "club_name": team.get("club_name"),
        "pre_image": stored_state(team),
        "proposed": proposed,
        "tier": tier,
        "confidence": TIER_CONFIDENCE[tier],
        "action": action,
        "reason": reason,
    }


def build_snapshot(
    sb,
    use_tier_a: bool,
    workers: int,
    only_team: Optional[str] = None,
    audit_contradictions: bool = False,
    probe_limit: Optional[int] = None,
    reprobe_after_days: Optional[int] = None,
) -> Dict:
    """Decide every live team against one reading of the database.

    ``only_team`` narrows the decisions and the GotSport probe to one team, and nothing
    else: Tier B still counts that team's clubmates, so the whole table is still read.

    ``audit_contradictions`` swaps the candidate set for the teams whose state contradicts
    a provider-confirmed club-mate, and writes only decisions a provider record answered.
    A normal sweep asks about teams something already disputes; this asks about teams
    nothing local disputes, which is where a uniformly mislabelled club hides.
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

    # A named team is a named-team run, whichever other flags are set: it selects its own
    # candidate, keeps every tier's answer, and reports as a normal run. Deriving that once
    # is what stops the audit's behaviours -- the deferred abort above all -- reaching a
    # path that has no cache to protect.
    auditing = audit_contradictions and not only_team

    anchor_counts: Dict[str, int] = {}
    cached: Dict[str, str] = {}
    skipped_durable = 0
    budget_applied = False
    if only_team:
        # A named team is asked whatever the tiers think, which is the whole point of asking
        # about one team: a club whose teams are uniformly mislabelled agrees with itself, so
        # nothing local disputes the value and the sweep never looks.
        candidates = [only_team]
        # The budget still binds here. Recency does not: a named team is asked because
        # someone wants it asked now.
        to_probe = probe_list([(only_team, 0)], {}, probe_limit)
        if audit_contradictions:
            # Inert rather than refused, because --team wins over the audit flags. Said
            # out loud, because a flag that changes nothing and says nothing gets trusted --
            # and it names the budget, which is the one audit flag that still bites here.
            console.print(
                "  [yellow]--team run: --audit-contradictions selects nothing here, and "
                "--reprobe-after-days is ignored; --probe-limit still applies[/yellow]"
                if probe_limit is not None
                else "  [yellow]--team run: --audit-contradictions selects nothing here, and "
                "--reprobe-after-days is ignored; this team is asked regardless[/yellow]"
            )
    elif auditing:
        # Two passes elsewhere; here the first is skipped outright, since it walks every
        # team to build a disputed set this mode never consults.
        anchor_index = build_anchor_index(teams)
        console.print(f"  {len(anchor_index):,} clubs with a provider-confirmed state")
        window = reprobe_after_days if reprobe_after_days is not None else REPROBE_AFTER_DAYS
        recent = fetch_recent_probes(sb, datetime.now(timezone.utc) - timedelta(days=window))
        selected = contradiction_candidates(teams, anchor_index)
        anchor_counts = dict(selected)
        candidates = [team_id for team_id, _ in selected]
        # Sliced rather than re-derived, so ``budget_applied`` compares a list with its own
        # prefix. Two independent ``probe_list`` calls would leave that comparison resting
        # on an equivalence nothing in the code states.
        due = probe_list(selected, recent, None)
        to_probe = due if probe_limit is None else due[:probe_limit]
        # Whether the budget actually bit, rather than inferred from the probe list being
        # shorter than the population: a cached or durably-answered team shortens it too,
        # and reading that as "capped" mislabels the uncapped run that finishes the job.
        budget_applied = len(to_probe) < len(due)
        # An answer already bought is used whether or not the budget would have covered
        # it, so a run aborted after paying still produces its decisions on the retry.
        cached = {
            team_id: state
            for team_id, (outcome, state) in recent.items()
            if outcome == MAPPED_OUTCOME and state and team_id in anchor_counts
        }
        skipped_durable = sum(
            1 for team_id in candidates if team_id in recent and team_id not in cached
        )
        console.print(
            f"  {len(candidates):,} contradict a confirmed club-mate, "
            f"{len(to_probe):,} to probe, {len(cached):,} already answered"
        )
        if skipped_durable:
            console.print(f"  [dim]{skipped_durable:,} skipped: answered, but not with a state[/dim]")
    else:
        # Two passes. The first finds the teams any tier disputes, which is the only set
        # worth spending a GotSport call on; the second re-decides them with Tier A in hand.
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
        to_probe = candidates

    association_states: Dict[str, str] = dict(cached)
    aliases: Dict[str, str] = {}
    probed_answers: Dict[str, str] = {}
    blocked = False
    if use_tier_a and to_probe:
        console.print(f"[bold]Probing GotSport[/bold] for {len(to_probe):,} candidates")
        aliases = fetch_gotsport_aliases(sb, to_probe)
        console.print(f"  {len(aliases):,} have a GotSport id")

        stored_states = {t["team_id_master"]: stored_state(t) for t in teams}
        # A candidate the alias lookup did not find never reaches the probe, so it needs
        # its row written here or nothing ever records that it was asked for.
        no_alias = [
            probe_log_row(team_id, None, NO_ALIAS_OUTCOME, None, stored_states.get(team_id))
            for team_id in to_probe
            if team_id not in aliases
        ]
        write_probe_log(sb, no_alias)

        probed_answers, outcomes = probe_associations(aliases, workers, sb, stored_states)
        association_states.update(probed_answers)
        for outcome, count in outcomes.most_common():
            # The provider's own words reach this line -- ``unmapped code <raw>`` carries a
            # value straight from the payload -- and Rich reads square brackets as markup.
            # Unescaped, a bracketed value either renders as styling, quietly falsifying the
            # operator's record of what was said, or raises and kills the run.
            console.print(f"[dim]  {count:>6,}  {escape(outcome)}[/dim]")
        blocked = probe_is_unusable(outcomes)
        if blocked:
            # Keyed on the flag as typed, not on ``auditing``: a ``--team`` run with the
            # audit flag is not auditing, but the parser still refuses ``--no-tier-a``
            # beside ``--audit-contradictions``, so the sweep's advice cannot be followed
            # there either. The reason to keep the file is the decisions, not the calls --
            # those are already in the ledger and a retry reads them back free.
            recovery = (
                "Re-run with --out to keep the decisions; the answers already bought are in "
                "the probe ledger and cost nothing the second time."
                if audit_contradictions
                else "Re-run when GotSport lets us back in, or --no-tier-a to decide "
                "without it deliberately."
            )
            console.print(
                "[red]Tier A is blocked, not quiet: too many calls failed for its silence "
                f"to mean anything. {recovery}[/red]"
            )
            # Audit mode carries answers from earlier runs, and those are already paid
            # for. Exiting here would strand them again on every retry, so it decides
            # first and exits below. Nothing unverified rides along: audit decisions
            # already require a mapped answer.
            if not auditing:
                sys.exit(1)

    audit_scope = set(candidates) if auditing else set()
    decisions = [
        d
        for d in (
            decide(team, club_index, locality_index, association_states, revert_blocks)
            for team in teams
        )
        if d
        and only_team in (None, d["team_id"])
        # A candidate whose probe never answered would otherwise get a Tier B correction
        # auto-applied, on exactly the generic club names that produce false positives.
        and (
            not auditing
            or (d["team_id"] in audit_scope and d["team_id"] in association_states)
        )
    ]
    # Teams no tier can decide never reach the review queue either, because a queue row
    # has to carry a proposal. Most of them are dormant and nobody would notice; the ones
    # ranked Active are on a state board right now with no state, so the run names them
    # rather than leaving them to be silently unfixable.
    #
    # Audit mode probes no stateless team, so the count would measure what it did not ask
    # rather than what cannot be decided, and the lookup behind it costs a round trip per
    # hundred ids.
    if auditing:
        undecided, stranded = [], []
    else:
        decided = {d["team_id"] for d in decisions}
        undecided = [
            t["team_id_master"]
            for t in teams
            if not (t.get("state_code") or "").strip() and t["team_id_master"] not in decided
        ]
        stranded = ranked_and_active(sb, undecided) if undecided else []

    snapshot = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actor": ACTOR,
        "mode": "audit" if auditing else "normal",
        "live_teams": len(teams),
        # In audit mode this counts cache-seeded answers too, so it is not a paid-call
        # count. ``aliases_found`` is.
        "tier_a_probed": len(association_states),
        "tier_d_available": tier_d_ready,
        "undecidable": len(undecided),
        "undecidable_and_visible": stranded,
        "decisions": decisions,
    }
    if auditing:
        snapshot.update(
            {
                "candidates_selected": len(candidates),
                "probed": list(to_probe),
                "aliases_found": len(aliases),
                "probes_answered": len(probed_answers),
                "cached_answers": len(cached),
                "skipped_durable": skipped_durable,
                "budget_applied": budget_applied,
                "anchor_counts": anchor_counts,
                # Over the candidates, not the decisions. A team that answered and agreed
                # produces no decision, and leaving it out would make the denominator
                # equal the numerator and every hit rate exactly 100%.
                "answered": {t: t in association_states for t in candidates},
            }
        )

    # Deferred from the probe so the cache-backed decisions above are built and returned
    # first. The run writes the snapshot, then stops non-zero on this flag.
    if blocked:
        snapshot["probe_blocked"] = True
    return snapshot


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


def probe_log_row(
    team_id: str,
    provider_team_id: Optional[str],
    outcome: str,
    reported: Optional[str],
    stored: Optional[str],
) -> Dict:
    """One probe's record."""
    return {
        "team_id_master": team_id,
        "provider": "gotsport",
        "provider_team_id": provider_team_id,
        "outcome": outcome,
        "reported_state_code": reported,
        "stored_state_code": stored,
        "agreed": (reported == stored) if (reported and stored) else None,
        "probed_by": ACTOR,
    }


def write_probe_log(sb, rows: List[Dict]) -> None:
    """A failure here is fatal, and deliberately so.

    A half-written ledger is worse than none: a missing row reads as never probed and is
    paid for again, a present one as settled.
    """
    for start in range(0, len(rows), INSERT_BATCH):
        sb.table(PROBE_LOG_TABLE).insert(
            rows[start : start + INSERT_BATCH], returning="minimal"
        ).execute()


def apply_decision(sb, decision: Dict, reason: str) -> bool:
    """Write one state through the ledgered path. False means the row moved since."""
    result = sb.rpc(
        "apply_team_state",
        {
            "p_team_id": decision["team_id"],
            "p_expected_state_code": decision["pre_image"],
            "p_state_code": decision["proposed"],
            "p_source": state_source_for(decision["tier"]),
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

    if snapshot.get("mode", "normal") == "audit":
        _summarize_audit(snapshot, decisions)
        console.print("[dim]Undecidable teams are not examined in audit mode.[/dim]")
        return

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


# Named once. Spelled separately in the bucket function and the report loop, a rename that
# missed one would leave both ``Counter`` lookups returning 0 -- printing "0 of 0" rather
# than raising, and reading as an empty run instead of a broken one.
ANCHOR_BUCKETS = ("2 or more", "exactly 1")


def _anchor_bucket(count: int) -> str:
    """Which hit-rate bucket an anchor count falls in."""
    return ANCHOR_BUCKETS[0] if count >= 2 else ANCHOR_BUCKETS[1]


def _summarize_audit(snapshot: Dict, decisions: List[Dict]) -> None:
    """What the contradiction audit selected, what it paid for, and what it caught."""
    selected = snapshot.get("candidates_selected", 0)
    answered = snapshot.get("probes_answered", 0)
    cached = snapshot.get("cached_answers", 0)
    queued = sum(1 for d in decisions if d["action"] == "queue")

    console.print(
        f"[bold]Audit[/bold]: {selected:,} contradict a confirmed club-mate, "
        f"{len(snapshot.get('probed') or []):,} probed, "
        f"{snapshot.get('aliases_found', 0):,} had a GotSport id, "
        f"{answered + cached:,} answered ({cached:,} of them from earlier runs)."
    )
    if snapshot.get("skipped_durable"):
        console.print(
            f"[dim]  {snapshot['skipped_durable']:,} skipped: answered before, but with no state "
            f"to offer.[/dim]"
        )
    console.print(
        f"  {len(decisions):,} corrections, {len(decisions) - queued:,} auto-applied and "
        f"{queued:,} queued for review."
    )

    # Before the buckets, because it qualifies them and must survive a run that selected
    # nothing to bucket.
    if snapshot.get("budget_applied"):
        console.print(
            "[dim]  A capped run draws from the strongest-anchored end, so the buckets are "
            "only comparable on an uncapped one.[/dim]"
        )

    anchor_counts = snapshot.get("anchor_counts") or {}
    answered_by = snapshot.get("answered") or {}
    # "Disagreed", not "was wrong": a decision the tiers queued rather than applied -- a DC
    # relabel under R8, a value the operator already reverted under R17 -- is a provider
    # disagreement the tool deliberately refuses to call an established correction. Counting
    # those as confirmed errors would overstate the tier against itself.
    disagreed = Counter(
        _anchor_bucket(anchor_counts.get(d["team_id"], 0))
        for d in decisions
        if answered_by.get(d["team_id"])
    )
    # The denominator is the teams that answered, not the teams selected: measuring against
    # everything selected would dilute each bucket by its unanswered teams and confound the
    # only comparison this ordering exists to make.
    replied = Counter(
        _anchor_bucket(n) for team_id, n in anchor_counts.items() if answered_by.get(team_id)
    )
    for bucket in ANCHOR_BUCKETS:
        answered_here = replied[bucket]
        rate = (
            f"{100.0 * disagreed[bucket] / answered_here:.1f}%" if answered_here else "no answers"
        )
        console.print(
            f"[dim]  anchored by {bucket}: the provider disagreed on {disagreed[bucket]:,} "
            f"of {answered_here:,} answered ({rate})[/dim]"
        )


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

    current = stored_state(team)
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
        "--dry-run",
        action="store_true",
        default=True,
        help=(
            "Default. Decide and report. No team-state and no review-queue writes, but "
            "paid-probe observations are recorded"
        ),
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
        "--audit-contradictions",
        action="store_true",
        help=(
            "Probe the teams whose state contradicts a provider-confirmed club-mate, instead "
            "of the ones a tier disputes. Writes only decisions the provider answered"
        ),
    )
    parser.add_argument(
        "--probe-limit",
        type=int,
        help="With --audit-contradictions, probe at most this many teams. 0 probes none",
    )
    parser.add_argument(
        "--reprobe-after-days",
        type=int,
        help=(
            f"With --audit-contradictions, re-ask a team answered longer ago than this "
            f"(default {REPROBE_AFTER_DAYS})"
        ),
    )
    parser.add_argument(
        "--fills-only",
        action="store_true",
        help="With --execute, apply only decisions that fill a blank; withhold every correction",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help=f"Probe threads (default {DEFAULT_WORKERS})"
    )
    args = parser.parse_args()

    # Before the credential guard: CI sets no keys, so anything after it exits 1 for every
    # argv and a test asserting the exit code alone could never fail.
    if args.audit_contradictions and args.no_tier_a:
        console.print(
            "[red]ERROR: --audit-contradictions is a Tier A run; --no-tier-a would leave it "
            "nothing to ask[/red]"
        )
        sys.exit(1)
    if args.probe_limit is not None and not args.audit_contradictions:
        console.print(
            "[red]ERROR: --probe-limit only bounds --audit-contradictions; a sweep probes every "
            "candidate by design[/red]"
        )
        sys.exit(1)
    if args.reprobe_after_days is not None and not args.audit_contradictions:
        console.print(
            "[red]ERROR: --reprobe-after-days only applies to --audit-contradictions[/red]"
        )
        sys.exit(1)
    if args.probe_limit is not None and args.probe_limit < 0:
        console.print("[red]ERROR: --probe-limit cannot be negative; it would probe all but the last[/red]")
        sys.exit(1)
    if args.reprobe_after_days is not None and args.reprobe_after_days < 1:
        console.print(
            "[red]ERROR: --reprobe-after-days must be at least 1. Zero or less puts the cutoff at "
            "or after now, so no answer counts as recent and the whole population is bought "
            "again[/red]"
        )
        sys.exit(1)

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
        sb,
        use_tier_a=not args.no_tier_a,
        workers=args.workers,
        only_team=args.team,
        audit_contradictions=args.audit_contradictions,
        probe_limit=args.probe_limit,
        reprobe_after_days=args.reprobe_after_days,
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

    # Written first, so a blocked audit keeps the decisions its earlier runs paid for.
    if snapshot.get("probe_blocked"):
        sys.exit(1)


if __name__ == "__main__":
    main()
