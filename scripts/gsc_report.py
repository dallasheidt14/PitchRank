#!/usr/bin/env python3
"""
Google Search Console Report - Pull SEO metrics

Setup:
1. Go to Google Cloud Console (console.cloud.google.com)
2. Create a project (or use existing)
3. Enable "Google Search Console API"
4. Create Service Account credentials
5. Download JSON key file
6. Add service account email to GSC property (as user with read access)
7. Add to .env:
   - GSC_CREDENTIALS_FILE=path/to/credentials.json
   - GSC_SITE_URL=https://pitchrank.io/

Run: python3 scripts/gsc_report.py [--days 7] [--top 20]
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

GSC_CREDENTIALS_FILE = os.getenv('GSC_CREDENTIALS_FILE')
GSC_SITE_URL = os.getenv('GSC_SITE_URL', 'https://pitchrank.io/')


def get_gsc_service():
    """Initialize GSC API service."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("❌ Required packages not installed. Run:")
        print("   pip install google-auth google-api-python-client")
        return None
    
    if not GSC_CREDENTIALS_FILE or not os.path.exists(GSC_CREDENTIALS_FILE):
        print("❌ GSC_CREDENTIALS_FILE not set or file not found")
        print("   Set GSC_CREDENTIALS_FILE in .env to your service account JSON key")
        return None
    
    credentials = service_account.Credentials.from_service_account_file(
        GSC_CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/webmasters.readonly']
    )
    
    return build('searchconsole', 'v1', credentials=credentials)


def get_search_analytics(service, days=7, row_limit=100):
    """Get search analytics data from GSC."""
    end_date = datetime.now() - timedelta(days=3)  # GSC has ~3 day delay
    start_date = end_date - timedelta(days=days)
    
    request = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['query', 'page'],
        'rowLimit': row_limit,
        'dimensionFilterGroups': []
    }
    
    response = service.searchanalytics().query(
        siteUrl=GSC_SITE_URL,
        body=request
    ).execute()
    
    return response.get('rows', [])


def get_top_queries(service, days=7, limit=20):
    """Get top performing queries."""
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)
    
    request = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['query'],
        'rowLimit': limit,
    }
    
    response = service.searchanalytics().query(
        siteUrl=GSC_SITE_URL,
        body=request
    ).execute()
    
    return response.get('rows', [])


def get_top_pages(service, days=7, limit=20):
    """Get top performing pages."""
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)
    
    request = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['page'],
        'rowLimit': limit,
    }
    
    response = service.searchanalytics().query(
        siteUrl=GSC_SITE_URL,
        body=request
    ).execute()
    
    return response.get('rows', [])


def get_opportunity_keywords(service, days=28, limit=50):
    """Find keywords ranking #4-10 (opportunity to improve)."""
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)
    
    request = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['query'],
        'rowLimit': 1000,  # Get more to filter
    }
    
    response = service.searchanalytics().query(
        siteUrl=GSC_SITE_URL,
        body=request
    ).execute()
    
    rows = response.get('rows', [])
    
    # Filter for positions 4-10 with decent impressions
    opportunities = []
    for row in rows:
        position = row.get('position', 0)
        impressions = row.get('impressions', 0)
        if 4 <= position <= 10 and impressions >= 10:
            opportunities.append(row)
    
    # Sort by impressions (highest first)
    opportunities.sort(key=lambda x: x.get('impressions', 0), reverse=True)
    
    return opportunities[:limit]


def format_report(queries, pages, opportunities, days):
    """Format the GSC report."""
    lines = [
        f"📊 **GSC Report (Last {days} Days)**",
        "",
        "## 🔍 Top Queries",
    ]
    
    for i, row in enumerate(queries[:10], 1):
        query = row['keys'][0]
        clicks = row.get('clicks', 0)
        impressions = row.get('impressions', 0)
        position = row.get('position', 0)
        ctr = row.get('ctr', 0) * 100
        lines.append(f"{i}. **{query}**")
        lines.append(f"   Clicks: {clicks} | Impr: {impressions} | Pos: {position:.1f} | CTR: {ctr:.1f}%")
    
    lines.extend([
        "",
        "## 📄 Top Pages",
    ])
    
    for i, row in enumerate(pages[:10], 1):
        page = row['keys'][0].replace(GSC_SITE_URL, '/')
        clicks = row.get('clicks', 0)
        impressions = row.get('impressions', 0)
        lines.append(f"{i}. `{page}`")
        lines.append(f"   Clicks: {clicks} | Impressions: {impressions}")
    
    if opportunities:
        lines.extend([
            "",
            "## 🎯 Opportunity Keywords (Rank #4-10)",
            "_These keywords have potential - small improvements could push them to top 3_",
        ])
        
        for i, row in enumerate(opportunities[:10], 1):
            query = row['keys'][0]
            position = row.get('position', 0)
            impressions = row.get('impressions', 0)
            lines.append(f"{i}. **{query}** - Position {position:.1f} ({impressions} impressions)")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='GSC Report')
    parser.add_argument('--days', type=int, default=7, help='Days to analyze')
    parser.add_argument('--top', type=int, default=20, help='Number of results')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--check', action='store_true', help='Just check connection')
    args = parser.parse_args()
    
    service = get_gsc_service()
    if not service:
        print("\n📝 Setup Instructions:")
        print("1. Go to console.cloud.google.com")
        print("2. Create/select project")
        print("3. Enable 'Google Search Console API'")
        print("4. Create Service Account & download JSON key")
        print("5. Add service account email to GSC as user")
        print("6. Set GSC_CREDENTIALS_FILE in .env")
        sys.exit(1)
    
    if args.check:
        print("✅ GSC connection successful!")
        print(f"   Site: {GSC_SITE_URL}")
        return
    
    print(f"Fetching GSC data for last {args.days} days...")
    
    queries = get_top_queries(service, args.days, args.top)
    pages = get_top_pages(service, args.days, args.top)
    opportunities = get_opportunity_keywords(service, 28, args.top)
    
    if args.json:
        print(json.dumps({
            'queries': queries,
            'pages': pages,
            'opportunities': opportunities,
        }, indent=2))
    else:
        print(format_report(queries, pages, opportunities, args.days))


if __name__ == '__main__':
    main()
