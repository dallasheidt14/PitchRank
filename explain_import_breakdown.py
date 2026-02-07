"""
Breakdown of why only 9 games were imported from 3,828 CSV rows
"""

print("="*70)
print("IMPORT BREAKDOWN ANALYSIS")
print("="*70)

total_csv_rows = 3828
perspective_duplicates = 1971  # Same game from both teams' perspective
unique_games_after_dedup = 1857  # Total unique games (by game_uid)
composite_key_duplicates = 307  # Games already in DB with same composite key
games_accepted = 9

# Calculate game_uid conflicts
games_after_composite_check = unique_games_after_dedup - composite_key_duplicates
game_uid_conflicts = games_after_composite_check - games_accepted

print(f"\n1. CSV ROWS: {total_csv_rows:,}")
print(f"   Each game appears twice (home + away perspective)")

print(f"\n2. PERSPECTIVE DEDUPLICATION: -{perspective_duplicates:,}")
print(f"   Removed duplicate perspectives")
print(f"   Remaining: {unique_games_after_dedup:,} unique games")

print(f"\n3. COMPOSITE KEY DUPLICATES: -{composite_key_duplicates:,}")
print(f"   Games already in database (same teams/date/scores)")
print(f"   Remaining: {games_after_composite_check:,} potentially new games")

print(f"\n4. GAME_UID CONFLICTS: -{game_uid_conflicts:,}")
print(f"   Games with same game_uid as existing games but DIFFERENT scores")
print(f"   These CAN'T be inserted due to unique constraint on game_uid")
print(f"   Example: DB has scores 3-4, CSV has scores 1-5 (same teams/date)")

print(f"\n5. FINAL ACCEPTED: {games_accepted:,}")
print(f"   Games that were successfully imported")

print("\n" + "="*70)
print("THE PROBLEM:")
print("="*70)
print("""
The database has a UNIQUE constraint on `game_uid`, which is:
  {provider}:{date}:{team1}:{team2}

But `game_uid` doesn't include scores! So if the same teams play on the 
same date with different scores, they have the same `game_uid` but are 
different games.

The database prevents inserting a second game with the same `game_uid`,
even if the scores are different.

SOLUTIONS:
1. Update existing games with CSV scores (if CSV is more accurate)
2. Remove unique constraint on game_uid (allows multiple games with same game_uid)
3. Change game_uid format to include scores (breaks existing data)
4. Keep current behavior (skip conflicting games)
""")

print("\n" + "="*70)
print("RECOMMENDATION:")
print("="*70)
print("""
Since you just rescraped the data, the CSV likely has the most accurate scores.
Consider updating existing games with CSV scores for games where:
- game_uid matches
- composite key differs (different scores)
- CSV date is more recent than DB game date
""")
