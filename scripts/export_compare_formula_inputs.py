"""Freeze verified v8 inputs for formula research. Never select target scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    sys.dont_write_bytecode = True

from src.predictions.private_research_output import private_output_path  # noqa: E402


def run(client, signature, *, execute=False, output=None):
    output = private_output_path(execute, output)
    pin = json.loads((ROOT / "frontend/lib/compareFormulaPin.json").read_text(encoding="utf-8"))
    model = (
        client.table("compare_monitoring_models")
        .select("signature,manifest")
        .eq("signature", signature)
        .single()
        .execute()
        .data
    )
    manifest = model["manifest"]
    if (
        manifest["model_version"] != pin["model_version"]
        or manifest["code_revision"] != pin["revision"]
        or not manifest.get("runtime_profile")
    ):
        raise ValueError("Only verified collecting v8 inputs are eligible")
    cutoff = client.rpc("compare_monitor_clock", {}).execute().data
    metadata = []
    offset = 0
    while True:
        page = (
            client.table("compare_monitoring_forecasts")
            .select("baseline_forecast_id,captured_at,history_as_of:payload->context->frozenEvidence->>as_of")
            .eq("monitor_signature", signature)
            .lte("captured_at", cutoff)
            .order("baseline_forecast_id")
            .range(offset, offset + 999)
            .execute()
            .data
            or []
        )
        metadata.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    eligible, withheld, unbounded, release_days = [], [], [], {}
    for row in metadata:
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        try:
            history_day = date.fromisoformat(row.get("history_as_of"))
            if history_day.isoformat() != row["history_as_of"]:
                raise ValueError("Noncanonical history cutoff")
        except (TypeError, ValueError):
            unbounded.append(row)
            continue
        last_history_day = max(captured.date(), history_day).isoformat()
        if last_history_day not in release_days:
            release_days[last_history_day] = (
                client.rpc("compare_monitor_results_open", {"p_day": last_history_day}).execute().data is True
            )
        # Active seals extend through today, so open past days form a prefix. The
        # frozen fetch cutoff bounds omitted records even when the collector's
        # clock crosses midnight ahead of the server capture clock.
        (eligible if release_days[last_history_day] else withheld).append(row)
    rows = []
    result = {
        "captures": len(eligible),
        "found": len(metadata),
        "withheld_history_seals": len(withheld),
        "withheld_missing_history_bound": len(unbounded),
        "cutoff": cutoff,
        "output_written": execute,
    }
    if execute:
        for start in range(0, len(eligible), 100):
            batch = {row["baseline_forecast_id"]: row["captured_at"] for row in eligible[start : start + 100]}
            fields = "baseline_forecast_id,captured_at,payload,payload_sha256"
            fields += ",prospective_match_predictions!inner(game_date,provider_code)"
            page = (
                client.table("compare_monitoring_forecasts")
                .select(fields)
                .eq("monitor_signature", signature)
                .in_("baseline_forecast_id", list(batch))
                .order("baseline_forecast_id")
                .range(0, 99)
                .execute()
                .data
                or []
            )
            if {row["baseline_forecast_id"] for row in page} != set(batch) or any(
                row["captured_at"] != batch[row["baseline_forecast_id"]] for row in page
            ):
                raise ValueError("Frozen capture inventory changed")
            for row in page:
                fixture = row.pop("prospective_match_predictions")
                row.update(game_date=fixture["game_date"], provider=fixture["provider_code"])
                rows.append(row)
        serialized = json.dumps(
            {
                "cutoff": cutoff,
                "model": model,
                "rows": rows,
                "withheld": withheld,
                "withheld_missing_history_bound": unbounded,
                "history_release_days": release_days,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with output.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
        result["sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    print(json.dumps(run(client, args.signature, execute=args.execute, output=args.output)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Formula input export failed; no forecasts changed.")
        raise SystemExit(1)
