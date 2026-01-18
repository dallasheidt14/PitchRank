#!/usr/bin/env python3
"""Analyze how many games each team played"""
import csv
from collections import Counter
from pathlib import Path

csv_path = Path('data/raw/tgs/tgs_events_4066_4066_2025-12-11T20-26-36-840795+00-00.csv')

team_games = Counter()

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '')
        team_name = row.get('team_name', '')
        if team_id:
            team_games[(team_id, team_name)] += 1

print(f"Total team appearances: {sum(team_games.values())}")
print(f"Unique teams: {len(team_games)}")
print(f"Total games: {sum(team_games.values()) // 2}")
print(f"\nAverage games per team: {sum(team_games.values()) / len(team_games):.1f}")
print("\n" + "=" * 80)
print("Teams by number of games played:")
print("=" * 80)

# Group by number of games
games_count = Counter(team_games.values())
for num_games in sorted(games_count.keys(), reverse=True):
    num_teams = games_count[num_games]
    print(f"{num_games} games: {num_teams} teams")

print("\n" + "=" * 80)
print("Sample teams:")
print("=" * 80)
for (team_id, team_name), count in team_games.most_common(10):
    print(f"{team_name:<50} ({team_id}): {count} appearances ({count//2} games)")









