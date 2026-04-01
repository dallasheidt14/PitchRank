#!/usr/bin/env python3
"""
Scrappy Monitor - Check GitHub Actions status and game import summary

Run: python3 scripts/scrappy_monitor.py [--full]
"""

import argparse
import json
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv("/Users/pitchrankio-dev/Projects/PitchRank/.env")

DATABASE_URL = os.getenv("DATABASE_URL")

# Workflows to monitor
WORKFLOWS = [
    {"name": "scrape-games.yml", "display": "GotSport Team Scrape"},
    {"name": "auto-gotsport-event-scrape.yml", "display": "GotSport Event Discovery"},
    {"name": "tgs-event-scrape-import.yml", "display": "TGS Event Scrape"},
    {"name": "calculate-rankings.yml", "display": "Rankings Calculation"},
    {"name": "process-missing-games.yml", "display": "Missing Games Backfill"},
]


def get_connection():
    import psycopg2

    return psycopg2.connect(DATABASE_URL)


def check_workflow_status(workflow_file):
    """Check the status of the last run for a workflow."""
    try:
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow_file,
                "--limit",
                "1",
                "--json",
                "conclusion,status,createdAt,displayTitle,headBranch",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/Users/pitchrankio-dev/Projects/PitchRank",
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        runs = json.loads(result.stdout)
        if not runs:
            return {"status": "no_runs"}

        return runs[0]
    except Exception as e:
        return {"error": str(e)}


def get_game_import_stats(cur, hours=24):
    """Get game import statistics for the last N hours."""
    stats = {}

    # Total games in last N hours
    cur.execute(
        """
        SELECT COUNT(*) FROM games
        WHERE created_at > NOW() - INTERVAL '%s hours'
    """,
        (hours,),
    )
    stats["total_games"] = cur.fetchone()[0]

    # Teams created in last N hours
    cur.execute(
        """
        SELECT COUNT(*) FROM teams
        WHERE created_at > NOW() - INTERVAL '%s hours'
    """,
        (hours,),
    )
    stats["new_teams"] = cur.fetchone()[0]

    # Aliases by provider in last N hours (indicates scrape activity)
    cur.execute(
        """
        SELECT
            COALESCE(p.name, tam.provider_id::text) as provider,
            COUNT(*) as count
        FROM team_alias_map tam
        LEFT JOIN providers p ON tam.provider_id = p.id
        WHERE tam.created_at > NOW() - INTERVAL '%s hours'
        GROUP BY COALESCE(p.name, tam.provider_id::text)
        ORDER BY count DESC
    """,
        (hours,),
    )
    stats["aliases_by_provider"] = cur.fetchall()

    return stats


def get_weekly_stats(cur):
    """Get weekly game import statistics."""
    stats = {}

    # Total games in last 7 days
    cur.execute("""
        SELECT COUNT(*) FROM games
        WHERE created_at > NOW() - INTERVAL '7 days'
    """)
    stats["total_games"] = cur.fetchone()[0]

    # Teams created in last 7 days
    cur.execute("""
        SELECT COUNT(*) FROM teams
        WHERE created_at > NOW() - INTERVAL '7 days'
    """)
    stats["new_teams"] = cur.fetchone()[0]

    # Aliases by provider in last 7 days
    cur.execute("""
        SELECT
            COALESCE(p.name, tam.provider_id::text) as provider,
            COUNT(*) as count
        FROM team_alias_map tam
        LEFT JOIN providers p ON tam.provider_id = p.id
        WHERE tam.created_at > NOW() - INTERVAL '7 days'
        GROUP BY COALESCE(p.name, tam.provider_id::text)
        ORDER BY count DESC
    """)
    stats["aliases_by_provider"] = cur.fetchall()

    return stats


def format_workflow_status(workflow, status_data):
    """Format workflow status for display."""
    if "error" in status_data:
        return f"❓ {workflow['display']}: Error checking ({status_data['error'][:50]})"

    if status_data.get("status") == "no_runs":
        return f"⚪ {workflow['display']}: No runs found"

    conclusion = status_data.get("conclusion")
    status = status_data.get("status")
    created_at = status_data.get("createdAt", "")[:10]

    if status == "in_progress":
        return f"🔄 {workflow['display']}: Running..."
    elif conclusion == "success":
        return f"✅ {workflow['display']}: Success ({created_at})"
    elif conclusion == "failure":
        return f"❌ {workflow['display']}: FAILED ({created_at})"
    elif conclusion == "cancelled":
        return f"⚠️ {workflow['display']}: Cancelled ({created_at})"
    else:
        return f"❓ {workflow['display']}: {conclusion or status} ({created_at})"


def main():
    parser = argparse.ArgumentParser(description="Scrappy Monitor")
    parser.add_argument("--full", action="store_true", help="Full report with weekly stats")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    lines = []
    alerts = []

    # Check workflow statuses
    lines.append("🕷️ **Scrappy Status Report**")
    lines.append("")
    lines.append("**GitHub Actions:**")

    for workflow in WORKFLOWS:
        status = check_workflow_status(workflow["name"])
        line = format_workflow_status(workflow, status)
        lines.append(f"  {line}")

        # Track failures for alerts
        if status.get("conclusion") == "failure":
            alerts.append(workflow["display"])

    # Get database stats
    try:
        conn = get_connection()
        cur = conn.cursor()

        # 24-hour stats
        stats_24h = get_game_import_stats(cur, hours=24)

        lines.append("")
        lines.append("**Last 24 Hours:**")
        lines.append(f"  📊 Games imported: {stats_24h['total_games']:,}")
        lines.append(f"  👥 New teams: {stats_24h['new_teams']:,}")

        if stats_24h["aliases_by_provider"]:
            lines.append("  New aliases by provider:")
            for provider, count in stats_24h["aliases_by_provider"]:
                lines.append(f"    - {provider}: {count:,}")

        # Weekly stats (always check for alerts, display if full report)
        stats_7d = get_weekly_stats(cur)

        # Check for critical alert: no games imported in 7 days
        if stats_7d["total_games"] == 0:
            alerts.append("CRITICAL: No games imported in the last 7 days")

        if args.full:
            lines.append("")
            lines.append("**Last 7 Days:**")
            lines.append(f"  📊 Games imported: {stats_7d['total_games']:,}")
            lines.append(f"  👥 New teams: {stats_7d['new_teams']:,}")

            if stats_7d["aliases_by_provider"]:
                lines.append("  New aliases by provider:")
                for provider, count in stats_7d["aliases_by_provider"]:
                    lines.append(f"    - {provider}: {count:,}")
        else:
            # Even in short mode, show 7-day stats for context
            lines.append("")
            lines.append(f"**Over the last 7 days, we imported {stats_7d['total_games']:,} games**")

        conn.close()
    except Exception as e:
        lines.append("")
        lines.append(f"⚠️ Database error: {str(e)[:100]}")

    # Add alerts section if any failures
    if alerts:
        lines.append("")
        lines.append("🚨 **ALERTS:**")
        for alert in alerts:
            lines.append(f"  - {alert} workflow FAILED!")

    if args.json:
        print(
            json.dumps(
                {
                    "workflows": [{"name": w["name"], "status": check_workflow_status(w["name"])} for w in WORKFLOWS],
                    "alerts": alerts,
                },
                indent=2,
                default=str,
            )
        )
    else:
        print("\n".join(lines))

    # Exit code based on alerts
    if alerts:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
