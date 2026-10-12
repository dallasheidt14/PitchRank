"""Build the owner's review page for duplicate pairs the rules could not settle.

Reads a JSON list of pairs, each carrying `merge_id` and `keep_id`, from either scanner's output:
`status` and `reason` (the squad-key scan), or `tier` and `rejected_reason` (the cross-provider
scan). It reads both teams and their merge-resolved games from Supabase and writes two files: a
self-contained page from assets/review-page.html, and beside it `<out>.manifest.json`, which
records exactly which pairs the page showed, in which direction, and each team's age group,
gender, state and club as the page read them, so the applier can refuse a pair that has changed.

Publish the page as an Artifact with the db capability. The owner's choices land in the page's
own collection, `decisions-<run>`. A saved choice holds the decision, the swap, a note and a
timestamp, never team ids: collect_review_decisions.py takes the ids from the manifest, so a
write to the page can decide a pair the page shows but cannot add one.

Read-only: it never writes to the database.

    python .claude/skills/merging-duplicate-teams/scripts/build_review_page.py \
        --pairs held.json --title "Colorado Held Pairs" --out review.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import (  # noqa: E402
    REJECTED_TIER,
    build_evidence,
    fetch_games,
    get_client,
    load_merge_map,
    merged_into,
    resolver,
)
from scripts.team_cleanup import review_page  # noqa: E402
from scripts.team_cleanup.decisions import new_page_run  # noqa: E402
from scripts.team_cleanup.review_page import fetch_teams  # noqa: E402
from scripts.team_cleanup.vetted import stamp  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "review-page.html"
STATUSES = ("held", "rejected", "proposed")


def normalise(pair: dict) -> dict:
    """A cross-provider record carries a tier: its rejected tier means rejected, any other a
    proposal. A record with neither status nor tier is a hand-built held pair."""
    tier = pair.get("tier")
    status = pair.get("status") or ("rejected" if tier == REJECTED_TIER else "proposed" if tier else "held")
    if status not in STATUSES:
        raise SystemExit(f"unknown status {status!r} for {pair['merge_id']} -> {pair['keep_id']}")
    reason = pair.get("reason") or pair.get("rejected_reason") or ""
    return {"merge_id": pair["merge_id"], "keep_id": pair["keep_id"], "status": status, "reason": reason}


def side(tid, teams, ev, providers) -> dict:
    t, dates = teams[tid], ev.dates[tid]
    return {
        "team_id": tid,
        "name": t["team_name"],
        "original": t["team_name_original"],
        "club": t["club_name"],
        "age": t["age_group"],
        "gender": t["gender"],
        "provider": providers.get(t["provider_id"]),
        "games": ev.games[tid],
        "excluded": ev.excluded[tid],
        "first": min(dates, default=None),
        "last": max(dates, default=None),
    }


def build_records(pairs, teams, canonical, ev, providers, run) -> tuple[list[dict], list[str]]:
    """The page's records, plus a line for every pair left out.

    A row that is missing, deprecated, or live but already resolving to another row through
    team_merge_map is gone in effect, and a pair listed twice (in either direction) would share
    one saved choice. Each id carries the run, so a choice saved on another build of the page
    can never be read as this one's, and a short hash of the pair in its direction, so the file
    a choice is saved to stays well inside Windows' path limit; the manifest holds the team ids.
    """
    records, skipped, seen = [], [], set()
    for p in pairs:
        ids = (p["merge_id"], p["keep_id"])
        gone = [t for t in ids if t not in teams or teams[t]["is_deprecated"] or canonical(t) != t]
        if gone:
            skipped.append(f"{ids[0]} -> {ids[1]}: {', '.join(gone)} is no longer a live team")
            continue
        if frozenset(ids) in seen:
            skipped.append(f"{ids[0]} -> {ids[1]}: listed more than once")
            continue
        seen.add(frozenset(ids))
        records.append({
            "id": review_page.card_id(run, f"{ids[0]}_{ids[1]}"),
            "status": p["status"],
            "reason": p["reason"],
            "rows": [side(ids[0], teams, ev, providers), side(ids[1], teams, ev, providers)],
        })
    records.sort(key=lambda r: (STATUSES.index(r["status"]), r["rows"][1]["age"] or "", r["rows"][1]["gender"] or ""))
    for n, r in enumerate(records, 1):
        r["n"] = n
    return records, skipped


def render(records, title, run) -> str:
    return review_page.render(TEMPLATE, records, title, run)


def manifest(records, teams, title, run) -> dict:
    return {
        "run": run,
        "title": title,
        "pairs": {
            r["id"]: {
                "merge_id": r["rows"][0]["team_id"],
                "keep_id": r["rows"][1]["team_id"],
                "merge_name": r["rows"][0]["name"],
                "keep_name": r["rows"][1]["name"],
                **stamp(teams[r["rows"][0]["team_id"]], teams[r["rows"][1]["team_id"]]),
            }
            for r in records
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", required=True, help="JSON list of pairs with merge_id and keep_id")
    ap.add_argument("--title", required=True, help="the page's name, e.g. 'Colorado Held Pairs'")
    ap.add_argument("--out", required=True, help="where to write the page; the manifest goes beside it")
    args = ap.parse_args()

    pairs = [normalise(p) for p in json.loads(Path(args.pairs).read_text(encoding="utf-8"))]
    ids = sorted({tid for p in pairs for tid in (p["merge_id"], p["keep_id"])})
    sb = get_client()
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    teams = fetch_teams(sb, ids)
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    ev = build_evidence(fetch_games(sb, sorted(merged_into(ids, merge_map, canonical))), [], canonical, ids)

    run = new_page_run()
    records, skipped = build_records(pairs, teams, canonical, ev, providers, run)
    out = Path(args.out)
    out.write_text(render(records, args.title, run), encoding="utf-8")
    manifest_path = out.with_name(out.name + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest(records, teams, args.title, run), indent=1), encoding="utf-8")
    print(f"wrote {out}: {len(records)} pairs, run {run}")
    print(f"wrote {manifest_path}")
    for line in skipped:
        print(f"  left out {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
