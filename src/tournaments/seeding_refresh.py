"""Durable, resumable team refreshes, separate from frozen seeding evidence.

The journal is saved beside the run, not inside its potentially large pack. A
client-generated request ID makes a lost response safe to retry even after the
consumer finishes. The atomic enqueue RPC also saves adoption receipts, so
another producer's completed request remains recoverable after a lost response.
"""

from __future__ import annotations

import json
from collections import Counter
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.tournaments.gotsport_event_roster import event_id_from
from src.tournaments.roster_paste import ParsedRoster
from src.tournaments.roster_resolver import fetch_gotsport_provider_id
from src.tournaments.seeding_assessment import effective_roster
from src.tournaments.seeding_enqueue import make_provider_team_id_lookup
from src.tournaments.seeding_run_store import SeedingRun, legacy_event_id
from src.tournaments.storage._file_lock import _acquire_file_lock
from src.tournaments.storage._io import write_json
from src.utils.merge_resolver import MergeResolver

JOURNAL_FILENAME = "team_refresh.json"
_TERMINAL = {"completed"}
_RETRYABLE = {"failed", "unavailable_source", "conflict"}


def read_refresh(run_dir: Path, name: str) -> dict:
    path = run_dir / JOURNAL_FILENAME
    if not path.exists():
        return {"schema_version": 1, "name": name, "teams": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("name") != name or not isinstance(data.get("teams"), dict):
        raise ValueError("Team refresh history needs recovery; no new requests were sent.")
    return data


def refresh_summary(journal: dict) -> dict[str, int]:
    return dict(Counter(item["status"] for item in journal.get("teams", {}).values() if item.get("current", True)))


class RefreshQueue:
    """Small database boundary; all writes happen at execute(), never on read."""

    def __init__(self, client: Any):
        self.client = client
        self.resolver = MergeResolver(client)
        self.provider = fetch_gotsport_provider_id(client)
        if not self.provider:
            raise ValueError("GotSport is unavailable. Your matches are saved.")
        self.lookup = make_provider_team_id_lookup(client, self.provider)

    def canonical(self, identity: str) -> str:
        result = self.resolver.resolve(identity)
        if self.resolver.version == "error":
            raise ValueError("Could not verify merged team identities.")
        return result

    def source(self, identity: str) -> str | None:
        return self.lookup(identity)

    def get(self, request_id: str) -> dict | None:
        intents = (self.client.table("scrape_request_intents").select("request_id")
                   .eq("intent_id", request_id).limit(1).execute().data or [])
        if intents:
            request_id = intents[0]["request_id"]
        rows = self.client.table("scrape_requests").select("*").eq("id", request_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def active(self, identity: str) -> list[dict]:
        rows = []
        canonical = self.canonical(identity)
        related = sorted({canonical, *(team for team in self.resolver.get_deprecated_teams()
                                       if self.canonical(team) == canonical)})
        for start in range(0, len(related), 100):
            for offset in range(0, 10000, 100):
                page = (self.client.table("scrape_requests").select("*")
                        .in_("team_id_master", related[start:start + 100])
                        .in_("status", ["pending", "processing"]).order("id").range(offset, offset + 99)
                        .execute().data or [])
                rows.extend(page)
                if len(page) < 100:
                    break
            else:
                raise ValueError("Refresh queue lookup was incomplete; no request was sent.")
        return rows

    def insert(self, receipt: dict, *, dry_run: bool = False) -> dict | None:
        if dry_run:
            return None
        rows = self.client.rpc("enqueue_scrape_request_once", {
            "p_intent_id": receipt["request_id"], "p_team_id_master": receipt["team_id_master"],
            "p_team_name": receipt["team_name"], "p_provider_id": receipt["provider_id"],
            "p_provider_team_id": receipt["provider_team_id"], "p_game_date": receipt["game_date"],
            "p_request_type": "missing_games", "p_priority": 1,
        }).execute().data
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("The refresh response was incomplete; check its saved receipt.")
        return rows[0]

    def prioritize(self, request: dict) -> None:
        if request.get("status") != "pending" or request.get("priority", 1) <= 1:
            return
        query = self.client.table("scrape_requests").update({"priority": 1})
        for key in ("id", "team_id_master", "provider_id", "provider_team_id", "game_date"):
            query = query.eq(key, request[key])
        query.eq("status", "pending").gt("priority", 1).execute()


def _compatible(request: dict, receipt: dict, canonical) -> bool:
    same_team = (canonical(request.get("team_id_master")) == canonical(receipt.get("team_id_master"))
                 and all(str(request.get(key) or "") == str(receipt.get(key) or "")
                         for key in ("provider_id", "provider_team_id")))
    try:
        anchor = date.fromisoformat(request["game_date"])
        today = date.fromisoformat(receipt["game_date"])
    except (KeyError, TypeError, ValueError):
        return False
    # The existing consumer scrapes anchor +/-90 days. An older anchor is
    # reusable if its window still covers all of today's preceding 90 days.
    return same_team and anchor <= today <= anchor + timedelta(days=90)


def _adopt(receipt: dict, request: dict, canonical) -> None:
    if not _compatible(request, receipt, canonical):
        receipt.update(status="conflict", reason="An existing refresh uses a different source or date. "
                       "Review it before retrying.")
        return
    receipt.update(request_id=request["id"], status=request["status"],
                   completed_at=request.get("completed_at"), games_found=request.get("games_found"),
                   reason="The game refresh failed. Retry the request." if request["status"] == "failed" else "")


def refresh_run(
    run: SeedingRun, run_dir: Path, queue: Any, *, retry_failed: bool = False,
    status_only: bool = False, dry_run: bool = False,
) -> dict:
    """Queue only saved matches; repeated calls resume the same durable intents.

    Caller supplies the saved run, never an unsaved session selection. Dry runs
    do not create directories, lock files, or journals. Status checks
    update the recovery journal without queueing work. Serialization
    across runs in one storage root prevents competing Streamlit sessions.
    """
    if not run.saved_at or not run_dir.is_dir():
        raise ValueError("Save the matched roster before refreshing teams.")
    lock = nullcontext() if dry_run else _acquire_file_lock(run_dir.parent / ".team-refresh.lock", timeout=0)
    with lock:
        journal = read_refresh(run_dir, run.name)
        event = str(run.assessment.get("event_id") or event_id_from(run.source_url)
                    or legacy_event_id(run.name) or "")
        saved_event = str(journal.get("event_id") or event_id_from(journal.get("source_url", ""))
                          or legacy_event_id(journal.get("name")) or "")
        if "source_url" in journal and event != saved_event:
            raise ValueError("This refresh history belongs to another tournament.")
        journal["source_url"] = run.source_url
        journal["event_id"] = event

        def save():
            if not dry_run:
                write_json(run_dir / JOURNAL_FILENAME, journal, indent=2)

        resolved = {item.source_index: item for item in run.resolved}
        identities = {}
        roster = effective_roster(ParsedRoster(run.rows, run.warnings), run.cohort_decisions)
        for row in roster.rows:
            override = run.overrides.get(row.source_index, {})
            item = resolved.get(row.source_index)
            identity = override.get("team_id_master") or (item.team_id_master if item else None)
            if identity and not override.get("not_found") and not row.intake_issue:
                canonical = queue.canonical(identity)
                identities.setdefault(canonical, row.team_name_raw)
        prior = {}
        for key, receipt in journal["teams"].items():
            receipt["current"] = False
            canonical = queue.canonical(receipt.get("team_id_master") or key)
            prior.setdefault(canonical, []).append((key, receipt))
        for identity, name in identities.items():
            # Retain the original receipt and request identity after a merge.
            # A completed refresh wins over a newer unsent intent for its survivor.
            candidates = sorted(prior.get(identity, []), key=lambda item: (
                item[1]["status"] != "completed", not bool(item[1].get("request_id")), item[0]))
            receipt_key, receipt = candidates[0] if candidates else (identity, None)
            if receipt:
                receipt["current"] = True
            if receipt and receipt["status"] in _TERMINAL:
                continue
            if receipt and receipt["status"] in {"pending", "processing"} and not (status_only or retry_failed):
                continue
            if not receipt and status_only:
                continue
            if receipt and receipt["status"] in _RETRYABLE and not (retry_failed or status_only):
                continue
            try:
                if receipt and receipt.get("request_id"):
                    existing = queue.get(receipt["request_id"])
                    if existing:
                        _adopt(receipt, existing, queue.canonical)
                        save()
                        if receipt["status"] == "pending" and not (dry_run or status_only):
                            queue.prioritize(existing)
                        retry_terminal = (retry_failed and not status_only
                                          and receipt["status"] in {"failed", "conflict"}
                                          and existing["status"] in {"failed", "completed"})
                        if not retry_terminal:
                            continue
                    elif receipt["status"] in {"pending", "processing"}:
                        receipt.update(status="conflict", reason="The saved request is no longer available. "
                                       "Check its outcome before requesting another refresh.")
                        save()
                        continue
                if status_only:
                    continue
                if receipt is None or receipt["status"] in _RETRYABLE:
                    receipt = {
                        "team_id_master": identity, "team_name": name, "provider_id": queue.provider,
                        "game_date": datetime.now(timezone.utc).date().isoformat(), "status": "planned",
                        "requested_at": datetime.now(timezone.utc).isoformat(), "current": True,
                    }
                    journal["teams"][receipt_key] = receipt
                # Re-check the chosen identity's source, never a rejected roster ID.
                source = queue.source(identity)
                if not source:
                    receipt.update(status="unavailable_source",
                                   reason="No verified GotSport source is linked to this team.")
                    save()
                    continue
                if receipt.get("provider_team_id") and receipt["provider_team_id"] != source:
                    receipt.update(status="conflict", reason="This team's source changed. "
                                   "Review the existing request before retrying.")
                    save()
                    continue
                receipt["provider_team_id"] = source
                active = queue.active(identity)
                if active:
                    compatible = [request for request in active if _compatible(request, receipt, queue.canonical)]
                    _adopt(receipt, compatible[0] if compatible else active[0], queue.canonical)
                    save()
                    if compatible and not dry_run:
                        queue.prioritize(compatible[0])
                    continue
                # No queue row exists yet; a merge may have changed the target
                # since this intent was saved. Keep its idempotency identity.
                receipt["team_id_master"] = identity
                receipt.setdefault("request_id", str(uuid4()))
                receipt["status"] = "submitting"
                save()  # The same ID survives even a process exit after the insert.
                if dry_run:
                    receipt["status"] = "would_queue"
                    continue
                request = queue.insert(receipt)
                _adopt(receipt, request, queue.canonical)
            except Exception:
                if receipt is None:
                    receipt = {"team_id_master": identity, "team_name": name, "current": True}
                    journal["teams"][receipt_key] = receipt
                # Keep request_id on an uncertain insert; a retry reuses it.
                receipt.update(status="uncertain" if receipt.get("request_id") else "failed",
                               reason="Could not confirm the refresh. Your match is saved; check status or retry.")
            save()
        save()
        return journal
