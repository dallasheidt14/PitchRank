#!/usr/bin/env python3
"""
Correct teams whose stored age group is older than both GotSport and the team's own
two-year band say it is.

Scope is derived, never hand-listed: every team in the reconcile_teams_with_gotsport
logs where

  * GotSport's cohort is YOUNGER than the stored one, and
  * the team's name (GotSport's current name, ours, or both) carries exactly one
    two-year band ("2015/16", "B2014-2015"), and that band resolves to GotSport's cohort.

The band is the value; GotSport is corroboration. A band names both birth years of a
cohort, so it resolves without knowing which season wrote it -- the project's own rule,
scripts/normalize_team_names._resolve_band. Measured 2026-09-15 across 50 states: where
a band decides a GotSport-younger disagreement it backs GotSport 9,149 times and the
stored label 65. The reverse direction (GotSport older) is not planned here: the
reconcile-gotsport skill's triage decides those per team under the owner's rules
(CLAUDE.md), and --apply applies the plans it writes.

Three modes, so what gets reviewed is exactly what gets written:

  (default)                     Dry run. Re-verify every candidate against the live
                                table, check the target cohort for a same-named team,
                                write a plan CSV. No database writes.
  --apply PLAN [--limit N] [--include-collisions] --execute
                                Apply the plan. Each write carries the planned old value
                                as a predicate, so a team that moved since the plan is
                                skipped and reported, never overwritten.
  --revert LOG --execute        Undo an apply log, again only where the row still holds
                                the value this tool wrote.

Tracked under scripts/ so CI imports it; its plan and apply logs stay in data/exports/
(gitignored), because the revert path has to outlive the session that ran it. --exports-dir
moves all of it: the reconcile logs the dry run reads, the plan, and the apply log.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from config.settings import AGE_GROUPS  # noqa: E402
from scripts.normalize_team_names import _resolve_band  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.team_name_utils import _FORMAT_TOKEN, _UAGE_TOKEN, birth_years  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402
from supabase import create_client  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
# Teams the owner decided to leave at their stored age. Whenever the owner declines a team or a held
# group, add it here, with the date and the owner's answer in its section's `decided`.
OWNER_DECISIONS = ROOT / ".claude" / "skills" / "correcting-team-age-groups" / "scripts" / "owner_decisions.json"
DEFAULT_ACTOR = "pitchrank-operator"
IN_BATCH = 100
PAGE = 1000
SEASON_START = f"{_soccer_season_year()}-08-01"
_COHORT = re.compile(r"^u([0-9]{1,2})$")
_TEAM_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# An apply row whose outcome the run never confirmed. It is not "not written": the
# write may have landed and the reply been lost, so the undo has to consider it.
IN_FLIGHT = "in_flight"
UNCONFIRMED = "unconfirmed"
REVERTABLE = frozenset({"updated", UNCONFIRMED, IN_FLIGHT, "planned_not_applied"})

PLAN_FIELDS = [
    "state_code",
    "team_id_master",
    "team_name",
    "club_name",
    "gender",
    "gotsport_team_name",
    "band",
    "old_age_group",
    "new_age_group",
    "action",
    "collision_with",
    "evidence_tier",
    "fixture_verdict",
    "opp_games_proposed",
    "opp_games_current",
]
APPLY_LOG_FIELDS = PLAN_FIELDS + ["result", "hold_reason", "actor"]


def load_env() -> None:
    env_local = ROOT / ".env.local"
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv(ROOT / ".env")


def get_supabase():
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def age_num(cohort: str) -> int:
    match = _COHORT.match(cohort or "")
    if not match:
        raise ValueError(f"not a cohort: {cohort!r}")
    return int(match.group(1))


def cohort_years(age: int, season: Optional[int] = None) -> set:
    """Birth years a cohort holds this season; u19 also holds the U18 band filed into it."""
    younger = (season or _soccer_season_year()) - age + 1
    years = {younger, younger - 1}
    return years | {younger + 1} if age == 19 else years


# Years joined by "/" or "-", each written with two or four digits, read wherever they sit. birth_years
# refuses a band beside a word or an M/F letter ("Knights13/14B", "11/12M") and can stop partway along
# a run ("2012/13/14" reads as 2012 and 2013); name_years reads both years of every consecutive pair in
# it, because the owner holds a move whenever the name states any year outside the new group
# (2026-10-11: "Hold every span").
# A two-digit year's apostrophe may be straight or curly ("’09", "‘11/‘12", "11/’12"), as _resolve_band
# reads it.
_YEAR_SEQ = re.compile(r"(?<![0-9])['‘’]?(?:20)?[0-9]{2}(?:\s*[/-]\s*['‘’]?(?:20)?[0-9]{2})+(?![0-9])")
_YEAR_4 = re.compile(r"(?<![0-9])20[0-9]{2}(?![0-9])")
_YEAR_APOS = re.compile(r"['‘’]([0-9]{2})(?![0-9])")
# "U/10B" is a U-age whose slash _UAGE_TOKEN does not expect; left in, birth_years reads "10B" as 2010.
_UAGE_SLASH = re.compile(r"(?<![0-9A-Za-z])[BGMF]?U/([0-9]{1,2})[BGMF]?(?![0-9A-Za-z])", re.I)
# "Town-G09A-Coach": a B/G age wrapped in hyphens is last season's U-age, not a birth year (owner,
# 2026-10-11).
_HYPHEN_AGE = re.compile(r"(?<=-)[BG]([0-9]{2})[A-Z]?(?=-)", re.I)
_NAME_UAGE = re.compile(r"(?i)(?<![a-z0-9])[bg]?u-?([0-9]{1,2})(?![0-9])|(?<![0-9])([0-9]{1,2})u(?=[bg]?(?![a-z0-9]))")


def without_u_ages(name: Optional[str]) -> str:
    """The name with the U-ages birth_years would read as birth years blanked."""
    return _HYPHEN_AGE.sub(" ", _UAGE_SLASH.sub(" ", name or ""))


def name_u_ages(name: Optional[str]) -> set:
    """Every U-age the name states: "U13", "13U", "U12A", "U 13", "Under 13", "U/13B", "-G13A-",
    every age of a span such as "U12/13/14" or "U11/10", and both ends of a rising range such as
    "BU17-19". A game format ("11 v 11") is not an age, and a reverse span ("13/14U") reads as its
    last age only.

    A span of three or more numbers counts on only while each is one from the last, so "U12G-14/15"
    reads as U12 alone; a number that cannot continue the span ("U10-1", "U14-49") is not read."""
    name = _FORMAT_TOKEN.sub(" ", name or "")
    ages = {int(m.group(1) or m.group(2)) for m in _NAME_UAGE.finditer(name)}
    ages |= {int(m.group(1)) for m in _HYPHEN_AGE.finditer(name)}
    ages |= {int(m.group(1)) for m in _UAGE_SLASH.finditer(name)}
    for m in _UAGE_TOKEN.finditer(name):
        # _UAGE_TOKEN's \d also matches non-ASCII digits, which this reads as no age.
        run = [int(n) for n in re.findall(r"[0-9]{1,2}", m.group(0))]
        if not run:
            continue
        ages.add(run[0])
        if len(run) == 2 and run[0] < run[1] <= 19:
            ages.add(run[1])
            continue
        for a, b in zip(run, run[1:]):
            if abs(a - b) != 1:
                break
            ages.add(b)
    return ages


def name_years(name: Optional[str]) -> set:
    """birth_years, plus each year of every consecutive pair in a run, every four-digit year and
    every apostrophe year, read on the same text birth_years reads (U-ages and game formats removed).

    A year older than the oldest group is kept, since it names another squad; the forms only
    birth_years reads ("04B", "04 Girls") stop at its 2005 floor. A year after the youngest a season
    can hold (the season less six: U7's younger year) is a season label ("2025-26", "Fall 2026")."""
    name = without_u_ages(name)
    text = _UAGE_TOKEN.sub(" ", _FORMAT_TOKEN.sub(" ", name))
    years = birth_years(name) | {int(y) for y in _YEAR_4.findall(text)}
    years |= {2000 + int(y) for y in _YEAR_APOS.findall(text)}
    for match in _YEAR_SEQ.finditer(text):
        run = [int(part[-2:]) for part in re.findall(r"[0-9]+", match.group(0))]
        for a, b in zip(run, run[1:]):
            if abs(a - b) == 1:
                years |= {2000 + a, 2000 + b}
    youngest = _soccer_season_year() - 6
    return {y for y in years if y <= youngest}


def band_of(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    _, label = _resolve_band(name)
    return normalize_age_group(label) if label else None


def single_band(*names: Optional[str]) -> Optional[str]:
    """The one cohort the names' bands agree on, or None if none or they conflict."""
    bands = {b for b in (band_of(n) for n in names) if b}
    return bands.pop() if len(bands) == 1 else None


def norm_name(name: Optional[str]) -> str:
    return " ".join((name or "").lower().split())


# Provider-written text that reaches a plan or apply CSV. These files exist to be opened
# in a spreadsheet, which reads a leading =, +, -, @, tab or newline as a formula whatever
# the quoting, so the value is escaped on the way out and unescaped on the way back in.
TEXT_FIELDS = ("team_name", "club_name", "gotsport_team_name")
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n"})


def csv_safe(value: str) -> str:
    """Prefix a formula-leading value with ``'`` so a spreadsheet renders it as text.

    A value already opening with ``'`` is escaped too; without that the encoding is not
    injective and the undo below could restore the wrong one of two values.
    """
    return "'" + value if value and (value[0] in _FORMULA_PREFIXES or value[0] == "'") else value


def csv_unsafe(value: Optional[str]) -> str:
    """Undo :func:`csv_safe`."""
    text = value or ""
    if len(text) >= 2 and text[0] == "'" and (text[1] in _FORMULA_PREFIXES or text[1] == "'"):
        return text[1:]
    return text


def shown(path: Path) -> Path:
    """For printed commands."""
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def write_csv(rows: List[Dict], path: Path, fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    escaped = [
        {k: csv_safe(v) if k in TEXT_FIELDS and isinstance(v, str) else v for k, v in row.items()}
        for row in rows
    ]
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(escaped)
    tmp.replace(path)


def read_csv(path: Path) -> List[Dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_our_csv(path: Path) -> List[Dict]:
    """A plan or apply log this tool wrote, with the escaping of :func:`csv_safe` undone.

    The reconcile logs another script writes are read with :func:`read_csv` instead: they
    were never escaped, so unescaping them would strip a leading quote that belongs.
    """
    rows = read_csv(path)
    for row in rows:
        for field in TEXT_FIELDS:
            if field in row:
                row[field] = csv_unsafe(row[field])
    return rows


# --------------------------------------------------------------------------- plan


def derive_candidates(exports_dir: Optional[Path] = None) -> List[Dict]:
    """Latest execute-mode audit row per team, filtered to band-confirmed too-old labels."""
    latest: Dict[str, Dict] = {}
    for path in sorted((exports_dir or EXPORTS).glob("reconcile_teams_with_gotsport_*.csv")):
        try:
            for row in read_csv(path):
                if (row.get("run_mode") or "").lower() == "execute":
                    latest[row["team_id_master"]] = row
        except Exception as e:  # a log still being written by a live chunk
            print(f"  skipped unreadable log {path.name}: {e}")

    candidates = []
    for row in latest.values():
        ours = normalize_age_group(row.get("stored_age_group"))
        theirs = normalize_age_group(row.get("gotsport_age_group"))
        if not ours or not theirs or age_num(theirs) >= age_num(ours):
            continue
        if single_band(row.get("gotsport_team_name"), row.get("stored_team_name")) != theirs:
            continue
        candidates.append(
            {
                "team_id_master": row["team_id_master"],
                "audit_age_group": ours,
                "new_age_group": theirs,
                "gotsport_team_name": row.get("gotsport_team_name") or "",
            }
        )
    print(f"Audit rows read: {len(latest):,} teams | band-confirmed too-old candidates: {len(candidates):,}")
    return candidates


def fetch_live(sb, ids: List[str]) -> Dict[str, Dict]:
    live: Dict[str, Dict] = {}
    cols = "team_id_master,team_name,club_name,age_group,gender,state_code,is_deprecated"
    for i in range(0, len(ids), IN_BATCH):
        for row in sb.table("teams").select(cols).in_("team_id_master", ids[i : i + IN_BATCH]).execute().data or []:
            live[row["team_id_master"]] = row
    return live


def fetch_all_live_teams(sb) -> List[Dict]:
    rows: List[Dict] = []
    start = 0
    while True:
        batch = (
            sb.table("teams")
            .select("team_id_master,team_name,age_group,gender")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(start, start + PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def evidence_tier(our_name: Optional[str], target: str) -> str:
    """How independent of GotSport the name evidence for this move is.

    A band found only in GotSport's name is GotSport agreeing with itself, and a bare
    year in ours ("2014") fits both of the cohorts it straddles, so neither decides.
    A year OUTSIDE the target's birth years means our record and GotSport's describe
    different squads -- a wrong alias or a fused row, not a label to move -- even beside a
    band that agrees. Years are checked before the band so this tier agrees with
    name_contradiction's year check; name_contradiction's U-age check has no counterpart here.
    """
    years = name_years(our_name)
    if years - cohort_years(age_num(target)):
        return "D_name_contradicts"
    if band_of(our_name) == target:
        return "A_own_name_band"
    return "C_bare_year_fits" if years else "B_gotsport_name_only"


def merged_away_ids(sb, ids: List[str]) -> Dict[str, str]:
    """Each deprecated id that resolves to one of ``ids``, mapped to its survivor.

    Game rows keep the id they were imported under, and ``execute_team_merge`` flattens
    chains, so one hop reaches every absorbed row.
    """
    absorbed: Dict[str, str] = {}
    for i in range(0, len(ids), IN_BATCH):
        found = (
            sb.table("team_merge_map")
            .select("deprecated_team_id,canonical_team_id")
            .in_("canonical_team_id", ids[i : i + IN_BATCH])
            .execute()
            .data
            or []
        )
        for row in found:
            absorbed[row["deprecated_team_id"]] = row["canonical_team_id"]
    return absorbed


def attach_fixture_evidence(sb, rows: List[Dict]) -> None:
    """Count this season's games against opponents whose OWN band names each cohort.

    Opponent names are independent of both our column and GotSport's label, which is
    why they are the witness (CLAUDE.md: settle a cohort from the fixtures, reading the
    opponent's name, not its column).

    Games absorbed by a merge still carry the deprecated id, so they are gathered under
    it and counted against the survivor. Reading the survivor's id alone does not merely
    undercount: the games it drops may be the ones backing the current cohort, and losing
    those lifts proposed over current until a mixed schedule reads as backing the move.
    """
    by_id = {r["team_id_master"]: r for r in rows}
    ids = list(by_id)
    absorbed = merged_away_ids(sb, ids)
    games = []
    query_ids = ids + list(absorbed)
    for i in range(0, len(query_ids), 50):
        batch = query_ids[i : i + 50]
        sides = (
            ("home_team_master_id", "away_team_master_id"),
            ("away_team_master_id", "home_team_master_id"),
        )
        for col, other in sides:
            # Paged and ordered: PostgREST caps a response, and a truncated read drops
            # fixtures that may be the ones backing the current cohort, which is the same
            # way an unresolved merge tips a mixed schedule into backs_move.
            start = 0
            while True:
                page = (
                    sb.table("games")
                    .select(f"{col},{other}")
                    .in_(col, batch)
                    .gte("game_date", SEASON_START)
                    .order("id")
                    .range(start, start + PAGE - 1)
                    .execute()
                    .data
                    or []
                )
                games += [(absorbed.get(g[col], g[col]), g[other]) for g in page if g.get(other)]
                if len(page) < PAGE:
                    break
                start += PAGE

    opp_ids = list({o for _, o in games})
    names: Dict[str, str] = {}
    for i in range(0, len(opp_ids), IN_BATCH):
        listed = (
            sb.table("teams")
            .select("team_id_master,team_name")
            .in_("team_id_master", opp_ids[i : i + IN_BATCH])
            .execute()
            .data
            or []
        )
        for t in listed:
            names[t["team_id_master"]] = t["team_name"]

    counts: Dict[str, Counter] = defaultdict(Counter)
    for me, opp in games:
        cohort = band_of(names.get(opp))
        row = by_id[me]
        if cohort == row["new_age_group"]:
            counts[me]["proposed"] += 1
        elif cohort and cohort == normalize_age_group(row["old_age_group"]):
            counts[me]["current"] += 1

    for tid, row in by_id.items():
        proposed, current = counts[tid]["proposed"], counts[tid]["current"]
        row["opp_games_proposed"], row["opp_games_current"] = proposed, current
        if proposed + current < 2:
            row["fixture_verdict"] = "thin"
        elif proposed >= 3 * current:
            row["fixture_verdict"] = "backs_move"
        elif current >= 3 * proposed:
            row["fixture_verdict"] = "backs_current"
        else:
            row["fixture_verdict"] = "mixed"


def _no_repeated_keys(pairs: List[Tuple[str, object]]) -> Dict[str, object]:
    # json keeps the last of two equal keys, so a second "left_held" block would silently drop the first.
    keys = [key for key, _ in pairs]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise ValueError(f"the key {repeated[0]!r} appears twice")
    return dict(pairs)


def _decided_team_id(team: Dict) -> str:
    # Lowercased because Postgres compares uuids case-insensitively and returns them lowercase, and
    # matched in full so only a well-formed uuid reaches the PostgREST in_ filter.
    team_id = team["team_id"].lower()
    if not _TEAM_ID.fullmatch(team_id):
        raise ValueError(f"{team['team_id']!r} is not a team id")
    return team_id


def load_owner_decisions(sb) -> Dict[str, Tuple[str, str]]:
    """{team id: (section, when and why)} for every team the owner decided to leave at its stored
    age, in every section of owner_decisions.json, and for each row those teams were merged into
    since: a decision outlives a merge.

    A missing or malformed file stops the run, since reading it as empty would move teams the owner
    decided to leave."""
    try:
        data = json.loads(OWNER_DECISIONS.read_text(encoding="utf-8-sig"), object_pairs_hook=_no_repeated_keys)
        decided = {}
        for section, body in data.items():
            if not isinstance(body["teams"], list):
                raise TypeError(f"the teams of {section!r} are not a list")
            for team in body["teams"]:
                decided[_decided_team_id(team)] = (section, body["decided"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SystemExit(
            f"Cannot read the owner's age decisions in {OWNER_DECISIONS} ({type(exc).__name__}: {exc}). Fix it "
            "and run again: read as empty, it would move teams the owner decided to leave."
        ) from None
    frontier = list(decided)
    while frontier:
        found = []
        for i in range(0, len(frontier), IN_BATCH):
            rows = (
                sb.table("team_merge_map")
                .select("deprecated_team_id,canonical_team_id")
                .in_("deprecated_team_id", frontier[i : i + IN_BATCH])
                .execute()
                .data
                or []
            )
            for row in rows:
                if row["canonical_team_id"] not in decided:
                    decided[row["canonical_team_id"]] = decided[row["deprecated_team_id"]]
                    found.append(row["canonical_team_id"])
        frontier = found
    return decided


def build_plan(sb, exports_dir: Optional[Path] = None) -> Path:
    candidates = derive_candidates(exports_dir)
    decided = load_owner_decisions(sb)
    live = fetch_live(sb, [c["team_id_master"] for c in candidates])

    plan: List[Dict] = []
    for c in candidates:
        tid = c["team_id_master"]
        team = live.get(tid)
        row = {
            "team_id_master": tid,
            "gotsport_team_name": c["gotsport_team_name"],
            "new_age_group": c["new_age_group"],
            "collision_with": "",
        }
        if tid in decided:
            plan.append({**row, "action": "skipped_owner_decision"})
            continue
        if not team:
            plan.append({**row, "action": "skipped_missing"})
            continue
        row.update(
            state_code=team.get("state_code") or "",
            team_name=team.get("team_name") or "",
            club_name=team.get("club_name") or "",
            gender=team.get("gender") or "",
            old_age_group=team.get("age_group") or "",
        )
        current = normalize_age_group(team.get("age_group"))
        band = single_band(c["gotsport_team_name"], team.get("team_name"))
        row["band"] = band or ""
        if team.get("is_deprecated"):
            action = "skipped_deprecated"
        elif current == c["new_age_group"]:
            action = "skipped_already_correct"
        elif current != c["audit_age_group"]:
            action = "skipped_moved_since_audit"
        elif band != c["new_age_group"]:
            action = "skipped_band_changed"
        else:
            action = "would_update"
        plan.append({**row, "action": action})

    pending = [r for r in plan if r["action"] == "would_update"]
    for r in pending:
        r["evidence_tier"] = evidence_tier(r["team_name"], r["new_age_group"])
    print(f"Reading this season's fixtures for {len(pending):,} teams...")
    attach_fixture_evidence(sb, pending)
    # Holds are decided before the collision index, so a team that will NOT move is
    # indexed in its current cohort rather than the one it was proposed for.
    for r in pending:
        if r["evidence_tier"] == "D_name_contradicts":
            r["action"] = "held_name_contradicts"
        elif r["fixture_verdict"] in ("backs_current", "mixed"):
            r["action"] = "held_fixtures_disagree"

    movers = {r["team_id_master"]: r for r in plan if r["action"] == "would_update"}
    print("Paging live teams for the collision check...")
    index: Dict[tuple, set] = defaultdict(set)
    for t in fetch_all_live_teams(sb):
        tid = t["team_id_master"]
        cohort = movers[tid]["new_age_group"] if tid in movers else normalize_age_group(t.get("age_group"))
        index[(norm_name(t.get("team_name")), t.get("gender") or "", cohort)].add(tid)
    for tid, r in movers.items():
        others = index[(norm_name(r["team_name"]), r["gender"], r["new_age_group"])] - {tid}
        if others:
            r["action"] = "would_update_collision"
            r["collision_with"] = ";".join(sorted(others)[:3])

    plan.sort(key=lambda r: (r.get("state_code") or "", r.get("new_age_group") or "", r.get("team_name") or ""))
    path = (exports_dir or EXPORTS) / f"fix_band_cohorts_plan_{datetime.now():%Y%m%d_%H%M%S}.csv"
    write_csv(plan, path, PLAN_FIELDS)

    counts = Counter(r["action"] for r in plan)
    print("\n=== Plan (DRY RUN - nothing written) ===")
    for action, n in counts.most_common():
        print(f"  {action:28s} {n:>6,}")
    clean = [r for r in plan if r["action"] == "would_update"]
    transitions = Counter(f"{r['old_age_group']} -> {r['new_age_group']}" for r in clean)
    print("\nMoves (clean rows): " + ", ".join(f"{k} {v:,}" for k, v in transitions.most_common(12)))
    per_state = Counter(r["state_code"] for r in clean)
    print("By state (clean rows): " + ", ".join(f"{k} {v:,}" for k, v in per_state.most_common(12)))
    print("Clean rows by evidence tier x fixture verdict:")
    for (tier, verdict), n in sorted(Counter((r["evidence_tier"], r["fixture_verdict"]) for r in clean).items()):
        print(f"  {tier:22s} {verdict:14s} {n:>6,}")
    off_board = sum(1 for r in clean if r["new_age_group"] not in AGE_GROUPS)
    print(f"Clean rows landing in a cohort the boards do not rank: {off_board:,}")
    print("\nSample:")
    for r in clean[:: max(1, len(clean) // 12)][:12]:
        print(f"  {r['state_code']:2s} {r['old_age_group']:>3s} -> {r['new_age_group']:3s}  {r['team_name'][:60]}")
    coll = [r for r in plan if r["action"] == "would_update_collision"]
    if coll:
        print("\nCollision samples (a same-named team already in the target cohort):")
        for r in coll[:6]:
            print(f"  {r['state_code']:2s} {r['old_age_group']:>3s} -> {r['new_age_group']:3s}  {r['team_name'][:60]}")
    print(f"\nPlan: {path}")
    return path


# --------------------------------------------------------------------------- apply


def classify_miss(sb, tid: str, new: str) -> str:
    rows = sb.table("teams").select("age_group,is_deprecated").eq("team_id_master", tid).execute().data or []
    if not rows:
        return "skipped_missing"
    if rows[0].get("is_deprecated"):
        return "skipped_deprecated"
    return "already_applied" if normalize_age_group(rows[0].get("age_group")) == new else "skipped_moved"


def is_strong(row: Dict) -> bool:
    """Two independent signals: our own name's band, or the opponents' own names."""
    return row.get("evidence_tier", "").startswith("A_") or row.get("fixture_verdict") == "backs_move"


def name_contradiction(name: Optional[str], target: str) -> str:
    """Why OUR name plainly describes a different age than the move, or "" if it does not.

    Reads only OUR name, because the owner's rule is that GotSport's two-year band is trusted.
    Any year name_years finds outside the new group holds the move, a span overlapping it
    included (owner, 2026-10-11: "Hold every span"). A U-age one group away in either direction
    passes: names keep last season's U-age after the Aug 1 roll, and squads play a year up.
    """
    name = name or ""
    n = age_num(target)
    allowed = cohort_years(n)
    stray = sorted(name_years(name) - allowed)
    if stray:
        shown_years = "/".join(str(y) for y in sorted(allowed, reverse=True))
        return f"name has birth year {stray[0]}, outside {target.upper()} ({shown_years})"
    for age in sorted(name_u_ages(name)):
        steps = _group_steps(age, n)
        if 5 <= age <= 19 and steps >= 2:
            return f"name says U{age}, {steps} away from {target.upper()}"
    return ""


def _group_steps(a: int, b: int) -> int:
    """Steps from one U-age's group to another's, with U18 filed into u19: U17 to U19 is one step."""
    lo, hi = sorted(19 if age == 18 else age for age in (a, b))
    return hi - lo - (1 if lo <= 17 < hi else 0)


def apply_plan(
    sb,
    plan_path: Path,
    execute: bool,
    limit: Optional[int],
    include_collisions: bool,
    strong_only: bool,
    boarded_only: bool,
    unboarded_only: bool = False,
    exclude: frozenset = frozenset(),
    gotsport_only: bool = False,
    skip_name_contradictions: bool = False,
    exports_dir: Optional[Path] = None,
    actor: str = DEFAULT_ACTOR,
) -> None:
    if boarded_only and unboarded_only:
        raise SystemExit("--boarded-only and --unboarded-only select disjoint sets; pass one")
    if strong_only and gotsport_only:
        raise SystemExit("--strong-only and --gotsport-only select disjoint sets; pass one")
    wanted = {"would_update"} | ({"would_update_collision"} if include_collisions else set())
    selected = [
        r
        for r in read_our_csv(plan_path)
        if r["action"] in wanted
        and r["team_id_master"] not in exclude
        and (not strong_only or is_strong(r))
        and (not gotsport_only or not is_strong(r))
        and (not boarded_only or r["new_age_group"] in AGE_GROUPS)
        and (not unboarded_only or r["new_age_group"] not in AGE_GROUPS)
    ]
    # Every producer's plan passes here, and a decision can postdate the plan, so the owner's
    # decisions are read again at apply time.
    decided = load_owner_decisions(sb)
    held, writable = [], []
    for r in selected:
        owner = decided.get(r["team_id_master"].lower())
        if owner:
            r["hold_reason"], r["result"] = f"owner decision {owner[0]}: {owner[1]}", "held_owner_decision"
        else:
            reason = name_contradiction(r["team_name"], r["new_age_group"]) if skip_name_contradictions else ""
            r["hold_reason"] = reason
            if reason:
                r["result"] = "held_name_contradicts"
        (held if r["hold_reason"] else writable).append(r)
    # Apply in id order: effectively a random spread, so a --limit pilot samples every state.
    writable.sort(key=lambda r: r["team_id_master"])
    if limit is not None:
        # Not `if limit:` -- 0 is a request for no rows, and falling through to the
        # unsliced list turns an aborted pilot into the whole plan.
        writable = writable[:limit]
    todo = writable + ([] if limit is not None else sorted(held, key=lambda r: r["team_id_master"]))

    log_path = (exports_dir or EXPORTS) / f"fix_band_cohorts_apply_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fields = APPLY_LOG_FIELDS
    for r in todo:
        r["actor"] = actor
        if not r["hold_reason"]:
            r["result"] = "planned_not_applied" if execute else "would_update"
    write_csv(todo, log_path, fields)  # lands before the first write: the log is the way back

    print(
        f"=== Apply {plan_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : "
        f"{len(writable):,} to write, {len(held):,} held ==="
    )
    try:
        for i, r in enumerate(todo, 1):
            if not execute or r["hold_reason"]:
                continue
            r["result"] = IN_FLIGHT
            updated = (
                sb.table("teams")
                .update({"age_group": r["new_age_group"]})
                .eq("team_id_master", r["team_id_master"])
                .eq("is_deprecated", False)
                .eq("age_group", r["old_age_group"])
                .execute()
                .data
            )
            r["result"] = "updated" if updated else classify_miss(sb, r["team_id_master"], r["new_age_group"])
            if i % 500 == 0:
                print(f"  {i:,} / {len(todo):,}")
                write_csv(todo, log_path, fields)
    finally:
        # The row whose PATCH may have committed without us seeing the reply is unknown
        # rather than unwritten. A row the loop never reached was never sent and stays
        # planned_not_applied. revert() replays both against the live value instead of
        # trusting this file.
        for r in todo:
            if r["result"] == IN_FLIGHT and execute and not r["hold_reason"]:
                r["result"] = UNCONFIRMED
        write_csv(todo, log_path, fields)

    print("\n=== Result ===")
    for result, n in Counter(r["result"] for r in todo).most_common():
        print(f"  {result:22s} {n:>6,}")
    print(f"\nLog: {log_path}")
    if execute:
        print(f'Undo with: python {Path(__file__).resolve().relative_to(ROOT)} --revert "{shown(log_path)}" --execute')


def revert(sb, log_path: Path, execute: bool) -> None:
    """Replay an apply log backwards, restoring only rows still holding what it wrote.

    Unconfirmed and planned_not_applied rows are replayed too: an unconfirmed write may
    have committed with the reply lost, and a hard kill leaves rows written after the
    log's last checkpoint as planned_not_applied, so the live value is the only thing
    that settles it -- and the predicate below means a row that never moved matches
    nothing.
    """
    rows = [r for r in read_our_csv(log_path) if r.get("result") in REVERTABLE]
    decided = load_owner_decisions(sb)
    print(f"=== Revert {log_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : {len(rows):,} rows ===")
    outcome = Counter()
    for r in rows:
        # Apply holds decided teams, so a decided team in a log was moved before its decision, and
        # undoing that move would take it off the age the owner chose to keep.
        if r["team_id_master"].lower() in decided:
            outcome["held_owner_decision"] += 1
            continue
        if not execute:
            outcome["would_revert"] += 1
            continue
        done = (
            sb.table("teams")
            .update({"age_group": r["old_age_group"]})
            .eq("team_id_master", r["team_id_master"])
            .eq("age_group", r["new_age_group"])
            .execute()
            .data
        )
        key = "reverted" if done else "skipped_changed_since"
        outcome[f"{key}_unconfirmed" if r.get("result") == UNCONFIRMED else key] += 1
    for k, n in outcome.most_common():
        print(f"  {k:22s} {n:>6,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", type=Path, help="Apply a plan CSV produced by a dry run")
    parser.add_argument("--revert", type=Path, help="Undo an apply log")
    parser.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--limit", type=int, help="Apply only the first N plan rows (pilot); 0 applies none")
    parser.add_argument(
        "--include-collisions", action="store_true", help="Also apply rows with a same-named team in the target cohort"
    )
    parser.add_argument(
        "--strong-only", action="store_true", help="Only rows with two independent signals (own-name band or opponents)"
    )
    parser.add_argument(
        "--boarded-only", action="store_true", help="Only rows whose new cohort is one the ranking boards rank"
    )
    parser.add_argument(
        "--unboarded-only",
        action="store_true",
        help="Only rows whose new cohort the boards do not rank (u9 and younger)",
    )
    parser.add_argument("--exclude", default="", help="Comma-separated team_id_master values to leave untouched")
    parser.add_argument(
        "--gotsport-only", action="store_true", help="Only rows whose evidence is GotSport's two-year band alone"
    )
    parser.add_argument(
        "--skip-name-contradictions", action="store_true", help="Hold rows whose own name states a different age"
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        help="Folder to read reconcile logs from and write the plan and apply log to (default: <repo>/data/exports)",
    )
    parser.add_argument("--actor", default=DEFAULT_ACTOR, help="Who ran this; recorded on every apply log row")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit cannot be negative; it would apply all but the last rows")
    execute = args.execute and not args.dry_run

    load_env()
    sb = get_supabase()
    if args.revert:
        revert(sb, args.revert, execute)
    elif args.apply:
        apply_plan(
            sb,
            args.apply,
            execute,
            args.limit,
            args.include_collisions,
            args.strong_only,
            args.boarded_only,
            args.unboarded_only,
            frozenset(x.strip() for x in args.exclude.split(",") if x.strip()),
            args.gotsport_only,
            args.skip_name_contradictions,
            args.exports_dir,
            args.actor,
        )
    else:
        if args.execute:
            print("--execute without --apply does nothing: take a dry run, review the plan, then --apply it.")
        build_plan(sb, args.exports_dir)


if __name__ == "__main__":
    main()
