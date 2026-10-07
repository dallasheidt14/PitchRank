#!/usr/bin/env python3
"""Re-key the modular11_ea ids already in PitchRank by season. Dry run unless --execute.

An EA team id names an age slot that is reused every season, so a stored link is only true
for one season. This rewrites each raw ``provider_team_id`` (``3432``) in ``team_alias_map``
and ``teams`` to its season key (``3432:2026``). Rows already keyed are left alone, so a
re-run changes nothing. Game rows keep the raw ids they were imported with.

Each update is guarded on the value it read, and an executed run logs every write to
``season_key_log_<UTC>.jsonl``, which ``--undo`` reverses.

Usage:
    python scripts/migrate_modular11_ea_season_keys.py --season 2026
    python scripts/migrate_modular11_ea_season_keys.py --season 2026 --execute
    python scripts/migrate_modular11_ea_season_keys.py --undo data/modular11_ea/season_key_log_<UTC>.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.modular11_ea_keys import ea_key, refuse_raw_keys  # noqa: E402
from src.models.modular11_ea_matcher import PROVIDER_CODE  # noqa: E402
from supabase import create_client  # noqa: E402

PAGE_SIZE = 1000
ROW_ID = {"team_alias_map": "id", "teams": "team_id_master"}


def _rows(sb, table: str, provider_id: str) -> list[dict]:
    id_column = ROW_ID[table]
    rows, offset = [], 0
    while True:
        page = (
            sb.table(table)
            .select(f"{id_column}, provider_team_id")
            .eq("provider_id", provider_id)
            .order(id_column)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def refuse_unmigrated(sb, provider_id: str) -> None:
    """Stops a linker, matcher or builder run that would read raw ids as unlinked teams."""
    refuse_raw_keys(row["provider_team_id"] for table in ROW_ID for row in _rows(sb, table, provider_id))


def migrate(sb, provider_id: str, season: int, log_path: Path, execute: bool) -> dict[str, int]:
    """A raw id whose key is already taken (a row linked or created after keys were introduced)
    is counted as a collision and left for a person, rather than failing the unique index."""
    counts = {"aliases": 0, "teams": 0, "already_keyed": 0, "collisions": 0}
    log = log_path.open("a", encoding="utf-8") if execute else None
    try:
        for table, counter in (("team_alias_map", "aliases"), ("teams", "teams")):
            id_column = ROW_ID[table]
            rows = _rows(sb, table, provider_id)
            taken = {row["provider_team_id"] for row in rows}
            for row in rows:
                old = row["provider_team_id"]
                if ":" in old:
                    counts["already_keyed"] += 1
                    continue
                new = ea_key(old, season)
                if new in taken:
                    counts["collisions"] += 1
                    print(f"{table} {row[id_column]}: {new} is already taken; resolve by hand")
                    continue
                counts[counter] += 1
                if not execute:
                    continue
                written = (
                    sb.table(table)
                    .update({"provider_team_id": new})
                    .eq(id_column, row[id_column])
                    .eq("provider_team_id", old)
                    .execute()
                    .data
                )
                if written:
                    log.write(json.dumps({"table": table, id_column: row[id_column], "old": old, "new": new}) + "\n")
    finally:
        if log:
            log.close()
    return counts


def undo(sb, log_path: Path) -> dict[str, int]:
    """Puts each logged row back to its raw id, unless it has moved since the run."""
    counts = {"restored": 0, "skipped": 0}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        id_column = ROW_ID[entry["table"]]
        restored = (
            sb.table(entry["table"])
            .update({"provider_team_id": entry["old"]})
            .eq(id_column, entry[id_column])
            .eq("provider_team_id", entry["new"])
            .execute()
            .data
        )
        counts["restored" if restored else "skipped"] += 1
    return counts


def _new_client():
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _provider_id(sb) -> str:
    try:
        return sb.table("providers").select("id").eq("code", PROVIDER_CODE).single().execute().data["id"]
    except APIError as exc:
        raise SystemExit(f"ERROR: provider {PROVIDER_CODE!r} is missing; apply migration 20261005120000 first") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, help="season start year, e.g. 2026 for 2026-27")
    parser.add_argument("--out-dir", type=Path, default=Path("data/modular11_ea"))
    parser.add_argument("--execute", action="store_true", help="write the new ids")
    parser.add_argument("--undo", type=Path, help="reverse the writes logged in this file")
    args = parser.parse_args(argv)

    sb = _new_client()
    if args.undo:
        counts = undo(sb, args.undo)
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        return 0
    if not args.season:
        parser.error("--season is required")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.out_dir / f"season_key_log_{stamp}.jsonl"
    counts = migrate(sb, _provider_id(sb), args.season, log_path, args.execute)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    if args.execute:
        print(f"Undo with: --undo {log_path}")
    else:
        print("DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
