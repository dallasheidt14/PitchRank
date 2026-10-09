#!/usr/bin/env python3
"""Propose config/yssl_club_map.csv: each YSSL club against PitchRank's IL clubs.

Only a name equal after normalizing is filled in (``decided_by=auto-exact``).
Every other club is left blank with up to three candidates in its note, for the
owner: club branches are separate clubs, so a shared prefix never decides a match.

Read-only against the database. Writes the proposal to ``--output`` (default
``data/raw/yssl/club_map_proposal.csv``); decided rows are copied into the config
file by hand.

Usage:
    python scripts/propose_yssl_club_map.py
"""

import argparse
import csv
import difflib
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from scripts.import_yssl import BASE_URL, _get, make_session  # noqa: E402
from supabase import create_client  # noqa: E402

COLUMNS = ["yssl_code", "yssl_name", "team_prefix", "pitchrank_club_name", "state_code", "decided_by", "note"]
_CLUB_CODE = re.compile(r"clu_code=([A-Z0-9]{2,5})\b")
_FILLER = {"fc", "sc", "soccer", "club", "futbol", "the"}


def club_names(html: str) -> List[Tuple[str, str]]:
    """``(code, name)`` for every club on ``clublinks.php``, sorted by code."""
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, str] = {}
    for link in soup.select('a[href*="club.php?clu_code="]'):
        code = _CLUB_CODE.search(link["href"]).group(1)
        found.setdefault(code, " ".join(link.get_text().split()))
    return sorted(found.items())


def _key(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _FILLER)


def propose_rows(yssl_clubs: List[Tuple[str, str]], pitchrank_clubs: List[str]) -> List[Dict]:
    by_key: Dict[str, str] = {}
    for club in sorted(set(pitchrank_clubs)):
        by_key.setdefault(_key(club), club)
    rows = []
    for code, name in sorted(yssl_clubs):
        exact = by_key.get(_key(name))
        candidates = difflib.get_close_matches(_key(name), list(by_key), n=3, cutoff=0.4)
        rows.append(
            {
                "yssl_code": code,
                "yssl_name": name,
                "team_prefix": "",
                "pitchrank_club_name": exact or "",
                "state_code": "",
                "decided_by": "auto-exact" if exact else "",
                "note": "" if exact else "candidates: " + "; ".join(by_key[c] for c in candidates),
            }
        )
    return rows


def il_club_names(supabase) -> List[str]:
    names = set()
    offset = 0
    while True:
        page = (
            supabase.table("teams")
            .select("club_name")
            .eq("state_code", "IL")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + 999)
            .execute()
        ).data or []
        names.update(row["club_name"] for row in page if row.get("club_name"))
        if len(page) < 1000:
            return sorted(names)
        offset += 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/raw/yssl/club_map_proposal.csv"))
    args = parser.parse_args()
    load_dotenv()
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    clubs = club_names(_get(make_session(), f"{BASE_URL}/clublinks.php").text)
    rows = propose_rows(clubs, il_club_names(supabase))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{sum(1 for row in rows if row['decided_by'])} of {len(rows)} clubs auto-decided -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
