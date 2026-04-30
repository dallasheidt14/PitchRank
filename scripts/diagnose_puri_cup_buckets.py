"""Query build_logs for recent SincSports tournament imports.

Per gotcha_import_games_enhanced_dedup.md: IMPORT_RESULT line under-reports
because only 4 of the 19 ImportMetrics counters are surfaced. The full
counters live in build_logs.metrics (JSONB).

Goal: surface the bucket distribution for any sincsports game_import runs
in the last week, focused on the Puri Cup window (~2026-04-25). If a single
clear "silent" bucket dominates, that's the real root cause.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Bridge SUPABASE_KEY <- SUPABASE_SERVICE_ROLE_KEY per memory
# gotcha_supabase_key_env_mismatch.md
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

env_local = Path(__file__).parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv(Path(__file__).parent.parent / ".env")

if not os.environ.get("SUPABASE_KEY") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

from supabase import create_client  # noqa: E402

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("ERROR: SUPABASE_URL or SUPABASE_KEY missing", file=sys.stderr)
    sys.exit(1)

sb = create_client(url, key)

# 1. Find the SincSports provider_id (UUID)
prov = sb.table("providers").select("id, code").eq("code", "sincsports").execute()
if not prov.data:
    print("No sincsports provider row found", file=sys.stderr)
    sys.exit(1)
sincsports_provider_id = prov.data[0]["id"]
print(f"sincsports provider_id (UUID): {sincsports_provider_id}\n")

# 2. Pull recent build_logs rows for sincsports game_import stage
rows = (
    sb.table("build_logs")
    .select(
        "build_id, started_at, completed_at, records_processed, records_succeeded, records_failed, metrics, parameters"
    )
    .eq("stage", "game_import")
    .eq("provider_id", sincsports_provider_id)
    .gte("started_at", "2026-04-20")
    .order("started_at", desc=True)
    .limit(20)
    .execute()
)

if not rows.data:
    print("No sincsports game_import rows in build_logs since 2026-04-20")
    sys.exit(0)

print(f"Found {len(rows.data)} sincsports game_import runs since 2026-04-20:\n")

# 3. For each row, surface the full bucket distribution
for r in rows.data:
    build_id = r.get("build_id")
    started = r.get("started_at", "")
    metrics = r.get("metrics") or {}
    params = r.get("parameters") or {}

    processed = metrics.get("games_processed", 0)
    accepted = metrics.get("games_accepted", 0)
    quarantined = metrics.get("games_quarantined", 0)
    dup_found = metrics.get("duplicates_found", 0)
    dup_skipped = metrics.get("duplicates_skipped", 0)
    failed_match = metrics.get("failed_games_count", 0)
    empty_pid = metrics.get("skipped_empty_provider_ids", 0)
    empty_date = metrics.get("skipped_empty_game_date", 0)
    empty_scores = metrics.get("skipped_empty_scores", 0)
    dup_key_viol = metrics.get("duplicate_key_violations", 0)
    teams_matched = metrics.get("teams_matched", 0)
    teams_created = metrics.get("teams_created", 0)
    matched_count = metrics.get("matched_games_count", 0)
    partial_count = metrics.get("partial_games_count", 0)

    # Sum of input-consuming buckets
    bucket_sum = (
        accepted
        + quarantined
        + dup_found
        + dup_skipped
        + failed_match
        + empty_pid
        + empty_date
        + empty_scores
        + dup_key_viol
    )
    drift = processed - bucket_sum

    print(f"--- {started}  build_id={build_id}")
    print(f"    parameters={json.dumps(params)}")
    print(
        f"    processed={processed:>5} | accepted={accepted:>5} | quarantined={quarantined:>4} "
        f"| dup_found={dup_found:>4} | dup_skipped={dup_skipped:>4}"
    )
    print(
        f"    failed_match={failed_match:>4} | empty_pid={empty_pid:>3} | empty_date={empty_date:>3} "
        f"| empty_scores={empty_scores:>3} | dup_key_viol={dup_key_viol:>3}"
    )
    print(
        f"    teams_matched={teams_matched:>4} | teams_created={teams_created:>3} "
        f"| matched_games={matched_count:>4} | partial_games={partial_count:>3}"
    )
    print(f"    BUCKET SUM = {bucket_sum} (drift from processed = {drift})")
    print()
