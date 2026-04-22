"""Shared bulk-update helpers for Supabase RPC calls.

Centralizes the chunked `bulk_update_last_scraped_at` RPC pattern used by
`scripts/scrape_games.py` and `src/etl/enhanced_pipeline.py`. Callers supply an
optional fallback for the "RPC function does not exist yet" case (SQLSTATE
42883), which happens when the migration hasn't been applied.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)

BULK_UPDATE_RPC = "bulk_update_last_scraped_at"
BULK_UPDATE_CHUNK_SIZE = 2000
BULK_UPDATE_MIN_CHUNK = 125
PG_UNDEFINED_FUNCTION = "42883"
# postgrest-py uses an int for the HTTP status on non-JSON bodies and a
# string for PostgREST JSON error codes — accept both for 413.
HTTP_PAYLOAD_TOO_LARGE_CODES = (413, "413")
# Explicit ceiling on SETOF-returning RPC responses. PostgREST enforces a
# server-side `db-max-rows` cap (default 1000, raised to 200000 on the
# PitchRank project); this client-side limit guarantees we request the full
# expected payload even if that server-side cap is reduced later.
RPC_RESULT_LIMIT = 200_000


def call_rpc_with_fallback(
    supabase,
    fn_name: str,
    params: Dict[str, Any],
    *,
    fallback: Callable[[], Any],
    limit: Optional[int] = RPC_RESULT_LIMIT,
    log_msg: str = "PERF REGRESSION: RPC missing: %s",
) -> Any:
    """Call a Supabase RPC, fall back to a Python path if the function is missing.

    Triggers `fallback()` only for SQLSTATE 42883 ("function does not exist"),
    which is the expected signal during rolling deploys where the Python code
    is live but the migration has not yet applied. Any other APIError re-raises.

    `limit` controls the max rows returned by PostgREST. It defaults to
    `RPC_RESULT_LIMIT` (200k) so SETOF-returning RPCs don't silently truncate
    at PostgREST's 1000-row default. Pass `None` to omit the query param.

    Returns `res.data` from the RPC on success, or `fallback()`'s return on 42883.
    `log_msg` must contain a single `%s` placeholder for the error.
    """
    try:
        builder = supabase.rpc(fn_name, params)
        if limit is not None:
            builder = builder.limit(limit)
        return builder.execute().data
    except APIError as err:
        if getattr(err, "code", None) == PG_UNDEFINED_FUNCTION:
            logger.error(log_msg, err)
            return fallback()
        raise


def bulk_update_last_scraped_at(
    supabase,
    updates: List[Dict[str, Any]],
    *,
    chunk_size: int = BULK_UPDATE_CHUNK_SIZE,
    on_missing_function: Optional[Callable[[], int]] = None,
    missing_function_log: str = "PERF REGRESSION: bulk_update_last_scraped_at RPC missing: %s",
) -> int:
    """Call `bulk_update_last_scraped_at` in chunks, halving on HTTP 413.

    Returns total rows actually updated (may be < len(updates) if some
    team_id_master values have no matching teams row — logged as a warning).

    If the RPC is missing (SQLSTATE 42883) and `on_missing_function` is
    provided, it is invoked and its return value is returned as the count.
    Without a fallback, 42883 re-raises.
    """
    if not updates:
        return 0

    total_updated = 0
    i = 0
    size = chunk_size
    while i < len(updates):
        chunk = updates[i : i + size]
        try:
            res = supabase.rpc(BULK_UPDATE_RPC, {"updates": chunk}).execute()
            returned = res.data if isinstance(res.data, int) else len(chunk)
            total_updated += returned
            if returned < len(chunk):
                logger.warning(
                    "bulk_update_last_scraped_at: %d of %d rows updated",
                    returned,
                    len(chunk),
                )
            i += len(chunk)
            size = chunk_size
        except APIError as err:
            code = getattr(err, "code", None)
            msg = str(err)
            if code == PG_UNDEFINED_FUNCTION:
                if on_missing_function is not None:
                    logger.error(missing_function_log, err)
                    return on_missing_function()
                raise
            if (code in HTTP_PAYLOAD_TOO_LARGE_CODES or "413" in msg) and size > BULK_UPDATE_MIN_CHUNK:
                new_size = max(size // 2, BULK_UPDATE_MIN_CHUNK)
                logger.warning(
                    "bulk_update_last_scraped_at: 413 on chunk size %d, halving to %d",
                    size,
                    new_size,
                )
                size = new_size
                continue
            logger.warning(
                "Error bulk updating last_scraped_at (chunk %d-%d): %s",
                i,
                i + len(chunk),
                err,
            )
            # Advance by the chunk we actually attempted, not the pre-shrink
            # `size`, so a non-413 error mid-halving doesn't skip rows.
            i += len(chunk)
            size = chunk_size

    return total_updated
