#!/usr/bin/env python3
"""Correct teams.gender from gotsport's own registration, not from the team's name.

`fix_team_gender_from_name.py` and `fix_gender_from_registered_name.py` both read the
gender out of the team's name. That works, but it only reaches teams whose name spells
it out, and it is a reading of a label rather than a fact from the registry.

gotsport already knows. `team_ranking_data/team_details` returns `display_gender`
alongside the `club_name` this repo has always read from the same payload. Sampled
against 25 of the 445 corrections made from names on 2026-09-17, it agreed with 23,
backed the pre-correction value on 1, and answered `Coed` on 1.

So it is a strong witness rather than an infallible one, and this script treats it that
way: it corrects only where gotsport states a gender it recognises, records the previous
value for every write, and leaves `Coed`, blanks and unreachable teams alone.

It does NOT touch age_group. Whether `display_age_group` is the birth-year cohort or the
registered event cohort is an open question in this repo, and a wrong cohort moves a team
to another ranking board.

Every call is an HTTP request, so a full sweep is not the intended use. Target it with
--state / --provider-team-ids, or pilot it with --limit and read the yield before
widening.

Usage:
    python scripts/fix_gender_from_gotsport.py --limit 200            # dry run
    python scripts/fix_gender_from_gotsport.py --limit 200 --execute
    python scripts/fix_gender_from_gotsport.py --state AZ --execute
    python scripts/fix_gender_from_gotsport.py --revert logs/gender_from_gotsport_*.json
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fix_team_gender_from_name import gender_from_name  # noqa: E402
from src.scrapers.gotsport import gender_code_from_label  # noqa: E402
from supabase import create_client  # noqa: E402

DETAILS_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}
# Only these two are actionable. "Coed" and anything unrecognised is left alone
# rather than forced into the two-value column.
GENDER_MAP = {"male": "Male", "boys": "Male", "boy": "Male", "female": "Female", "girls": "Female", "girl": "Female"}


def log(message: str) -> None:
    print(message, flush=True)


def gender_the_name_states(team_name: Optional[str]) -> Optional[str]:
    """Union of the two name readers in this repo.

    `gender_from_name` reads the words and the ``GU12``/``G U 12`` forms;
    `gender_code_from_label` adds the ones glued to a birth year (``G2013/14``,
    ``B2016``), which the first misses and which are common in league names.
    """
    stated = gender_from_name(team_name)
    if stated:
        return stated
    code = gender_code_from_label(team_name)
    return {"M": "Male", "F": "Female"}.get(code) if code else None


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError("Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(supabase_url, supabase_key)


def fetch_candidates(
    supabase,
    state: Optional[str],
    provider_team_ids: Optional[List[str]],
    limit: Optional[int],
    seed: Optional[int] = None,
):
    """Live gotsport teams.

    A --limit samples at random rather than taking the first page, so a capped run
    measures a yield that generalises instead of whatever the table happens to
    order first.
    """
    if provider_team_ids:
        return (
            supabase.table("teams")
            .select("team_id_master,team_name,club_name,gender,age_group,state_code,provider_team_id")
            .in_("provider_team_id", provider_team_ids[:100])
            .execute()
            .data
            or []
        )

    page_size = 1000
    offset = 0
    out: List[Dict] = []
    while True:
        query = (
            supabase.table("teams")
            .select("team_id_master,team_name,club_name,gender,age_group,state_code,provider_team_id")
            .eq("is_deprecated", False)
            .not_.is_("provider_team_id", "null")
        )
        if state:
            query = query.eq("state_code", state.upper())
        batch = query.range(offset, offset + page_size - 1).execute().data or []
        if not batch:
            break
        out.extend(row for row in batch if str(row.get("provider_team_id") or "").isdigit())
        if len(batch) < page_size:
            break
        offset += page_size

    if limit and len(out) > limit:
        # Postgres returns no guaranteed order without an ORDER BY, so seeding the
        # shuffle alone does not reproduce a sample. Sort first, then shuffle.
        out.sort(key=lambda row: row["team_id_master"])
        random.Random(seed).shuffle(out)
        return out[:limit]
    return out


def resolve_gender(session: requests.Session, provider_team_id: str, timeout: int) -> Dict[str, str]:
    """gotsport's stated gender for a team, or a reason it could not be read."""
    try:
        response = session.get(DETAILS_URL, params={"team_id": provider_team_id}, timeout=timeout)
    except requests.RequestException as exc:
        return {"error": f"request failed: {exc}"}

    if response.status_code == 404:
        return {"error": "gone: gotsport has no such team"}
    if response.status_code != 200:
        server = response.headers.get("Server", "?")
        return {"error": f"HTTP {response.status_code} (Server: {server})"}

    try:
        payload = response.json()
    except ValueError as exc:
        return {"error": f"non-JSON body: {exc}"}
    if not isinstance(payload, dict):
        return {"error": "non-dict body"}

    raw = str(payload.get("display_gender") or "").strip()
    if not raw:
        return {"error": "no display_gender"}
    mapped = GENDER_MAP.get(raw.lower())
    if not mapped:
        return {"error": f"unactionable value: {raw}"}
    return {"gender": mapped, "raw": raw}


def revert(supabase, log_path: Path) -> None:
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    for entry in entries:
        supabase.table("teams").update({"gender": entry["old_gender"]}).eq(
            "team_id_master", entry["team_id_master"]
        ).execute()
    log(f"Reverted {len(entries)} teams from {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix team gender from gotsport's registered value")
    parser.add_argument("--execute", action="store_true", help="Write the corrections (default is a dry run)")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to probe")
    parser.add_argument("--state", help="Restrict to one state code")
    parser.add_argument("--provider-team-ids", nargs="+", help="Probe these gotsport team ids only (max 100)")
    parser.add_argument("--delay-min", type=float, default=1.5, help="Min seconds between requests")
    parser.add_argument("--delay-max", type=float, default=3.0, help="Max seconds between requests")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--seed", type=int, help="Make a --limit sample reproducible")
    parser.add_argument("--revert", help="Replay a run log backwards")
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()

    if args.revert:
        revert(supabase, Path(args.revert))
        return

    teams = fetch_candidates(supabase, args.state, args.provider_team_ids, args.limit, args.seed)
    log(f"Probing {len(teams):,} gotsport teams" + ("" if args.execute else " [dry run]"))

    session = requests.Session()
    session.headers.update(HEADERS)

    tally: Counter = Counter()
    changes: List[Dict] = []
    conflicts: List[Dict] = []
    for index, row in enumerate(teams, 1):
        result = resolve_gender(session, row["provider_team_id"], args.timeout)
        if "error" in result:
            tally[result["error"].split(":")[0]] += 1
        elif result["gender"] == row["gender"]:
            tally["agrees"] += 1
        elif (stated := gender_the_name_states(row.get("team_name"))) and stated != result["gender"]:
            # Two independent witnesses disagree: the club's registered name says one
            # thing, gotsport's registration says the other. Neither is reliable enough
            # to overrule the other, and a wrong write moves the team to the other
            # ranking board, so hold and report instead.
            tally["conflicts with name"] += 1
            conflicts.append(
                {
                    "team_name": row["team_name"],
                    "state_code": row["state_code"],
                    "stored": row["gender"],
                    "name_says": stated,
                    "gotsport_says": result["gender"],
                }
            )
        else:
            tally["differs"] += 1
            changes.append(
                {
                    "team_id_master": row["team_id_master"],
                    "team_name": row["team_name"],
                    "club_name": row["club_name"],
                    "state_code": row["state_code"],
                    "old_gender": row["gender"],
                    "new_gender": result["gender"],
                }
            )
            log(f"  {row['team_name']!r} ({row['state_code']}): {row['gender']} -> {result['gender']}")
        if index % 100 == 0:
            log(f"  ... {index}/{len(teams)} probed, {len(changes)} differ")
        time.sleep(random.uniform(args.delay_min, args.delay_max))

    log(f"\nprobed {len(teams):,}  ->  {dict(tally)}")
    if teams:
        log(f"yield: {len(changes)} corrections per {len(teams)} probed")

    if conflicts:
        log(f"\nheld, name and gotsport disagree ({len(conflicts)}) — decide these from fixtures:")
        for conflict in conflicts:
            log(
                f"  {conflict['team_name']!r} ({conflict['state_code']}): stored {conflict['stored']}, "
                f"name says {conflict['name_says']}, gotsport says {conflict['gotsport_says']}"
            )

    if not changes:
        log("Nothing to correct.")
        return

    if not args.execute:
        log(f"\n[dry run] would correct {len(changes)} teams; re-run with --execute")
        return

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"gender_from_gotsport_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    log_path.write_text(json.dumps(changes, indent=2), encoding="utf-8")
    log(f"Run log written before any write: {log_path}")

    failures = []
    for change in changes:
        try:
            supabase.table("teams").update({"gender": change["new_gender"]}).eq(
                "team_id_master", change["team_id_master"]
            ).execute()
        except Exception as exc:  # one bad row must not abandon the rest mid-batch
            failures.append({**change, "error": str(exc)})
    log(f"Corrected {len(changes) - len(failures)} teams, {len(failures)} failed")
    for failure in failures:
        log(f"  FAILED {failure['team_name']!r}: {failure['error']}")
    log(f"Revert with: python scripts/fix_gender_from_gotsport.py --revert {log_path}")


if __name__ == "__main__":
    sys.exit(main())
