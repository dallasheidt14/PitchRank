#!/usr/bin/env python3
"""
Proactive Data Quality Report - Monitor PitchRank data health

Generates comprehensive metrics dashboard, quality scores, anomaly detection,
and trend comparison. Saves history for trending.

Run: python3 scripts/data_quality_report.py
Output: Human-readable summary for D H
Exit: code 1 if critical issues found

Created: 2026-02-06
"""

import os
import sys
import json
import psycopg2
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
DATABASE_URL = os.getenv('DATABASE_URL')

# Output paths
HISTORY_FILE = Path(__file__).parent / 'data_quality_history.json'

# Thresholds for anomaly detection
THRESHOLDS = {
    'quarantine_rate_critical': 0.20,  # >20% of new games in quarantine
    'duplicate_rate_critical': 0.15,   # >15% duplication rate
    'club_variants_critical': 3,        # >3 name variants per club
    'missing_critical_fields': 0.10,    # >10% teams missing critical data
    'old_review_queue_days': 30,        # Review queue entries older than 30 days
}


def get_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)


def get_metrics_dashboard(cur):
    """Generate metrics dashboard."""
    print("\n" + "=" * 70)
    print("📊 METRICS DASHBOARD")
    print("=" * 70)
    
    metrics = {}
    
    # Total teams by status
    cur.execute("SELECT COUNT(*) FROM teams WHERE is_deprecated = false")
    metrics['teams_active'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM teams WHERE is_deprecated = true")
    metrics['teams_deprecated'] = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM teams")
    metrics['teams_total'] = cur.fetchone()[0]
    
    print(f"📈 Total Teams: {metrics['teams_total']:,}")
    print(f"   ✅ Active: {metrics['teams_active']:,}")
    print(f"   🗑️  Deprecated: {metrics['teams_deprecated']:,}")
    
    # Missing field counts
    cur.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE club_name IS NULL OR club_name = '') as missing_club,
            COUNT(*) FILTER (WHERE state_code IS NULL OR state_code = '') as missing_state,
            COUNT(*) FILTER (WHERE age_group IS NULL OR age_group = '') as missing_age,
            COUNT(*) FILTER (WHERE gender IS NULL OR gender = '') as missing_gender
        FROM teams
        WHERE is_deprecated = false
    """)
    row = cur.fetchone()
    metrics['missing_club_name'] = row[0]
    metrics['missing_state_code'] = row[1]
    metrics['missing_age_group'] = row[2]
    metrics['missing_gender'] = row[3]
    
    print(f"\n📋 Missing Fields (Active Teams):")
    print(f"   Club Name: {metrics['missing_club_name']:,}")
    print(f"   State Code: {metrics['missing_state_code']:,}")
    print(f"   Age Group: {metrics['missing_age_group']:,}")
    print(f"   Gender: {metrics['missing_gender']:,}")
    
    # Quarantine queue
    cur.execute("SELECT COUNT(*) FROM quarantine_games")
    metrics['quarantine_games_total'] = cur.fetchone()[0]
    
    # Quarantine breakdown by reason
    cur.execute("""
        SELECT reason_code, COUNT(*) 
        FROM quarantine_games 
        GROUP BY reason_code 
        ORDER BY COUNT(*) DESC
    """)
    quarantine_reasons = dict(cur.fetchall())
    metrics['quarantine_breakdown'] = quarantine_reasons
    
    print(f"\n🚧 Quarantine Queue: {metrics['quarantine_games_total']:,} games")
    if quarantine_reasons:
        for reason, count in list(quarantine_reasons.items())[:5]:
            print(f"   {reason}: {count:,}")
    
    # Match review queue
    cur.execute("SELECT COUNT(*) FROM team_match_review_queue WHERE status = 'pending'")
    metrics['review_queue_pending'] = cur.fetchone()[0]
    
    cur.execute("""
        SELECT MIN(created_at) 
        FROM team_match_review_queue 
        WHERE status = 'pending'
    """)
    oldest = cur.fetchone()[0]
    metrics['review_queue_oldest_days'] = None
    if oldest:
        metrics['review_queue_oldest_days'] = (datetime.now() - oldest).days
    
    print(f"\n🔍 Match Review Queue: {metrics['review_queue_pending']:,} pending")
    if metrics['review_queue_oldest_days'] is not None:
        print(f"   Oldest Entry: {metrics['review_queue_oldest_days']} days old")
    
    # Teams added in last 7 days
    cur.execute("""
        SELECT COUNT(*) 
        FROM teams 
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """)
    metrics['teams_added_7d'] = cur.fetchone()[0]
    
    print(f"\n📆 Teams Added (Last 7 Days): {metrics['teams_added_7d']:,}")
    
    # Games added in last 7 days
    cur.execute("""
        SELECT COUNT(*) 
        FROM games 
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """)
    metrics['games_added_7d'] = cur.fetchone()[0]
    
    print(f"⚽ Games Added (Last 7 Days): {metrics['games_added_7d']:,}")
    
    return metrics


def get_quality_scores(cur, metrics):
    """Calculate quality scores."""
    print("\n" + "=" * 70)
    print("⭐ QUALITY SCORES")
    print("=" * 70)
    
    scores = {}
    
    # % of teams with complete data (all critical fields filled)
    total_active = metrics['teams_active']
    if total_active > 0:
        complete = total_active - max(
            metrics['missing_club_name'],
            metrics['missing_state_code'],
            metrics['missing_age_group'],
            metrics['missing_gender']
        )
        scores['complete_data_pct'] = (complete / total_active) * 100
    else:
        scores['complete_data_pct'] = 0
    
    print(f"✅ Complete Data: {scores['complete_data_pct']:.1f}%")
    
    # % of clubs with consistent naming (no variants)
    cur.execute("""
        SELECT COUNT(DISTINCT LOWER(club_name)) as unique_lower,
               COUNT(DISTINCT club_name) as unique_exact
        FROM teams 
        WHERE club_name IS NOT NULL AND club_name != '' AND is_deprecated = false
    """)
    row = cur.fetchone()
    if row and row[0] > 0:
        scores['club_consistency_pct'] = (row[0] / row[1]) * 100
    else:
        scores['club_consistency_pct'] = 100
    
    print(f"🏢 Club Naming Consistency: {scores['club_consistency_pct']:.1f}%")
    
    # Auto-merge success rate (from merge history if available)
    cur.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE merge_reason LIKE '%auto%' OR merge_reason LIKE '%case%') as auto,
            COUNT(*) as total
        FROM team_merge_map
        WHERE merged_at >= NOW() - INTERVAL '30 days'
    """)
    row = cur.fetchone()
    if row and row[1] > 0:
        scores['auto_merge_success_pct'] = (row[0] / row[1]) * 100
        scores['recent_merges_30d'] = row[1]
    else:
        scores['auto_merge_success_pct'] = None
        scores['recent_merges_30d'] = 0
    
    if scores['auto_merge_success_pct'] is not None:
        print(f"🔀 Auto-Merge Success Rate (30d): {scores['auto_merge_success_pct']:.1f}%")
        print(f"   Total Merges: {scores['recent_merges_30d']:,}")
    else:
        print(f"🔀 Auto-Merge Success Rate: N/A (no recent merges)")
    
    return scores


def detect_anomalies(cur, metrics, scores):
    """Detect data quality anomalies."""
    print("\n" + "=" * 70)
    print("🚨 ANOMALY DETECTION")
    print("=" * 70)
    
    anomalies = []
    critical_count = 0
    
    # Flag if quarantine rate spikes (>20% of new games)
    if metrics['games_added_7d'] > 0:
        quarantine_rate = metrics['quarantine_games_total'] / metrics['games_added_7d']
        if quarantine_rate > THRESHOLDS['quarantine_rate_critical']:
            anomalies.append({
                'level': 'CRITICAL',
                'message': f"Quarantine rate spike: {quarantine_rate*100:.1f}% of games in quarantine (>{THRESHOLDS['quarantine_rate_critical']*100:.0f}% threshold)"
            })
            critical_count += 1
    
    # Flag if duplicate rate spikes
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT club_name, LOWER(REGEXP_REPLACE(team_name, '[^a-zA-Z0-9]', '', 'g'))
            FROM teams
            WHERE is_deprecated = false AND club_name IS NOT NULL
            GROUP BY club_name, LOWER(REGEXP_REPLACE(team_name, '[^a-zA-Z0-9]', '', 'g'))
            HAVING COUNT(*) > 1
        ) dupes
    """)
    potential_dupes = cur.fetchone()[0]
    if metrics['teams_active'] > 0:
        dupe_rate = potential_dupes / metrics['teams_active']
        if dupe_rate > THRESHOLDS['duplicate_rate_critical']:
            anomalies.append({
                'level': 'WARNING',
                'message': f"Potential duplicate rate: {dupe_rate*100:.1f}% (>{THRESHOLDS['duplicate_rate_critical']*100:.0f}% threshold)"
            })
    
    # Flag clubs with >3 name variants
    cur.execute("""
        SELECT LOWER(club_name), COUNT(DISTINCT club_name) as variants
        FROM teams
        WHERE club_name IS NOT NULL AND club_name != '' AND is_deprecated = false
        GROUP BY LOWER(club_name)
        HAVING COUNT(DISTINCT club_name) > %s
        ORDER BY variants DESC
        LIMIT 10
    """, (THRESHOLDS['club_variants_critical'],))
    clubs_with_variants = cur.fetchall()
    
    if clubs_with_variants:
        anomalies.append({
            'level': 'WARNING',
            'message': f"{len(clubs_with_variants)} clubs have >{THRESHOLDS['club_variants_critical']} name variants"
        })
        for club_lower, variant_count in clubs_with_variants[:5]:
            anomalies.append({
                'level': 'INFO',
                'message': f"   {club_lower}: {variant_count} variants"
            })
    
    # Flag teams missing critical fields
    missing_critical = max(
        metrics['missing_club_name'],
        metrics['missing_state_code'],
        metrics['missing_age_group'],
        metrics['missing_gender']
    )
    if metrics['teams_active'] > 0:
        missing_rate = missing_critical / metrics['teams_active']
        if missing_rate > THRESHOLDS['missing_critical_fields']:
            anomalies.append({
                'level': 'CRITICAL',
                'message': f"Missing critical fields: {missing_rate*100:.1f}% of teams (>{THRESHOLDS['missing_critical_fields']*100:.0f}% threshold)"
            })
            critical_count += 1
    
    # Flag old review queue entries
    if metrics['review_queue_oldest_days'] and metrics['review_queue_oldest_days'] > THRESHOLDS['old_review_queue_days']:
        anomalies.append({
            'level': 'WARNING',
            'message': f"Review queue has entries {metrics['review_queue_oldest_days']} days old (>{THRESHOLDS['old_review_queue_days']} day threshold)"
        })
    
    # Flag if no games added in last 7 days (pipeline down)
    if metrics['games_added_7d'] == 0:
        anomalies.append({
            'level': 'CRITICAL',
            'message': "Data pipeline down: 0 games added in last 7 days"
        })
        critical_count += 1
    
    # Print anomalies
    if not anomalies:
        print("✅ No anomalies detected")
    else:
        for anomaly in anomalies:
            level_icon = {
                'CRITICAL': '🔴',
                'WARNING': '⚠️',
                'INFO': 'ℹ️'
            }.get(anomaly['level'], '•')
            print(f"{level_icon} {anomaly['level']}: {anomaly['message']}")
    
    return anomalies, critical_count


def compare_trends(metrics, scores):
    """Compare to last week's metrics."""
    print("\n" + "=" * 70)
    print("📈 TREND COMPARISON")
    print("=" * 70)
    
    # Load history
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load history: {e}")
    
    # Find last week's entry
    one_week_ago = datetime.now() - timedelta(days=7)
    last_week = None
    for entry in reversed(history):
        entry_date = datetime.fromisoformat(entry['timestamp'])
        if entry_date <= one_week_ago:
            last_week = entry
            break
    
    if last_week:
        print(f"Comparing to: {last_week['timestamp']}")
        print()
        
        # Compare key metrics
        comparisons = [
            ('Active Teams', metrics['teams_active'], last_week['metrics'].get('teams_active')),
            ('Games (7d)', metrics['games_added_7d'], last_week['metrics'].get('games_added_7d')),
            ('Quarantine Queue', metrics['quarantine_games_total'], last_week['metrics'].get('quarantine_games_total')),
            ('Review Queue', metrics['review_queue_pending'], last_week['metrics'].get('review_queue_pending')),
            ('Complete Data %', scores['complete_data_pct'], last_week['scores'].get('complete_data_pct')),
        ]
        
        for label, current, previous in comparisons:
            if previous is not None and current is not None:
                diff = current - previous
                if isinstance(current, float):
                    diff_str = f"{diff:+.1f}"
                    print(f"{label}: {current:.1f} ({diff_str})")
                else:
                    diff_str = f"{diff:+,}"
                    print(f"{label}: {current:,} ({diff_str})")
            else:
                print(f"{label}: {current}")
    else:
        print("No previous data for comparison (first run or >1 week gap)")
    
    # Save current metrics to history
    history_entry = {
        'timestamp': datetime.now().isoformat(),
        'metrics': metrics,
        'scores': scores
    }
    history.append(history_entry)
    
    # Keep last 90 days
    cutoff = datetime.now() - timedelta(days=90)
    history = [e for e in history if datetime.fromisoformat(e['timestamp']) >= cutoff]
    
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
        print(f"\n💾 Metrics saved to {HISTORY_FILE}")
    except Exception as e:
        print(f"\n⚠️  Could not save history: {e}")


def main():
    """Run data quality report."""
    print("=" * 70)
    print("🔍 PITCHRANK DATA QUALITY REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # 1. Metrics Dashboard
        metrics = get_metrics_dashboard(cur)
        
        # 2. Quality Scores
        scores = get_quality_scores(cur, metrics)
        
        # 3. Anomaly Detection
        anomalies, critical_count = detect_anomalies(cur, metrics, scores)
        
        # 4. Trend Comparison
        compare_trends(metrics, scores)
        
        cur.close()
        conn.close()
        
        # Summary
        print("\n" + "=" * 70)
        print("📝 SUMMARY")
        print("=" * 70)
        
        if critical_count > 0:
            print(f"🔴 {critical_count} CRITICAL issue(s) found")
            print("\n⚠️  Exiting with code 1 (critical issues detected)")
            sys.exit(1)
        elif anomalies:
            print(f"⚠️  {len(anomalies)} warning(s) found, but no critical issues")
            print("✅ Exiting with code 0")
            sys.exit(0)
        else:
            print("✅ All systems healthy")
            print("✅ Exiting with code 0")
            sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
