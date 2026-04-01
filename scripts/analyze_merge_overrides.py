#!/usr/bin/env python3
"""Analyze full merge history for club canonical override candidates."""

import csv
from collections import defaultdict

with open("data/exports/merge_history_full.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

# Merge direction: deprecated (source) -> canonical (destination)
# The canonical is what the user KEPT. So we want: variant -> canonical
pairs = defaultdict(int)
for row in rows:
    d = (row.get("deprecated_club_name") or "").strip()
    c = (row.get("canonical_club_name") or "").strip()
    state = row.get("deprecated_state") or row.get("canonical_state") or ""
    if d and c and d.lower() != c.lower():
        pairs[(state, d, c)] += 1

# Check conflicts: same state, reverse directions
print("Potential conflicts (A->B and B->A both exist):")
seen = set()
for (state, dep, can), cnt in sorted(pairs.items(), key=lambda x: -x[1]):
    rev = (state, can, dep)
    if rev in pairs and (state, dep, can) not in seen:
        rev_cnt = pairs[rev]
        print(f'  {state}: "{dep}" <-> "{can}" ({cnt}x vs {rev_cnt}x)')
        seen.add((state, dep, can))
        seen.add(rev)

print()
print("Top 40 patterns (deprecated -> canonical) for override candidates:")
print("Format: state | count | FROM -> TO (canonical)")
print("=" * 100)
for (state, dep, can), cnt in sorted(pairs.items(), key=lambda x: -x[1])[:40]:
    print(f"  {state:3} | {cnt:2}x | {dep[:45]:<45} -> {can[:45]}")
