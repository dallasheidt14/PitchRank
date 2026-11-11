"""Read-only Compare research; --execute saves local artifacts, never database rows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.form_research import (  # noqa: E402
    FORM_CANDIDATES,
    PINNED_REVISION,
    ResearchPolicy,
    audit_cases,
    compare_outputs,
    digest,
    residual_form,
    write_bundle,
)

COVERAGE_QUERY = """
WITH targets AS MATERIALIZED (
 SELECT g.game_date,g.home_team_master_id,g.away_team_master_id,g.home_score,g.away_score,
  g.age_group,g.is_excluded,g.game_uid,coalesce(p.code,'unknown') AS provider,
  CASE WHEN g.game_date <= '2026-10-11' THEN 'development' ELSE 'evaluation' END AS period
 FROM public.games g LEFT JOIN public.providers p ON p.id=g.provider_id
 WHERE g.game_date BETWEEN '{start}' AND '{end}'
), team_days AS (
 SELECT home_team_master_id AS team_id,game_date FROM targets
 UNION SELECT away_team_master_id,game_date FROM targets
), snapshots AS MATERIALIZED (
 SELECT d.team_id,d.game_date,h.games_played
 FROM team_days d LEFT JOIN LATERAL (
  SELECT h.games_played FROM public.prediction_feature_history h
  WHERE h.team_id=d.team_id AND h.snapshot_date<d.game_date
   AND h.created_at<(d.game_date::timestamp AT TIME ZONE 'UTC')
   AND h.last_calculated<(d.game_date::timestamp AT TIME ZONE 'UTC')
  ORDER BY h.snapshot_date DESC LIMIT 1
 )h ON true
), coverage AS (
 SELECT t.period,t.provider,coalesce(t.age_group,'unknown') AS recorded_age_group,
  CASE WHEN a.games_played IS NULL OR b.games_played IS NULL THEN 'unavailable'
   WHEN least(a.games_played,b.games_played)=0 THEN '0'
   WHEN least(a.games_played,b.games_played)<4 THEN '1-3'
   WHEN least(a.games_played,b.games_played)<8 THEN '4-7' ELSE '8+' END AS snapshot_history_band,
  count(*) AS target_rows,
  count(*) FILTER (WHERE coalesce(t.is_excluded,false)) AS excluded_rows,
  count(*) FILTER (WHERE t.game_uid IS NULL) AS missing_source_identity_rows,
  count(*) FILTER (WHERE t.home_team_master_id IS NULL OR t.away_team_master_id IS NULL) AS unmatched_team_rows,
  count(*) FILTER (WHERE t.home_score IS NULL OR t.away_score IS NULL) AS missing_result_rows,
  count(*) FILTER (WHERE a.games_played IS NULL OR b.games_played IS NULL) AS unavailable_snapshot_rows
 FROM targets t
 LEFT JOIN snapshots a ON a.team_id=t.home_team_master_id AND a.game_date=t.game_date
 LEFT JOIN snapshots b ON b.team_id=t.away_team_master_id AND b.game_date=t.game_date
 GROUP BY 1,2,3,4
)
SELECT current_setting('transaction_read_only') AS read_only,
 coalesce(jsonb_agg(x),'[]'::jsonb) AS coverage FROM (SELECT * FROM coverage
 ORDER BY period,provider,recorded_age_group,snapshot_history_band)x;
"""

INVENTORY_QUERY = """
SELECT jsonb_build_object(
 'snapshot_columns',(SELECT jsonb_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns
  WHERE table_schema='public' AND table_name='prediction_feature_history'),
 'development_snapshots',(SELECT count(*) FROM public.prediction_feature_history
  WHERE snapshot_date BETWEEN '2026-08-17' AND '2026-10-11'),
 'evaluation_snapshots',(SELECT count(*) FROM public.prediction_feature_history
  WHERE snapshot_date BETWEEN '2026-10-12' AND '2026-11-08'),
 'training_run_columns',(SELECT jsonb_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns
  WHERE table_schema='public' AND table_name='model_training_runs'),
 'recent_training_runs',(SELECT jsonb_agg(x) FROM (SELECT model_version,created_at,git_sha,model_dir
  FROM public.model_training_runs ORDER BY created_at DESC LIMIT 3)x),
 'read_only',current_setting('transaction_read_only')) AS inventory;
"""


def inventory_report(inventory: dict) -> dict:
    columns = set(inventory.get("snapshot_columns") or [])
    missing = sorted({"training_run_id", "training_cutoff", "calibration_signature"} - columns)
    return {
        "status": "inventory_only",
        "historical_selection": "not_performed",
        "inventory": inventory,
        "missing_snapshot_lineage": missing,
        "coverage_unit": "database_rows_before_source_deduplication",
        "verified_eligible": {period: {"matches": 0, "groups": 0} for period in ("development", "evaluation")},
        "coverage_limits": "Recorded game age groups and snapshot-reported history are inventory labels, not "
        "verified pre-match predictor inputs or usable residual samples. Zero verified eligibility reflects "
        "unresolved lineage, not a claim that no historical matches can ever qualify. Exclusion counts overlap.",
        "remedy": "Supply immutable per-snapshot training/calibration lineage, or a verified external "
        "manifest linking exact snapshot hashes to artifacts and pre-match training cutoffs. "
        "Existing offline-model runs do not establish ranking-feature lineage.",
        "production_promotion": False,
    }


def read_inventory() -> dict:
    import requests
    from dotenv import dotenv_values

    cfg = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local"), **os.environ}
    project_url = cfg.get("SUPABASE_URL", "")
    host = urlparse(project_url).hostname
    if not host or not host.endswith(".supabase.co") or not cfg.get("SUPABASE_ACCESS_TOKEN"):
        raise ValueError("Configure existing Supabase URL and management access token")
    ref = host.split(".")[0]

    def query(sql: str) -> dict:
        response = requests.post(
            f"https://api.supabase.com/v1/projects/{ref}/database/query/read-only",
            headers={"Authorization": "Bearer " + cfg["SUPABASE_ACCESS_TOKEN"]},
            json={"query": sql},
            timeout=40,
            allow_redirects=False,
        )
        if not response.ok:
            raise ValueError(f"Read-only inventory failed (HTTP {response.status_code})")
        return response.json()[0]

    result = query(INVENTORY_QUERY)["inventory"]
    if result["read_only"] != "on":
        raise ValueError("Database read-only mode not confirmed")
    result["target_coverage"] = []
    # Disjoint weekly batches bound each indexed as-of lookup query; never retry a full-range scan.
    for start, end in coverage_windows():
        chunk = query(COVERAGE_QUERY.format(start=start, end=end))
        if chunk["read_only"] != "on":
            raise ValueError("Database read-only mode not confirmed")
        result["target_coverage"].extend({**row, "week_start": start, "week_end": end} for row in chunk["coverage"])
    return result


def coverage_windows() -> list[tuple[str, str]]:
    policy = ResearchPolicy()
    windows = []
    for start, end in (
        (policy.development_start, policy.development_end),
        (policy.evaluation_start, policy.evaluation_end),
    ):
        day, last = date.fromisoformat(start), date.fromisoformat(end)
        while day <= last:
            end_day = min(day + timedelta(days=6), last)
            windows.append((day.isoformat(), end_day.isoformat()))
            day = end_day + timedelta(days=1)
    return windows


def run_predictor(bundle: dict, output: Path) -> dict:
    input_path = output / "runner-input.json"
    input_path.write_text(json.dumps(bundle, allow_nan=False), encoding="utf-8")
    runner_output = output / "runner-output.json"
    command = [
        str(ROOT / "frontend/node_modules/.bin/tsx"),
        str(ROOT / "frontend/scripts/run-form-research.ts"),
        str(input_path.resolve()),
        str(runner_output.resolve()),
    ]
    # Invoke the installed JS entry point directly; Windows .cmd wrappers need a shell.
    if os.name == "nt":
        command = ["node", str(ROOT / "frontend/node_modules/tsx/dist/cli.mjs"), *command[1:]]
    # Windows keeps imported modules open until the child exits; the caller owns cleanup.
    with TemporaryDirectory(prefix="compare-form-research-") as workspace:
        subprocess.run(
            [*command, workspace], check=True, cwd=ROOT / "frontend", timeout=1800, capture_output=True, text=True
        )
    result = json.loads(runner_output.read_text(encoding="utf-8"))
    if not result.get("aa_parity") or result.get("predictor_revision") != PINNED_REVISION:
        raise ValueError("Pinned baseline parity not established")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Frozen research JSON bundle")
    source.add_argument("--database-audit", action="store_true", help="Read-only aggregate lineage inventory")
    parser.add_argument("--output-dir", type=Path, help="New local artifact directory; required with --execute")
    parser.add_argument("--execute", action="store_true", help="Save local research artifacts; no database writes")
    parser.add_argument(
        "--parity-only", action="store_true", help="Replay frozen forecasts without inspecting outcomes"
    )
    args = parser.parse_args()
    if args.execute and not args.output_dir:
        parser.error("--execute requires --output-dir")
    if args.parity_only and (not args.input or not args.execute):
        parser.error("--parity-only requires --input and --execute")
    if args.database_audit:
        queries = {"inventory": INVENTORY_QUERY, "coverage": COVERAGE_QUERY, "coverage_windows": coverage_windows()}
        inputs = {**queries, "query_hash": digest(queries)}
        report = inventory_report(read_inventory())
    else:
        inputs = json.loads(args.input.read_text(encoding="utf-8"))
        if inputs.get("schema_version") != 1 or inputs.get("predictor_revision") != PINNED_REVISION:
            raise ValueError("Wrong frozen bundle schema or predictor revision")
        for case in inputs["cases"]:
            case["calibrations"] = inputs.get("calibrations", {})
        eligible, audit = audit_cases(inputs["cases"], ResearchPolicy())
        report = {"status": audit["status"], "audit": audit, "production_promotion": False}
        if args.parity_only:
            report = {"status": "parity_only", "production_promotion": False}
        elif args.execute and audit["status"] == "eligible":
            for case in eligible:
                case["formDiagnostics"] = {
                    name: {
                        case[team]["team_id_master"]: residual_form(
                            case[team]["team_id_master"],
                            case["games"],
                            case.get("expectations", {}),
                            case["fixture"]["game_date"],
                            name,
                        )
                        for team in ("teamA", "teamB")
                    }
                    for name in FORM_CANDIDATES[1:]
                }
                case["formOverrides"] = {
                    name: {team: value["value"] for team, value in values.items()}
                    for name, values in case["formDiagnostics"].items()
                }
            inputs = {**inputs, "cases": eligible}
    write_bundle(args.output_dir, inputs, report, dry_run=not args.execute)
    if args.input and args.execute and (args.parity_only or report["status"] == "eligible"):
        result = run_predictor(inputs, args.output_dir)
        report = (
            {**report, "aa_parity": result["aa_parity"], "cases": result["cases"]}
            if args.parity_only
            else compare_outputs(inputs["cases"], result["outputs"], ResearchPolicy())
        )
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
