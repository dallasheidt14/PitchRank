#!/usr/bin/env python3
"""
Restore club names that the importer and the weekly club cleanup overwrote.

Two faults put wrong values in ``teams.club_name``:

* From 68ecb678f (2026-03-01) the game importer replaced every incoming club name
  with the canonical club ``club_normalizer`` matched it to, before matching, and
  that match was often a different club: "NC Fusion" became VENTURA COUNTY FUSION
  and "Oregon Surf" became SURF. A team the matcher created kept the swapped name.
* The weekly club cleanup (``full_club_analysis.py``) re-cased names that were
  already right and lowered their abbreviations on 2026-09-14: "JSC Soccer Club"
  became "Jsc Soccer Club", "Homewood Soccer Club (AL)" became "... (al)".

Three sources supply the right value, each for one fault, and every proposal is
tagged with its source:

* ``playmetrics`` -- a PlayMetrics team whose club is a canonical club name gets
  the club PlayMetrics itself reports for that team id. ``state_note`` flags a team
  whose state differs from its league's, because the matcher derived that state
  from the swapped club; state corrections belong to the assigning-team-states
  skill, not to this script.
* ``team_name`` -- any other provider except GotSport: the club is the start of
  the team's own name, up to its first age or level token ("Oregon Surf GU11
  PreECNL" -> "Oregon Surf"). A club still in the canonical upper case is the
  importer's signature and is approved; one the cleanup has since re-cased is only
  listed, because a squad label reads the same way. NEFC is left alone: it is that
  club's real name.
* ``abbreviation`` -- every provider: the cleanup's own log (``gh run view <run>
  --log``) names each rename, and one that only lowered an all-caps word or
  bracketed segment of a mixed-case name is undone for every live team in that
  state still holding the lowered spelling. A rename that re-cased some other word
  holding a capital ("SoCal" -> "Socal") is proposed too, listed but not approved.

The dry run writes a snapshot CSV to data/exports and changes nothing. Read it, set
``approved`` to true on any listed row you accept, then replay it with --execute:
nothing is recomputed, and an approved row is written only while its team still
holds the club the snapshot read, a change of case aside. Every write is logged to
a CSV that --revert replays backwards.

Usage:
    python scripts/repair_swapped_club_names.py
    python scripts/repair_swapped_club_names.py --abbreviation-run 34866235667 --abbreviation-run <later run>
    python scripts/repair_swapped_club_names.py --execute data/exports/repair_swapped_club_names_<ts>.csv
    python scripts/repair_swapped_club_names.py --revert data/exports/repair_swapped_club_names_log_<ts>.csv
    python scripts/repair_swapped_club_names.py --revert data/exports/repair_swapped_club_names_log_<ts>.csv --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_playmetrics_league import (  # noqa: E402
    GB_STATE_MAP,
    _parse_league_url,
    get_division,
    get_league,
)
from src.utils.club_normalizer import CANONICAL_CLUBS, _core_and_codes, _light_form  # noqa: E402

# The WI (1014) and NC (1207) PlayMetrics leagues whose teams the importer created.
DEFAULT_LEAGUE_URLS = (
    "https://playmetricssports.com/g/leagues/1014-2319-3e2c725a/league_view.html",
    "https://playmetricssports.com/g/leagues/1207-2289-46ec05ca/league_view.html",
)
# The Monday run of update-missing-club-and-state.yml that lowered the abbreviations.
DEFAULT_ABBREVIATION_RUNS = ("34866235667",)

# The team_name source never reads these: GotSport's clubs come from GotSport, and
# PlayMetrics has its own source above.
TEAM_NAME_SKIPPED_PROVIDERS = frozenset({"gotsport", "playmetrics"})
TEAM_NAME_EXCLUDED_CLUBS = frozenset({"NEFC"})

TEAM_COLUMNS = "team_id_master,team_name,club_name,state_code,provider_id,provider_team_id"

SNAPSHOT_FIELDS = (
    "team_id_master",
    "provider",
    "state",
    "team_name",
    "stored_club",
    "proposed_club",
    "source",
    "tier",
    "needs_review",
    "approved",
    "state_note",
)
# Untrusted text, defanged in the CSV so a spreadsheet shows it as text.
SNAPSHOT_TEXT_FIELDS = ("team_name", "stored_club", "proposed_club", "state_note")
LOG_FIELDS = ("team_id_master", "run_mode", "action", "source", "tier", "before", "after")

# The first age or level token ends the club part of a team name. ASCII-bounded,
# because the text before it is written to teams.club_name.
LEVEL_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[BG]?U-?[0-9]{1,2}[BG]?"
    r"|[BG]?20[0-2][0-9](?:/[0-9]{2})?"
    r"|[BG][0-9]{2}(?:/[0-9]{2})?"
    r"|[0-9]{2}[BG]"
    r"|Pre-?\s?ECNL"
    r"|ECNL(?:-RL)?"
    r"|NPL|HD|AD|EA2?"
    r"|MLS\s+NEXT"
    r"|Boys|Girls"
    r")(?![A-Za-z0-9])",
    re.ASCII | re.IGNORECASE,
)
TRAILING_SEPARATORS = re.compile(r"[\s\-–—/|,:;]+$")

# One rename printed by the cleanup's --execute. The step column of ``gh run view
# --log`` can read UNKNOWN STEP on every line, so lines are chosen by what they say.
FIX_LINE = re.compile(r'✅ ([A-Z0-9_ ]+): "(.*)" → "(.*)"')
NO_STATE = "NO_STATE"
STATE_LABEL = re.compile(r"[A-Z]{2}")
BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
LETTER_RUN = re.compile(r"[A-Za-z]+")
CAPS_WORD = re.compile(r"[A-Z]{2,}")
ASCII_LOWER = re.compile(r"[a-z]")
ASCII_UPPER = re.compile(r"[A-Z]")
RUN_ID = re.compile(r"[0-9]{1,20}")

# Spreadsheet apps read a cell as a formula when it starts with one of these.
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n"})

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# teams.club_name is unbounded text; a replayed or reverted value is not.
MAX_NAME_LENGTH = 200

EXPORTS_DIR = Path("data/exports")
PAGE_SIZE = 1000
IN_BATCH = 100
DIVISION_DELAY_SEC = 0.3


def csv_safe(value: str) -> str:
    """Prefix a formula-leading value with ``'`` so a spreadsheet renders it as text.

    A value already opening with ``'`` is escaped too, without which the encoding is
    not injective and the undo could restore the wrong one of two values.
    """
    return "'" + value if value and (value[0] in _FORMULA_PREFIXES or value[0] == "'") else value


def csv_unsafe(value: Optional[str]) -> str:
    """Undo :func:`csv_safe`."""
    text = value or ""
    if len(text) >= 2 and text[0] == "'" and (text[1] in _FORMULA_PREFIXES or text[1] == "'"):
        return text[1:]
    return text


def printable(value: object) -> str:
    """Strip non-printable characters (controls, format characters, non-ASCII spaces) before
    a value reaches the operator's terminal.

    The dry run is the only human gate before a service-role batch, and every name
    in it was written by a scraper. A bare ``\\r`` repaints the whole line.
    """
    return "".join(c for c in str(value if value is not None else "") if c.isprintable())


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
        # to zero rows and PostgREST answers 200 with an empty body.
        raise ValueError("--execute needs SUPABASE_SERVICE_ROLE_KEY; the anon key writes nothing under RLS.")
    return create_client(supabase_url, supabase_key)


def resolve_execute(execute_flag: bool, dry_run_flag: bool) -> bool:
    """Fail safe: asking for both means the caller wants the preview."""
    return execute_flag and not dry_run_flag


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_log(rows: List[Dict], path: Path) -> None:
    """Write a CSV, replacing any previous copy as nearly atomically as we can.

    The log is the only way back from a service-role batch and it is rewritten once
    the writes finish, so truncating it in place would leave a failure during that
    second write with no recovery record at all.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # utf-8-sig: without the BOM a spreadsheet opens the file in its local code page.
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --- reading -----------------------------------------------------------------------


def escape_like(value: str) -> str:
    """Escape ``value`` so ILIKE reads none of it as a wildcard, ignoring only case.

    PostgREST turns every ``*`` into ``%`` before Postgres sees the pattern, so an
    escaped ``*`` matches only a literal ``%``.
    """
    return re.sub(r"([\\%_*])", r"\\\1", value)


def _paged(make_query) -> List[Dict]:
    rows: List[Dict] = []
    offset = 0
    while True:
        batch = make_query().order("team_id_master").range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def fetch_provider_codes(supabase) -> Dict[str, str]:
    rows = supabase.table("providers").select("id,code").execute().data or []
    return {row["id"]: row["code"] for row in rows}


def fetch_canonical_holders(supabase) -> List[Dict]:
    """Every live team whose club is a canonical club name, compared ignoring case.

    Case-insensitive because the weekly cleanup re-cases an upper-case club where its
    state already holds a mixed-case spelling ("CHARLOTTE FC" -> "Charlotte FC").
    """
    found: Dict[str, Dict] = {}
    for key in CANONICAL_CLUBS:
        rows = _paged(
            lambda k=key: (
                supabase.table("teams")
                .select(TEAM_COLUMNS)
                .ilike("club_name", escape_like(k))
                .eq("is_deprecated", False)
            )
        )
        for row in rows:
            found[row["team_id_master"]] = row
    return list(found.values())


def fetch_teams_holding(supabase, value: str, state: Optional[str]) -> List[Dict]:
    """Every live team in ``state`` whose club is exactly ``value``; no state means NULL or empty."""

    def query():
        q = supabase.table("teams").select(TEAM_COLUMNS).eq("club_name", value).eq("is_deprecated", False)
        return q.eq("state_code", state) if state else q.or_("state_code.is.null,state_code.eq.")

    return _paged(query)


def parse_league_urls(urls: Iterable[str]) -> List[Tuple[int, int, str]]:
    leagues = []
    for url in urls:
        parsed = _parse_league_url(url)
        if not parsed:
            raise ValueError(f"Could not parse PlayMetrics league URL: {url}")
        if parsed[0] not in GB_STATE_MAP:
            raise ValueError(f"Unknown PlayMetrics governing_body_id {parsed[0]} in {url}")
        leagues.append(parsed)
    return leagues


def fetch_playmetrics_clubs(
    leagues: Iterable[Tuple[int, int, str]],
    league: Callable = get_league,
    division: Callable = get_division,
    delay: float = DIVISION_DELAY_SEC,
) -> Dict[str, Tuple[str, str]]:
    """PlayMetrics' own club for each team id it lists, with the league's state.

    Keyed the way ``scrape_division`` builds its lookup, so the ids are the
    ``provider_team_id`` values the importer stored.
    """
    clubs: Dict[str, Tuple[str, str]] = {}
    for gb_id, league_id, key in leagues:
        state = GB_STATE_MAP[gb_id]
        for entry in league(gb_id, league_id, key).get("divisions") or []:
            if entry.get("id") is None:
                continue
            data = division(gb_id, league_id, key, entry["id"])
            time.sleep(delay)
            for listed in data.get("teams") or []:
                team = listed.get("team") or {}
                club = listed.get("club") or {}
                if team.get("id") is None:
                    continue
                clubs.setdefault(str(team["id"]), (str(club.get("name") or "").strip(), state))
    return clubs


def validate_run_ids(run_ids: Iterable[str]) -> None:
    bad = [run_id for run_id in run_ids if not RUN_ID.fullmatch(run_id)]
    if bad:
        raise ValueError(f"A GitHub run id is digits only: {', '.join(bad)}")


def read_run_log(run_id: str) -> str:
    validate_run_ids([run_id])
    result = subprocess.run(["gh", "run", "view", run_id, "--log"], capture_output=True, encoding="utf-8", check=True)
    return result.stdout


# --- deciding ----------------------------------------------------------------------


def club_part(team_name: str) -> Tuple[str, bool]:
    """The team name up to its first age or level token, and whether it had one."""
    match = LEVEL_TOKEN.search(team_name)
    text = team_name[: match.start()] if match else team_name
    return TRAILING_SEPARATORS.sub("", text).strip(), match is not None


def has_repeated_half(words: List[str]) -> bool:
    """Whether the words open with one run said twice ("WSC Crush WSC Crush")."""
    lowered = [w.lower() for w in words]
    return any(lowered[:k] == lowered[k : 2 * k] for k in range(1, len(lowered) // 2 + 1))


def classify_team_name(team_name: str, stored: str) -> Tuple[str, str]:
    """Return ``(outcome, proposal)`` for a team whose stored club is a canonical club name.

    First match wins: ``skip_prefix`` (the team name opens with the stored club, so the
    stored club is kept), ``needs_review`` (no token, fewer than two words, or a
    repeated half), ``skip_same``, ``swap`` (still the upper case the importer wrote),
    ``skip_core`` (a squad label naming the stored club), else ``recased``.
    """
    light = _light_form(team_name)
    stored_light = _light_form(stored)
    if light == stored_light or light.startswith(stored_light + " "):
        return "skip_prefix", ""
    proposal, has_token = club_part(team_name)
    words = proposal.split()
    if not has_token or len(words) < 2 or has_repeated_half(words):
        return "needs_review", proposal
    if proposal.lower() == stored.lower():
        return "skip_same", ""
    if stored in CANONICAL_CLUBS:
        return "swap", proposal
    core, _ = _core_and_codes(stored)
    if f" {core} " in f" {_light_form(proposal)} ":
        return "skip_core", ""
    return "recased", proposal


def lowered_abbreviation(before: str, after: str) -> Optional[str]:
    """``word`` or ``bracket`` when a rename only lowered an abbreviation, ``capital`` when
    it re-cased a word that held a capital in some other way, else None.

    All must hold: (a) the names differ only in case; (b) the name was already mixed
    case; (c) an all-caps run of two or more letters outside brackets, or an all-caps
    bracketed segment, changed case. A run, not a whitespace word, so "SG1" and the
    "FC" of "FC/North" count. Failing (c), ``capital`` covers the same run's other
    damage ("SoCal" -> "Socal", "La Jolla" -> "LA Jolla"), while a rename that only
    touched all-lowercase words ("Chesapeake united sc") was the cleanup doing its job.
    """
    if before == after or before.lower() != after.lower():
        return None
    if not ASCII_LOWER.search(before):
        return None
    outside_before, outside_after = BRACKETED.sub(" ", before), BRACKETED.sub(" ", after)
    if any(
        CAPS_WORD.fullmatch(run.group()) and outside_after[run.start() : run.end()] != run.group()
        for run in LETTER_RUN.finditer(outside_before)
    ):
        return "word"
    segments = zip(BRACKETED.findall(before), BRACKETED.findall(after))
    if any(ASCII_UPPER.search(was) and not ASCII_LOWER.search(was) and was != now for was, now in segments):
        return "bracket"
    if any(
        ASCII_UPPER.search(run.group()) and after[run.start() : run.end()] != run.group()
        for run in LETTER_RUN.finditer(before)
    ):
        return "capital"
    return None


def parse_cleanup_log(text: str) -> List[Tuple[Optional[str], str, str, str]]:
    """``(state, before, after, tier)`` for each logged rename :func:`lowered_abbreviation`
    classifies (word, bracket or capital).

    ``state`` is None for NO_STATE, the cleanup's label for a NULL or empty state.
    """
    fixes = []
    for line in text.splitlines():
        match = FIX_LINE.search(line)
        if not match:
            continue
        label, before, after = match.group(1).strip(), match.group(2), match.group(3)
        if label != NO_STATE and not STATE_LABEL.fullmatch(label):
            continue
        tier = lowered_abbreviation(before, after)
        if tier:
            fixes.append((None if label == NO_STATE else label, before, after, tier))
    return fixes


def snapshot_row(
    team: Dict,
    codes: Dict[str, str],
    proposed: str,
    source: str,
    tier: str,
    approved: bool,
    needs_review: bool = False,
    state_note: str = "",
) -> Dict:
    return {
        "team_id_master": team["team_id_master"],
        "provider": codes.get(team.get("provider_id"), ""),
        "state": team.get("state_code") or "",
        "team_name": team.get("team_name") or "",
        "stored_club": team.get("club_name") or "",
        "proposed_club": proposed,
        "source": source,
        "tier": tier,
        "needs_review": needs_review,
        "approved": approved,
        "state_note": state_note,
    }


def playmetrics_rows(
    teams: List[Dict], codes: Dict[str, str], clubs: Dict[str, Tuple[str, str]]
) -> Tuple[List[Dict], int]:
    """Proposals from PlayMetrics' own club, and how many teams no league listed."""
    rows = []
    unlisted = 0
    for team in teams:
        if codes.get(team.get("provider_id")) != "playmetrics":
            continue
        club, league_state = clubs.get(str(team.get("provider_team_id") or ""), ("", ""))
        if not club:
            unlisted += 1
            continue
        if club == team.get("club_name"):
            continue
        stored_state = team.get("state_code") or ""
        note = "" if stored_state == league_state else f"stored state {stored_state or 'none'}, league {league_state}"
        rows.append(snapshot_row(team, codes, club, "playmetrics", "provider", approved=True, state_note=note))
    return rows, unlisted


def team_name_rows(teams: List[Dict], codes: Dict[str, str]) -> Tuple[List[Dict], Counter]:
    """Proposals from the start of each team's own name, and every outcome counted."""
    rows = []
    outcomes: Counter = Counter()
    for team in teams:
        if codes.get(team.get("provider_id")) in TEAM_NAME_SKIPPED_PROVIDERS:
            continue
        stored = team.get("club_name") or ""
        if stored.upper() in TEAM_NAME_EXCLUDED_CLUBS:
            continue
        outcome, proposal = classify_team_name(team.get("team_name") or "", stored)
        outcomes[outcome] += 1
        if outcome in ("swap", "recased"):
            rows.append(snapshot_row(team, codes, proposal, "team_name", outcome, approved=outcome == "swap"))
        elif outcome == "needs_review":
            rows.append(snapshot_row(team, codes, proposal, "team_name", "unclear", approved=False, needs_review=True))
    return rows, outcomes


def abbreviation_rows(
    supabase, fixes: Iterable[Tuple[Optional[str], str, str, str]], codes: Dict[str, str]
) -> List[Dict]:
    rows = []
    for state, before, after, tier in fixes:
        for team in fetch_teams_holding(supabase, after, state):
            rows.append(snapshot_row(team, codes, before, "abbreviation", tier, approved=tier != "capital"))
    return rows


def merge_proposals(rows: List[Dict]) -> Tuple[List[Dict], List[Tuple[str, List[Dict]]]]:
    """One row per team. Two proposals of different clubs for one team leave it for review."""
    by_team: Dict[str, List[Dict]] = {}
    for row in rows:
        by_team.setdefault(row["team_id_master"], []).append(row)
    merged = []
    conflicts = []
    for team_id, proposals in by_team.items():
        row = proposals[0]
        if len({p["proposed_club"] for p in proposals}) > 1:
            row = {**row, "needs_review": True, "approved": False}
            conflicts.append((team_id, proposals))
        merged.append(row)
    return merged, conflicts


def build_snapshot(supabase, clubs: Dict[str, Tuple[str, str]], cleanup_logs: Iterable[str]) -> Tuple[List[Dict], Dict]:
    """Every proposal from the three sources, one row per team, and what the summary reports."""
    codes = fetch_provider_codes(supabase)
    holders = fetch_canonical_holders(supabase)
    provider_rows, unlisted = playmetrics_rows(holders, codes, clubs)
    name_rows, outcomes = team_name_rows(holders, codes)

    fixes: Dict[Tuple[Optional[str], str, str], Tuple[Optional[str], str, str, str]] = {}
    for text in cleanup_logs:
        for fix in parse_cleanup_log(text):
            fixes.setdefault(fix[:3], fix)
    lowered_rows = abbreviation_rows(supabase, fixes.values(), codes)

    rows, conflicts = merge_proposals(provider_rows + name_rows + lowered_rows)
    rows.sort(key=lambda r: (r["source"], r["tier"], r["state"], r["stored_club"], r["team_name"]))
    stats = {
        "playmetrics_unlisted": unlisted,
        "team_name_outcomes": outcomes,
        "abbreviation_renames": Counter(fix[3] for fix in fixes.values()),
        "conflicts": conflicts,
    }
    return rows, stats


def snapshot_csv_row(row: Dict) -> Dict:
    out = {name: row[name] for name in SNAPSHOT_FIELDS}
    for name in SNAPSHOT_TEXT_FIELDS:
        out[name] = csv_safe(out[name])
    out["needs_review"] = "true" if row["needs_review"] else "false"
    out["approved"] = "true" if row["approved"] else "false"
    return out


def print_summary(rows: List[Dict], stats: Dict) -> None:
    print("\n=== Proposals by source and tier ===")
    for (source, tier), count in sorted(Counter((r["source"], r["tier"]) for r in rows).items()):
        approved = sum(1 for r in rows if (r["source"], r["tier"]) == (source, tier) and r["approved"])
        print(f"  {source:13s} {tier:9s} {count:6d}  approved by default: {approved}")
    print(f"  PlayMetrics teams no league listed (not proposed): {stats['playmetrics_unlisted']}")
    skipped = {k: v for k, v in stats["team_name_outcomes"].items() if k.startswith("skip_")}
    print(f"  team_name rows skipped: {dict(sorted(skipped.items()))}")
    renames = stats["abbreviation_renames"]
    print(
        f"  cleanup renames undone: {sum(renames.values())} ({renames['word']} word, {renames['bracket']} bracket, "
        f"{renames['capital']} capital, listed only)"
    )

    for team_id, proposals in stats["conflicts"]:
        offers = "; ".join(f"{p['source']} proposes {printable(p['proposed_club'])!r}" for p in proposals)
        print(f"  CONFLICT {team_id}: {offers} -- left for review, not approved")

    listed = [r for r in rows if r["needs_review"] or r["tier"] in ("recased", "capital")]
    if listed:
        print("\n=== Listed for review (approved false) ===")
    for row in listed:
        print(
            f"  {row['tier']:9s} {row['provider'] or '-':12s} {row['state'] or '--':2s}  "
            f"{printable(row['team_name'])[:40]:40s} {printable(row['stored_club'])!r} -> "
            f"{printable(row['proposed_club'])!r}"
        )


# --- writing -----------------------------------------------------------------------


def load_snapshot(path: Path) -> List[Dict]:
    # utf-8-sig: a spreadsheet saving "CSV UTF-8" prefixes a BOM to the first header.
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = set(SNAPSHOT_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is not a snapshot this script wrote; missing {sorted(missing)}")
        rows = list(reader)
    for row in rows:
        for name in SNAPSHOT_TEXT_FIELDS:
            row[name] = csv_unsafe(row[name])
    return rows


def is_approved(row: Dict) -> bool:
    return (row.get("approved") or "").strip().lower() == "true"


def _replay_row_is_sound(row: Dict) -> bool:
    """Whether a snapshot row is shaped like something this script wrote.

    The replay turns a file from the command line, edited by hand, into service-role
    writes, so the row it targets and the value it writes are both checked.
    """
    if not _UUID.match(row.get("team_id_master") or ""):
        return False
    stored, proposed = row.get("stored_club") or "", row.get("proposed_club") or ""
    return 0 < len(stored) <= MAX_NAME_LENGTH and 0 < len(proposed.strip()) and len(proposed) <= MAX_NAME_LENGTH


def fetch_current(supabase, team_ids: List[str]) -> Dict[str, Optional[str]]:
    """Each live team's club as it stands now; a merged-away team is absent."""
    current: Dict[str, Optional[str]] = {}
    for start in range(0, len(team_ids), IN_BATCH):
        rows = (
            supabase.table("teams")
            .select("team_id_master,club_name")
            .in_("team_id_master", team_ids[start : start + IN_BATCH])
            .eq("is_deprecated", False)
            .execute()
            .data
            or []
        )
        for row in rows:
            current[row["team_id_master"]] = row.get("club_name")
    return current


def plan_replay(approved: List[Dict], current: Dict[str, Optional[str]]) -> List[Dict]:
    """A log entry for every approved row: ``updated`` if it is due a write, else why not."""
    entries = []
    for row in approved:
        entry = {
            "team_id_master": row.get("team_id_master") or "",
            "source": row.get("source") or "",
            "tier": row.get("tier") or "",
            "before": "",
            "after": row.get("proposed_club") or "",
        }
        now = current.get(entry["team_id_master"])
        if not _replay_row_is_sound(row):
            entry["action"] = "refused_shape"
        elif entry["team_id_master"] not in current:
            entry["action"] = "skipped_missing"
        elif now is None or now.lower() != row["stored_club"].lower():
            entry["action"] = "skipped_changed_since_snapshot"
        elif now == row["proposed_club"]:
            entry["before"] = now
            entry["action"] = "skipped_already_applied"
        else:
            entry["before"] = now
            entry["action"] = "updated"
        entries.append(entry)
    return entries


def apply_club(supabase, team_id: str, expected: str, value: str) -> bool:
    """Write one club, refusing the row if it moved or was merged away since it was read."""
    result = (
        supabase.table("teams")
        .update({"club_name": value})
        .eq("team_id_master", team_id)
        .eq("is_deprecated", False)
        .eq("club_name", expected)
        .execute()
    )
    return bool(result.data)


def log_row(entry: Dict, run_mode: str) -> Dict:
    return {
        "team_id_master": entry["team_id_master"],
        "run_mode": run_mode,
        "action": entry["action"],
        "source": entry["source"],
        "tier": entry["tier"],
        "before": csv_safe(entry["before"]),
        "after": csv_safe(entry["after"]),
    }


def run_replay(supabase, entries: List[Dict], execute: bool) -> None:
    """Preview every due write, and apply them only when executing."""
    for entry in entries:
        if entry["action"] != "updated":
            continue
        print(f"  {printable(entry['before'])[:44]:44s} -> {printable(entry['after'])}")
        if not execute:
            continue
        entry["attempted"] = True
        if not apply_club(supabase, entry["team_id_master"], entry["before"], entry["after"]):
            entry["action"] = "skipped_changed_since_read"


def _revert_row_is_sound(row: Dict, before: str, after: str) -> bool:
    """Whether a log row is shaped like something this script produced.

    The undo is the other path that turns a file from the command line into a
    service-role write, and the operator is trained to run it on a file they did not
    audit.
    """
    if not _UUID.match(row.get("team_id_master") or ""):
        return False
    return 0 < len(before) <= MAX_NAME_LENGTH and 0 < len(after) <= MAX_NAME_LENGTH


def revert(supabase, log_path: Path, execute: bool) -> Dict[str, int]:
    """Replay a log backwards, refusing any row that no longer holds what we wrote."""
    with log_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if set(LOG_FIELDS) - set(reader.fieldnames or ()):
            raise ValueError(f"{log_path} is not a log this script wrote.")
        rows = list(reader)

    if any(r.get("run_mode") == "dry-run" for r in rows):
        # A preview records its planned rows so the operator can read them, but
        # nothing was written, so restoring them would overwrite live values.
        raise ValueError(f"{log_path} is a dry-run log; there is nothing to revert.")

    counts = {"reverted": 0, "refused_changed": 0, "refused_shape": 0}
    for row in [r for r in rows if r.get("action") == "updated"]:
        before, after = csv_unsafe(row["before"]), csv_unsafe(row["after"])
        if not _revert_row_is_sound(row, before, after):
            counts["refused_shape"] += 1
            continue
        print(f"  {printable(after)[:44]:44s} -> {printable(before)}")
        if not execute:
            counts["reverted"] += 1
        elif apply_club(supabase, row["team_id_master"], after, before):
            counts["reverted"] += 1
        else:
            counts["refused_changed"] += 1
            print(f"    refused: {row['team_id_master']} no longer holds {printable(after)!r}")
    return counts


# --- entry point -------------------------------------------------------------------


def replay_snapshot(snapshot_path: Path, execute: bool) -> int:
    rows = load_snapshot(snapshot_path)
    run_mode = "execute" if execute else "dry-run"
    log_path = EXPORTS_DIR / f"repair_swapped_club_names_log_{timestamp()}.csv"
    if log_path.exists():
        raise ValueError(f"{log_path} already exists and is the only undo record for that run.")

    supabase = get_supabase(require_service_role=execute)
    print(f"=== Repair swapped club names: replay {snapshot_path} ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
    approved = [r for r in rows if is_approved(r)]
    ids = [r["team_id_master"] for r in approved if _UUID.match(r["team_id_master"] or "")]
    entries = plan_replay(approved, fetch_current(supabase, ids))

    # The log lands before the first write and again after the last, so a run that
    # dies mid-loop still leaves every applied row on disk.
    write_log([log_row(e, run_mode) for e in entries], log_path)
    try:
        run_replay(supabase, entries, execute)
    finally:
        if execute:
            # The write in flight when a run dies stays ``updated``: it may have landed,
            # and the undo's compare-and-set leaves it alone if it did not.
            for e in entries:
                if e["action"] == "updated" and not e.get("attempted"):
                    e["action"] = "not_attempted"
        try:
            write_log([log_row(e, run_mode) for e in entries], log_path)
        except OSError as e:
            # Never let the rewrite mask an in-flight exception or destroy the copy
            # already on disk; on Windows this fails while the CSV is open in Excel.
            print(f"\nCould not rewrite {log_path}: {e}")
            print(f"The pre-write copy stands; the updated rows are in {log_path}.tmp if it survived.")

    counts = Counter(e["action"] for e in entries)
    print(f"\nSnapshot rows: {len(rows)}; approved: {len(entries)}")
    for action in sorted(counts):
        print(f"{action}: {counts[action]}")
    if entries:
        print(f"Log: {log_path}")
    if execute and counts.get("updated"):
        print(f"Undo with: python scripts/repair_swapped_club_names.py --revert {log_path} --execute")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--execute",
        nargs="?",
        const=True,
        default=None,
        metavar="SNAPSHOT",
        help="Write the approved rows of a dry run's snapshot; with --revert, apply the undo (bare flag)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument(
        "--league-url",
        action="append",
        help="PlayMetrics league to read clubs from; repeatable (default: the two imported leagues)",
    )
    parser.add_argument(
        "--abbreviation-run",
        action="append",
        help="Run id of update-missing-club-and-state.yml whose log to read; repeatable "
        f"(default: {', '.join(DEFAULT_ABBREVIATION_RUNS)})",
    )
    parser.add_argument("--revert", type=Path, help="Undo a previous --execute from its CSV log")
    args = parser.parse_args()
    execute = resolve_execute(args.execute is not None, args.dry_run)

    if args.revert:
        if isinstance(args.execute, str):
            parser.error("--revert takes --execute on its own, without a snapshot")
        load_env()
        supabase = get_supabase(require_service_role=execute)
        print(f"=== Revert {args.revert} ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
        try:
            counts = revert(supabase, args.revert, execute)
        except ValueError as e:
            parser.error(str(e))
        print(f"\n{'Reverted' if execute else 'Would revert'}: {counts['reverted']}")
        for name in ("refused_changed", "refused_shape"):
            if counts[name]:
                print(f"{name}: {counts[name]}")
        return 0

    if args.execute is True:
        parser.error("--execute needs the snapshot the dry run wrote")
    if args.execute is not None:
        snapshot_path = Path(args.execute)
        if not snapshot_path.exists():
            parser.error(f"{snapshot_path} does not exist. Run the dry run first and review its snapshot.")
        load_env()
        try:
            return replay_snapshot(snapshot_path, execute)
        except ValueError as e:
            parser.error(str(e))

    run_ids = args.abbreviation_run or list(DEFAULT_ABBREVIATION_RUNS)
    try:
        leagues = parse_league_urls(args.league_url or DEFAULT_LEAGUE_URLS)
        validate_run_ids(run_ids)
    except ValueError as e:
        parser.error(str(e))
    snapshot_path = EXPORTS_DIR / f"repair_swapped_club_names_{timestamp()}.csv"
    if snapshot_path.exists():
        parser.error(f"{snapshot_path} already exists and may hold a reviewed list. Re-run in a moment.")

    load_env()
    supabase = get_supabase()
    print("=== Repair swapped club names (DRY-RUN) ===")
    clubs = fetch_playmetrics_clubs(leagues)
    print(f"PlayMetrics teams listed by {len(leagues)} league(s): {len(clubs)}")
    logs = [read_run_log(run_id) for run_id in run_ids]
    rows, stats = build_snapshot(supabase, clubs, logs)

    write_log([snapshot_csv_row(r) for r in rows], snapshot_path)
    print_summary(rows, stats)
    if not rows:
        print("\nNothing to repair; no snapshot written.")
        return 0
    print(f"\nDRY RUN -- nothing written to the database. Snapshot: {snapshot_path}")
    print("Set approved to true on any listed row you accept, then re-run with:")
    print(f"  python scripts/repair_swapped_club_names.py --execute {snapshot_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
