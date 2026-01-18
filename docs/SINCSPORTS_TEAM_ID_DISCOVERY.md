# SincSports Team ID Discovery

## Key Finding

From browser analytics data, discovered:

### Team URL Structure
- **Base URL**: `https://soccer.sincsports.com/team/default.aspx`
- **Team ID Parameter**: `teamid=NCM14762`
- **Full URL**: `https://soccer.sincsports.com/team/default.aspx?teamid=NCM14762`

### Team ID Format
- **Format**: Alphanumeric (not just numeric!)
- **Example**: `NCM14762`
- **Pattern**: Appears to be `[PREFIX][NUMBERS]`
  - `NCM` - Possibly state/region code (NC = North Carolina?)
  - `14762` - Sequential or encoded number

### Implications

1. **Team IDs are alphanumeric**: Need to handle string IDs, not just integers
2. **State/Region Prefix**: IDs may include location information
3. **URL Parameter**: Uses `teamid=` query parameter (not path-based)

## Next Steps

1. **Test Team Page Access**:
   - Try accessing `https://soccer.sincsports.com/team/default.aspx?teamid=NCM14762`
   - Document page structure
   - Check for game history/schedule

2. **Find More Team IDs**:
   - Perform searches to get more team ID examples
   - Identify patterns in prefixes
   - Map prefixes to states/regions if possible

3. **Explore Team Page Data**:
   - What data is available on team pages?
   - Is game history visible?
   - Are there links to games/matches?

4. **Document ID Patterns**:
   - Collect multiple team IDs
   - Identify common prefixes
   - Understand numbering scheme

## Team ID Examples

- `NCM14762` - First discovered example

## Scraper Implementation Notes

When implementing the scraper:

```python
def scrape_team_games(self, team_id: str, since_date: Optional[datetime] = None):
    """
    Scrape games for a SincSports team
    
    Args:
        team_id: SincSports team ID (e.g., 'NCM14762')
        since_date: Only scrape games after this date
    """
    # Team page URL
    team_url = f"https://soccer.sincsports.com/team/default.aspx?teamid={team_id}"
    
    # Fetch team page
    response = self.session.get(team_url)
    
    # Parse HTML for game data
    # ... implementation
```

**Important**: Team IDs are strings, not integers. Handle accordingly in validation and storage.


















