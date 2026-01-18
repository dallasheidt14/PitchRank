# ECNL Conference Discovery Note

## Current Status

The `data/raw/ecnl_conferences_simplified.json` file currently contains **test data** with only 3 entries for one conference (Mid-Atlantic) with different age groups.

## Expected Conferences

From browser inspection, there should be **10 conferences**:

1. ECNL Girls Mid-Atlantic 2025-26
2. ECNL Girls Midwest 2025-26
3. ECNL Girls New England 2025-26
4. ECNL Girls North Atlantic 2025-26
5. ECNL Girls Northern Cal 2025-26
6. ECNL Girls Northwest 2025-26
7. ECNL Girls Ohio Valley 2025-26
8. ECNL Girls Southeast 2025-26
9. ECNL Girls Southwest 2025-26
10. ECNL Girls Texas 2025-26

Each conference typically has **6 age groups**:
- G2013
- G2012
- G2011
- G2010
- G2009
- G2008/2007

So we should have approximately **60 conference/age group combinations** (10 conferences × 6 age groups).

## Discovery Challenge

The discovery scripts may not be finding all conferences because:

1. **API Response Format**: The AthleteOne API may return data in a format that's not easily parseable (JSON, HTML, or JavaScript)
2. **Dynamic Loading**: Conferences may be loaded dynamically via JavaScript
3. **Authentication**: Some endpoints may require authentication or specific headers

## Solutions

### Option 1: Browser Automation (Recommended)

Use Selenium or Playwright to:
1. Navigate to the ECNL schedule page
2. Extract conference dropdown options
3. For each conference, extract age group options
4. Map conferences to event/flight IDs by monitoring network requests

### Option 2: Manual Mapping

Manually test each conference by:
1. Opening the ECNL schedule page in a browser
2. Selecting each conference and age group
3. Monitoring network requests to find event_id and flight_id
4. Creating the conferences file manually

### Option 3: Test Event IDs

Try different event_id values systematically:
- Start with known event_id (3925 for Mid-Atlantic)
- Test nearby IDs (3924, 3926, etc.)
- Test IDs for other conferences (may follow a pattern)

## Next Steps

1. **Run discovery script** and check the log file:
   ```bash
   python scripts/discover_ecnl_conferences_simple.py
   # Check: data/raw/ecnl_discovery_log.txt
   ```

2. **Inspect API response**:
   ```bash
   # Check: data/raw/ecnl_event_list_api.html
   ```

3. **Test with browser automation** to extract all conferences

4. **For now**: Use the test data to verify the scraping works, then expand to all conferences once discovered

## Testing with Current Data

Even with just 3 test entries, you can:
- Test the scraping infrastructure
- Verify data structure
- Check API access
- Validate parsing logic

Once the scraping works for one conference, it should work for all conferences once they're discovered.












