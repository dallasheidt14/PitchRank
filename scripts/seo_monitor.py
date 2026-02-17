#!/usr/bin/env python3
"""
SEO Monitor - Proactive SEO health checking for PitchRank.
Used by Socialy for automated monitoring.
"""

import os
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

def run_gsc_report(days=7):
    """Run GSC report and return output."""
    try:
        result = subprocess.run(
            ['python3', 'scripts/gsc_report.py', '--days', str(days)],
            capture_output=True,
            text=True,
            cwd='/Users/pitchrankio-dev/Projects/PitchRank'
        )
        return result.stdout
    except Exception as e:
        return f"Error running GSC report: {e}"

def check_sitemap():
    """Check sitemap availability and basic stats."""
    try:
        result = subprocess.run(
            ['curl', '-sL', 'https://pitchrank.io/sitemap.xml'],
            capture_output=True,
            text=True
        )
        xml = result.stdout
        url_count = xml.count('<url>')
        return {
            'available': url_count > 0,
            'url_count': url_count,
            'has_lastmod': '<lastmod>' in xml
        }
    except Exception as e:
        return {'error': str(e)}

def check_robots_txt():
    """Check robots.txt configuration."""
    try:
        result = subprocess.run(
            ['curl', '-sL', 'https://pitchrank.io/robots.txt'],
            capture_output=True,
            text=True
        )
        content = result.stdout
        return {
            'available': len(content) > 0,
            'allows_googlebot': 'Disallow: /' not in content or 'User-agent: Googlebot' in content,
            'has_sitemap': 'Sitemap:' in content,
            'content': content[:500]
        }
    except Exception as e:
        return {'error': str(e)}

def check_page_headers(url):
    """Check HTTP headers for a page."""
    try:
        result = subprocess.run(
            ['curl', '-sI', url],
            capture_output=True,
            text=True
        )
        headers = result.stdout
        return {
            'status': '200' in headers.split('\n')[0],
            'has_canonical': 'link:' in headers.lower() and 'canonical' in headers.lower(),
            'content_type': 'text/html' in headers.lower(),
            'headers': headers
        }
    except Exception as e:
        return {'error': str(e)}

def generate_report():
    """Generate full SEO health report."""
    report = {
        'timestamp': datetime.now().isoformat(),
        'checks': {}
    }
    
    print("🔍 Running SEO Health Check...\n")
    
    # Check sitemap
    print("Checking sitemap...")
    report['checks']['sitemap'] = check_sitemap()
    
    # Check robots.txt
    print("Checking robots.txt...")
    report['checks']['robots'] = check_robots_txt()
    
    # Check key pages
    print("Checking key pages...")
    key_pages = [
        'https://pitchrank.io/',
        'https://pitchrank.io/rankings/ca/u14/male',
        'https://pitchrank.io/rankings/az/u12/male',
    ]
    report['checks']['pages'] = {}
    for url in key_pages:
        report['checks']['pages'][url] = check_page_headers(url)
    
    # Summary
    print("\n" + "="*60)
    print("SEO HEALTH SUMMARY")
    print("="*60)
    
    sitemap = report['checks']['sitemap']
    if sitemap.get('available'):
        print(f"✅ Sitemap: {sitemap.get('url_count', 0)} URLs indexed")
    else:
        print("❌ Sitemap: Not available or error")
    
    robots = report['checks']['robots']
    if robots.get('available') and robots.get('allows_googlebot'):
        print("✅ Robots.txt: Configured correctly")
    else:
        print("⚠️ Robots.txt: Needs review")
    
    for url, data in report['checks']['pages'].items():
        status = "✅" if data.get('status') else "❌"
        print(f"{status} {url}")
    
    return report

def main():
    report = generate_report()
    
    # Save report
    output_path = Path('/Users/pitchrankio-dev/Projects/PitchRank/logs/seo_health.json')
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nReport saved to: {output_path}")

if __name__ == '__main__':
    main()
