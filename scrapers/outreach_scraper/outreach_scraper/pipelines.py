"""
Supabase sink pipeline for the outreach_scraper project.

Replaces modular11_scraper's CSV pipeline. Writes scraped targets to the
outreach_targets table as status='queued', verification_status='unverified',
with Python-side dedupe on (segment, source_domain, org) plus a lower(contact)
guard. The uq_outreach_targets_contact partial unique index is the DB safety net
behind the in-memory email set. Runs are sequential, so this is race-free
without DB-level claim machinery.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from scrapy import Spider

from outreach_scraper.items import OutreachTargetItem
from supabase import create_client

logger = logging.getLogger(__name__)

TABLE = "outreach_targets"
INSERT_BATCH_SIZE = 100
SELECT_PAGE_SIZE = 1000


def _load_repo_env():
    # pipelines.py -> outreach_scraper/ -> outreach_scraper/ -> scrapers/ -> repo root
    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env.local")
    load_dotenv(repo_root / ".env")


class OutreachSupabasePipeline:
    """Dedupe scraped items and batch-insert new targets into outreach_targets."""

    def __init__(self):
        self.client = None
        self.dry_run = False
        self.seen_keys = set()  # (segment, source_domain, org)
        self.seen_emails = set()  # lower(contact)
        self.buffer = []
        self.inserted = 0
        self.skipped_dupes = 0

    def open_spider(self, spider: Spider):
        self.dry_run = bool(getattr(spider, "dry_run", False))

        _load_repo_env()
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self.client = create_client(url, key)

        self._load_dedupe_sets()
        logger.info(
            "OutreachSupabasePipeline open (dry_run=%s): %d existing keys, %d existing emails",
            self.dry_run,
            len(self.seen_keys),
            len(self.seen_emails),
        )

    def _load_dedupe_sets(self):
        offset = 0
        while True:
            res = (
                self.client.table(TABLE)
                .select("segment, source_domain, org, contact")
                .order("id")
                .range(offset, offset + SELECT_PAGE_SIZE - 1)
                .execute()
            )
            rows = res.data or []
            for row in rows:
                self.seen_keys.add(self._dedupe_key(row))
                if row.get("contact"):
                    self.seen_emails.add(row["contact"].lower())
            if len(rows) < SELECT_PAGE_SIZE:
                break
            offset += SELECT_PAGE_SIZE

    @staticmethod
    def _dedupe_key(row):
        return (row.get("segment"), row.get("source_domain"), row.get("org"))

    def process_item(self, item: OutreachTargetItem, spider: Spider) -> OutreachTargetItem:
        key = self._dedupe_key(item)
        email = (item.get("contact") or "").strip() or None

        if key in self.seen_keys:
            self.skipped_dupes += 1
            return item
        if email and email.lower() in self.seen_emails:
            self.skipped_dupes += 1
            return item

        self.seen_keys.add(key)
        if email:
            self.seen_emails.add(email.lower())

        self.buffer.append(
            {
                "segment": item.get("segment"),
                "org": item.get("org"),
                "contact": email,
                "source_domain": item.get("source_domain"),
                "link_url": item.get("link_url"),
                "personalization": item.get("personalization") or {},
                "status": "queued",
                "verification_status": "unverified",
            }
        )
        if len(self.buffer) >= INSERT_BATCH_SIZE:
            self._flush()
        return item

    def close_spider(self, spider: Spider):
        self._flush()
        logger.info(
            "OutreachSupabasePipeline closed: %d inserted, %d duplicates skipped",
            self.inserted,
            self.skipped_dupes,
        )

    def _flush(self):
        if not self.buffer:
            return
        batch, self.buffer = self.buffer, []

        if self.dry_run:
            logger.info("[dry-run] would insert %d rows:", len(batch))
            for row in batch:
                logger.info(
                    "[dry-run]   %s | %s | %s | contact=%s | %s",
                    row["segment"],
                    row["org"],
                    row["source_domain"],
                    row["contact"],
                    row["personalization"],
                )
            return

        # On failure, re-raise: a re-run reloads dedupe sets from the DB and
        # re-scrapes only the rows that never persisted, so nothing is lost.
        self.client.table(TABLE).insert(batch).execute()
        self.inserted += len(batch)
