#!/usr/bin/env python3
"""
One-time backfill script to import existing Modular11 (MLS NEXT) game data
into the games table so HD teams appear in rankings and SOS is accurate.

This script:
1. Finds the best source files in scrapers/modular11_scraper/output/
2. Combines league + events data, deduplicating by (team_id, opponent_id, game_date, age_group)
3. Pipes the combined data through the existing import pipeline

Usage:
    python scripts/backfill_modular11_games.py                    # Full import
    python scripts/backfill_modular11_games.py --dry-run          # Preview without DB writes
    python scripts/backfill_modular11_games.py --events-only      # Only events data
    python scripts/backfill_modular11_games.py --league-only      # Only league data
"""
import argparse
import csv
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / 'scrapers' / 'modular11_scraper' / 'output'

# Expected CSV columns from Modular11 scraper
EXPECTED_COLUMNS = [
    'provider', 'team_id', 'team_id_source', 'team_name', 'club_name',
    'opponent_id', 'opponent_id_source', 'opponent_name', 'opponent_club_name',
    'age_group', 'gender', 'state', 'competition', 'division_name',
    'event_name', 'venue', 'mls_division', 'game_date', 'home_away',
    'goals_for', 'goals_against', 'result', 'source_url', 'scraped_at'
]


def find_best_league_file() -> Path:
    """Find the most comprehensive league data file.

    Strategy: use modular11_results.csv (the consolidated file) if it exists,
    otherwise fall back to the newest timestamped file.
    """
    consolidated = OUTPUT_DIR / 'modular11_results.csv'
    if consolidated.exists() and consolidated.stat().st_size > 1000:
        return consolidated

    # Fall back to newest timestamped file
    timestamped = sorted(
        OUTPUT_DIR.glob('modular11_results_*.csv'),
        key=lambda p: p.stat().st_size,
        reverse=True
    )
    # Pick the largest file (most complete scrape)
    for f in timestamped:
        if f.stat().st_size > 1000:  # Skip empty/header-only files
            return f

    return None


def find_events_file() -> Path:
    """Find the events data file."""
    events_file = OUTPUT_DIR / 'modular11_events_365days.csv'
    if events_file.exists() and events_file.stat().st_size > 1000:
        return events_file
    return None


def load_and_validate_csv(filepath: Path) -> list:
    """Load a CSV file and validate it has the expected structure."""
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Check for key columns
        required = {'team_id', 'opponent_id', 'game_date', 'goals_for', 'goals_against', 'age_group'}
        missing = required - set(headers)
        if missing:
            logger.warning(f"File {filepath.name} missing columns: {missing}")
            return []

        for row in reader:
            # Skip rows with empty scores (unplayed games)
            gf = (row.get('goals_for') or '').strip()
            ga = (row.get('goals_against') or '').strip()
            if not gf or not ga:
                continue
            try:
                int(float(gf))
                int(float(ga))
            except (ValueError, TypeError):
                continue

            # Skip rows with empty team IDs
            if not (row.get('team_id') or '').strip():
                continue
            if not (row.get('opponent_id') or '').strip():
                continue

            rows.append(row)

    return rows


def deduplicate_games(rows: list) -> list:
    """Deduplicate games by composite key.

    Each game appears as 2 perspective rows (home + away). We keep the
    home perspective row (home_away=H) and drop the away duplicate.
    This prevents the import pipeline from seeing each game twice.
    """
    seen = set()
    unique = []

    for row in rows:
        team_id = (row.get('team_id') or '').strip()
        opp_id = (row.get('opponent_id') or '').strip()
        date = (row.get('game_date') or '').strip()
        age = (row.get('age_group') or '').strip()
        division = (row.get('mls_division') or '').strip()

        # Canonical key: sort team IDs so both perspectives map to same key
        teams = tuple(sorted([team_id, opp_id]))
        key = (teams[0], teams[1], date, age, division)

        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    return unique


def write_combined_csv(rows: list, output_path: Path):
    """Write combined, deduplicated rows to a CSV file."""
    if not rows:
        return

    # Use the union of all keys present in rows
    all_keys = set()
    for row in rows:
        all_keys.update(row.keys())

    # Prefer expected column order, then add any extras
    fieldnames = [c for c in EXPECTED_COLUMNS if c in all_keys]
    extras = sorted(all_keys - set(fieldnames))
    fieldnames.extend(extras)

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description='Backfill Modular11 game data')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without importing to database')
    parser.add_argument('--league-only', action='store_true',
                        help='Only import league (season) games')
    parser.add_argument('--events-only', action='store_true',
                        help='Only import events/tournament games')
    parser.add_argument('--batch-size', type=int, default=500,
                        help='Import batch size (default: 500)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit number of games to import (for testing)')
    args = parser.parse_args()

    if args.league_only and args.events_only:
        logger.error("Cannot use both --league-only and --events-only")
        sys.exit(1)

    # Find source files
    all_rows = []

    if not args.events_only:
        league_file = find_best_league_file()
        if league_file:
            logger.info(f"Loading league data from: {league_file.name} ({league_file.stat().st_size / 1024:.0f} KB)")
            league_rows = load_and_validate_csv(league_file)
            logger.info(f"  Loaded {len(league_rows):,} valid league game rows")
            all_rows.extend(league_rows)
        else:
            logger.warning("No league data file found")

    if not args.league_only:
        events_file = find_events_file()
        if events_file:
            logger.info(f"Loading events data from: {events_file.name} ({events_file.stat().st_size / 1024:.0f} KB)")
            events_rows = load_and_validate_csv(events_file)
            logger.info(f"  Loaded {len(events_rows):,} valid events game rows")
            all_rows.extend(events_rows)
        else:
            logger.warning("No events data file found")

    if not all_rows:
        logger.error("No game data found to import")
        sys.exit(1)

    logger.info(f"Total rows before deduplication: {len(all_rows):,}")

    # Deduplicate
    unique_rows = deduplicate_games(all_rows)
    logger.info(f"After deduplication: {len(unique_rows):,} unique games")

    if args.limit:
        unique_rows = unique_rows[:args.limit]
        logger.info(f"Limited to {len(unique_rows):,} games for testing")

    # Write combined CSV to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, prefix='modular11_backfill_') as tmp:
        tmp_path = Path(tmp.name)

    write_combined_csv(unique_rows, tmp_path)
    logger.info(f"Wrote combined CSV to: {tmp_path}")

    # Build import command
    import_script = Path(__file__).parent / 'import_games_enhanced.py'
    cmd_parts = [
        sys.executable, str(import_script),
        str(tmp_path), 'modular11',
        '--batch-size', str(args.batch_size),
        '--summary-only',
    ]

    if args.dry_run:
        cmd_parts.append('--dry-run')

    logger.info(f"Running import: {' '.join(cmd_parts)}")

    # Execute import
    import subprocess
    result = subprocess.run(cmd_parts, cwd=str(Path(__file__).parent.parent))

    # Cleanup
    try:
        tmp_path.unlink()
    except OSError:
        pass

    if result.returncode != 0:
        logger.error(f"Import failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    logger.info("Backfill complete!")


if __name__ == '__main__':
    main()
