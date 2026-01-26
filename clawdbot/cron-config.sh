#!/bin/bash
# PitchRank Clawdbot Cron Configuration
#
# Run this script to set up all scheduled tasks for the PitchRank agents.
#
# Usage:
#   chmod +x clawdbot/cron-config.sh
#   ./clawdbot/cron-config.sh
#
# This will configure the following cron jobs in Clawdbot:
# - Scout: Morning/evening briefings
# - Hunter: Continuous scrape request processing
# - Doc: Data quality patrols
# - Ranker: Weekly ranking calculations

set -e

echo "🦞 Configuring PitchRank Clawdbot Cron Jobs..."

# Scout - Morning Briefing (6:00 AM local time)
echo "📋 Setting up Scout morning briefing..."
clawdbot cron add \
  --name "scout-morning-briefing" \
  --cron "0 6 * * *" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Generate morning briefing for PitchRank. Summarize overnight activity from Hunter (games imported), Doc (issues found), and any errors. Format as a concise status report." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Scout - Evening Summary (6:00 PM local time)
echo "📋 Setting up Scout evening summary..."
clawdbot cron add \
  --name "scout-evening-summary" \
  --cron "0 18 * * *" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Generate evening summary for PitchRank. Summarize today's activity, pending items, and prepare for overnight processing." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Hunter - Process Scrape Requests (every 15 minutes)
echo "🎯 Setting up Hunter scrape processing..."
clawdbot cron add \
  --name "hunter-process-requests" \
  --cron "*/15 * * * *" \
  --session isolated \
  --system-event "Process pending scrape requests from scrape_requests table. Run: python scripts/process_missing_games.py --limit 5. Report results to Scout." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Hunter - Event Discovery (every 6 hours)
echo "🎯 Setting up Hunter event discovery..."
clawdbot cron add \
  --name "hunter-event-discovery" \
  --cron "0 */6 * * *" \
  --session isolated \
  --system-event "Check for new GotSport and TGS events. Run discovery in --list-only mode. Report any new events found to Scout for approval." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Doc - Data Quality Patrol (every 4 hours)
echo "🔍 Setting up Doc data quality patrol..."
clawdbot cron add \
  --name "doc-quality-patrol" \
  --cron "0 */4 * * *" \
  --session isolated \
  --system-event "Run data quality patrol. Execute: python clawdbot/check_data_quality.py --alert. Report issues found and request approval for fixes." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Doc - Review Queue Check (every hour)
echo "🔍 Setting up Doc review queue check..."
clawdbot cron add \
  --name "doc-review-queue" \
  --cron "0 * * * *" \
  --session isolated \
  --system-event "Check team_match_review_queue for pending items. Report count and any high-confidence matches that could be auto-approved." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Ranker - Weekly Ranking Check (Monday 9:30 AM MT)
echo "📈 Setting up Ranker weekly check..."
clawdbot cron add \
  --name "ranker-weekly-check" \
  --cron "30 9 * * 1" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Check if rankings need recalculation. Report: games since last calc, data quality changes, and recommendation. Request approval if recalc recommended." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# Ranker - Post-Calculation Validation (Monday 10:30 AM MT, after scheduled GitHub Action)
echo "📈 Setting up Ranker validation..."
clawdbot cron add \
  --name "ranker-validation" \
  --cron "30 10 * * 1" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Validate latest rankings calculation. Check for anomalies: teams moving >20 positions, missing teams, unusual power scores. Report any issues." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

# System - Health Check (every hour)
echo "💚 Setting up system health check..."
clawdbot cron add \
  --name "system-health-check" \
  --cron "30 * * * *" \
  --session isolated \
  --system-event "Check PitchRank system health. Verify: Supabase connection, provider API access, disk space, recent error count. Alert if any issues." \
  --wake now \
  2>/dev/null || echo "  (already exists or skipped)"

echo ""
echo "✅ Cron jobs configured!"
echo ""
echo "View all jobs: clawdbot cron list"
echo "Remove a job:  clawdbot cron remove --name <job-name>"
echo ""
