#!/usr/bin/env python3
"""
PitchRank Clawdbot Runner

This is the main entry point for the Clawdbot automation agent.
It runs continuously and executes scheduled tasks.

Usage:
    python clawdbot/runner.py                    # Run in safe mode (observer)
    python clawdbot/runner.py --mode safe_writer # Allow safe writes
    python clawdbot/runner.py --mode supervised  # Allow approved operations
    python clawdbot/runner.py --once             # Run once and exit

Environment:
    CLAWDBOT_MODE: Operating mode (observer, safe_writer, supervised)
    CLAWDBOT_ALERT_WEBHOOK: Webhook URL for sending alerts
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Optional
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# Load environment
env_local = PROJECT_ROOT / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("clawdbot")


class ClawdbotRunner:
    """
    Main runner for PitchRank Clawdbot automation.

    Executes scheduled tasks in a safe, controlled manner.
    """

    # Task schedule (minutes between runs)
    SCHEDULE = {
        "check_data_quality": 240,      # Every 4 hours
        "process_missing_games": 15,    # Every 15 minutes
        "check_review_queue": 60,       # Every hour
        "cleanup_old_logs": 1440,       # Once a day
    }

    def __init__(self, mode: str = "observer"):
        self.mode = mode
        self.running = True
        self.last_run: Dict[str, datetime] = {}
        self.stats = {
            "tasks_run": 0,
            "errors": 0,
            "started_at": datetime.now().isoformat()
        }

        # Initialize Supabase
        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

        self.supabase = create_client(url, key)
        logger.info(f"ClawdbotRunner initialized in '{mode}' mode")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        logger.info("Shutdown signal received, stopping...")
        self.running = False

    def should_run_task(self, task_name: str) -> bool:
        """Check if a task should run based on schedule"""
        if task_name not in self.SCHEDULE:
            return False

        interval = timedelta(minutes=self.SCHEDULE[task_name])
        last = self.last_run.get(task_name)

        if last is None:
            return True

        return datetime.now() - last >= interval

    def run_task(self, task_name: str) -> bool:
        """Execute a scheduled task"""
        logger.info(f"Running task: {task_name}")

        try:
            if task_name == "check_data_quality":
                return self._task_check_data_quality()
            elif task_name == "process_missing_games":
                return self._task_process_missing_games()
            elif task_name == "check_review_queue":
                return self._task_check_review_queue()
            elif task_name == "cleanup_old_logs":
                return self._task_cleanup_old_logs()
            else:
                logger.warning(f"Unknown task: {task_name}")
                return False

        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}")
            self.stats["errors"] += 1
            return False

        finally:
            self.last_run[task_name] = datetime.now()
            self.stats["tasks_run"] += 1

    def _task_check_data_quality(self) -> bool:
        """Run data quality checks"""
        script = PROJECT_ROOT / "clawdbot" / "check_data_quality.py"

        result = subprocess.run(
            [sys.executable, str(script), "--alert"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )

        if result.returncode != 0:
            logger.error(f"Data quality check failed: {result.stderr}")
            return False

        # Parse and maybe send alert
        alert_message = result.stdout.strip()
        if "issues" in alert_message.lower() and "0 issues" not in alert_message.lower():
            self._send_alert(alert_message)

        logger.info("Data quality check completed")
        return True

    def _task_process_missing_games(self) -> bool:
        """Process pending scrape requests"""
        if self.mode == "observer":
            logger.info("Skipping process_missing_games in observer mode")
            return True

        script = PROJECT_ROOT / "scripts" / "process_missing_games.py"

        # Always use dry-run in safe_writer mode unless explicitly approved
        args = [sys.executable, str(script), "--limit", "5"]
        if self.mode == "safe_writer":
            # In safe_writer mode, we DO process requests (it's adding new data, not modifying)
            pass  # No dry-run needed for imports
        else:
            args.append("--dry-run")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )

        if result.returncode != 0:
            logger.error(f"Missing games processing failed: {result.stderr}")
            return False

        logger.info("Missing games processing completed")
        return True

    def _task_check_review_queue(self) -> bool:
        """Check and report on review queue"""
        try:
            result = self.supabase.table("team_match_review_queue")\
                .select("id", count="exact")\
                .eq("status", "pending")\
                .execute()

            count = result.count or 0
            if count > 10:
                self._send_alert(f"📋 Review queue has {count} pending items")

            logger.info(f"Review queue: {count} pending items")
            return True

        except Exception as e:
            logger.error(f"Review queue check failed: {e}")
            return False

    def _task_cleanup_old_logs(self) -> bool:
        """Clean up old log entries (safe operation)"""
        # This is a read operation to identify old logs
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()

        try:
            result = self.supabase.table("clawdbot_audit_log")\
                .select("id", count="exact")\
                .lt("timestamp", cutoff)\
                .execute()

            old_count = result.count or 0
            if old_count > 0:
                logger.info(f"Found {old_count} old log entries (>30 days)")
                # In observer/safe_writer mode, we just report
                # In supervised mode with approval, we would delete

            return True

        except Exception as e:
            # Table might not exist yet
            logger.warning(f"Log cleanup check failed: {e}")
            return True

    def _send_alert(self, message: str):
        """Send an alert via configured webhook"""
        webhook_url = os.getenv("CLAWDBOT_ALERT_WEBHOOK")

        if not webhook_url:
            logger.info(f"ALERT (no webhook configured): {message}")
            return

        try:
            import urllib.request
            data = json.dumps({"text": message}).encode()
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info("Alert sent successfully")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def run_once(self):
        """Run all due tasks once"""
        logger.info("Running single iteration...")

        for task_name in self.SCHEDULE:
            if self.should_run_task(task_name):
                self.run_task(task_name)

    def run_forever(self):
        """Run continuously until stopped"""
        logger.info("Starting continuous runner...")
        logger.info(f"Mode: {self.mode}")
        logger.info(f"Schedule: {self.SCHEDULE}")

        while self.running:
            for task_name in self.SCHEDULE:
                if not self.running:
                    break

                if self.should_run_task(task_name):
                    self.run_task(task_name)

            # Sleep for 1 minute between checks
            if self.running:
                time.sleep(60)

        logger.info("Runner stopped")
        logger.info(f"Stats: {self.stats}")


def main():
    parser = argparse.ArgumentParser(description="PitchRank Clawdbot Runner")
    parser.add_argument("--mode", type=str, default="observer",
                        choices=["observer", "safe_writer", "supervised"],
                        help="Operating mode")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit")
    args = parser.parse_args()

    # Allow env override
    mode = os.getenv("CLAWDBOT_MODE", args.mode)

    runner = ClawdbotRunner(mode=mode)

    if args.once:
        runner.run_once()
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()
