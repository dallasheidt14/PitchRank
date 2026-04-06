#!/usr/bin/env python3
"""Parse NEW TEAMS CREATED block from import_games_enhanced stdout log; write review xlsx."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LINE_RE = re.compile(
    r"^\s+(.+?) -> (.+?) \(id: ([a-f0-9-]{36}), age: ([^,]+), div: (.+)\)\s*$",
    re.MULTILINE,
)
BATCH = 100


def read_log_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8", errors="replace")


def parse_log(text: str) -> list[dict]:
    rows = []
    for m in LINE_RE.finditer(text):
        rows.append(
            {
                "incoming_name": m.group(1).strip(),
                "clean_name": m.group(2).strip(),
                "uuid": m.group(3),
                "age_group": m.group(4).strip(),
                "division": m.group(5).strip(),
            }
        )
    return rows


NUM_NAME_RE = re.compile(r"^\s+\d+\.\s+(.+)$")
ID_RE = re.compile(r"^\s+ID:\s+([a-f0-9-]{36})\s*$", re.IGNORECASE)
AGE_DIV_RE = re.compile(r"^\s+Age:\s+([^,]+),\s+Division:\s+(.+?)\s*$")


def parse_enhanced_pipeline_new_teams(text: str) -> list[dict]:
    """Parse NEW TEAMS CREATED block from enhanced_pipeline (numbered + ID + Age lines)."""
    marker = "NEW TEAMS CREATED:"
    if marker not in text:
        return []
    start = text.index(marker) + len(marker)
    chunk = text[start:]
    rows: list[dict] = []
    name: str | None = None
    tid: str | None = None
    for raw in chunk.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("===") or line.startswith("IMPORT_RESULT"):
            break
        m_num = NUM_NAME_RE.match(line)
        if m_num:
            name = m_num.group(1).strip()
            tid = None
            continue
        m_id = ID_RE.match(line)
        if m_id and name:
            tid = m_id.group(1)
            continue
        m_ad = AGE_DIV_RE.match(line)
        if m_ad and name and tid:
            rows.append(
                {
                    "incoming_name": name,
                    "clean_name": name,
                    "uuid": tid,
                    "age_group": m_ad.group(1).strip(),
                    "division": m_ad.group(2).strip(),
                }
            )
            name = None
            tid = None
    return rows


def parse_new_teams_from_log(text: str) -> list[dict]:
    rows = parse_log(text)
    if rows:
        return rows
    return parse_enhanced_pipeline_new_teams(text)


def fetch_teams(sb, uuids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(uuids), BATCH):
        chunk = uuids[i : i + BATCH]
        r = (
            sb.table("teams")
            .select("team_id_master,team_name,club_name,state_code,provider_team_id,league")
            .in_("team_id_master", chunk)
            .execute()
        )
        for row in r.data or []:
            out[str(row["team_id_master"])] = row
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if not args.log.is_file():
        print(f"Log not found: {args.log}", file=sys.stderr)
        sys.exit(1)

    text = read_log_text(args.log)
    parsed = parse_new_teams_from_log(text)
    out_path = args.out or (REPO_ROOT / "artifacts" / "modular11_import_new_teams.xlsx")

    env_local = REPO_ROOT / ".env.local"
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv(REPO_ROOT / ".env", override=True)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing Supabase env", file=sys.stderr)
        sys.exit(1)

    sb = create_client(url, key)
    uuids = [r["uuid"] for r in parsed]
    db = fetch_teams(sb, uuids) if uuids else {}

    rows = []
    for r in parsed:
        t = db.get(r["uuid"], {})
        rows.append(
            {
                **r,
                "team_name": t.get("team_name", ""),
                "club_name": t.get("club_name", ""),
                "state_code": t.get("state_code", "") or "",
                "provider_team_id": t.get("provider_team_id", ""),
                "league": t.get("league", "") or "",
            }
        )

    cols = [
        "incoming_name",
        "clean_name",
        "uuid",
        "age_group",
        "division",
        "team_name",
        "club_name",
        "state_code",
        "provider_team_id",
        "league",
    ]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False, sheet_name="new_teams")
    print(f"Parsed {len(parsed)} new teams from log; wrote {out_path}")


if __name__ == "__main__":
    main()
