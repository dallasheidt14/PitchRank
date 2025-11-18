# Fuzzy Match Review Dashboard

## Overview

The Fuzzy Match Review Dashboard is a web-based interface built with Streamlit that allows you to review and approve team matches that require manual verification. This dashboard provides a user-friendly way to manage fuzzy team matches with confidence scores between 0.75 and 0.90.

## Features

### 📊 Statistics Dashboard
- **Total pending matches** - Overall count of matches needing review
- **High confidence matches (0.85-0.89)** - Best quality matches, usually safe to approve
- **Medium confidence matches (0.80-0.84)** - Good quality matches
- **Low confidence matches (0.75-0.79)** - Requires careful review
- **Visual confidence distribution chart** - Bar chart showing match quality distribution

### 🔎 Advanced Filtering
- **Confidence threshold slider** - Filter matches by minimum confidence score
- **Age group filter** - Review matches for specific age groups
- **Gender filter** - Filter by Male/Female teams

### ✅ Match Review Interface
Each match displays:
- **Side-by-side comparison** of provider team vs. matched database team
- **Team details**: Name, age group, gender, club, state
- **Confidence score** with color coding (🟢 High, 🟡 Medium, 🔴 Low)
- **Match method** and creation date
- **Master Team ID** for reference

### ⚡ Batch Operations
- **Auto-approve high confidence matches** - Bulk approve matches above a confidence threshold
- **Refresh data** - Reload pending matches from the database

### ℹ️ Built-in Help
- Comprehensive guide on how fuzzy matching works
- Confidence score calculation breakdown
- Best practices for reviewing matches
- Explanation of what happens after approval

## Getting Started

### Prerequisites

1. **Environment Variables** - Ensure you have these set in your `.env` file:
   ```bash
   SUPABASE_URL=your_supabase_url
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
   ```

2. **Python Dependencies** - Install required packages:
   ```bash
   pip install streamlit pandas supabase python-dotenv
   ```

### Running the Dashboard

1. **Start the Streamlit dashboard:**
   ```bash
   streamlit run dashboard.py
   ```

2. **Navigate to the Fuzzy Match Review section:**
   - Open your browser to `http://localhost:8501`
   - Use the sidebar navigation to select "Fuzzy Match Review"

3. **Review matches:**
   - Browse pending matches sorted by confidence (highest first)
   - Use filters to narrow down matches by confidence, age group, or gender
   - Expand each match to see detailed comparison
   - Click "Approve" or "Reject" for individual matches

## Understanding Fuzzy Matching

### How Confidence Scores Are Calculated

The fuzzy matching system uses a weighted scoring algorithm:

| Component | Weight | Description |
|-----------|--------|-------------|
| Team Name Similarity | 65% | Primary matching factor - normalized team name comparison |
| Club Name Similarity | 25% | Secondary factor - helps distinguish teams with similar names |
| Age Group Match | 5% | Must be exact match |
| Location Match | 5% | State/region proximity |

**Example:**
```
Provider Team: "FC Dallas U12 Boys"
Database Team: "FC Dallas 12 Boys"

Team Name: 95% similar (after normalization)
Club Name: 100% similar ("FC Dallas")
Age Group: 100% match (U12 = 12)
Location: 100% match (both Texas)

Final Score: (0.95 × 0.65) + (1.0 × 0.25) + (1.0 × 0.05) + (1.0 × 0.05) = 0.918
```

### Confidence Thresholds

| Score Range | Action | Description |
|-------------|--------|-------------|
| ≥ 0.90 | Auto-Approve | High confidence - automatically accepted |
| 0.75 - 0.89 | Manual Review | Requires human verification (this dashboard) |
| < 0.75 | Auto-Reject | Too uncertain - not matched |

## Best Practices

### 1. Review Priority
Start with high-confidence matches (0.85-0.89) as they're usually correct and quick to verify.

### 2. What to Check
- ✅ **Age group matches** - Ensure both teams are the same age
- ✅ **Gender matches** - Verify male/female alignment
- ✅ **Club similarity** - Check if club names are related or identical
- ✅ **Team name similarity** - Look for obvious matches despite formatting differences

### 3. When to Approve
Approve when:
- Team names are clearly the same (ignoring formatting)
- Age group and gender match exactly
- Club names are identical or clearly related
- You're confident they represent the same team

### 4. When to Reject
Reject when:
- Team names are substantially different
- Age groups don't match
- Gender doesn't match
- You suspect they're different teams
- **When in doubt, reject** - it's safer to review again later

### 5. Batch Operations
- Use **Auto-Approve** for high confidence matches (≥0.88) to save time
- Review a few manually first to ensure quality
- Set a high threshold (0.88+) for batch operations

## What Happens After Approval?

When you approve a match:
1. The entry in `team_alias_map` is updated with `review_status = 'approved'`
2. Future imports will automatically match this provider team to the master team
3. Games for this team will be properly linked to the team's historical data
4. No manual review will be needed for this team in future imports

When you reject a match:
1. The entry is marked with `review_status = 'rejected'`
2. The game remains unmatched (won't be imported with this team linkage)
3. The team may be re-evaluated in future imports if data improves

## Troubleshooting

### Dashboard won't load
- **Check environment variables** - Ensure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set
- **Verify .env file** - Make sure it's in the project root directory
- **Test connection** - Try running `scripts/review_matches.py --stats` to verify database connectivity

### No matches appearing
- **Check review_status** - Matches may have already been reviewed
- **Verify confidence range** - Adjust the confidence slider
- **Check filters** - Reset age group and gender filters to "All"

### Approve/Reject not working
- **Database permissions** - Ensure your service role key has write permissions
- **Check browser console** - Look for JavaScript errors
- **Try refresh** - Click the "Refresh" button to reload data

## CLI Alternative

If you prefer command-line tools, you can use the original CLI reviewer:

```bash
# Review pending matches interactively
python scripts/review_matches.py

# Limit to first 10 matches
python scripts/review_matches.py --limit 10

# Show statistics only
python scripts/review_matches.py --stats
```

## Database Schema

The dashboard interacts with these tables:

### team_alias_map
Stores team match mappings and review status.

```sql
CREATE TABLE team_alias_map (
    id UUID PRIMARY KEY,
    provider_id UUID REFERENCES providers(id),
    provider_team_id TEXT NOT NULL,
    team_id_master UUID REFERENCES teams(team_id_master),
    team_name VARCHAR(255),
    age_group VARCHAR(10),
    gender VARCHAR(10),
    match_confidence FLOAT NOT NULL,
    match_method VARCHAR(50) NOT NULL,
    review_status VARCHAR(20) DEFAULT 'approved',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### teams
Master team database.

```sql
CREATE TABLE teams (
    id UUID PRIMARY KEY,
    team_id_master UUID NOT NULL UNIQUE,
    team_name TEXT NOT NULL,
    club_name TEXT,
    state_code CHAR(2),
    age_group TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('Male', 'Female')),
    ...
);
```

## Configuration

Fuzzy matching parameters can be viewed in the "Matching Configuration" section of the dashboard:

| Parameter | Default | Description |
|-----------|---------|-------------|
| fuzzy_threshold | 0.75 | Minimum score for potential matches |
| auto_approve_threshold | 0.90 | Score for automatic approval |
| review_threshold | 0.75 | Score requiring manual review |
| max_age_diff | 2 | Maximum age group difference |

These can be modified in `config/settings.py` under `MATCHING_CONFIG`.

## Support

For issues, questions, or feature requests:
- Review the main documentation: `TEAM_MATCHING_EXPLAINED.md`
- Check the system overview: `SYSTEM_OVERVIEW.md`
- Run CLI stats: `python scripts/review_matches.py --stats`

## Version History

- **v1.0** (2025) - Initial release with comprehensive fuzzy match review interface
  - Statistics dashboard with confidence distribution
  - Advanced filtering (confidence, age group, gender)
  - Individual and batch approve/reject operations
  - Built-in help and best practices guide
