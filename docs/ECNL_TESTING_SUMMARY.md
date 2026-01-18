# ECNL Scraping - Testing Summary

## Current Status

### ✅ What's Been Built

1. **Discovery Scripts**: 
   - `scripts/discover_ecnl_conferences.py` - Full discovery
   - `scripts/discover_ecnl_conferences_simple.py` - Simplified version
   - `scripts/discover_ecnl_manual.py` - Manual/API testing

2. **Scraping Scripts**:
   - `scripts/scrape_ecnl_365days.py` - One-time 365-day scraper
   - `scripts/scrape_ecnl_weekly.py` - Weekly incremental scraper

3. **Test Data**:
   - `data/raw/ecnl_conferences_simplified.json` - 3 test entries (1 conference, 3 age groups)

### ⚠️ Known Issues

1. **API 403 Forbidden**: The event list endpoint returns 403, so automatic discovery doesn't work
2. **Discovery Needed**: We only have test data for 1 conference, need to discover all 10 conferences

## Expected Game Data Structure

When the scraper runs successfully, each game will have this structure:

### JSONL Format (for database import)

```json
{
  "provider": "ecnl",
  "team_id": "athone:abc12345",
  "team_id_source": "athone:abc12345",
  "opponent_id": "athone:def67890",
  "opponent_id_source": "athone:def67890",
  "team_name": "FC United 2010",
  "opponent_name": "Real Madrid 2010",
  "game_date": "2025-01-15",
  "home_away": "H",
  "goals_for": 2,
  "goals_against": 1,
  "result": "W",
  "competition": "ECNL Girls Mid-Atlantic 2025-26",
  "venue": "Field 1",
  "source_url": "https://api.athleteone.com/api/Script/get-conference-schedules/9/69/3925/0/0",
  "scraped_at": "2025-12-08T21:30:00"
}
```

### Field Descriptions

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `provider` | string | Always "ecnl" | "ecnl" |
| `team_id` | string | Hash-based team ID | "athone:abc12345" |
| `team_id_source` | string | Source of team ID | "athone:abc12345" |
| `opponent_id` | string | Hash-based opponent ID | "athone:def67890" |
| `opponent_id_source` | string | Source of opponent ID | "athone:def67890" |
| `team_name` | string | Team name from schedule | "FC United 2010" |
| `opponent_name` | string | Opponent name from schedule | "Real Madrid 2010" |
| `game_date` | string | ISO date (YYYY-MM-DD) | "2025-01-15" |
| `home_away` | string | "H" (home) or "A" (away) | "H" |
| `goals_for` | integer/null | Goals scored by team | 2 |
| `goals_against` | integer/null | Goals scored by opponent | 1 |
| `result` | string | "W" (win), "L" (loss), "D" (draw), "U" (unknown) | "W" |
| `competition` | string | Conference name | "ECNL Girls Mid-Atlantic 2025-26" |
| `venue` | string | Venue/field name | "Field 1" |
| `source_url` | string | API endpoint used | "https://api.athleteone.com/..." |
| `scraped_at` | string | ISO timestamp | "2025-12-08T21:30:00" |

### Key Points

1. **Duplicate Games**: Each game appears twice (home and away perspectives). The scraper deduplicates these.

2. **Team IDs**: Generated using MD5 hash of normalized team name (format: `athone:{first_8_chars}`)

3. **Scores**: 
   - `null` = Game not yet played (scheduled)
   - Integer = Final score

4. **Result**: Calculated from scores:
   - `goals_for > goals_against` → "W"
   - `goals_for < goals_against` → "L"
   - `goals_for == goals_against` → "D"
   - Missing scores → "U"

## Testing the Scraper

### Step 1: Test with Current Data

```bash
# Run the 365-day scraper
python scripts/scrape_ecnl_365days.py \
  --conferences-file data/raw/ecnl_conferences_simplified.json \
  --output data/raw/ecnl_test.jsonl

# Inspect the output
head -n 5 data/raw/ecnl_test.jsonl | python -m json.tool
```

### Step 2: Check What Data You Get

Each game should have:
- ✅ Team names (both teams)
- ✅ Game date
- ✅ Home/away indicator
- ✅ Scores (if game was played)
- ✅ Result (W/L/D)
- ✅ Competition name
- ✅ Venue information
- ✅ Team IDs (generated)

### Step 3: Verify Data Quality

Check for:
- Date format consistency (YYYY-MM-DD)
- Score validity (integers or null)
- Team name quality (no extra whitespace, consistent formatting)
- Venue information completeness

## Next Steps

1. **Test Scraper**: Run with current 3 test entries to verify it works
2. **Discover All Conferences**: 
   - Use browser automation to extract all 10 conferences
   - Or manually map them by testing different event_ids
3. **Run Full Scrape**: Once all conferences are discovered, run 365-day scrape
4. **Set Up Weekly**: Configure weekly scraper for ongoing updates

## Troubleshooting

### If API Returns 403

The AthleteOne API may block direct requests. Solutions:
1. Use browser automation (Selenium/Playwright) to fetch HTML
2. Add proper headers and referrer
3. Use the existing AthleteOne client which has retry logic

### If No Games Found

1. Check date range - games might be outside 365 days
2. Verify event_id and flight_id are correct
3. Check if conference has games in that date range
4. Inspect saved HTML to see what the API returns

### If Discovery Fails

1. Use browser DevTools to monitor network requests
2. Extract conference/event mappings manually
3. Test different event_id values systematically
4. Use browser automation to extract dropdown options












