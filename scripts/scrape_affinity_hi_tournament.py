#!/usr/bin/env python3
"""
Scrape Hawaii Youth Soccer's Oahu League game results from Sports Affinity.

HYSA's public pages share the Oregon layout, so this runs the OR scraper over
the Oahu League.  HYSA labels divisions ``B12U``, ``B14U R1`` and ``G15-19U``,
and starts every team name with that team's own age and gender
(``13UB - HSC Bulls 13/14B - II``).  A game's row carries the home team's label,
and the matcher reads each team's own, so the division sets no team's age.

Usage:
    python scripts/scrape_affinity_hi_tournament.py \
        --age u12 --gender male --days-back 7 --days-forward 30 \
        --output data/raw/affinity_hi/out.csv
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from scripts.scrape_affinity_or_tournament import main

# ── Known HI tournaments / leagues on Affinity ────────────────────────────────

TOURNAMENTS = [
    {
        "name": "2026/27 Oahu League Season",
        "tournament_guid": "B52D16EC-4B82-4251-AD18-8E5C35567EC2",
        # The league's own site; hysa.sportsaffinity.com's league list links here.
        "base_url": "https://ol-fall-26-27.sportsaffinity.com",
        "provider": "affinity_hi",
        "state": "Hawaii",
        "state_code": "HI",
        # The season this event's labels were written in; never the wall clock,
        # for the reason given on the OR scraper's TOURNAMENTS.
        "season_year": 2026,
        # A division holds teams of several ages ('B19U' fields 17UB, 18UB and
        # 19UB), and each name states its own.
        "age_from_name_prefix": True,
        "mixed_age_divisions": True,
        # Games before the 2026-27 season are out, however wide the window.
        "min_game_date": "2026-08-01",
    },
]


if __name__ == "__main__":
    main(TOURNAMENTS)
