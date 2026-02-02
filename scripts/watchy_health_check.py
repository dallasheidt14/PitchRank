#!/usr/bin/env python3
"""
Watchy Health Check - Monitor PitchRank system health

Run: python3 scripts/watchy_health_check.py [--full]
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

DATABASE_URL = os.getenv('DATABASE_URL')

# Thresholds
THRESHOLDS = {
    'quarantine_games_warning': 100,
    'quarantine_games_critical': 500,
    'quarantine_teams_warning': 50,
    'quarantine_teams_critical': 200,
    'validation_errors_warning': 50,
    'validation_errors_critical': 200,
    'rankings_stale_warning_days': 3,
    'rankings_stale_critical_days': 7,
    'missing_state_warning': 2000,
    'missing_state_critical': 5000,
    'missing_club_warning': 5000,
    'missing_club_critical': 10000,
    'pending_reviews_warning': 500,
    'pending_reviews_critical': 2000,
}


def get_connection():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def check_data_volumes(cur):
    """Check basic data volume metrics."""
    metrics = {}
    
    cur.execute("SELECT COUNT(*) FROM teams WHERE is_deprecated = false")
    metrics['teams'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM teams")
    metrics['teams_total'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM games")
    metrics['games'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM team_alias_map")
    metrics['aliases'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM team_merge_map")
    metrics['merges'] = cur.fetchone()[0]
    
    return metrics


def check_data_quality(cur):
    """Check data quality issues."""
    issues = {}
    
    # Missing state codes
    cur.execute("SELECT COUNT(*) FROM teams WHERE state_code IS NULL OR state_code = ''")
    issues['missing_state'] = cur.fetchone()[0]
    
    # Missing club names
    cur.execute("SELECT COUNT(*) FROM teams WHERE club_name IS NULL OR club_name = ''")
    issues['missing_club'] = cur.fetchone()[0]
    
    # Quarantine games
    cur.execute("SELECT COUNT(*) FROM quarantine_games")
    issues['quarantine_games'] = cur.fetchone()[0]
    
    # Quarantine teams
    cur.execute("SELECT COUNT(*) FROM quarantine_teams")
    issues['quarantine_teams'] = cur.fetchone()[0]
    
    # Validation errors
    cur.execute("SELECT COUNT(*) FROM validation_errors")
    issues['validation_errors'] = cur.fetchone()[0]
    
    # Pending match reviews
    cur.execute("SELECT COUNT(*) FROM team_match_review_queue WHERE status = 'pending'")
    issues['pending_reviews'] = cur.fetchone()[0]
    
    return issues


def check_rankings_freshness(cur):
    """Check when rankings were last updated."""
    freshness = {}
    
    # Check build logs for last successful build
    cur.execute("""
        SELECT completed_at FROM build_logs 
        WHERE completed_at IS NOT NULL
        ORDER BY completed_at DESC 
        LIMIT 1
    """)
    row = cur.fetchone()
    if row and row[0]:
        freshness['last_build'] = row[0]
        if row[0].tzinfo:
            freshness['build_age_hours'] = (datetime.now(row[0].tzinfo) - row[0]).total_seconds() / 3600
        else:
            freshness['build_age_hours'] = (datetime.now() - row[0]).total_seconds() / 3600
    else:
        freshness['last_build'] = None
        freshness['build_age_hours'] = None
    
    # Check current rankings timestamp
    cur.execute("""
        SELECT MAX(last_calculated) FROM current_rankings
    """)
    row = cur.fetchone()
    if row and row[0]:
        freshness['rankings_updated'] = row[0]
        if row[0].tzinfo:
            freshness['rankings_age_hours'] = (datetime.now(row[0].tzinfo) - row[0]).total_seconds() / 3600
        else:
            freshness['rankings_age_hours'] = (datetime.now() - row[0]).total_seconds() / 3600
    else:
        freshness['rankings_updated'] = None
        freshness['rankings_age_hours'] = None
    
    return freshness


def check_scraper_health(cur):
    """Check scraper activity."""
    scraper = {}
    
    # Recent scrapes (last 24h)
    cur.execute("""
        SELECT COUNT(*) FROM team_scrape_log 
        WHERE scraped_at > NOW() - INTERVAL '24 hours'
    """)
    scraper['scrapes_24h'] = cur.fetchone()[0]
    
    # Last scrape timestamp
    cur.execute("""
        SELECT MAX(scraped_at) FROM team_scrape_log
    """)
    row = cur.fetchone()
    if row and row[0]:
        scraper['last_scrape'] = row[0]
        if row[0].tzinfo:
            scraper['last_scrape_hours'] = (datetime.now(row[0].tzinfo) - row[0]).total_seconds() / 3600
        else:
            scraper['last_scrape_hours'] = (datetime.now() - row[0]).total_seconds() / 3600
    else:
        scraper['last_scrape'] = None
        scraper['last_scrape_hours'] = None
    
    # Scrape watermarks
    cur.execute("SELECT provider, last_successful_scrape FROM scrape_watermarks ORDER BY last_successful_scrape DESC LIMIT 5")
    scraper['watermarks'] = cur.fetchall()
    
    return scraper


def evaluate_status(issues, freshness):
    """Evaluate overall status and generate alerts."""
    alerts = []
    status = 'OK'
    
    # Check quarantine
    if issues['quarantine_games'] >= THRESHOLDS['quarantine_games_critical']:
        alerts.append(('CRITICAL', f"Quarantine games: {issues['quarantine_games']}"))
        status = 'CRITICAL'
    elif issues['quarantine_games'] >= THRESHOLDS['quarantine_games_warning']:
        alerts.append(('WARNING', f"Quarantine games: {issues['quarantine_games']}"))
        if status != 'CRITICAL': status = 'WARNING'
    
    if issues['quarantine_teams'] >= THRESHOLDS['quarantine_teams_critical']:
        alerts.append(('CRITICAL', f"Quarantine teams: {issues['quarantine_teams']}"))
        status = 'CRITICAL'
    elif issues['quarantine_teams'] >= THRESHOLDS['quarantine_teams_warning']:
        alerts.append(('WARNING', f"Quarantine teams: {issues['quarantine_teams']}"))
        if status != 'CRITICAL': status = 'WARNING'
    
    # Check validation errors
    if issues['validation_errors'] >= THRESHOLDS['validation_errors_critical']:
        alerts.append(('CRITICAL', f"Validation errors: {issues['validation_errors']}"))
        status = 'CRITICAL'
    elif issues['validation_errors'] >= THRESHOLDS['validation_errors_warning']:
        alerts.append(('WARNING', f"Validation errors: {issues['validation_errors']}"))
        if status != 'CRITICAL': status = 'WARNING'
    
    # Check rankings freshness
    if freshness.get('rankings_age_hours'):
        age_days = freshness['rankings_age_hours'] / 24
        if age_days >= THRESHOLDS['rankings_stale_critical_days']:
            alerts.append(('CRITICAL', f"Rankings are {age_days:.1f} days stale"))
            status = 'CRITICAL'
        elif age_days >= THRESHOLDS['rankings_stale_warning_days']:
            alerts.append(('WARNING', f"Rankings are {age_days:.1f} days stale"))
            if status != 'CRITICAL': status = 'WARNING'
    
    # Check missing data
    if issues['missing_state'] >= THRESHOLDS['missing_state_critical']:
        alerts.append(('CRITICAL', f"Teams missing state_code: {issues['missing_state']}"))
        status = 'CRITICAL'
    elif issues['missing_state'] >= THRESHOLDS['missing_state_warning']:
        alerts.append(('WARNING', f"Teams missing state_code: {issues['missing_state']}"))
        if status != 'CRITICAL': status = 'WARNING'
    
    # Check pending reviews
    if issues['pending_reviews'] >= THRESHOLDS['pending_reviews_critical']:
        alerts.append(('WARNING', f"Pending match reviews: {issues['pending_reviews']}"))
        if status != 'CRITICAL': status = 'WARNING'
    
    return status, alerts


def format_report(volumes, issues, freshness, scraper, status, alerts, full=False):
    """Format the health check report."""
    lines = []
    
    if status == 'OK':
        lines.append("👁️ **Watchy Health Check — All systems nominal**")
    elif status == 'WARNING':
        lines.append("⚠️ **Watchy Alert — Issues detected**")
    else:
        lines.append("🚨 **Watchy Alert — CRITICAL issues detected**")
    
    lines.append("")
    
    # Summary line
    rankings_age = f"{freshness['rankings_age_hours']:.0f}h ago" if freshness.get('rankings_age_hours') else "unknown"
    scrape_age = f"{scraper['last_scrape_hours']:.0f}h ago" if scraper.get('last_scrape_hours') else "unknown"
    
    lines.append(f"📊 Teams: {volumes['teams']:,} | Games: {volumes['games']:,}")
    lines.append(f"⏰ Rankings: {rankings_age} | Last scrape: {scrape_age}")
    lines.append(f"🔄 Quarantine: {issues['quarantine_games']} games, {issues['quarantine_teams']} teams")
    
    # Alerts
    if alerts:
        lines.append("")
        lines.append("**Issues:**")
        for level, msg in alerts:
            icon = '🔴' if level == 'CRITICAL' else '🟡'
            lines.append(f"  {icon} {msg}")
    
    # Full report details
    if full:
        lines.append("")
        lines.append("**Data Quality:**")
        lines.append(f"  - Missing state_code: {issues['missing_state']:,}")
        lines.append(f"  - Missing club_name: {issues['missing_club']:,}")
        lines.append(f"  - Validation errors: {issues['validation_errors']:,}")
        lines.append(f"  - Pending reviews: {issues['pending_reviews']:,}")
        
        lines.append("")
        lines.append("**Volumes:**")
        lines.append(f"  - Active teams: {volumes['teams']:,}")
        lines.append(f"  - Total teams: {volumes['teams_total']:,}")
        lines.append(f"  - Games: {volumes['games']:,}")
        lines.append(f"  - Aliases: {volumes['aliases']:,}")
        lines.append(f"  - Merges: {volumes['merges']:,}")
        
        if scraper.get('watermarks'):
            lines.append("")
            lines.append("**Recent Scrapes:**")
            for provider, ts in scraper['watermarks'][:3]:
                lines.append(f"  - {provider}: {ts}")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Watchy Health Check')
    parser.add_argument('--full', action='store_true', help='Full detailed report')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--preflight', action='store_true', help='Quick check: exit 0 if OK (skip agent), exit 1 if needs attention')
    args = parser.parse_args()
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Gather metrics
    volumes = check_data_volumes(cur)
    issues = check_data_quality(cur)
    freshness = check_rankings_freshness(cur)
    scraper = check_scraper_health(cur)
    
    # Evaluate
    status, alerts = evaluate_status(issues, freshness)
    
    conn.close()
    
    # Pre-flight mode: exit 0 if OK (no agent needed), exit 1 if work needed
    if args.preflight:
        if status == 'OK':
            print("PREFLIGHT_OK: All systems nominal, skipping agent")
            sys.exit(0)
        else:
            print(f"PREFLIGHT_NEEDED: Status={status}, {len(alerts)} alerts")
            sys.exit(1)
    
    if args.json:
        import json
        print(json.dumps({
            'status': status,
            'alerts': alerts,
            'volumes': volumes,
            'issues': issues,
            'freshness': {k: str(v) if v else None for k, v in freshness.items()},
            'scraper': {k: str(v) if isinstance(v, datetime) else v for k, v in scraper.items()}
        }, indent=2, default=str))
    else:
        report = format_report(volumes, issues, freshness, scraper, status, alerts, full=args.full)
        print(report)
    
    # Exit code based on status
    if status == 'CRITICAL':
        sys.exit(2)
    elif status == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
