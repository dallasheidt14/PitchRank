#!/usr/bin/env python3
"""
Test harness for PitchRank sub-agents.

Runs agent prompts in dry-run mode without waiting for scheduled crons.
Useful for testing agent logic, prompt changes, and script behavior.

Usage:
    python3 scripts/test_agent.py --agent watchy
    python3 scripts/test_agent.py --agent cleany --dry-run
    python3 scripts/test_agent.py --list
"""

import argparse
import os
import subprocess
import sys

# Agent test commands - what each agent would run
AGENT_TESTS = {
    "watchy": {
        "name": "Watchy 👁️",
        "description": "Health monitoring",
        "preflight": "python3 scripts/watchy_health_check.py --preflight",
        "full": "python3 scripts/watchy_health_check.py --full",
    },
    "cleany": {
        "name": "Cleany 🧹",
        "description": "Data hygiene",
        "preflight": "python3 scripts/run_weekly_cleany.py --preflight",
        "full": "python3 scripts/run_weekly_cleany.py",
    },
    "scrappy": {
        "name": "Scrappy 🕷️",
        "description": "Scrape monitoring",
        "preflight": 'python3 scripts/scrappy_monitor.py --preflight 2>/dev/null || echo "No preflight"',
        "full": "python3 scripts/scrappy_monitor.py --full",
    },
    "ranky": {
        "name": "Ranky 📊",
        "description": "Rankings calculation",
        "preflight": 'echo "Ranky has no preflight - runs calculate_rankings.py"',
        "full": 'python3 scripts/calculate_rankings.py --dry-run 2>/dev/null || echo "No dry-run mode"',
    },
    "movy": {
        "name": "Movy 📈",
        "description": "Movers report",
        "preflight": 'echo "Checking movy_report.py..."',
        "full": "python3 scripts/movy_report.py --limit 3",
    },
    "compy": {
        "name": "COMPY 🧠",
        "description": "Knowledge compounding",
        "preflight": "python3 scripts/compy_review.py --preflight",
        "full": "python3 scripts/compy_review.py --hours 24",
    },
}


def list_agents():
    """List all testable agents."""
    print("\n📋 Available Agents for Testing:\n")
    for key, agent in AGENT_TESTS.items():
        print(f"  {agent['name']:15} ({key:8}) - {agent['description']}")
    print("\nUsage: python3 scripts/test_agent.py --agent <name>")
    print("       python3 scripts/test_agent.py --agent <name> --dry-run  (preflight only)")


def test_agent(agent_key: str, dry_run: bool = False):
    """Run agent test commands."""
    if agent_key not in AGENT_TESTS:
        print(f"❌ Unknown agent: {agent_key}")
        list_agents()
        sys.exit(1)

    agent = AGENT_TESTS[agent_key]
    print(f"\n🧪 Testing {agent['name']}")
    print(f"   {agent['description']}")
    print("-" * 50)

    # Change to project directory
    project_dir = "/Users/pitchrankio-dev/Projects/PitchRank"
    os.chdir(project_dir)

    # Run preflight first
    print("\n📋 Preflight check:")
    subprocess.run(agent["preflight"], shell=True, capture_output=False)

    if dry_run:
        print("\n✅ Dry run complete (preflight only)")
        return

    # Run full test
    print("\n🚀 Full test:")
    subprocess.run(agent["full"], shell=True, capture_output=False)

    print(f"\n✅ Test complete for {agent['name']}")


def main():
    parser = argparse.ArgumentParser(description="Test PitchRank sub-agents")
    parser.add_argument("--agent", "-a", help="Agent to test (watchy, cleany, scrappy, ranky, movy, compy)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Run preflight only")
    parser.add_argument("--list", "-l", action="store_true", help="List available agents")
    parser.add_argument("--all", action="store_true", help="Test all agents (preflight only)")

    args = parser.parse_args()

    if args.list:
        list_agents()
        return

    if args.all:
        print("\n🧪 Running preflight for ALL agents...\n")
        for key in AGENT_TESTS:
            test_agent(key, dry_run=True)
            print()
        return

    if not args.agent:
        print("❌ Please specify an agent with --agent or use --list")
        sys.exit(1)

    test_agent(args.agent.lower(), args.dry_run)


if __name__ == "__main__":
    main()
