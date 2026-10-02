#!/usr/bin/env python3
"""
Scrape Utah Youth Soccer game results from Sports Affinity (uysa.sportsaffinity.com).

UYSA's public pages share the Oregon layout, so this runs the OR scraper over
Utah's leagues.  UYSA labels divisions ``Boys 12U Premier`` and
``Boys 18/19U Premier``; as in Oregon, the U-number is the cohort. Unlike
Oregon, a game is filed by its teams' own names rather than its division.

Usage:
    python scripts/scrape_affinity_ut_tournament.py \
        --age u12 --gender male --days-back 7 --days-forward 30 \
        --output data/raw/affinity_ut/out.csv
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from scripts.scrape_affinity_or_tournament import main

# ── Known UT tournaments / leagues on Affinity ────────────────────────────────

TOURNAMENTS = [
    {
        "name": "2026 UYSA Fall League",
        "tournament_guid": "69C35A62-D325-418C-95D3-C61FA95030D3",
        "base_url": "https://uysa.sportsaffinity.com",
        "provider": "affinity_ut",
        "state": "Utah",
        "state_code": "UT",
        # The season this event's U-numbers were written in; never the wall
        # clock, for the reason given on the OR scraper's TOURNAMENTS.
        "season_year": 2026,
        # Utah's team names carry their age ("Peak SC 13/14B", "La Roca U12B"),
        # and teams play up, so each game is filed by its teams' names.
        "age_from_team_name": True,
    },
]


if __name__ == "__main__":
    main(TOURNAMENTS)
