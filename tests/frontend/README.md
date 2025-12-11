# Frontend Testing with Playwright

This directory contains Playwright-based testing tools for auditing and testing the PitchRank frontend.

## Setup

### Node.js (Recommended)

Playwright is included in frontend dependencies:

```bash
cd frontend
npm install
npx playwright install chromium
```

### Python

For Python scripts:

```bash
pip install playwright
python -m playwright install chromium
```

## Quick Start

### Option 1: With Server Helper (Recommended)

The `with_server.py` helper manages the dev server lifecycle automatically:

```bash
# Run element discovery
python scripts/with_server.py \
  --server "cd frontend && npm run dev" --port 3000 \
  -- python examples/element_discovery.py http://localhost:3000

# Run comprehensive audit
python scripts/with_server.py \
  --server "cd frontend && npm run dev" --port 3000 \
  -- python examples/pitchrank_audit.py --verbose

# Capture console logs
python scripts/with_server.py \
  --server "cd frontend && npm run dev" --port 3000 \
  -- python examples/console_logging.py http://localhost:3000
```

### Option 2: Manual Server Start

Start the dev server separately, then run tests:

```bash
# Terminal 1: Start the server
cd frontend && npm run dev

# Terminal 2: Run tests
python examples/pitchrank_audit.py --base-url http://localhost:3000
```

## Available Scripts

### `scripts/with_server.py`

Server lifecycle manager. Starts servers, waits for them to be ready, runs your command, then cleans up.

```bash
python scripts/with_server.py --help
```

Features:
- Supports multiple servers
- Waits for ports to be ready
- Automatic cleanup on exit
- Timeout configuration

### `examples/element_discovery.py`

Discovers all interactive elements on a page (buttons, links, inputs, etc.).

```bash
python examples/element_discovery.py http://localhost:3000/rankings
```

Output:
- List of all buttons, links, and inputs
- UI pattern detection
- Screenshot saved to `/tmp/element_discovery.png`

### `examples/page_audit.py`

Generic page auditor that checks multiple pages for:
- Console errors
- Network failures
- Missing elements
- Load times

```bash
python examples/page_audit.py --base-url http://localhost:3000
```

### `examples/pitchrank_audit.py` / `examples/pitchrank_audit.js`

Comprehensive PitchRank-specific audit (available in Python and JavaScript):
- Home page structure
- Rankings display
- Teams page and search
- Login form
- Navigation flow
- Mobile responsiveness
- JavaScript error detection

```bash
# Python version
python examples/pitchrank_audit.py --base-url http://localhost:3000 --verbose

# JavaScript version (recommended)
node examples/pitchrank_audit.js --base-url=http://localhost:3000 --verbose
```

### `examples/console_logging.py`

Captures browser console output (logs, warnings, errors).

```bash
# Quick check
python examples/console_logging.py http://localhost:3000

# Watch mode (30 seconds)
python examples/console_logging.py http://localhost:3000 --watch --duration 60
```

## Writing Custom Tests

Use the `playwright.sync_api` for synchronous tests:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto('http://localhost:3000')
    page.wait_for_load_state('networkidle')  # CRITICAL: wait for JS

    # Take screenshot
    page.screenshot(path='/tmp/test.png', full_page=True)

    # Find elements
    buttons = page.locator('button').all()

    # Click elements
    page.locator('text=Rankings').click()

    # Fill forms
    page.fill('input[name="email"]', 'test@example.com')

    browser.close()
```

## Best Practices

1. **Always wait for networkidle** - Dynamic apps need time for JS to execute
2. **Use descriptive selectors** - `text=`, `role=`, CSS selectors, or IDs
3. **Take screenshots** - Helpful for debugging and documentation
4. **Capture console errors** - Client-side errors indicate problems
5. **Test mobile viewports** - Ensure responsive design works

## Screenshots

All audit scripts save screenshots to `/tmp/`:
- `/tmp/audit_home.png`
- `/tmp/audit_rankings.png`
- `/tmp/audit_teams.png`
- `/tmp/audit_login.png`
- `/tmp/audit_methodology.png`
- `/tmp/audit_mobile.png`
