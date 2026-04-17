"""Pull 90-day GSC impressions for /rankings/{state}/* pages, aggregated by state code.

Used to identify which state pages have the highest search demand for prioritizing
curated meta description work. See docs/superpowers/specs/2026-04-16-seo-roadmap-design.md.
"""

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

KEY_PATH = os.path.expanduser("~/.config/google-analytics/service-account-key.json")
SITE_URL = "sc-domain:pitchrank.io"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
}

ALREADY_CURATED = {"az", "ca", "co", "fl", "ga", "md", "nj", "ny", "pa", "tx"}

# Matches /rankings/{state} or /rankings/{state}/...
RANKING_PATH = re.compile(r"/rankings/([a-z]{2})(?:/|$)")


def main():
    creds = service_account.Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
    svc = build("searchconsole", "v1", credentials=creds)

    end = datetime.utcnow().date()
    start = end - timedelta(days=90)
    print(f"Date range: {start} to {end}\n")

    rows_all = []
    start_row = 0
    page_size = 25000
    while True:
        resp = svc.searchanalytics().query(siteUrl=SITE_URL, body={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["page"],
            "dimensionFilterGroups": [{
                "filters": [{"dimension": "page", "operator": "contains", "expression": "/rankings/"}]
            }],
            "rowLimit": page_size,
            "startRow": start_row,
            "orderBy": [{"field": "impressions", "descending": True}],
        }).execute()
        rows = resp.get("rows", [])
        rows_all.extend(rows)
        if len(rows) < page_size:
            break
        start_row += page_size

    print(f"Pulled {len(rows_all)} ranking page rows\n")

    # Aggregate by state code
    state_totals = defaultdict(lambda: {"impressions": 0, "clicks": 0, "pages": 0, "landing_impressions": 0})
    for r in rows_all:
        page = r["keys"][0]
        m = RANKING_PATH.search(page)
        if not m:
            continue
        code = m.group(1)
        if code not in US_STATE_CODES:
            continue
        state_totals[code]["impressions"] += r.get("impressions", 0)
        state_totals[code]["clicks"] += r.get("clicks", 0)
        state_totals[code]["pages"] += 1
        # Landing page is exactly /rankings/{state} (no trailing path)
        if page.rstrip("/").endswith(f"/rankings/{code}"):
            state_totals[code]["landing_impressions"] += r.get("impressions", 0)

    sorted_states = sorted(state_totals.items(), key=lambda x: -x[1]["impressions"])

    print(f"{'State':<6} {'Impr':>8} {'Clicks':>7} {'LandImpr':>9} {'Pages':>6} {'Curated?'}")
    print("-" * 55)
    for code, t in sorted_states:
        flag = "YES" if code in ALREADY_CURATED else ""
        print(f"{code:<6} {t['impressions']:>8} {t['clicks']:>7} {t['landing_impressions']:>9} {t['pages']:>6}  {flag}")

    # Top 20 not yet curated
    print("\n=== TOP 20 STATES NOT YET CURATED ===")
    not_curated = [(c, t) for c, t in sorted_states if c not in ALREADY_CURATED]
    for i, (code, t) in enumerate(not_curated[:20], 1):
        print(f"{i:>2}. {code}  impr={t['impressions']:>6}  clicks={t['clicks']:>4}  landing={t['landing_impressions']:>5}  pages={t['pages']}")


if __name__ == "__main__":
    main()
