#!/usr/bin/env python3
"""
Qualityy gate script: collect pre-ranking telemetry and emit PASS/WARN/FAIL verdicts.

Usage:
    python3 scripts/qualityy_gate.py --write-status
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2 import OperationalError
from dotenv import load_dotenv
import requests

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "system_status.md")
SCORECARD_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "system_scorecard.json")

THRESHOLDS = {
    "games_24h_fail": 0,
    "games_24h_warn": 250,
    "quarantine_warn": 1000,
    "quarantine_fail": 2000,
    "stale_team_warn": 15000,
}


def fetch_metrics_sql(cur):
    cur.execute("SELECT COUNT(*) FROM games WHERE created_at > NOW() - INTERVAL '24 hours'")
    games_24h = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM quarantine_games")
    quarantine = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*)
        FROM teams
        WHERE last_scraped_at IS NULL
           OR last_scraped_at < NOW() - INTERVAL '7 days'
        """
    )
    stale_teams = cur.fetchone()[0]

    return {
        "games_24h": games_24h,
        "quarantine": quarantine,
        "stale_teams": stale_teams,
    }


def _supabase_headers():
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        raise RuntimeError("Supabase REST credentials not configured")
    return supabase_url.rstrip("/"), {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Prefer": "count=exact",
        "Accept": "application/json",
    }


def _extract_count(response):
    content_range = response.headers.get("content-range")
    if content_range and "/" in content_range:
        try:
            return int(content_range.split("/")[-1])
        except ValueError:
            pass
    try:
        data = response.json()
    except ValueError:
        return 0
    return len(data)


def _supabase_count(table, params):
    base_url, headers = _supabase_headers()
    final_params = {"select": "id", "limit": "1"}
    final_params.update(params)
    resp = requests.get(
        f"{base_url}/rest/v1/{table}",
        headers=headers,
        params=final_params,
        timeout=30,
    )
    resp.raise_for_status()
    return _extract_count(resp)


def fetch_metrics_supabase_rest():
    now = datetime.now(timezone.utc)
    games_cutoff = (now - timedelta(hours=24)).isoformat()
    stale_cutoff = (now - timedelta(days=7)).isoformat()

    games_24h = _supabase_count("games", {"created_at": f"gte.{games_cutoff}"})
    quarantine = _supabase_count("quarantine_games", {})
    stale_teams = _supabase_count(
        "teams",
        {
            "or": f"(last_scraped_at.is.null,last_scraped_at.lt.{stale_cutoff})",
        },
    )

    return {
        "games_24h": games_24h,
        "quarantine": quarantine,
        "stale_teams": stale_teams,
    }


def fetch_metrics(db_url):
    if db_url:
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    metrics = fetch_metrics_sql(cur)
                    metrics["source"] = "postgres"
                    return metrics
        except OperationalError as exc:
            print(f"WARN: direct DB connection failed ({exc}); falling back to Supabase REST")

    metrics = fetch_metrics_supabase_rest()
    metrics["source"] = "supabase_rest"
    return metrics


def grade(metrics):
    verdict = "PASS"
    notes = []

    if metrics["games_24h"] is None:
        return "FAIL", ["Telemetry metrics unavailable"]

    if metrics["games_24h"] <= THRESHOLDS["games_24h_fail"]:
        verdict = "FAIL"
        notes.append("No games ingested in the last 24h")
    elif metrics["games_24h"] < THRESHOLDS["games_24h_warn"]:
        verdict = "WARN"
        notes.append(f"Low ingestion volume ({metrics['games_24h']})")

    if metrics["quarantine"] >= THRESHOLDS["quarantine_fail"]:
        verdict = "FAIL"
        notes.append(f"Quarantine backlog critical ({metrics['quarantine']})")
    elif metrics["quarantine"] >= THRESHOLDS["quarantine_warn"] and verdict != "FAIL":
        verdict = "WARN"
        notes.append(f"Quarantine backlog high ({metrics['quarantine']})")

    if metrics["stale_teams"] >= THRESHOLDS["stale_team_warn"] and verdict != "FAIL":
        verdict = "WARN"
        notes.append(f"{metrics['stale_teams']} teams not scraped in >7 days")

    return verdict, notes


def write_scorecard(metrics, verdict):
    try:
        with open(SCORECARD_PATH, "r", encoding="utf-8") as fh:
            scorecard = json.load(fh)
    except FileNotFoundError:
        scorecard = {}

    scorecard.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "games_ingested_24h": metrics.get("games_24h"),
            "quarantine_backlog": metrics.get("quarantine"),
            "pipeline_freshness_hours": None,
            "duplicate_team_candidates": scorecard.get("duplicate_team_candidates"),
            "open_incidents": 0 if verdict == "PASS" else 1,
        }
    )

    with open(SCORECARD_PATH, "w", encoding="utf-8") as fh:
        json.dump(scorecard, fh, indent=2)


def append_report(verdict, metrics, notes):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M MT")
    block = [
        "## Qualityy Gate",
        f"_Updated: {stamp}_",
        f"**Verdict:** {verdict}",
        f"- Games (24h): {metrics.get('games_24h', 'n/a')}",
        f"- Quarantine backlog: {metrics.get('quarantine', 'n/a')}",
        f"- Stale teams (>7d): {metrics.get('stale_teams', 'n/a')}",
    ]
    if notes:
        block.append("- Notes: " + "; ".join(notes))

    try:
        with open(REPORT_PATH, "r", encoding="utf-8") as fh:
            existing = fh.read().split("## Qualityy Gate")[0].rstrip()
    except FileNotFoundError:
        existing = "# PitchRank System Status\n"

    new_content = existing + "\n\n" + "\n".join(block) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_content)


def main():
    parser = argparse.ArgumentParser(description="Run the Qualityy gate")
    parser.add_argument("--write-status", action="store_true", help="Update telemetry files")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    db_url = os.getenv("DATABASE_URL")

    try:
        metrics = fetch_metrics(db_url)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"ERROR: Telemetry collection failed: {exc}")
        metrics = {"games_24h": None, "quarantine": None, "stale_teams": None}
        verdict = "FAIL"
        notes = ["Telemetry collection failed"]
    else:
        verdict, notes = grade(metrics)

    print(json.dumps({"verdict": verdict, "metrics": metrics, "notes": notes}, indent=2))

    if args.write_status:
        write_scorecard(metrics, verdict)
        append_report(verdict, metrics, notes)


if __name__ == "__main__":
    main()
