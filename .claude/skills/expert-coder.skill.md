---
name: expert-coder
description: Expert Python/TypeScript coding patterns for PitchRank - async patterns, error handling, Supabase integration, testing
---

# Expert Coder Skill for PitchRank

You are an expert software engineer working on PitchRank, a youth soccer ranking platform.

## Tech Stack

- **Backend**: Python 3.11 (async/await, pandas, supabase-py)
- **Frontend**: Next.js 16, React 19, TypeScript
- **Database**: PostgreSQL via Supabase
- **ML**: XGBoost, scikit-learn
- **Scraping**: requests, beautifulsoup4, scrapy

## Code Patterns

### Python Async Pattern
```python
async def fetch_data(supabase_client, table: str, filters: dict):
    """Standard async fetch with error handling."""
    try:
        query = supabase_client.table(table).select('*')
        for key, value in filters.items():
            query = query.eq(key, value)
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Fetch failed for {table}: {e}")
        raise
```

### Batch Processing Pattern
```python
async def process_in_batches(items: list, batch_size: int = 1000):
    """Process large datasets in batches to avoid timeouts."""
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        await process_batch(batch)
        # Small delay between batches
        await asyncio.sleep(0.5)
```

### Supabase Upsert Pattern
```python
def safe_upsert(client, table: str, records: list, batch_size: int = 1000):
    """Upsert with retry logic and batch splitting."""
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        for attempt in range(3):
            try:
                client.table(table).upsert(batch).execute()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
```

## Error Handling

### Always Use
```python
try:
    result = await operation()
except SpecificException as e:
    logger.warning(f"Expected error: {e}")
    # Handle gracefully
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise  # Re-raise unexpected errors
```

### Never Swallow Errors Silently
```python
# BAD
except:
    pass

# GOOD
except Exception as e:
    logger.error(f"Operation failed: {e}")
    # Either handle or re-raise
```

## Logging Standards

```python
import logging
logger = logging.getLogger(__name__)

# Use appropriate levels
logger.debug("Verbose details for debugging")
logger.info("Normal operation milestone")
logger.warning("Recoverable issue")
logger.error("Operation failed")
```

## Type Hints

Always use type hints:
```python
from typing import List, Dict, Optional

def process_teams(
    teams: List[Dict],
    filter_state: Optional[str] = None
) -> List[Dict]:
    ...
```

## Testing Patterns

### Dry Run First
```python
parser.add_argument('--dry-run', action='store_true')

if args.dry_run:
    print(f"Would process {len(items)} items")
    return

# Actual processing
```

### Validation Before Action
```python
def validate_before_save(data: dict) -> List[str]:
    """Return list of validation errors."""
    errors = []
    if not data.get('required_field'):
        errors.append("Missing required_field")
    return errors

errors = validate_before_save(data)
if errors:
    raise ValueError(f"Validation failed: {errors}")
```

## File Organization

```
scripts/           # Runnable scripts with argparse
src/
  scrapers/        # Web scraping modules
  etl/             # Data pipeline
  rankings/        # Ranking algorithm
  models/          # Data models
  utils/           # Shared utilities
tests/
  unit/            # Unit tests
  integration/     # Integration tests
```

## Git Commit Style

```
<type>: <short description>

Types: feat, fix, refactor, docs, test, chore
Example: feat: add TGS event scraper for IDs 4150-4200
```

## Before Submitting Code

1. ✅ Runs without errors
2. ✅ Has --dry-run option for destructive operations
3. ✅ Includes logging at appropriate levels
4. ✅ Type hints on function signatures
5. ✅ Handles errors gracefully
6. ✅ Follows existing patterns in codebase
