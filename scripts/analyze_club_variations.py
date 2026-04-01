#!/usr/bin/env python3
"""Find club name variations in DB that could use canonical overrides."""

import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
db = create_client(url, key)

# Fetch all distinct (club_name, state_code) with team count
r = db.table("teams").select("club_name, state_code").eq("is_deprecated", False).execute()
rows = r.data or []

# Group by state
by_state = defaultdict(lambda: defaultdict(int))
for row in rows:
    club = (row.get("club_name") or "").strip()
    state = (row.get("state_code") or "").strip()
    if club and state:
        by_state[state][club] += 1


# Find variations: same lowercase, or obvious abbrevs
def find_variations():
    suggestions = []
    for state, clubs in sorted(by_state.items()):
        # 1. Case variations (same lower, different casing)
        by_lower = defaultdict(list)
        for name, cnt in clubs.items():
            by_lower[name.lower()].append((name, cnt))
        for lower, variants in by_lower.items():
            if len(variants) > 1:
                winner = max(variants, key=lambda x: x[1])
                for name, cnt in variants:
                    if name != winner[0]:
                        suggestions.append((state, "CAPS", name, winner[0], cnt))

        # 2. Common abbreviation patterns
        abbrevs = [
            ("OK Energy FC", "Oklahoma Energy FC"),
            ("Ok Energy FC", "Oklahoma Energy FC"),
            ("Lonestar", "Lonestar SC"),
            ("Mo Rush", "Missouri Rush"),
            ("Florida Krush", "Florida Kraze Krush"),
            ("Oklahoma Celtic", "Oklahoma Celtic Football Club"),
            ("St Petersburg FC", "St. Petersburg Football Club"),
            ("St. Petersburg Football Club", "St Petersburg FC"),
            ("East Valley/NSFC", "East Valley NSFC"),
            ("East Valley NSFC", "East Valley/NSFC"),
        ]
        for short, long_form in abbrevs:
            if short in clubs and long_form in clubs:
                # Both exist - pick one as canonical
                sc = clubs[short]
                lc = clubs[long_form]
                canonical = long_form if lc >= sc else short
                other = short if canonical == long_form else long_form
                suggestions.append((state, "ABBREV", other, canonical, clubs[other]))

    return suggestions


# Also: clubs that look like they could be merged (similar names)
print("Checking for club name variations in DB...")
print()

# States with high merge activity from our analysis
high_merge_states = ["OK", "TX", "FL", "OH", "CA", "MO", "NC", "WA", "OR", "GA", "MD", "VA", "SC", "CO", "NM", "AZ"]

for state in high_merge_states:
    clubs = by_state.get(state, {})
    if not clubs:
        continue
    # Case variations
    by_lower = defaultdict(list)
    for name, cnt in clubs.items():
        by_lower[name.lower()].append((name, cnt))
    for lower, variants in by_lower.items():
        if len(variants) > 1:
            sorted_v = sorted(variants, key=lambda x: -x[1])
            winner = sorted_v[0][0]
            for name, cnt in sorted_v[1:]:
                print(f"  {state} CAPS: '{name}' ({cnt}) -> '{winner}'")

# Explicit patterns we've seen in merges / data
print()
print("Suggested canonical overrides (from common patterns):")
print("-" * 80)

suggestions = []
# OK
if "Ok Energy FC" in by_state.get("OK", {}):
    suggestions.append(("OK", "exact", "Ok Energy FC", "Oklahoma Energy FC"))
if "OK Energy FC" in by_state.get("OK", {}):
    suggestions.append(("OK", "exact", "OK Energy FC", "Oklahoma Energy FC"))
# TX
if "Lonestar" in by_state.get("TX", {}) and "Lonestar SC" not in by_state.get("TX", {}):
    suggestions.append(("TX", "exact", "Lonestar", "Lonestar SC"))
# MO
if "Mo Rush" in by_state.get("MO", {}):
    suggestions.append(("MO", "exact", "Mo Rush", "Missouri Rush"))
# FL
if "Florida Krush" in by_state.get("FL", {}):
    suggestions.append(("FL", "exact", "Florida Krush", "Florida Kraze Krush"))
# OK
if "Oklahoma Celtic" in by_state.get("OK", {}) and "Oklahoma Celtic" != "Oklahoma Celtic Football Club":
    suggestions.append(("OK", "prefix", "Oklahoma Celtic", "Oklahoma Celtic Football Club"))

# Query actual DB for these
for state in ["OK", "TX", "MO", "FL"]:
    clubs = list(by_state.get(state, {}).keys())
    for c in clubs:
        c_lower = c.lower()
        if "ok energy" in c_lower or "oklahoma energy" in c_lower:
            print(f"  OK Energy variants: {c} ({by_state['OK'][c]} teams)")
        if "lonestar" in c_lower and state == "TX":
            print(f"  TX Lonestar variants: {c} ({by_state['TX'][c]} teams)")
        if "mo rush" in c_lower or "missouri rush" in c_lower:
            print(f"  MO Rush variants: {c} ({by_state['MO'][c]} teams)")
        if "florida krush" in c_lower or "florida kraze" in c_lower:
            print(f"  FL Krush variants: {c} ({by_state['FL'][c]} teams)")
        if "oklahoma celtic" in c_lower:
            print(f"  OK Celtic variants: {c} ({by_state['OK'][c]} teams)")
