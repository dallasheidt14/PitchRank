"""Email enrichment for queued outreach targets via Hunter.

``enrich_queued`` resolves an email for each queued row missing a contact and
writes it back, merging Hunter's confidence into ``personalization`` without
clobbering scraped tokens (read-merge-write; safe because the runner is
sequential). If writing the email hits the uq_outreach_targets_contact unique
index (two orgs share a role inbox), that row is moved to ``held`` instead of
crashing. Already-enriched rows have a contact and are skipped, so a re-run
resumes cleanly.
"""

import logging
import os

import requests
from postgrest.exceptions import APIError

from src.outreach._db import TABLE, get_client
from src.scrapers._http import retry_session_get

logger = logging.getLogger(__name__)

HUNTER_BASE = "https://api.hunter.io/v2"
UNIQUE_VIOLATION = "23505"


def _hunter_key():
    key = os.getenv("HUNTER_API_KEY")
    if not key:
        raise RuntimeError("HUNTER_API_KEY is not set")
    return key


def _pick_domain_email(emails):
    """Prefer a generic/role inbox, highest Hunter confidence first."""
    if not emails:
        return None
    ranked = sorted(
        emails,
        key=lambda e: (e.get("type") == "generic", e.get("confidence") or 0),
        reverse=True,
    )
    return ranked[0]


def find_email(source_domain, full_name=None):
    """Resolve an email for a domain. Returns ``(email|None, confidence)``.

    Uses Hunter Email Finder when a name is known, else Domain Search for a role
    inbox. ``confidence`` is Hunter's score (0-100).
    """
    key = _hunter_key()
    session = requests.Session()

    if full_name:
        url = f"{HUNTER_BASE}/email-finder"
        params = {"domain": source_domain, "full_name": full_name, "api_key": key}
    else:
        url = f"{HUNTER_BASE}/domain-search"
        params = {"domain": source_domain, "api_key": key}

    resp = retry_session_get(
        session,
        url,
        attempts=4,
        retry_delay=2.0,
        baseline_bytes=None,
        is_event_url=False,
        provider="hunter",
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}

    if full_name:
        email, score = data.get("email"), data.get("score")
    else:
        chosen = _pick_domain_email(data.get("emails") or [])
        email = chosen.get("value") if chosen else None
        score = chosen.get("confidence") if chosen else None

    if not email:
        return None, 0.0
    return email, float(score) if score is not None else 0.0


def merge_confidence(personalization, confidence):
    """Return personalization with ``enrich_confidence`` added, tokens preserved."""
    merged = dict(personalization or {})
    merged["enrich_confidence"] = confidence
    return merged


def enrich_queued(limit=None, client=None, segment=None):
    """Find and write emails for queued rows missing a contact.

    When ``segment`` is given, only that segment is enriched, so a ``limit`` is
    spent on the segment the caller asked for (matching ``verify_and_gate``'s
    scoping) rather than starving it with other segments' rows.
    """
    client = client or get_client()
    query = (
        client.table(TABLE).select("id, source_domain, personalization").eq("status", "queued").is_("contact", "null")
    )
    if segment:
        query = query.eq("segment", segment)
    if limit:
        query = query.limit(limit)
    rows = query.execute().data or []

    stats = {"resolved": 0, "no_email": 0, "held_collision": 0}
    for row in rows:
        domain = row.get("source_domain")
        if not domain:
            stats["no_email"] += 1
            continue

        personalization = row.get("personalization") or {}
        email, confidence = find_email(domain, full_name=personalization.get("contact_name"))
        if not email:
            stats["no_email"] += 1
            continue

        merged = merge_confidence(personalization, confidence)
        try:
            client.table(TABLE).update({"contact": email, "personalization": merged}).eq("id", row["id"]).execute()
            stats["resolved"] += 1
        except APIError as err:
            if getattr(err, "code", None) == UNIQUE_VIOLATION:
                client.table(TABLE).update({"status": "held"}).eq("id", row["id"]).execute()
                stats["held_collision"] += 1
                logger.info("held %s: email already tracked on another target", row["id"])
            else:
                raise

    logger.info("enrich_queued: %s", stats)
    return stats
