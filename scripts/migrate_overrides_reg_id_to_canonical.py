"""One-shot: rewrite overrides.jsonl team_ref values from gotsport reg-id
to canonical-pid format after the canonical-id resolver landed.

Background:
- Operator clicks (accept_match, assign_division, edit_external) recorded
  ``team_ref`` = the team's ``provider_team_id`` AT WRITE TIME.
- Pre-canonical-id flow stored reg-ids in ``provider_team_id``.
- Post-canonical-id flow stores canonical API team ids; reg-ids live in
  the new ``provider_registration_id`` field.
- Existing overrides therefore look like "orphans" against the new
  registry. The team is still there — just keyed differently.

This script translates each orphan ``team_ref`` to the new canonical
pid by joining on raw_scrape.jsonl's ``provider_registration_id`` →
``provider_team_id`` mapping.

Usage:
    python scripts/migrate_overrides_reg_id_to_canonical.py <event_key> [scenario]

    # dry-run (default) — prints what WOULD change, writes nothing:
    python scripts/migrate_overrides_reg_id_to_canonical.py gotsport__42433__unknown

    # apply for real (creates a .bak.<UTC-timestamp> backup first):
    python scripts/migrate_overrides_reg_id_to_canonical.py gotsport__42433__unknown default --apply

Idempotent. Safe to re-run; already-canonical team_refs are skipped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REG_ID_MIN_DIGITS = 7  # Reg-ids are 7+ digits; canonical pids are 5-6.


def build_reg_id_to_canonical_map(raw_scrape_path: Path) -> dict[str, str]:
    """Map gotsport reg-id (7-digit) -> canonical API team_id (5-6 digit)."""
    mapping: dict[str, str] = {}
    if not raw_scrape_path.exists():
        return mapping
    for line in raw_scrape_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        canonical = str(rec.get("provider_team_id") or "").strip()
        reg_id = str(rec.get("provider_registration_id") or "").strip()
        if canonical and reg_id and reg_id != canonical:
            mapping[reg_id] = canonical
    return mapping


def looks_like_reg_id(team_ref: str) -> bool:
    return team_ref.isdigit() and len(team_ref) >= REG_ID_MIN_DIGITS


def migrate(
    event_key: str, scenario: str, *, base_dir: Path, apply: bool
) -> int:
    event_dir = base_dir / event_key
    raw_scrape_path = event_dir / "intake" / "raw_scrape.jsonl"
    overrides_path = event_dir / "scenarios" / scenario / "overrides.jsonl"

    if not overrides_path.exists():
        print(f"ERROR: overrides file not found: {overrides_path}", file=sys.stderr)
        return 1

    reg_to_canon = build_reg_id_to_canonical_map(raw_scrape_path)
    print(f"raw_scrape map: {len(reg_to_canon)} reg_id -> canonical entries")

    lines_in = overrides_path.read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    translated = 0
    skipped_already_canonical = 0
    skipped_unmapped = 0

    for line in lines_in:
        if not line.strip():
            rewritten.append(line)
            continue
        rec = json.loads(line)
        team_ref = str(rec.get("team_ref") or "")
        if not team_ref or not looks_like_reg_id(team_ref):
            skipped_already_canonical += 1
            rewritten.append(line)
            continue
        new_ref = reg_to_canon.get(team_ref)
        if not new_ref:
            skipped_unmapped += 1
            rewritten.append(line)
            continue
        rec["team_ref"] = new_ref
        rec.setdefault("migration_notes", {})["team_ref_was_reg_id"] = team_ref
        rewritten.append(json.dumps(rec, ensure_ascii=False))
        translated += 1

    print()
    print(f"OVERRIDES SUMMARY for {overrides_path}")
    print(f"  total records:               {sum(1 for l in lines_in if l.strip())}")
    print(f"  translated reg_id -> canon:  {translated}")
    print(f"  skipped (already canonical): {skipped_already_canonical}")
    print(f"  skipped (no mapping found):  {skipped_unmapped}")

    if not apply:
        print()
        print("DRY-RUN — no changes written. Re-run with --apply to commit.")
        return 0

    if translated == 0:
        print()
        print("Nothing to translate; leaving file untouched.")
        return 0

    backup_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup_path = overrides_path.with_suffix(f".jsonl.bak.{backup_ts}")
    shutil.copy2(overrides_path, backup_path)
    print(f"Backup written: {backup_path}")

    overrides_path.write_text(
        "\n".join(rewritten) + ("\n" if not rewritten[-1].endswith("\n") else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(rewritten)} lines to {overrides_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_key", help="e.g. gotsport__42433__unknown")
    parser.add_argument("scenario", nargs="?", default="default")
    parser.add_argument(
        "--base-dir", default="reports", help="reports root (default: reports)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="commit changes (default is dry-run)"
    )
    args = parser.parse_args()
    return migrate(
        args.event_key,
        args.scenario,
        base_dir=Path(args.base_dir),
        apply=args.apply,
    )


if __name__ == "__main__":
    sys.exit(main())
