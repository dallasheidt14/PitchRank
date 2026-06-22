#!/usr/bin/env python3
"""Build the outreach target list for one segment: scrape -> enrich -> verify+gate.

Idempotent and resumable via the status fields — a crashed run is recovered by
re-running (enrichment skips rows that already have a contact, verification
skips rows that already have a verification_status, and the gate finalizes once
the slice is fully verified). Run one segment at a time, sequentially; there is
no lease/heartbeat/reaper because the pipeline is solo and sequential.
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

from src.outreach import enrich, verify  # noqa: E402
from src.outreach._db import TABLE, get_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_outreach_list")

SEGMENTS = ("associations", "clubs", "media", "bloggers")
SCRAPER_DIR = REPO_ROOT / "scrapers" / "outreach_scraper"


def run_spider(segment, dry_run):
    cmd = [sys.executable, "-m", "scrapy", "crawl", segment, "-a", f"dry_run={'1' if dry_run else '0'}"]
    logger.info("Running spider: %s (cwd=%s)", " ".join(cmd), SCRAPER_DIR)
    result = subprocess.run(cmd, cwd=SCRAPER_DIR)
    if result.returncode != 0:
        raise SystemExit(f"spider '{segment}' exited with code {result.returncode}")


def segment_counts(client, segment):
    rows = client.table(TABLE).select("status").eq("segment", segment).execute().data or []
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def queued_slice_ids(client, segment, limit):
    """The first ``limit`` queued rows for a segment, ordered for determinism.

    Enrich and verify share this slice so a capped run advances the same rows
    through both stages.
    """
    res = (
        client.table(TABLE)
        .select("id")
        .eq("segment", segment)
        .eq("status", "queued")
        .order("id")
        .limit(limit)
        .execute()
    )
    return [row["id"] for row in (res.data or [])]


def main():
    parser = argparse.ArgumentParser(description="Build the outreach target list for one segment.")
    parser.add_argument("--segment", required=True, choices=SEGMENTS)
    parser.add_argument("--limit", type=int, default=None, help="Cap rows enriched/verified this run")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only; no DB writes, no enrich/verify")
    args = parser.parse_args()

    run_spider(args.segment, args.dry_run)
    if args.dry_run:
        logger.info("dry-run: scrape only, skipping enrichment and verification")
        return

    client = get_client()
    if args.limit:
        slice_ids = queued_slice_ids(client, args.segment, args.limit)
        enrich_stats = enrich.enrich_queued(client=client, ids=slice_ids)
        gate_summary = verify.verify_and_gate(client=client, ids=slice_ids)
    else:
        enrich_stats = enrich.enrich_queued(client=client, segment=args.segment)
        gate_summary = verify.verify_and_gate(client=client, segment=args.segment)

    counts = segment_counts(client, args.segment)
    logger.info("=" * 60)
    logger.info("Segment: %s", args.segment)
    logger.info("Enrichment: %s", enrich_stats)
    logger.info("Gate: %s", gate_summary)
    logger.info("Status counts: %s", counts)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
