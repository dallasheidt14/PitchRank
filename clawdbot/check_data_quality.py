#!/usr/bin/env python3
"""
PitchRank Data Quality Checker for Clawdbot

This script runs data quality checks and reports issues found.
It is READ-ONLY and safe to run at any time.

Usage:
    python clawdbot/check_data_quality.py                    # Run all checks
    python clawdbot/check_data_quality.py --check age        # Run specific check
    python clawdbot/check_data_quality.py --json             # Output as JSON
    python clawdbot/check_data_quality.py --alert            # Send alert if issues found
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataQualityReport:
    """Container for data quality check results"""

    def __init__(self):
        self.checks_run = []
        self.issues = []
        self.summary = {}
        self.checked_at = datetime.now().isoformat()

    def add_check(self, name: str, issues: List[Dict], severity: str = "medium"):
        """Add a check result to the report"""
        self.checks_run.append(name)
        for issue in issues:
            issue["check"] = name
            issue["severity"] = severity
            self.issues.append(issue)
        self.summary[name] = len(issues)

    def to_dict(self) -> Dict:
        return {
            "checked_at": self.checked_at,
            "checks_run": self.checks_run,
            "total_issues": len(self.issues),
            "summary": self.summary,
            "issues": self.issues[:100]  # Limit to first 100
        }

    def to_alert_message(self) -> str:
        """Format report as an alert message for chat"""
        if not self.issues:
            return "✅ PitchRank Data Quality: All checks passed!"

        lines = [
            "🔍 **PitchRank Data Quality Report**",
            "",
            f"Found **{len(self.issues)}** issues:",
            ""
        ]

        for check, count in self.summary.items():
            if count > 0:
                emoji = "⚠️" if count > 10 else "📋"
                lines.append(f"{emoji} {check}: {count}")

        lines.extend([
            "",
            "**Top Issues:**"
        ])

        # Show first 5 issues
        for issue in self.issues[:5]:
            team_name = issue.get("team_name", "Unknown")[:30]
            check = issue.get("check", "")
            lines.append(f"  - {team_name} ({check})")

        if len(self.issues) > 5:
            lines.append(f"  ... and {len(self.issues) - 5} more")

        lines.extend([
            "",
            "Reply **FIX-AGE** to approve age group fixes",
            "Reply **FIX-STATE** to approve state code fixes",
            "Reply **DETAILS** for full report"
        ])

        return "\n".join(lines)


class DataQualityChecker:
    """
    Comprehensive data quality checker for PitchRank.
    All operations are READ-ONLY.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client
        self.report = DataQualityReport()

    def run_all_checks(self) -> DataQualityReport:
        """Run all data quality checks"""
        logger.info("Running all data quality checks...")

        self.check_age_group_mismatches()
        self.check_missing_state_codes()
        self.check_stale_teams()
        self.check_pending_requests()
        self.check_review_queue()

        logger.info(f"Checks complete. Found {len(self.report.issues)} issues.")
        return self.report

    def check_age_group_mismatches(self) -> List[Dict]:
        """Find teams where age_group doesn't match birth year in name"""
        import re

        logger.info("Checking age group mismatches...")
        current_year = 2025

        # Fetch all teams (paginated)
        all_teams = []
        offset = 0
        batch_size = 1000

        while True:
            result = self.supabase.table("teams")\
                .select("team_id_master, team_name, age_group")\
                .range(offset, offset + batch_size - 1)\
                .execute()

            if not result.data:
                break

            all_teams.extend(result.data)
            if len(result.data) < batch_size:
                break
            offset += batch_size

        mismatches = []
        for team in all_teams:
            team_name = team.get("team_name", "")
            current_age = (team.get("age_group") or "").lower()

            # Check for two-year patterns first (e.g., 2013/2014)
            two_year_match = re.search(r'(?<![0-9])(20\d{2})[/-](20\d{2})(?![0-9])', team_name)
            if two_year_match:
                year1 = int(two_year_match.group(1))
                year2 = int(two_year_match.group(2))
                birth_year = min(year1, year2)
            else:
                # Single year match
                match = re.search(r'(?<![0-9])(20\d{2})(?![0-9])', team_name)
                if not match:
                    continue
                birth_year = int(match.group(1))

            # Validate birth year range
            if not (2005 <= birth_year <= 2018):
                continue

            expected_age = current_year - birth_year + 1
            expected_group = f"u{expected_age}"

            if 7 <= expected_age <= 19 and expected_group != current_age:
                mismatches.append({
                    "team_id": team["team_id_master"],
                    "team_name": team_name,
                    "current": current_age,
                    "expected": expected_group,
                    "birth_year": birth_year
                })

        self.report.add_check("age_group_mismatches", mismatches, severity="medium")
        logger.info(f"Found {len(mismatches)} age group mismatches")
        return mismatches

    def check_missing_state_codes(self) -> List[Dict]:
        """Find teams without state_code that have a club with state_code"""
        logger.info("Checking missing state codes...")

        # Teams without state_code but with club_name
        result = self.supabase.table("teams")\
            .select("team_id_master, team_name, club_name")\
            .is_("state_code", "null")\
            .not_.is_("club_name", "null")\
            .limit(500)\
            .execute()

        missing = result.data or []
        self.report.add_check("missing_state_codes", missing, severity="low")
        logger.info(f"Found {len(missing)} teams missing state codes")
        return missing

    def check_stale_teams(self) -> List[Dict]:
        """Find teams that haven't been scraped in over 14 days"""
        logger.info("Checking stale teams...")

        cutoff = (datetime.now() - timedelta(days=14)).isoformat()

        result = self.supabase.table("teams")\
            .select("team_id_master, team_name, last_scraped_at")\
            .lt("last_scraped_at", cutoff)\
            .limit(100)\
            .execute()

        stale = result.data or []
        self.report.add_check("stale_teams", stale, severity="low")
        logger.info(f"Found {len(stale)} stale teams")
        return stale

    def check_pending_requests(self) -> List[Dict]:
        """Check for pending scrape requests"""
        logger.info("Checking pending scrape requests...")

        result = self.supabase.table("scrape_requests")\
            .select("id, team_name, game_date, requested_at")\
            .eq("status", "pending")\
            .order("requested_at")\
            .limit(50)\
            .execute()

        pending = result.data or []
        self.report.add_check("pending_scrape_requests", pending, severity="high")
        logger.info(f"Found {len(pending)} pending scrape requests")
        return pending

    def check_review_queue(self) -> List[Dict]:
        """Check for items in review queue"""
        logger.info("Checking review queue...")

        result = self.supabase.table("team_match_review_queue")\
            .select("id, suggested_team_name, confidence_score, created_at")\
            .eq("status", "pending")\
            .order("created_at")\
            .limit(50)\
            .execute()

        pending = result.data or []
        self.report.add_check("pending_reviews", pending, severity="medium")
        logger.info(f"Found {len(pending)} items in review queue")
        return pending


def main():
    parser = argparse.ArgumentParser(description="PitchRank Data Quality Checker")
    parser.add_argument("--check", type=str, choices=["age", "state", "stale", "requests", "reviews"],
                        help="Run specific check only")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--alert", action="store_true", help="Format as alert message")
    args = parser.parse_args()

    # Initialize Supabase
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        sys.exit(1)

    client = create_client(url, key)
    checker = DataQualityChecker(client)

    # Run checks
    if args.check:
        check_map = {
            "age": checker.check_age_group_mismatches,
            "state": checker.check_missing_state_codes,
            "stale": checker.check_stale_teams,
            "requests": checker.check_pending_requests,
            "reviews": checker.check_review_queue
        }
        check_map[args.check]()
    else:
        checker.run_all_checks()

    # Output results
    if args.json:
        print(json.dumps(checker.report.to_dict(), indent=2))
    elif args.alert:
        print(checker.report.to_alert_message())
    else:
        # Human-readable output
        print("\n" + "=" * 60)
        print("PITCHRANK DATA QUALITY REPORT")
        print("=" * 60)
        print(f"Checked at: {checker.report.checked_at}")
        print(f"Total issues: {len(checker.report.issues)}")
        print()

        for check, count in checker.report.summary.items():
            status = "✅" if count == 0 else "⚠️"
            print(f"{status} {check}: {count} issues")

        if checker.report.issues:
            print("\n" + "-" * 60)
            print("TOP ISSUES:")
            print("-" * 60)
            for issue in checker.report.issues[:10]:
                print(f"  [{issue['check']}] {issue.get('team_name', 'Unknown')[:50]}")

        print("=" * 60)


if __name__ == "__main__":
    main()
