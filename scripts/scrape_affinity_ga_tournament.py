#!/usr/bin/env python3
"""
Scrape Georgia Soccer's fall league game results from Sports Affinity.

Georgia Soccer's public pages share the Oregon layout, so this runs the OR scraper
over the league.  It labels divisions ``12UB Pre GPL``, ``13/14UG GPL/CH`` and
``17/19UB CH/CF North``.  A mixed division carries its youngest age, which stands
in only for a team name stating no board's age: the matcher reads every other
team's age from its own name, so a team playing up keeps its age.

Usage:
    python scripts/scrape_affinity_ga_tournament.py \
        --age u12 --gender male --days-back 7 --days-forward 30 \
        --output data/raw/affinity_ga/out.csv
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from scripts.scrape_affinity_or_tournament import main

# ── Known GA tournaments / leagues on Affinity ────────────────────────────────

TOURNAMENTS = [
    {
        "name": "Fall 26 Georgia Soccer Scheduling",
        "tournament_guid": "72B7A2F4-DB78-434C-8D08-D119FEFD741C",
        # The league's own site; gs.sportsaffinity.com's league list links here.
        "base_url": "https://gs-fall26schedule.sportsaffinity.com",
        "provider": "affinity_ga",
        "state": "Georgia",
        "state_code": "GA",
        # The season the division labels were written in, which set the age of a
        # name stating none; never the wall clock, for the reason given on the OR
        # scraper's TOURNAMENTS.
        "season_year": 2026,
        # Georgia Soccer's rec schedule ('19U BOYS RIAS').
        "skip_divisions": ("RIAS",),
        # A division can span boards ('15/16UB', '17/19UB'), and is scraped once
        # on its youngest age's pass.
        "mixed_age_divisions": True,
        # Games before the 2026-27 season are out, however wide the window.
        "min_game_date": "2026-08-01",
    },
]


if __name__ == "__main__":
    main(TOURNAMENTS)
