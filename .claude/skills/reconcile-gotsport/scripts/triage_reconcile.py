#!/usr/bin/env python3
"""
Sort the teams a GotSport reconcile run flagged into gender_fix, reused_id, relabel and hold.

Reads one or more reconcile_teams_with_gotsport logs and examines every team whose live
age or gender differs from GotSport's. For each it reads the schedule on both sides of
this season's Aug 1 start, reads each opponent's age from a two-year band in the
opponent's own name where there is one (season-proof) and from the opponent's stored
column otherwise, reads gender from team names, and compares the squad word in our name
with the one in GotSport's name.

Read-only: writes a triage CSV, two age plans in scripts/fix_band_cohorts.py's format
and a gender plan in the bundled apply_team_fields.py's format to data/exports, and
nothing to the database.

Classes:
  gender_fix  GotSport's gender differs from ours, our own name or the names of the
              teams it played agree with GotSport, and neither backs ours. The age is
              judged on the next run.
  reused_id   GotSport's name names another squad, last season's opponents sit at our
              stored age and this season's at GotSport's. The record was handed to
              another squad, younger or older; the old games belong to the old squad's
              new GotSport id.
  relabel     A squad word shared by both names, and this season's opponents sit at
              GotSport's age. Only our age label is wrong. Last season's opponents look
              the same as for a reused record -- a squad that stayed in its group two
              seasons running shows the same drop -- so the squad word decides.
  hold        Anything else; the reason says which.

Usage:
    python .claude/skills/reconcile-gotsport/scripts/triage_reconcile.py --log data/exports/<log>.csv
    python .claude/skills/reconcile-gotsport/scripts/triage_reconcile.py --log <log> <log> --probe-gotsport
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_team_fields import PLAN_COLUMNS as FIELD_PLAN_COLUMNS  # noqa: E402
from apply_team_fields import write_rows as write_field_plan  # noqa: E402

from scripts.fix_band_cohorts import (  # noqa: E402
    PLAN_FIELDS,
    band_of,
    csv_safe,
    csv_unsafe,
    get_supabase,
    load_env,
    norm_name,
    read_csv,
    single_band,
)
from scripts.fix_band_cohorts import write_csv as write_age_plan  # noqa: E402
from scripts.fix_gender_from_registered_name import any_gender, spelled_gender  # noqa: E402
from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.team_name_utils import _UAGE_TOKEN, birth_years  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
OWNER_DECISIONS = ROOT / ".claude" / "skills" / "correcting-team-age-groups" / "scripts" / "owner_decisions.json"
IN_BATCH = 100
PAGE = 1000
# Fewer fall games with a readable opponent age than this cannot show which cohort a
# squad plays in; the 2026-09-17 audit held exactly these teams as "thin".
MIN_FALL_GAMES = 3
# A team still on its old record plays opponents within half a group of one cohort.
NEAR = 0.5
# Probing ids beside a reused record finds the old squad when the club registered
# its squads in one batch (Bala FC: 614082 reused, old squad on 614084).
ADJACENT_SPAN = 3
GOTSPORT_DELAY = 3.0
# Consecutive failed lookups that mean GotSport's WAF is blocking, not 404s.
MAX_PROBE_FAILURES = 3

_WORD = re.compile(r"[a-z]+")
# Words that name a club's tier, region or format rather than one squad. Compass
# words matter most: "RSL Arizona South" squads all carry "south".
_NOISE = frozenset(
    "boys girls boy girl soccer club academy pre ecnl npl elite premier select the and "
    "north south east west central valley mls next team".split()
)

TRIAGE_FIELDS = (
    "class reason team_id_master provider_team_id team_name team_name_original gotsport_team_name "
    "club_name gender gotsport_gender name_gender opponent_name_gender opponent_gender_votes "
    "state_code stored_age_group gotsport_age_group same_squad our_squad_words gotsport_squad_words "
    "stated_birth_years own_band games_last_season opp_age_last_season games_this_season "
    "opp_age_this_season fixture_verdict opp_games_proposed opp_games_current collision_with "
    "adjacent_gotsport"
).split()


def group_number(age_group: Optional[str]) -> Optional[int]:
    """Group number, with U18 folded into U19: PitchRank files U18 teams as u19."""
    norm = normalize_age_group(age_group)
    m = re.fullmatch(r"u([0-9]{1,2})", norm or "")
    if not m:
        return None
    n = int(m.group(1))
    return 19 if n == 18 else n


def squad_words(name: Optional[str], club: Optional[str]) -> set:
    """Words left in a team name once club, ages, years, gender and tier words are removed.

    Words of two letters or fewer go too: they are gender affixes and state codes.
    """
    text = _UAGE_TOKEN.sub(" ", (name or "").lower())
    text = re.sub(r"[0-9]+", " ", text)
    club_words = set(_WORD.findall((club or "").lower()))
    return {w for w in _WORD.findall(text) if len(w) > 2 and w not in _NOISE and w not in club_words}


def opponent_age(name: str, column: Optional[str]) -> Tuple[Optional[int], str]:
    """(age number, source) for one opponent: its own band first, its column otherwise."""
    band = group_number(band_of(name))
    if band:
        return band, "band"
    n = group_number(column)
    return (n, "column") if n else (None, "")


def cohort_years(age: int, season: Optional[int] = None) -> set:
    """Birth years a cohort holds this season; u19 also holds the U18 band filed into it."""
    younger = (season or _soccer_season_year()) - age + 1
    years = {younger, younger - 1}
    return years | {younger + 1} if age == 19 else years


def majority_gender(names: Iterable[Optional[str]]) -> Tuple[str, Counter]:
    """Gender a strict majority of the names state, one vote per name, and the tally.

    A tie returns "" -- most_common breaks ties by insertion order, so an even split would
    otherwise read as agreement (as scripts/fix_gender_from_registered_name.py notes).
    """
    votes = Counter(g for g in (any_gender(n) for n in names) if g)
    if not votes:
        return "", votes
    top, n = votes.most_common(1)[0]
    return (top if n * 2 > sum(votes.values()) else ""), votes


def fixture_verdict(opp_bands: List[Optional[str]], new: str, old: str) -> Tuple[str, int, int]:
    """scripts/fix_band_cohorts.py's verdict over this season's games' opponent bands."""
    proposed = sum(1 for b in opp_bands if b == new)
    current = sum(1 for b in opp_bands if b == normalize_age_group(old))
    if proposed + current < 2:
        return "thin", proposed, current
    if proposed >= 3 * current:
        return "backs_move", proposed, current
    if current >= 3 * proposed:
        return "backs_current", proposed, current
    return "mixed", proposed, current


def classify(
    stored: int,
    theirs: int,
    same_squad: Optional[bool],
    pre: Optional[float],
    fall: Optional[float],
    fall_games: int,
    fall_read: int,
    band: Optional[int] = None,
) -> Tuple[str, str]:
    """Age class. ``fall_games`` counts every game since Aug 1; ``fall_read`` those whose
    opponent's age could be read, which is what ``fall`` is the median of."""
    # Owner, 2026-10-09: no games since Aug 1 means we are right and the team is most
    # likely dormant.
    if fall_games == 0:
        return "hold", "no games since Aug 1; likely dormant, stored age kept"
    # A band in our own name decides, even for a team that plays up (owner, 2026-09-18).
    if band is not None and band == stored:
        return "hold", "the band in our own name backs the stored age"
    if band is not None and band != theirs:
        return "hold", f"the band in our own name says U{band}, neither ours nor GotSport's"
    if fall_read < MIN_FALL_GAMES or fall is None:
        return "hold", f"only {fall_read} game(s) this season with a readable opponent age"
    if abs(fall - stored) <= NEAR:
        return "hold", "this season's opponents back the stored age"
    if abs(fall - theirs) > NEAR:
        return "hold", f"this season's opponents sit at U{fall}, neither ours nor GotSport's"
    if same_squad is False and pre is not None and abs(pre - stored) <= NEAR:
        return "reused_id", "GotSport's name is another squad; opponents dropped a group at Aug 1"
    if same_squad is False:
        return "hold", "GotSport's name is another squad but last season does not show the old cohort"
    if same_squad is None:
        return "hold", "a name carries no squad word to compare; decide from the club's other teams"
    return "relabel", "same squad; this season's opponents sit at GotSport's age"


def classify_gender(
    ours: str,
    theirs: str,
    spelled: str,
    affix: str,
    opponents: str,
    seasons_split: bool,
    fall_games: int,
) -> Tuple[str, str]:
    """GotSport's gender plus at least one independent witness, and no witness against it.

    The witnesses are our own team name and the names of the teams it played. A name
    counts alone only when it spells "Boys" or "Girls"; a lone B/G affix in it (14B, U10G)
    counts only beside opponents saying the same, since a single letter can be a colour or
    a squad code. Opponents read their B/G affixes too, as
    scripts/fix_gender_from_registered_name.py does.
    """
    name = spelled or (affix if affix and affix in (opponents, ours) else "")
    witnesses = {"our name": name, "opponents' names": opponents}
    against = [w for w, g in witnesses.items() if g == ours]
    if against:
        return "hold", f"GotSport's gender differs from ours, but {' and '.join(against)} back ours"
    if seasons_split:
        return "hold", "opponents' names point one way last season and the other this season; the record may be reused"
    # Owner, 2026-10-09: of the fixes resting on opponents alone, only active teams were
    # changed; the dormant ones were left as stored.
    if name != theirs and fall_games == 0:
        return "hold", "GotSport's gender rests on opponents alone and no games since Aug 1; likely dormant"
    backing = [w for w, g in witnesses.items() if g == theirs]
    if backing:
        return "gender_fix", "GotSport's gender, backed by " + " and ".join(backing)
    return "hold", "GotSport's gender differs from ours, and neither our name nor opponents' names say which"


def latest_rows(logs: List[Path]) -> List[Dict]:
    """Last row per team across the logs, in the order given; values unescaped."""
    latest: Dict[str, Dict] = {}
    for log in logs:
        for row in read_csv(log):
            latest[row["team_id_master"]] = {k: csv_unsafe(v) for k, v in row.items()}
    return list(latest.values())


def kept_as_stored() -> set:
    """Teams the owner already decided to leave at their stored age."""
    try:
        data = json.loads(OWNER_DECISIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {t["team_id"] for t in data.get("kept_as_stored", {}).get("teams", []) if t.get("team_id")}


def fetch_in(sb, table: str, cols: str, column: str, values: List[str]) -> List[Dict]:
    out: List[Dict] = []
    for i in range(0, len(values), IN_BATCH):
        out.extend(sb.table(table).select(cols).in_(column, values[i : i + IN_BATCH]).execute().data or [])
    return out


def fetch_games(sb, ids: List[str], since: str) -> List[Dict]:
    clause = ",".join(f"home_team_master_id.eq.{i},away_team_master_id.eq.{i}" for i in ids)
    rows: List[Dict] = []
    offset = 0
    while True:
        batch = (
            sb.table("games")
            .select("id,game_date,home_team_master_id,away_team_master_id")
            .or_(clause)
            .gte("game_date", since)
            .eq("is_excluded", False)
            .order("id")
            .range(offset, offset + PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def fetch_cohort_names(sb, state: str, age_group: str, gender: str) -> Dict[str, List[str]]:
    """Normalised name -> team ids for one live cohort, for the collision check."""
    out: Dict[str, List[str]] = defaultdict(list)
    offset = 0
    while True:
        query = (
            sb.table("teams")
            .select("team_id_master,team_name")
            .eq("is_deprecated", False)
            .eq("age_group", age_group)
            .eq("gender", gender)
        )
        query = query.eq("state_code", state) if state else query.is_("state_code", "null")
        batch = query.order("team_id_master").range(offset, offset + PAGE - 1).execute().data or []
        for t in batch:
            out[norm_name(t["team_name"])].append(t["team_id_master"])
        if len(batch) < PAGE:
            return out
        offset += PAGE


def summarize(ages: List[int]) -> Optional[float]:
    return round(statistics.median(ages), 1) if ages else None


def other_side(game: Dict, ids: List[str]) -> Optional[str]:
    return game["away_team_master_id"] if game["home_team_master_id"] in ids else game["home_team_master_id"]


def assess(sb, row: Dict, team: Dict, ids: List[str], season_start: str, since: str, declined: set) -> Optional[Dict]:
    """One triage row for one flagged team, or None when the live values already agree."""
    tid = team["team_id_master"]
    stored, theirs = group_number(team["age_group"]), group_number(row["gotsport_age_group"])
    gs_gender = row.get("gotsport_gender") or ""
    # The live values, not the logged ones: a team corrected since the run is settled.
    gender_differs = bool(gs_gender and team.get("gender")) and gs_gender != team["gender"]
    if stored is None or theirs is None or (stored == theirs and not gender_differs):
        return None
    if not gender_differs and tid in declined:
        return None

    games = fetch_games(sb, ids, since)
    opp_cols = "team_id_master,team_name,team_name_original,age_group"
    opp_ids = list({other_side(g, ids) for g in games} - {None})
    opps = {t["team_id_master"]: t for t in fetch_in(sb, "teams", opp_cols, "team_id_master", opp_ids)}

    pre, fall, fall_bands = [], [], []
    pre_opps, fall_opps = set(), set()
    fall_games = 0
    for g in games:
        is_fall = g["game_date"] >= season_start
        fall_games += is_fall
        opp = opps.get(other_side(g, ids))
        if not opp:
            continue
        (fall_opps if is_fall else pre_opps).add(opp["team_id_master"])
        n, _ = opponent_age(opp.get("team_name") or "", opp.get("age_group"))
        if is_fall:
            fall_bands.append(band_of(opp.get("team_name")))
        if n is not None:
            (fall if is_fall else pre).append(n)

    def opp_name(o: str) -> Optional[str]:
        return opps[o].get("team_name_original") or opps[o].get("team_name")

    # One vote per distinct opponent, read from its name: the stored gender column of a
    # mislabelled batch confirms its own error. This season's opponents describe the squad
    # now on the record; when last season's point the other way, the record changed hands.
    fall_gender, fall_votes = majority_gender(opp_name(o) for o in fall_opps)
    pre_gender, pre_votes = majority_gender(opp_name(o) for o in pre_opps)
    opp_gender = fall_gender if fall_opps else pre_gender
    seasons_split = bool(fall_gender and pre_gender and fall_gender != pre_gender)

    our_name = team.get("team_name_original") or team["team_name"]
    spelled = spelled_gender(our_name) or ""
    affix = any_gender(our_name) or ""

    ours_words = squad_words(our_name, team.get("club_name"))
    gs_words = squad_words(row.get("gotsport_team_name"), row.get("gotsport_club_name") or team.get("club_name"))
    same_squad = None if not ours_words or not gs_words else bool(ours_words & gs_words)
    # A shared word can be a colour; a birth year in our own name that GotSport's
    # cohort cannot hold says the record now carries another squad
    # (Brazas FC 2016 Black is now "Brazas FC 2012/2013 Girls Black").
    stated = birth_years(team["team_name"]) | birth_years(team.get("team_name_original"))
    if stated and not stated & cohort_years(theirs):
        same_squad = False
    band = group_number(single_band(team["team_name"], team.get("team_name_original")))

    pre_med, fall_med = summarize(pre), summarize(fall)
    verdict, proposed, current = fixture_verdict(fall_bands, f"u{theirs}", team["age_group"])
    if gender_differs:
        # The age is judged on the next run, once the team sits on the right board.
        cls, reason = classify_gender(team["gender"], gs_gender, spelled, affix, opp_gender, seasons_split, fall_games)
    else:
        cls, reason = classify(stored, theirs, same_squad, pre_med, fall_med, fall_games, len(fall), band)

    votes = fall_votes if fall_opps else pre_votes
    return {
        "class": cls,
        "reason": reason,
        "team_id_master": tid,
        "provider_team_id": row.get("provider_team_id") or team.get("provider_team_id") or "",
        "team_name": team["team_name"],
        "team_name_original": team.get("team_name_original") or "",
        "gotsport_team_name": row.get("gotsport_team_name") or "",
        "club_name": team.get("club_name") or "",
        "gender": team.get("gender") or "",
        "gotsport_gender": gs_gender,
        "name_gender": spelled or (f"{affix} (affix)" if affix else ""),
        "opponent_name_gender": opp_gender,
        "opponent_gender_votes": " ".join(f"{k}:{v}" for k, v in sorted(votes.items())),
        "state_code": team.get("state_code") or "",
        "stored_age_group": team["age_group"],
        "gotsport_age_group": f"u{theirs}",
        "same_squad": "" if same_squad is None else str(same_squad),
        "our_squad_words": " ".join(sorted(ours_words)),
        "gotsport_squad_words": " ".join(sorted(gs_words)),
        "stated_birth_years": " ".join(str(y) for y in sorted(stated)),
        "own_band": f"u{band}" if band else "",
        "games_last_season": len(pre),
        "opp_age_last_season": "" if pre_med is None else pre_med,
        "games_this_season": fall_games,
        "opp_age_this_season": "" if fall_med is None else fall_med,
        "fixture_verdict": verdict,
        "opp_games_proposed": proposed,
        "opp_games_current": current,
        "collision_with": "",
        "adjacent_gotsport": "",
    }


def mark_collisions(sb, out: List[Dict]) -> None:
    """Hold a move into a cohort that already holds a same-named team.

    That is usually a duplicate pair split by the mislabel; relabelling into it needs the
    merge workflow, not this one.
    """
    cohorts: Dict[tuple, Dict[str, List[str]]] = {}
    for r in out:
        if r["class"] not in ("relabel", "reused_id"):
            continue
        key = (r["state_code"], r["gotsport_age_group"], r["gender"])
        if key not in cohorts:
            cohorts[key] = fetch_cohort_names(sb, *key)
        others = [t for t in cohorts[key].get(norm_name(r["team_name"]), []) if t != r["team_id_master"]]
        if others:
            r["collision_with"] = ";".join(sorted(others)[:3])
            r["class"], r["reason"] = "hold", "a same-named team already sits in GotSport's cohort"


def probe_adjacent(resolver, pid: str, ours_by_pid: Dict[str, str], failures: List[int]) -> str:
    """GotSport's current name and age for the ids beside ``pid``, and our row for each.

    ``failures`` carries the consecutive-failure count across calls; probing stops once it
    reaches MAX_PROBE_FAILURES. The resolver caches a 404 as ``{}`` but also caches any
    parsed 200, including the empty-name body a WAF interstitial returns, so only a cached
    ``{}`` is a missing record.
    """
    if not pid.isdigit():
        return ""
    found = []
    for n in range(int(pid) - ADJACENT_SPAN, int(pid) + ADJACENT_SPAN + 1):
        key = str(n)
        if key == pid:
            continue
        if failures[0] >= MAX_PROBE_FAILURES:
            found.append(f"{key}=? (stopped: GotSport lookups failing)")
            continue
        details = resolver.resolve(key)
        time.sleep(GOTSPORT_DELAY)
        if not details or not details.get("name"):
            if resolver.cache.get(key) != {}:
                failures[0] += 1
                found.append(f"{key}=? (lookup failed)")
            continue
        failures[0] = 0
        label = f"{key}={details['name']} [{(details.get('age_group') or '?').upper()}]"
        found.append(f"{label} ours:{ours_by_pid.get(key, 'none')}")
    return " | ".join(found)


def our_rows_for_gotsport_ids(sb, pids: List[str]) -> Dict[str, str]:
    """GotSport id -> our team name, through approved aliases and the teams column."""
    providers = sb.table("providers").select("id").eq("code", "gotsport").limit(1).execute().data or []
    if not providers or not pids:
        return {}
    gotsport = providers[0]["id"]
    owner: Dict[str, str] = {}
    alias_cols = "provider_team_id,team_id_master,provider_id,review_status"
    for a in fetch_in(sb, "team_alias_map", alias_cols, "provider_team_id", pids):
        if a["provider_id"] == gotsport and a.get("review_status") == "approved":
            owner[a["provider_team_id"]] = a["team_id_master"]
    for t in fetch_in(sb, "teams", "team_id_master,provider_team_id,provider_id", "provider_team_id", pids):
        if t["provider_id"] == gotsport:
            owner.setdefault(t["provider_team_id"], t["team_id_master"])
    owners = list(set(owner.values()))
    names = {
        t["team_id_master"]: t["team_name"]
        for t in fetch_in(sb, "teams", "team_id_master,team_name", "team_id_master", owners)
    }
    return {pid: names.get(tid, tid) for pid, tid in owner.items()}


def write_triage(rows: List[Dict], path: Path) -> None:
    """The triage CSV, every text value escaped: names and GotSport replies are provider text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRIAGE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: csv_safe(v) if isinstance(v, str) else v for k, v in r.items()} for r in rows)


def write_plans(out: List[Dict], stamp: str) -> Dict[str, Tuple[Path, int]]:
    def age_plan_row(r: Dict) -> Dict:
        return {
            "state_code": r["state_code"],
            "team_id_master": r["team_id_master"],
            "team_name": r["team_name"],
            "club_name": r["club_name"],
            "gender": r["gender"],
            "gotsport_team_name": r["gotsport_team_name"],
            "band": r["own_band"],
            "old_age_group": r["stored_age_group"],
            "new_age_group": r["gotsport_age_group"],
            # A reused record is relabelled only once its old games have moved, so its
            # rows start un-applyable; Step 6 flips each to would_update after its split.
            "action": "would_update" if r["class"] == "relabel" else "pending_split",
            "collision_with": "",
            "evidence_tier": f"R_{r['class']}",
            "fixture_verdict": r["fixture_verdict"],
            "opp_games_proposed": r["opp_games_proposed"],
            "opp_games_current": r["opp_games_current"],
        }

    plans: Dict[str, Tuple[Path, int]] = {}
    for cls in ("relabel", "reused_id"):
        rows = [age_plan_row(r) for r in out if r["class"] == cls]
        path = EXPORTS / f"reconcile_triage_{cls}_age_plan_{stamp}.csv"
        write_age_plan(rows, path, PLAN_FIELDS)
        plans[cls] = (path, len(rows))

    genders = [
        {
            "team_id_master": r["team_id_master"],
            "team_name": r["team_name"],
            "field": "gender",
            "old_value": r["gender"],
            "new_value": r["gotsport_gender"],
        }
        for r in out
        if r["class"] == "gender_fix"
    ]
    path = EXPORTS / f"reconcile_triage_gender_plan_{stamp}.csv"
    write_field_plan(genders, path, list(FIELD_PLAN_COLUMNS))
    plans["gender"] = (path, len(genders))
    return plans


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--log",
        type=Path,
        nargs="+",
        required=True,
        help="reconcile_teams_with_gotsport_*.csv logs; a later log wins for a team in several",
    )
    parser.add_argument(
        "--probe-gotsport",
        action="store_true",
        help=f"For reused_id rows, read GotSport ids within {ADJACENT_SPAN} of the record to find the old squad",
    )
    args = parser.parse_args()

    load_env()
    sb = get_supabase()
    declined = kept_as_stored()

    flagged = []
    for row in latest_rows(args.log):
        ours, theirs = group_number(row.get("stored_age_group")), group_number(row.get("gotsport_age_group"))
        ages_differ = bool(ours and theirs and ours != theirs) and row["team_id_master"] not in declined
        genders_differ = bool(row.get("gotsport_gender") and row.get("stored_gender")) and (
            row["gotsport_gender"] != row["stored_gender"]
        )
        if ages_differ or genders_differ:
            flagged.append(row)
    print(f"{len(flagged)} teams where GotSport's age or gender differs from ours")

    team_ids = [r["team_id_master"] for r in flagged]
    team_cols = (
        "team_id_master,team_name,team_name_original,club_name,age_group,gender,state_code,"
        "provider_team_id,is_deprecated"
    )
    teams = {t["team_id_master"]: t for t in fetch_in(sb, "teams", team_cols, "team_id_master", team_ids)}
    merged: Dict[str, List[str]] = {}
    for m in fetch_in(sb, "team_merge_map", "deprecated_team_id,canonical_team_id", "canonical_team_id", team_ids):
        merged.setdefault(m["canonical_team_id"], []).append(m["deprecated_team_id"])

    season_start = date(_soccer_season_year(), 8, 1).isoformat()
    since = (date.fromisoformat(season_start) - timedelta(days=365)).isoformat()

    out: List[Dict] = []
    for row in flagged:
        team = teams.get(row["team_id_master"])
        if not team or team.get("is_deprecated"):
            continue
        ids = [team["team_id_master"], *merged.get(team["team_id_master"], [])]
        assessed = assess(sb, row, team, ids, season_start, since, declined)
        if assessed:
            out.append(assessed)

    mark_collisions(sb, out)

    reused = [r for r in out if r["class"] == "reused_id"]
    if args.probe_gotsport and reused:
        from src.utils.gotsport_team_details import TeamDetailsResolver

        centres = [int(r["provider_team_id"]) for r in reused if r["provider_team_id"].isdigit()]
        pids = sorted({str(n) for c in centres for n in range(c - ADJACENT_SPAN, c + ADJACENT_SPAN + 1)})
        ours_by_pid = our_rows_for_gotsport_ids(sb, pids)
        resolver, failures = TeamDetailsResolver(), [0]
        print(f"Probing GotSport around {len(reused)} reused record(s), {GOTSPORT_DELAY}s per call ...")
        for r in reused:
            r["adjacent_gotsport"] = probe_adjacent(resolver, r["provider_team_id"], ours_by_pid, failures)

    order = {"gender_fix": 0, "reused_id": 1, "relabel": 2, "hold": 3}
    out.sort(key=lambda r: (order[r["class"]], r["club_name"], r["team_name"]))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    triage_path = EXPORTS / f"reconcile_triage_{stamp}.csv"
    write_triage(out, triage_path)
    plans = write_plans(out, stamp)

    print("\n=== Triage ===")
    for cls in order:
        print(f"  {cls:10s} {sum(1 for r in out if r['class'] == cls):>5}")
    print(f"\nTriage: {triage_path}")
    for name, (path, n) in plans.items():
        print(f"Plan ({name}, {n} rows): {path}")


if __name__ == "__main__":
    main()
