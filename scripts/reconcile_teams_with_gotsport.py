#!/usr/bin/env python3
"""
Reconcile stored team identity against GotSport, one cohort/state slice at a time.

``teams`` holds a name, club, state and cohort that were right when the row was
written and have drifted since -- a club renames a squad, a team re-registers in
another state, an early import guessed. GotSport's ``team_details`` still holds the
current registration, so this asks it again for a bounded slice.

What it writes is deliberately narrower than what it reports:

* ``team_name`` is overwritten whenever GotSport differs -- unless GotSport's cohort
  disagrees with ours, or its name is a retired-registration marker (``zz old - ...``).
  A record filed under another cohort is not describing this squad as it plays today,
  and clubs park dead squads under those markers, so neither is a name to take.
* ``club_name`` and ``state_code`` are filled only where ours is absent. Where both
  sides hold a value and they disagree the row is reported, not written:
  ``fill-team-states-weekly`` fills only, and the ``assigning-team-states`` skill
  owns corrections from ranked evidence, which is more than one provider field.
* ``age_group`` and ``gender`` are never written. ``display_age_group`` has returned
  U14 and U12 for two teams of the same birth year, and nothing may write
  ``teams.age_group`` from any source until that is settled (IMP-145). They are
  compared and logged so the disagreement is visible, and they are deliberately kept
  out of the ``conflicts_only`` count -- ``display_age_group`` is the registered
  event cohort, so a month after an Aug 1 rollover they would bury the club and
  state disagreements that count is for.

Every write carries its pre-image as a predicate, so a row that moved between the
read and the write is skipped and reported rather than overwritten. That matters
here: a default run spends around 25 minutes between the two, and
``backfill-unknown-team-names`` writes the same columns every 15 minutes with a bare
team-id filter. ``state_code`` goes through ``apply_team_state``, which applies that
predicate itself and stamps the provenance ledger, and is then mirrored into
``rankings_full`` because the state boards read their own copy and only Monday's
ranking run refreshes it. A state an operator has already reverted away from is
never re-filled, the way ``assign_team_states`` honours the same ledger.

``--state`` selects on the state already stored, so it cannot reach a team that has
none; use ``--age-group`` alone to include those.

Every write is logged to a CSV that --revert replays backwards, restoring the prior
state provenance and refusing any row that has changed since.

Usage:
    python scripts/reconcile_teams_with_gotsport.py --age-group u14 --state WA
    python scripts/reconcile_teams_with_gotsport.py --age-group u14 --state WA --execute
    python scripts/reconcile_teams_with_gotsport.py --age-group u14 --offset 500
    python scripts/reconcile_teams_with_gotsport.py --revert data/exports/<log>.csv --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from supabase import create_client

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tournaments.triage import _is_placeholder_team  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.gotsport_alias import fetch_gotsport_aliases  # noqa: E402
from src.utils.gotsport_team_details import TeamDetailsResolver  # noqa: E402
from src.utils.placeholder_clubs import is_placeholder_club  # noqa: E402

# Columns filled only where ours is absent; a disagreement is reported instead.
FILL_ONLY_FIELDS = ("club_name", "state_code")

# Everything this script may write. team_name is the one it overwrites.
WRITABLE_FIELDS = ("team_name", *FILL_ONLY_FIELDS)

# Written through apply_team_state rather than a table update, so that the ledger
# and the state boards see it. Derived rather than listed: a fourth writable column
# added to a hand-written TABLE_FIELDS would be planned, logged and never written.
LEDGER_FIELD = "state_code"
TABLE_FIELDS = tuple(name for name in WRITABLE_FIELDS if name != LEDGER_FIELD)

# Carried in the log so --revert can put back the provenance the fill overwrote.
PROVENANCE_FIELDS = ("state_source", "state_confidence")

# Compared and logged, never written. See the module docstring.
REPORTED_FIELDS = ("age_group", "gender")

# Fields whose presence means team_details answered about a real team. An HTTP 200
# carrying a non-team body -- the shape a WAF interstitial takes -- parses into a
# truthy dict with every one of these empty, which must count as a failed lookup
# rather than as a team that happens to match us.
IDENTITY_FIELDS = ("name", "club_name", "state_code", "age_group", "gender")

ACTOR = "reconcile_teams_with_gotsport"

# team_association IS assign_team_states' Tier A, so a fill from it is stamped with
# that tier's vocabulary and confidence rather than a fourth spelling of one signal.
STATE_SOURCE = "tier_a"
STATE_CONFIDENCE = 0.95

# GotSport clubs park a dead registration under a marker so it sorts to the bottom;
# a live WA slice offered "zz old - B13 Black" for a team we call "2013 Black".
# Substrings rather than prefixes because the marker also appears mid-name.
RETIRED_NAME_MARKERS = ("zz", "do not use", "donotuse", "duplicate", "old -", "- old", "delete", "inactive")

# Spreadsheet apps read a cell as a formula when it starts with one of these, and
# every provider value in the log is untrusted text. src/tournaments/reports/
# render_csv.py defangs the same set one-way; this pair round-trips, because the
# same file is the input to --revert.
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n"})

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# teams.team_name and club_name are unbounded text; a revert payload is not.
MAX_NAME_LENGTH = 200

EXPORTS_DIR = Path("data/exports")
PAGE_SIZE = 1000
IN_BATCH = 100


@dataclass
class Decision:
    """One team's reconciliation, carried in memory from decision to write.

    ``updates`` is the payload itself rather than a list of column names. The CSV is
    derived from this, never the other way round: re-reading the payload back out of
    the log would put the log's schema, and anything that could be edited into it,
    on the path to a service-role write.

    ``applied`` is set once the writes run and records what actually landed. The two
    halves commit separately -- a table PATCH and an RPC, no shared transaction -- so
    a row where one succeeded must still reach the log as revertible.
    """

    team: Dict
    provider_team_id: Optional[str]
    action: str
    updates: Dict[str, str] = field(default_factory=dict)
    conflicts: Tuple[str, ...] = ()
    blocked: Tuple[str, ...] = ()
    provider: Dict[str, str] = field(default_factory=dict)
    applied: Optional[Tuple[str, ...]] = None

    def written(self) -> Tuple[str, ...]:
        """What the log should record as written: what landed, or what was planned."""
        return self.applied if self.applied is not None else tuple(sorted(self.updates))


def csv_safe(value: str) -> str:
    """Prefix a formula-leading value with ``'`` so a spreadsheet renders it as text.

    A value already opening with ``'`` is escaped too, without which the encoding is
    not injective -- ``=x`` and ``'=x`` would both encode to ``'=x`` and the undo
    would restore the wrong one of them.
    """
    return "'" + value if value and (value[0] in _FORMULA_PREFIXES or value[0] == "'") else value


def csv_unsafe(value: Optional[str]) -> str:
    """Undo :func:`csv_safe`."""
    text = value or ""
    if len(text) >= 2 and text[0] == "'" and (text[1] in _FORMULA_PREFIXES or text[1] == "'"):
        return text[1:]
    return text


def printable(value: object) -> str:
    """Strip control characters from a value before it reaches the operator's terminal.

    The dry run is the only human gate before a service-role batch, and both sides of
    a preview line are untrusted: ours was written by a scraper, GotSport's is about
    to be. A bare ``\\r`` anywhere on the line repaints all of it.
    """
    return "".join(c for c in str(value if value is not None else "") if c.isprintable())


def is_retired_registration(name: str) -> bool:
    """Whether GotSport's name marks a parked registration rather than naming a team."""
    lowered = name.strip().lower()
    return any(marker in lowered for marker in RETIRED_NAME_MARKERS)


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase(require_service_role: bool = False):
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    service_role = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    supabase_key = service_role or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing Supabase credentials. "
            "Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_KEY."
        )
    if require_service_role and not service_role:
        # anon holds the UPDATE grant but no UPDATE policy, so RLS filters the write
        # to zero rows and PostgREST answers 200 with an empty body -- a run that
        # reports every change applied and writes none.
        raise ValueError("--execute needs SUPABASE_SERVICE_ROLE_KEY; the anon key writes nothing under RLS.")
    return create_client(supabase_url, supabase_key)


def fetch_target_teams(
    supabase,
    age_groups: List[str],
    states: List[str],
    limit: Optional[int],
    offset: int = 0,
) -> Tuple[List[Dict], int]:
    """Return ``(teams, matched)`` -- the slice to examine and the full match count.

    The whole matching set is paged before sorting, so ``--limit`` names a stable
    window of the cohort rather than an arbitrary one: breaking out of pagination
    early would fix every run to the lowest UUIDs, and no re-run could advance.
    """
    page = 0
    rows: List[Dict] = []
    while True:
        query = (
            supabase.table("teams")
            .select("team_id_master,team_name,club_name,state_code,age_group,gender,state_source,state_confidence")
            .eq("is_deprecated", False)
        )
        if age_groups:
            query = query.in_("age_group", age_groups)
        if states:
            query = query.in_("state_code", states)
        batch = query.order("team_id_master").range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    rows.sort(key=lambda r: (r.get("age_group") or "", r.get("team_name") or "", r.get("team_id_master") or ""))
    window = rows[offset:]
    return (window[:limit] if limit else window), len(rows)


def fetch_state_blocks(supabase, team_ids: List[str]) -> Set[Tuple[str, str]]:
    """``(team, state)`` pairs an operator has already reverted away from.

    Mirrors ``assign_team_states.fetch_revert_blocks``: a revert row records the value
    being undone in ``old_state_code``, and re-applying it is the decision the operator
    made against. Scoped to the slice rather than the whole ledger because this runs
    per cohort.
    """
    blocks: Set[Tuple[str, str]] = set()
    for start in range(0, len(team_ids), IN_BATCH):
        rows = (
            supabase.table("team_state_audit")
            .select("team_id_master,old_state_code")
            .eq("action", "revert")
            .in_("team_id_master", team_ids[start : start + IN_BATCH])
            .execute()
            .data
            or []
        )
        for row in rows:
            if row.get("old_state_code"):
                blocks.add((row["team_id_master"], row["old_state_code"].strip()))
    return blocks


def stored_value(team: Dict, name: str) -> str:
    """Return the stored value, with a placeholder club read as absent."""
    value = str(team.get(name) or "").strip()
    if name == "club_name" and is_placeholder_club(value):
        return ""
    return value


def provider_values(resolved: Dict, provider_team_id: str) -> Dict[str, str]:
    name = str(resolved.get("name") or "").strip()
    if len(name) < 2 or _is_placeholder_team(name, provider_team_id) or is_retired_registration(name):
        name = ""
    club = str(resolved.get("club_name") or "").strip()
    if is_placeholder_club(club):
        club = ""
    return {
        "team_name": name,
        "club_name": club,
        "state_code": str(resolved.get("state_code") or "").strip(),
        "age_group": str(resolved.get("age_group") or "").strip(),
        "gender": str(resolved.get("gender") or "").strip(),
    }


def classify_lookup(resolver, provider_team_id: str, resolved: Optional[Dict]) -> str:
    """Return ``resolved``, ``gone`` or ``failed`` for one team_details answer.

    The shared reader collapses a 404 and every exception into ``{}``, which is why
    the run's only WAF defence cannot be a count of empty answers. Two things
    separate them: the reader caches a 404 as the permanent answer it is and
    deliberately does not cache a transient failure, and a body that names no team
    parses truthy with every identity field empty.
    """
    if resolved and any(resolved.get(f) for f in IDENTITY_FIELDS):
        return "resolved"
    if resolved:
        return "failed"
    return "gone" if provider_team_id in resolver.cache else "failed"


def decide(
    team: Dict,
    provider_team_id: Optional[str],
    resolved: Optional[Dict],
    outcome: str,
    state_blocks: Set[Tuple[str, str]] = frozenset(),
) -> Decision:
    """Return the write, the disagreements and the refusals for one team."""
    if not provider_team_id:
        return Decision(team, provider_team_id, "skipped_no_alias")
    if outcome != "resolved":
        return Decision(team, provider_team_id, f"skipped_{'gone' if outcome == 'gone' else 'lookup_failed'}")

    provider = provider_values(resolved, provider_team_id)
    stored = {name: stored_value(team, name) for name in WRITABLE_FIELDS}
    # team_name compares against the RAW value, not the stripped one, so the decision
    # and the pre-image predicate agree: a padded stored name really does differ.
    raw_name = "" if team.get("team_name") is None else str(team["team_name"])

    updates: Dict[str, str] = {}
    blocked: List[str] = []
    # A registration whose cohort disagrees with ours is not describing this squad as
    # it plays today, so its name is not ours to take. Measured on a live AZ u13
    # slice: all seven rows GotSport called U12 play u13 opposition -- 243 games
    # across the seven, 18 to 55 each -- and one of the seven carries the contested
    # birth year in the name itself ("U12B (2015) Blue #2"). The thirteen rows whose
    # cohorts agreed all offered a sane name.
    #
    # This reads age only to withhold a write, never to make one, so it stays inside
    # the IMP-145 moratorium: a wrong veto costs a skipped rename, not a bad row.
    stored_age = str(team.get("age_group") or "").strip()
    cohorts_disagree = bool(provider["age_group"] and stored_age and provider["age_group"] != stored_age)
    if provider["team_name"] and provider["team_name"] != raw_name:
        if cohorts_disagree:
            blocked.append("team_name")
        else:
            updates["team_name"] = provider["team_name"]
    for name in FILL_ONLY_FIELDS:
        if not provider[name] or stored[name]:
            continue
        if name == LEDGER_FIELD and (team["team_id_master"], provider[name]) in state_blocks:
            blocked.append(name)
            continue
        updates[name] = provider[name]

    # Computed for every row, not only rows with nothing to write: a team can take a
    # club fill and still disagree about its state, and that disagreement is the
    # handoff to assigning-team-states.
    conflicts = tuple(
        name for name in FILL_ONLY_FIELDS if provider[name] and stored[name] and provider[name] != stored[name]
    )

    if updates:
        action = "updated"
    elif conflicts or blocked:
        action = "conflicts_only"
    else:
        action = "skipped_already_matching"
    return Decision(team, provider_team_id, action, updates, conflicts, tuple(blocked), provider)


def log_row(decision: Decision, run_mode: str) -> Dict:
    row = {
        "team_id_master": decision.team["team_id_master"],
        "provider_team_id": decision.provider_team_id or "",
        "run_mode": run_mode,
        "action": decision.action,
        "written_fields": "|".join(decision.written()),
        "conflict_fields": "|".join(decision.conflicts),
        "blocked_fields": "|".join(decision.blocked),
    }
    for name in (*WRITABLE_FIELDS, *REPORTED_FIELDS, *PROVENANCE_FIELDS):
        row[f"stored_{name}"] = csv_safe(str(decision.team.get(name) if decision.team.get(name) is not None else ""))
        row[f"gotsport_{name}"] = csv_safe(decision.provider.get(name, ""))
    return row


def write_log(rows: List[Dict], path: Path) -> None:
    """Write the log, replacing any previous copy as nearly atomically as we can.

    The log is the only way back from a service-role batch and it is rewritten once
    the writes finish, so truncating it in place would leave a failure during that
    second write with no recovery record at all.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def apply_state(
    supabase,
    team_id: str,
    expected: Optional[str],
    value: Optional[str],
    action: str,
    source: Optional[str],
    confidence: Optional[float],
) -> bool:
    """Write one state through the ledgered path. False means the row moved since.

    ``source`` and ``confidence`` are parameters rather than constants because the RPC
    rewrites all four provenance columns unconditionally: a revert that sent this
    script's own source would leave a team with no state still claiming GotSport put
    one there. ``revert_team_states`` restores the prior pair for the same reason.
    """
    result = supabase.rpc(
        "apply_team_state",
        {
            "p_team_id": team_id,
            "p_expected_state_code": expected,
            "p_state_code": value,
            "p_source": source,
            "p_confidence": confidence,
            "p_actor": ACTOR,
            "p_action": action,
            "p_reason": "reconciled against GotSport team_details",
        },
    ).execute()
    return bool(result.data)


def mirror_state(supabase, team_id: str, value: Optional[str]) -> None:
    """Carry a state onto the board, which reads its own copy.

    An UPDATE, never an upsert: Monday's ranking run re-derives the column from
    ``teams``, and an inserted row would be a ranking no run produced. Without this a
    fill -- or its undo -- is invisible on the state boards for up to a week.
    """
    supabase.table("rankings_full").update({"state_code": value}).eq("team_id", team_id).execute()


def apply_table_fields(supabase, team_id: str, payload: Dict[str, str], pre_image: Dict) -> bool:
    """Write the non-state columns, refusing the row if it moved since it was read.

    The predicate uses the raw stored value rather than ``stored_value``: a row
    actually holding a placeholder club reads as absent there, and filtering on
    ``IS NULL`` would match nothing and report a live row as changed.
    """
    query = supabase.table("teams").update(payload).eq("team_id_master", team_id)
    for name in payload:
        raw = pre_image.get(name)
        query = query.is_(name, "null") if raw is None else query.eq(name, raw)
    return bool(query.execute().data)


def apply_fields(
    supabase,
    team_id: str,
    values: Dict[str, str],
    pre_image: Dict,
    state_action: str,
    state_source: Optional[str],
    state_confidence: Optional[float],
) -> Tuple[str, ...]:
    """Apply one row's values, returning the field names that actually landed.

    Shared by the forward path and the undo so the compare-and-set and the ledger
    routing are specified once: tightening one and not the other would silently drop
    the property the write path exists to hold.

    The two halves commit separately, so the return is the set that succeeded rather
    than a single boolean -- a table write that lands while the RPC refuses must still
    be recorded as revertible.
    """
    applied: List[str] = []
    payload = {name: value for name, value in values.items() if name in TABLE_FIELDS}
    if payload and apply_table_fields(supabase, team_id, payload, pre_image):
        applied.extend(payload)
    if LEDGER_FIELD in values:
        if apply_state(
            supabase,
            team_id,
            pre_image.get(LEDGER_FIELD),
            values[LEDGER_FIELD],
            state_action,
            state_source,
            state_confidence,
        ):
            applied.append(LEDGER_FIELD)
            mirror_state(supabase, team_id, values[LEDGER_FIELD])
    return tuple(sorted(applied))


def apply_decision(supabase, decision: Decision) -> str:
    """Apply one decision, recording what landed. Returns the action to log."""
    decision.applied = apply_fields(
        supabase,
        decision.team["team_id_master"],
        decision.updates,
        decision.team,
        "fill",
        STATE_SOURCE,
        STATE_CONFIDENCE,
    )
    return "updated" if decision.applied else "skipped_changed_since_read"


def _revert_payload(row: Dict, names: List[str]) -> Dict[str, Optional[str]]:
    payload: Dict[str, Optional[str]] = {}
    for name in names:
        value = csv_unsafe(row[f"stored_{name}"])
        # team_name is NOT NULL, so it restores to "" rather than NULL. The fill-only
        # columns are nullable and were NULL before the fill; restoring "" there would
        # leave them non-null and invisible to every gap query.
        payload[name] = value if name == "team_name" else (value or None)
    return payload


def _revert_row_is_sound(row: Dict, names: List[str]) -> bool:
    """Whether a log row is shaped like something this script produced.

    The undo is the one path that takes a file from the command line and turns it into
    a service-role write, and the operator is trained to run it on a file they did not
    audit. The column allowlist is not enough on its own: the row it targets and the
    values it writes come from the same file.
    """
    if not _UUID.match(row.get("team_id_master") or ""):
        return False
    if any(name not in WRITABLE_FIELDS for name in names):
        return False
    if len(csv_unsafe(row.get("stored_state_code"))) > 2:
        return False
    return all(len(csv_unsafe(row.get(f"stored_{name}"))) <= MAX_NAME_LENGTH for name in TABLE_FIELDS)


def revert(supabase, log_path: Path, execute: bool) -> Dict[str, int]:
    """Replay a log backwards, refusing any row that no longer holds what we wrote."""
    with log_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    counts = {"reverted": 0, "partial": 0, "refused_changed": 0, "refused_shape": 0}
    if any(r.get("run_mode") == "dry-run" for r in rows):
        # A preview run records its planned rows so the operator can read them, but
        # nothing was written, so restoring them would overwrite live values with a
        # snapshot that never left the database.
        raise ValueError(f"{log_path} is a dry-run log; there is nothing to revert.")

    for row in [r for r in rows if r.get("action") == "updated" and r.get("written_fields")]:
        names = [n for n in row["written_fields"].split("|") if n]
        if not _revert_row_is_sound(row, names):
            counts["refused_shape"] += 1
            continue

        print(f"  {printable(csv_unsafe(row['stored_team_name']))[:44]:44s} {', '.join(names)}")
        if not execute:
            counts["reverted"] += 1
            continue

        confidence = csv_unsafe(row.get("stored_state_confidence"))
        applied = apply_fields(
            supabase,
            row["team_id_master"],
            _revert_payload(row, names),
            {name: csv_unsafe(row[f"gotsport_{name}"]) or None for name in names},
            "revert",
            csv_unsafe(row.get("stored_state_source")) or None,
            float(confidence) if confidence else None,
        )
        if len(applied) == len(names):
            counts["reverted"] += 1
        elif applied:
            counts["partial"] += 1
        else:
            counts["refused_changed"] += 1
    return counts


def drop_colliding_renames(decisions: List[Decision]) -> int:
    """Withhold any rename that would leave two teams in the slice sharing one name.

    GotSport names a squad within its own club, so a name can be perfectly
    identifying there and ambiguous here, where a cohort spans every club in the
    state. A live AZ u13 run renamed four teams from four different clubs to
    ``U13G DPL``, each from a name that had said which club it was.

    Judged per run rather than by any rule about what makes a name good: the batch
    that produced those four also cut names shared by two or more teams from 18 to 2,
    so the provider's names are usually the more distinctive ones. Only the collision
    itself is evidence, and it is visible without leaving the slice.

    Two teams that already shared a name keep it -- that is not this run's doing, and
    renaming one of them away is a decision nothing here has evidence for.
    """
    holders: Dict[str, int] = {}
    for decision in decisions:
        name = (decision.updates.get("team_name") or decision.team.get("team_name") or "").strip().lower()
        if name:
            holders[name] = holders.get(name, 0) + 1

    dropped = 0
    for decision in decisions:
        new_name = (decision.updates.get("team_name") or "").strip().lower()
        if not new_name or holders.get(new_name, 0) < 2:
            continue
        del decision.updates["team_name"]
        decision.blocked = (*decision.blocked, "team_name")
        if not decision.updates:
            decision.action = "conflicts_only"
        dropped += 1
    return dropped


def plan_writes(decisions: List[Decision]) -> Tuple[List[Decision], int]:
    """Return the rows still due a write, and how many renames collided.

    The collision pass runs here rather than in ``main`` so the planned list cannot be
    obtained without it: a caller that skipped the guard would have to rebuild this
    filter itself, which is a visible change rather than a silent omission.
    """
    collisions = drop_colliding_renames(decisions)
    return [d for d in decisions if d.action == "updated"], collisions


def next_failure_streak(streak: int, outcome: str) -> int:
    """Advance the consecutive-failure counter for one lookup outcome.

    A 404 is the origin answering, so it is evidence the endpoint is up and clears the
    streak; only a run of lookups nothing answered is grounds to stop. Leaving it
    merely unchanged let ``(failed, gone)`` repeated nine times plus one more failure
    abort a perfectly responsive run. A team with no alias made no call at all, so it
    neither counts nor clears.
    """
    if outcome == "failed":
        return streak + 1
    return 0 if outcome in ("resolved", "gone") else streak


def validate_bounds(limit: int, offset: int) -> None:
    """Refuse a negative window. ``rows[:-1]`` silently drops the last team of the
    cohort while reporting a deliberate cap."""
    if limit < 0 or offset < 0:
        raise ValueError("--limit and --offset must not be negative")


def resolve_execute(execute_flag: bool, dry_run_flag: bool) -> bool:
    """Fail safe: asking for both means the caller wants the preview.

    One boolean gates the credential requirement, whether any write runs, and the
    ``run_mode`` stamped into the log -- which is what makes a preview log unrevertable.
    """
    return execute_flag and not dry_run_flag


def run_writes(supabase, planned: List[Decision], execute: bool) -> None:
    """Preview every planned change, and apply them only when executing."""
    for decision in planned:
        changes = ", ".join(
            f"{name}: {printable(stored_value(decision.team, name)) or '(none)'} -> {printable(value)}"
            for name, value in sorted(decision.updates.items())
        )
        print(f"  {printable(decision.team.get('team_name'))[:44]:44s} {changes}")
        if execute:
            decision.action = apply_decision(supabase, decision)


def parse_filters(age_group: str, state: str) -> Tuple[List[str], List[str]]:
    requested = [v.strip() for v in age_group.split(",") if v.strip()]
    age_groups = [normalize_age_group(v) for v in requested]
    unknown = [raw for raw, norm in zip(requested, age_groups) if norm is None]
    if unknown:
        raise ValueError(f"Unrecognized age group(s): {', '.join(unknown)}")
    return age_groups, [v.strip().upper() for v in state.split(",") if v.strip()]


def describe_runtime(calls: int, delay: float) -> str:
    seconds = calls * delay
    return f"{seconds:.0f} sec" if seconds < 60 else f"{seconds / 60:.0f} min"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--age-group", default="", help="Comma-separated cohorts, e.g. u14,u15")
    parser.add_argument(
        "--state",
        default="",
        help="Comma-separated state codes, e.g. WA,OR. Selects on the state already stored, "
        "so teams with none are excluded.",
    )
    parser.add_argument("--limit", type=int, default=500, help="Max teams to examine (0 for no cap)")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many teams of the cohort first")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between GotSport calls")
    parser.add_argument(
        "--abort-after",
        type=int,
        default=10,
        help="Stop after this many consecutive failed lookups (a 404 is an answer and clears the streak)",
    )
    parser.add_argument("--revert", type=Path, help="Undo a previous run from its CSV log")
    args = parser.parse_args()
    execute = resolve_execute(args.execute, args.dry_run)

    try:
        validate_bounds(args.limit, args.offset)
    except ValueError as e:
        parser.error(str(e))

    # Before the credential check, so a typo'd cohort is not reported as a missing key.
    try:
        age_groups, states = parse_filters(args.age_group, args.state)
    except ValueError as e:
        parser.error(str(e))

    load_env()
    supabase = get_supabase(require_service_role=execute)

    if args.revert:
        print(f"=== Revert {args.revert} ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
        try:
            counts = revert(supabase, args.revert, execute)
        except ValueError as e:
            parser.error(str(e))
        print(f"\n{'Reverted' if execute else 'Would revert'}: {counts['reverted']}")
        for name in ("partial", "refused_changed", "refused_shape"):
            if counts[name]:
                print(f"{name}: {counts[name]}")
        return

    scope = ", ".join(filter(None, [",".join(age_groups), ",".join(states)])) or "all GotSport teams"
    run_mode = "execute" if execute else "dry-run"

    print(f"=== Reconcile teams with GotSport ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
    print(f"Scope: {scope}")

    teams, matched = fetch_target_teams(supabase, age_groups, states, args.limit or None, args.offset)
    window = f" of {matched:,}" + (f" from offset {args.offset:,}" if args.offset else " (--limit cap)")
    print(f"Teams in scope: {len(teams):,}{window if matched > len(teams) else ''}")
    if not teams:
        return

    team_ids = [t["team_id_master"] for t in teams]
    aliases = fetch_gotsport_aliases(supabase, team_ids)
    state_blocks = fetch_state_blocks(supabase, team_ids)
    print(f"With a resolvable GotSport alias: {len(aliases):,}")
    print(f"Estimated runtime at {args.delay}s/call: {describe_runtime(len(aliases), args.delay)}\n")

    resolver = TeamDetailsResolver()
    decisions: List[Decision] = []
    consecutive_failures = 0
    aborted = False

    for team in teams:
        pid = aliases.get(team["team_id_master"])
        outcome = "no_alias"
        resolved = None
        if pid:
            time.sleep(args.delay)
            resolved = resolver.resolve(pid)
            outcome = classify_lookup(resolver, pid, resolved)

        decisions.append(decide(team, pid, resolved, outcome, state_blocks))

        consecutive_failures = next_failure_streak(consecutive_failures, outcome)
        if consecutive_failures >= args.abort_after:
            aborted = True
            break

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EXPORTS_DIR / f"reconcile_teams_with_gotsport_{stamp}.csv"
    planned, collisions = plan_writes(decisions)
    # The log lands before the first write and again after the last, so a run that
    # dies mid-loop still leaves every applied row on disk.
    write_log([log_row(d, run_mode) for d in decisions], log_path)

    try:
        run_writes(supabase, planned, execute)
    finally:
        try:
            write_log([log_row(d, run_mode) for d in decisions], log_path)
        except OSError as e:
            # Never let the rewrite mask an in-flight exception or destroy the copy
            # already on disk -- on Windows this fails outright while the CSV is open
            # in Excel, which is exactly when an operator is reading it.
            print(f"\nCould not rewrite {log_path}: {e}")
            print(f"The pre-write copy stands; the updated rows are in {log_path}.tmp if it survived.")

    if aborted:
        print(f"\n{consecutive_failures} consecutive failed lookups — stopping. These are not 404s;")
        print("wait out the WAF cooldown before re-running, and raise --delay if it repeats.")

    counts: Dict[str, int] = {}
    for decision in decisions:
        counts[decision.action] = counts.get(decision.action, 0) + 1
    conflicted = sum(1 for d in decisions if d.conflicts)
    withheld_names = sum(1 for d in decisions if "team_name" in d.blocked)
    blocked_states = sum(1 for d in decisions if LEDGER_FIELD in d.blocked)

    print("\n=== Summary ===")
    for action in sorted(counts):
        print(f"{action}: {counts[action]}")
    print(f"\nLog: {log_path}")
    if conflicted:
        print(f"{conflicted} teams disagree with GotSport on a club or state this script will not overwrite.")
    if withheld_names - collisions > 0:
        print(f"{withheld_names - collisions} renames withheld: GotSport files those teams under a different cohort.")
    if collisions:
        print(f"{collisions} renames withheld: the name would have been shared with another team in this slice.")
    if blocked_states:
        print(f"{blocked_states} state fills skipped: an operator already reverted that state away.")
    if not execute and counts.get("updated"):
        print(f"Re-run with --execute to apply. Undo with --revert {log_path} --execute")


if __name__ == "__main__":
    main()
