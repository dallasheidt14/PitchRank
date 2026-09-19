#!/usr/bin/env python3
"""Review stored age groups against the label key in CLAUDE.md. Read-only.

Two modes:

  review       Read every live team in scope (all states, or --state), read its own name by the
               key, gather this season's season-proof evidence, and write one CSV row per team
               whose name disagrees with its stored age group. Nothing is written to the database.

  write-plan   Turn chosen groups of a review CSV into a plan for
               data/exports/fix_band_cohorts.py --apply.

Usage:
    python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py review [--state AZ,NC]
    python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py write-plan REVIEW.csv --groups 1,2,3

--exports-dir defaults to <repo>/data/exports and must hold the reconcile_teams_with_gotsport_*.csv
and fix_band_cohorts_apply_*.csv logs; point it at the main checkout's when running from a worktree.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.append(str(REPO))

# The chart in CLAUDE.md for the 2026-27 season, keyed by a band's YOUNGER year. U18 files into u19.
# Literal on purpose: the owner's key is a lookup, not arithmetic. Replace it from CLAUDE.md's table
# at every Aug 1 rollover; review() refuses to run while CHART_SEASON is not the current season.
CHART = {2020: "u7", 2019: "u8", 2018: "u9", 2017: "u10", 2016: "u11", 2015: "u12", 2014: "u13",
         2013: "u14", 2012: "u15", 2011: "u16", 2010: "u17", 2009: "u19", 2008: "u19"}
CHART_SEASON = 2026
YOUNGEST_YEAR, OLDEST_BAND_YEAR = max(CHART), min(CHART)
# The older year of the top band fits only that band; anything older has aged out.
OLDEST_YEAR = OLDEST_BAND_YEAR - 1
# A single birth year sits in two bands: as the younger year and as the older year.
YEAR_FITS = {y: {CHART.get(y), CHART.get(y + 1)} - {None} for y in range(OLDEST_BAND_YEAR, YOUNGEST_YEAR + 1)}
YEAR_FITS[OLDEST_YEAR] = {CHART[OLDEST_BAND_YEAR]}
# Groups in age order; u18 does not exist, so u17 and u19 are neighbours.
ORDER = sorted(set(CHART.values()), key=lambda g: int(g[1:]))

US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
# Teams the owner decided to leave as stored; the review never proposes them. Add to the file,
# with the date and the owner's answer, whenever the owner declines a team or a held group.
OWNER_DECISIONS = Path(__file__).with_name("owner_decisions.json")
OWNER_LEFT = {
    t["team_id"]
    for section in json.loads(OWNER_DECISIONS.read_text(encoding="utf-8")).values()
    for t in section["teams"]
}
SEASON_START = f"{CHART_SEASON}-08-01"
SIDES = (("home_team_master_id", "away_team_master_id"), ("away_team_master_id", "home_team_master_id"))
TOKEN_SPLIT = re.compile(r"[\s\-_/|(),.\[\]']+")
# "U-14" is one U-label; join it before the split turns it into "U" and a bare "14".
HYPHEN_ULABEL = re.compile(r"(?i)(?<![a-z0-9])([bg]?u)-([0-9]{1,2})(?![0-9])")
# A birth year standing alone in a name, in any spelling the leagues use: "2013", "13", "'13".
# Read only to date a U-label, never to pick a group, so a squad number read as a year costs a
# held row rather than a wrong one.
NAME_YEAR = re.compile(r"(?<![0-9A-Za-z])'?((?:20)?[0-2][0-9])(?![0-9A-Za-z])")
# "B10-12", "06/07/08": a multi-year squad, which a single-year reading gets wrong.
YEAR_RANGE = re.compile(r"(?<![0-9])(?:20)?[0-2][0-9]\s*[-/]\s*(?:20)?[0-2][0-9](?![0-9])")
GROUPS = {
    "band_older_by_1": "1",
    "band_younger": "2",
    "band_off_2plus": "2",
    "band_aged_out": "2",
    "ulabel_confirmed": "3",
    "ulabel_plays_up": "5",
    "year_outside": "4",
}
PLAN_FIELDS = [
    "state_code", "team_id_master", "team_name", "club_name", "gender", "gotsport_team_name", "band",
    "old_age_group", "new_age_group", "action", "collision_with", "evidence_tier", "fixture_verdict",
    "opp_games_proposed", "opp_games_current",
]


def num(label: str | None) -> int | None:
    m = re.match(r"^u([0-9]{1,2})$", label or "")
    return int(m.group(1)) if m else None


def between(a: str, b: str) -> set[str]:
    """Groups strictly between a and b in age order."""
    if a not in ORDER or b not in ORDER:
        return set()
    i, j = sorted((ORDER.index(a), ORDER.index(b)))
    return set(ORDER[i + 1:j])


def norm_name(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def log(t0: float, *parts) -> None:
    print(f"[{time.time() - t0:5.0f}s]", *parts, flush=True)


class Reader:
    """The key applied to a name, using the repo's own band and token readers."""

    def __init__(self) -> None:
        try:
            from scripts.team_name_normalizer import parse_age_gender
            from src.utils.team_utils import _soccer_season_year, extract_band_birth_year
        except ImportError as e:
            raise SystemExit(
                f"{e}. This needs origin/main's src/utils/team_utils.extract_band_birth_year; "
                "run it from a checkout synced to origin/main (a worktree is fine, with --exports-dir)."
            )
        if _soccer_season_year() != CHART_SEASON:
            raise SystemExit(
                f"CHART is the {CHART_SEASON}-{CHART_SEASON + 1 - 2000} chart but the season is now "
                f"{_soccer_season_year()}. Replace CHART and CHART_SEASON from CLAUDE.md's Age Groups table."
            )
        self._band_year = extract_band_birth_year
        self._parse = parse_age_gender
        self._cache: dict[str, str | None] = {}

    def band(self, name: str | None) -> str | None:
        y = self._band_year(name or "")
        if y is None:
            return None
        if y in CHART:
            return CHART[y]
        return f"u{CHART_SEASON - y + 1}" if y < OLDEST_BAND_YEAR else None  # aged out: u20, u21, ...

    def _token(self, tok: str) -> str | None:
        if tok not in self._cache:
            try:
                self._cache[tok] = self._parse(tok)[0]
            except Exception:
                self._cache[tok] = None
        return self._cache[tok]

    def labels(self, name: str | None) -> tuple[set[str], set[int]]:
        """U-labels (as cohorts) and single birth years the name states."""
        ulabels, years = set(), set()
        for tok in TOKEN_SPLIT.split(HYPHEN_ULABEL.sub(r"\1\2", name or "")):
            if not tok or (tok.isdigit() and len(tok) <= 2):
                continue  # a bare number is a squad number, not an age
            age = self._token(tok)
            if not age:
                continue
            if age.startswith("U") and age[1:].isdigit() and 6 <= int(age[1:]) <= 19:
                ulabels.add("u19" if age == "U18" else "u" + age[1:])
            elif age.isdigit() and OLDEST_YEAR - 2 <= int(age) <= YOUNGEST_YEAR:
                years.add(int(age))
        return ulabels, years

    def single_year(self, name: str | None) -> int | None:
        if not name or self.band(name):
            return None
        _, years = self.labels(name)
        return years.pop() if len(years) == 1 else None

    def label_age(self, name: str | None) -> str | None:
        b = self.band(name)
        if b:
            return b
        ul, _ = self.labels(name)
        return ul.pop() if len(ul) == 1 else None


def fetch_all(sb, table: str, select: str, **eq) -> list[dict]:
    rows, last = [], None
    while True:
        q = sb.table(table).select(select)
        for k, v in eq.items():
            q = q.eq(k, v)
        if last:
            q = q.gt("team_id_master", last)
        page = q.order("team_id_master").limit(1000).execute().data
        rows += page
        if len(page) < 1000:
            return rows
        last = page[-1]["team_id_master"]


def with_merge_survivors(sb, ids: set[str]) -> set[str]:
    """ids plus every canonical row they were merged into, following merge chains."""
    out, frontier = set(ids), list(ids)
    while frontier:
        found = []
        for i in range(0, len(frontier), 100):
            rows = (sb.table("team_merge_map").select("canonical_team_id")
                    .in_("deprecated_team_id", frontier[i:i + 100]).execute().data)
            found += [r["canonical_team_id"] for r in rows if r["canonical_team_id"] not in out]
        out.update(found)
        frontier = found
    return out


def retry(call):
    for attempt in range(4):
        try:
            return call()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3)


def review(args) -> None:
    from dotenv import load_dotenv

    from supabase import create_client

    exports = Path(args.exports_dir)
    for root in (REPO, exports.parent.parent):
        load_dotenv(root / ".env")
        load_dotenv(root / ".env.local", override=True)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    reader = Reader()
    t0 = time.time()
    states = {s.strip().upper() for s in args.state.split(",")} if args.state else US_STATES

    teams = fetch_all(sb, "teams", "team_id_master,team_name,club_name,age_group,gender,provider_id,state_code",
                      is_deprecated=False)
    log(t0, "live teams", len(teams))
    prov = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    excluded = {r["team_id_master"] for r in fetch_all(sb, "team_ranking_exclusions", "team_id_master")}
    # A listed team merged away later is the surviving row now; skip the survivor too.
    excluded, owner_left = with_merge_survivors(sb, excluded), with_merge_survivors(sb, OWNER_LEFT)
    by_id = {t["team_id_master"]: t for t in teams}
    index = defaultdict(list)
    for t in teams:
        index[(norm_name(t["team_name"]), t["gender"], t["age_group"])].append(t)

    gotsport = {}
    for path in sorted(glob.glob(str(exports / "reconcile_teams_with_gotsport_*.csv"))):
        try:
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                if (r.get("run_mode") or "").lower() == "execute" and r.get("team_id_master") in by_id:
                    gotsport[r["team_id_master"]] = (
                        r.get("gotsport_team_name") or "",
                        r.get("gotsport_age_group") or "",
                    )
        except (OSError, csv.Error, KeyError):
            continue  # a log still being written by a live reconcile chunk
    fixes = defaultdict(list)
    for path in sorted(glob.glob(str(exports / "fix_band_cohorts_apply_*.csv")), key=os.path.getmtime):
        try:
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                if r.get("result") in ("updated", "already_applied") and r.get("team_id_master") in by_id:
                    fixes[r["team_id_master"]].append((Path(path).name, r["old_age_group"], r["new_age_group"]))
        except (OSError, csv.Error, KeyError):
            continue
    # A revert writes no log, so a fix counts only while the team still holds its value: the newest
    # such fix, which after a reverted later fix is the earlier one it restored.
    prior = {}
    for tid, logged in fixes.items():
        standing = [f for f in logged if f[2] == by_id[tid]["age_group"]]
        if standing:
            prior[tid] = standing[-1]
    log(t0, f"gotsport records {len(gotsport)}, standing earlier fixes {len(prior)}")
    if not gotsport or not prior:
        print(f"  warning: no reconcile or apply logs under {exports}; GotSport evidence and earlier fixes are missing")

    rows, scope = [], Counter()
    for t in teams:
        tid, name, stored = t["team_id_master"], t["team_name"] or "", t["age_group"]
        provider = prov.get(t["provider_id"])
        state = t["state_code"] or ""
        if state not in states:
            scope["out_state"] += 1
            continue
        if provider == "modular11":
            scope["out_modular11"] += 1
            continue
        if tid in excluded:
            scope["out_ranking_exclusion"] += 1
            continue
        if tid in owner_left:
            scope["out_owner_decision"] += 1
            continue
        scope["in_scope"] += 1
        band = reader.band(name)
        ulabels, years = reader.labels(name)
        kind, key = None, ""
        if band:
            both_aged_out = (num(band) or 0) >= 20 and (num(stored) or 0) >= 20  # u20 and u21 are both off
            if band != stored and not both_aged_out:
                kind, key = "band", band
        elif ulabels:
            if len(ulabels) == 1 and stored not in ulabels:
                kind, key = "ulabel", next(iter(ulabels))
        elif years:
            allowed = set().union(*(YEAR_FITS.get(y, set()) for y in years))
            aged_out_already = (num(stored) or 0) >= 20 and max(years) < OLDEST_YEAR
            if len(years) == 1 and stored not in allowed and not YEAR_RANGE.search(name) and not aged_out_already:
                kind, key = "year", "/".join(sorted(allowed, key=num))
        if kind:
            gs_name, gs_age = gotsport.get(tid, ("", ""))
            # A birth year in the name that the U-label's group cannot hold dates the label to an
            # earlier season: "2008 17U" and "08 (17U)" are both 2008 teams, U19 now, whatever
            # "17U" said. The Carolinas leagues write that year two digits, so read both spellings.
            # Every year has to fit: in "2012 2015 U12" the 2015 fits while the 2012 rules it out.
            named = {int(y) if len(y) == 4 else 2000 + int(y) for y in NAME_YEAR.findall(name)}
            dated = any(key not in YEAR_FITS[y] for y in named if y in YEAR_FITS)
            rows.append({
                "team_id": tid, "state": state, "provider": provider, "name": name, "club": t["club_name"] or "",
                "gender": t["gender"], "stored": stored, "kind": kind, "key_age": key,
                "gotsport_name": gs_name, "gotsport_age": gs_age,
                "prior_fix": json.dumps(prior[tid]) if tid in prior else "",
                "label_predates_year": kind == "ulabel" and dated,
            })
    log(t0, "scope", dict(scope), "| names disagreeing with stored:", len(rows), dict(Counter(r["kind"] for r in rows)))

    # this season's games for every flagged team: division labels and opponents' names
    ids = [r["team_id"] for r in rows]
    games = []
    for i in range(0, len(ids), 60):
        batch = ids[i:i + 60]
        for col, oth in SIDES:
            off = 0
            while True:
                data = retry(lambda: sb.table("games").select(f"{col},{oth},division_name").in_(col, batch)
                             .gte("game_date", SEASON_START).order("id").range(off, off + 999).execute().data)
                games += [(g[col], g[oth], g["division_name"]) for g in data]
                if len(data) < 1000:
                    break
                off += 1000
    opp_ids = list({o for _, o, _ in games if o})
    opp_name = {}
    for i in range(0, len(opp_ids), 100):
        chunk = opp_ids[i:i + 100]
        for o in sb.table("teams").select("team_id_master,team_name").in_("team_id_master", chunk).execute().data:
            opp_name[o["team_id_master"]] = o["team_name"]
    log(t0, f"this season: {len(games)} games, {len(opp_name)} opponents")

    div_c, band_c, year_ws, n_games = defaultdict(Counter), defaultdict(Counter), defaultdict(list), Counter()
    for me, opp, division in games:
        n_games[me] += 1
        a = reader.label_age(division) if division else None
        if a:
            div_c[me][a] += 1
        opp_n = opp_name.get(opp)
        b = reader.band(opp_n)
        if b:
            band_c[me][b] += 1
        else:
            y = reader.single_year(opp_n)
            if y in YEAR_FITS:
                year_ws[me].append(YEAR_FITS[y])

    def decisive(c: Counter) -> str:
        """A cohort holding at least two games and three times everything else, or ''."""
        if not c:
            return ""
        k, v = c.most_common(1)[0]
        return k if v >= 2 and v >= 3 * (sum(c.values()) - v) else ""

    def year_witness(tid: str, a: str, b: str) -> tuple[int, int, str]:
        """Opponents with one birth year that fits a but not b, and the reverse.

        A year that also fits a group between a and b votes for neither: it cannot tell a team two
        groups from its stored one from a team in the group between.
        """
        mid = between(a, b)
        ca = sum(1 for f in year_ws[tid] if a in f and b not in f and not f & mid)
        cb = sum(1 for f in year_ws[tid] if b in f and a not in f and not f & mid)
        return ca, cb, "thin" if ca + cb < 2 else "A" if ca >= 3 * cb else "B" if cb >= 3 * ca else "mixed"

    for r in rows:
        tid, stored, key = r["team_id"], r["stored"], r["key_age"]
        dv, bo = decisive(div_c[tid]), decisive(band_c[tid])
        r.update(games_this_season=n_games[tid], div_says=dv, band_opps_say=bo, year_witness="", proposed="",
                 div_ages=" ".join(f"{k}:{v}" for k, v in div_c[tid].most_common()),
                 opp_bands=" ".join(f"{k}:{v}" for k, v in band_c[tid].most_common()))
        kind = r["kind"]
        backs_key = backs_stored = names_third = False
        if kind in ("band", "ulabel"):
            ca, cb, v = year_witness(tid, key, stored)
            r["year_witness"] = f"{v} {ca}:{cb}"
            backs_key = key in (dv, bo) or v == "A"
            backs_stored = stored in (dv, bo) or v == "B"
            names_third = any(w and w not in (key, stored) for w in (dv, bo))
        if r["prior_fix"]:
            cat = "prior_fix_stands"
        elif kind == "band":
            gap = num(key) - num(stored) if num(key) and num(stored) else None
            if (num(key) or 0) >= 20:
                cat = "band_aged_out"
            elif gap == -1 or (key == "u17" and stored == "u19"):
                cat = "band_older_by_1"
            elif gap and gap > 0:
                cat = "band_younger"
            else:
                cat = "band_off_2plus"
            r["proposed"] = key
        elif kind == "ulabel":
            # Opponents one group older than the label, with GotSport registering the label's group,
            # is a team playing up, not an old name: the owner files it by its label. The league's
            # own division, or a birth year in the name, can still show the label is out of date.
            plays_up = (
                backs_stored
                and stored in ORDER and key in ORDER and ORDER.index(stored) == ORDER.index(key) + 1
                and r["gotsport_age"] == key
                and div_c[tid][stored] == 0  # any division read for the stored group, split or not
                and not r["label_predates_year"]
            )
            if names_third:
                cat = "ulabel_evidence_names_third_group"
            elif backs_key and not backs_stored:
                cat, r["proposed"] = "ulabel_confirmed", key
            elif plays_up:
                cat, r["proposed"] = "ulabel_plays_up", key
            elif backs_stored and not backs_key:
                cat = "ulabel_stale_name"
            elif backs_key and backs_stored:
                cat = "ulabel_mixed"
            else:
                cat = "ulabel_unconfirmed"
        else:
            allowed = sorted(key.split("/"), key=num) if key else []
            pick = {x for x in (dv, bo) if x in allowed}
            if not pick and len(allowed) == 2:
                ca, cb, v = year_witness(tid, allowed[0], allowed[1])
                r["year_witness"] = f"{v} {ca}:{cb}"
                pick = {allowed[0]} if v == "A" else {allowed[1]} if v == "B" else set()
            if not pick and r["gotsport_age"] in allowed:
                pick = {r["gotsport_age"]}
            r["proposed"] = pick.pop() if len(pick) == 1 else ""
            cat = "year_outside" if r["proposed"] else "year_outside_no_value"
        # season-proof evidence two or more groups from the proposal: a U19-league 09/10 team, a
        # two-year play-up, or a number that is not a birth year. The owner decides these. Distance
        # is by number, so a u17 proposal with u19 evidence is held: U19 leagues run a year older.
        p = num(r["proposed"])
        far = p and any(num(w) and abs(num(w) - p) >= 2 for w in (dv, bo))
        far = far or (p and kind != "year" and r["year_witness"].startswith("B") and abs((num(stored) or p) - p) >= 2)
        if far:
            cat, r["proposed"] = "held_opponents_far_from_name", ""
        r["cat"] = cat

    # an identical name, same club and state, already in the target group: a duplicate pair to merge
    movers = [r for r in rows if r["proposed"] and r["proposed"] != r["stored"]]
    landing = Counter((norm_name(r["name"]), r["gender"], r["proposed"], r["club"].lower(), r["state"]) for r in movers)
    for r in rows:
        r["collision"] = ""
    for r in movers:
        k = (norm_name(r["name"]), r["gender"], r["proposed"])
        same = [x["team_id_master"] for x in index[k] if x["team_id_master"] != r["team_id"]
                and (x["club_name"] or "").lower() == r["club"].lower() and x["state_code"] == r["state"]]
        if same or landing[k + (r["club"].lower(), r["state"])] > 1:
            r["collision"], r["cat"], r["proposed"] = ";".join(same) or "another_mover", "held_duplicate_landing", ""

    ranked = {}
    moving = [r["team_id"] for r in rows if r["proposed"]]
    for i in range(0, len(moving), 100):
        chunk = moving[i:i + 100]
        for x in sb.table("rankings_full").select("team_id,rank_in_cohort_final").in_("team_id", chunk).execute().data:
            ranked[x["team_id"]] = x["rank_in_cohort_final"]
    for r in rows:
        r["ranked"] = str(ranked.get(r["team_id"]) or "")
        r["group"] = GROUPS.get(r["cat"], "") if r["proposed"] and r["proposed"] != r["stored"] else ""

    out = Path(args.out or exports / f"age_label_review_{datetime.now():%Y%m%d_%H%M%S}.csv")
    fields = ["group", "cat", "team_id", "state", "provider", "name", "club", "gender", "stored", "proposed", "kind",
              "label_predates_year",
              "key_age", "gotsport_name", "gotsport_age", "games_this_season", "div_says", "band_opps_say",
              "year_witness", "div_ages", "opp_bands", "ranked", "collision", "prior_fix"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["group"] or "9", r["cat"], r["state"], r["name"])))

    print(f"\nReview written: {out}\n")
    print("| Group | Teams | Ranked | To U9 or younger |\n|---|---|---|---|")
    for g in "12345":
        grp = [r for r in rows if r["group"] == g]
        n_ranked = sum(bool(r["ranked"]) for r in grp)
        n_off_board = sum((num(r["proposed"]) or 99) <= 9 for r in grp)
        print(f"| {g} | {len(grp)} | {n_ranked} | {n_off_board} |")
    print("\nNot proposed:", dict(Counter(r["cat"] for r in rows if not r["group"]).most_common()))


def write_plan(args) -> None:
    wanted = {g.strip() for g in args.groups.split(",")}
    rows = [r for r in csv.DictReader(open(args.review, encoding="utf-8")) if r["group"] in wanted]
    tier = {"band": "A_own_name_band", "ulabel": "U_own_name_ulabel_opponent_confirmed", "year": "Y_single_year"}
    # A play-up row's opponents point the other way; the tier must not claim they confirmed it.
    tier_by_cat = {"ulabel_plays_up": "U_own_name_ulabel_plays_up"}
    plan = [{
        "state_code": r["state"], "team_id_master": r["team_id"], "team_name": r["name"], "club_name": r["club"],
        "gender": r["gender"], "gotsport_team_name": r["gotsport_name"],
        "band": r["key_age"] if r["kind"] == "band" else "",
        "old_age_group": r["stored"], "new_age_group": r["proposed"], "action": "would_update", "collision_with": "",
        "evidence_tier": tier_by_cat.get(r["cat"], tier[r["kind"]]),
        "fixture_verdict": f"review_group_{r['group']}_{r['cat']}",
        "opp_games_proposed": "", "opp_games_current": "",
    } for r in rows]
    default = Path(args.review).with_name(f"fix_band_cohorts_plan_review_{datetime.now():%Y%m%d_%H%M%S}.csv")
    out = Path(args.out or default)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        w.writeheader()
        w.writerows(plan)
    print(f"Plan written: {out} ({len(plan)} rows, groups {sorted(wanted)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("review", help="read-only review; writes a CSV")
    r.add_argument("--state", help="comma-separated state codes (default: every US state)")
    r.add_argument("--exports-dir", default=str(REPO / "data" / "exports"))
    r.add_argument("--out")
    p = sub.add_parser("write-plan", help="build a fix_band_cohorts plan from chosen review groups")
    p.add_argument("review")
    p.add_argument("--groups", required=True, help="comma-separated group numbers, e.g. 1,2,3")
    p.add_argument("--out")
    args = ap.parse_args()
    review(args) if args.mode == "review" else write_plan(args)


if __name__ == "__main__":
    main()
