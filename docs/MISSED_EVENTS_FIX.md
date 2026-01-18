# Fixing Missed Events in GotSport Event Scraper

## Problem

The GitHub Action `src.scrapers.gotsport_event` was successfully running but missing some events. For example, event ID `45163` (The Open 2025) was not being discovered.

## Root Causes

1. **GotSport Search Limitations**: The event discovery relies on GotSport's search page (`home.gotsoccer.com/events.aspx`), which may not return all events due to:
   - Incomplete indexing
   - Pagination limits
   - Events not appearing in search results for their dates
   - Search results being filtered or limited

2. **Date Filtering**: Events ending on the same day as the scraper run might be filtered out if date extraction fails

3. **Event ID Resolution**: Some events might not resolve correctly from rankings EventIDs to system.gotsport.com event IDs

## Solutions Implemented

### 1. Manual Event ID Support

Added support for manually specifying event IDs that are known to be missed:

```bash
# Scrape specific missed events
python scripts/scrape_new_gotsport_events.py --manual-event-ids 45163 45164

# Or use the dedicated script
python scripts/scrape_specific_event.py 45163
```

### 2. Improved Event Discovery

- Added better logging to track discovery process
- Improved date filtering to include events ending today (not just past events)
- Better error handling for event ID resolution
- Improved event name extraction from JavaScript-discovered events

### 3. Fallback Scraping Method

When an event fails to extract teams via the normal method, the scraper now automatically tries the schedule page method, which is more reliable for some event formats.

### 4. Diagnostic Script

Created `scripts/diagnose_missed_events.py` to help identify missed events:

```bash
# Check for missed events in last 14 days
python scripts/diagnose_missed_events.py --days-back 14 --check-summaries
```

## Usage

### For Known Missed Events

If you know specific event IDs that were missed:

```bash
# Option 1: Add to the weekly scraper run
python scripts/scrape_new_gotsport_events.py --manual-event-ids 45163

# Option 2: Use the dedicated script (recommended for one-off events)
python scripts/scrape_specific_event.py 45163
```

### For Discovering Missed Events

Run the diagnostic script to find events that were discovered but not scraped:

```bash
python scripts/diagnose_missed_events.py --days-back 14 --check-summaries
```

This will:
- Compare discovered events vs scraped events
- Show events that were found but not scraped
- Check recent summary files for events with issues
- Save a list of missed events to `data/raw/missed_events_*.json`

### Using GitHub Actions

#### Scrape Specific Event (Recommended for One-Off Events)

A dedicated GitHub Action workflow is available to scrape specific events:

1. Go to **Actions** tab in your GitHub repository
2. Select **"Scrape Specific GotSport Event"** workflow
3. Click **"Run workflow"**
4. Enter the event ID (e.g., `45163`)
5. Optionally adjust:
   - **lookback_days**: How many days of games to scrape (default: 30)
   - **auto_import**: Whether to automatically import games (default: true)
6. Click **"Run workflow"**

The workflow will:
- Scrape the specified event
- Upload scraped data as artifacts
- Mark the event as scraped (so it won't be attempted again)
- Optionally import games to the database

#### Adding Manual Event IDs to Weekly Scraper

To add manual event IDs to the weekly scraper, you can:

1. **Temporary fix**: Manually trigger the workflow with manual event IDs
2. **Permanent fix**: Add a file with known event IDs and modify the workflow to read from it

Example workflow modification:

```yaml
- name: Run GotSport Event Scraper
  run: |
    # Check for manual event IDs file
    if [ -f "data/manual_event_ids.txt" ]; then
      MANUAL_IDS=$(cat data/manual_event_ids.txt | tr '\n' ' ')
      python scripts/scrape_new_gotsport_events.py --manual-event-ids $MANUAL_IDS
    else
      python scripts/scrape_new_gotsport_events.py
    fi
```

## Files Changed

1. `scripts/scrape_new_gotsport_events.py`
   - Added `manual_event_ids` parameter
   - Improved date filtering logic
   - Added fallback to schedule page scraping
   - Better logging and error handling

2. `scripts/scrape_specific_event.py` (new)
   - Dedicated script for scraping specific events
   - Useful for one-off event scraping
   - Supports `--force` flag for CI/non-interactive use

3. `scripts/diagnose_missed_events.py` (new)
   - Diagnostic tool to find missed events
   - Compares discovered vs scraped events
   - Analyzes recent scrape results

4. `.github/workflows/scrape-specific-event.yml` (new)
   - GitHub Action workflow for scraping specific events
   - Can be triggered manually with event ID input
   - Supports configurable lookback days and auto-import options

## Recommendations

1. **Regular Monitoring**: Run the diagnostic script weekly to catch missed events
2. **Manual Event List**: Maintain a list of known event IDs that need manual scraping
3. **Improve Discovery**: Consider alternative discovery methods (e.g., checking specific tournament series, known event organizers)
4. **Better Logging**: Monitor GitHub Action logs for events that fail to scrape

## Example: Scraping The Open 2025 (Event 45163)

### Option 1: Using GitHub Actions (Recommended)

1. Go to **Actions** → **Scrape Specific GotSport Event**
2. Click **"Run workflow"**
3. Enter event ID: `45163`
4. Click **"Run workflow"**

### Option 2: Using Command Line

```bash
# Scrape the missed event locally
python scripts/scrape_specific_event.py 45163

# Or add it to the weekly run
python scripts/scrape_new_gotsport_events.py --manual-event-ids 45163
```

The event will be scraped and marked as complete, preventing it from being attempted again in future runs.












