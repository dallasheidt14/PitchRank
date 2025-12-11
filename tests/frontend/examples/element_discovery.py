#!/usr/bin/env python3
"""
Element Discovery - Discover interactive elements on a page.

This script navigates to a URL and identifies all buttons, links, inputs,
and other interactive elements. Useful for understanding page structure
before writing targeted tests.

Usage:
    python element_discovery.py [URL]

    # With server helper:
    python scripts/with_server.py --server "npm run dev" --port 3000 \
        -- python examples/element_discovery.py http://localhost:3000
"""

import sys
from playwright.sync_api import sync_playwright


def discover_elements(url: str = "http://localhost:3000"):
    """Discover all interactive elements on the page."""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"\n{'='*60}")
        print(f"Element Discovery: {url}")
        print(f"{'='*60}\n")

        try:
            page.goto(url, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=30000)

            # Take a screenshot for visual reference
            screenshot_path = '/tmp/element_discovery.png'
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"Screenshot saved: {screenshot_path}\n")

            # Discover buttons
            buttons = page.locator('button').all()
            print(f"BUTTONS ({len(buttons)}):")
            for i, btn in enumerate(buttons[:20]):  # Limit to 20
                text = btn.inner_text().strip()[:50] or "[no text]"
                aria = btn.get_attribute('aria-label') or ""
                print(f"  {i+1}. {text} {f'(aria: {aria})' if aria else ''}")
            if len(buttons) > 20:
                print(f"  ... and {len(buttons) - 20} more")
            print()

            # Discover links
            links = page.locator('a[href]').all()
            print(f"LINKS ({len(links)}):")
            for i, link in enumerate(links[:20]):
                text = link.inner_text().strip()[:30] or "[no text]"
                href = link.get_attribute('href') or ""
                print(f"  {i+1}. {text} -> {href[:50]}")
            if len(links) > 20:
                print(f"  ... and {len(links) - 20} more")
            print()

            # Discover inputs
            inputs = page.locator('input, textarea, select').all()
            print(f"FORM INPUTS ({len(inputs)}):")
            for i, inp in enumerate(inputs[:20]):
                input_type = inp.get_attribute('type') or inp.evaluate('el => el.tagName.toLowerCase()')
                name = inp.get_attribute('name') or ""
                placeholder = inp.get_attribute('placeholder') or ""
                print(f"  {i+1}. [{input_type}] name={name} placeholder={placeholder[:30]}")
            if len(inputs) > 20:
                print(f"  ... and {len(inputs) - 20} more")
            print()

            # Discover navigation elements
            navs = page.locator('nav').all()
            print(f"NAVIGATION SECTIONS ({len(navs)}):")
            for i, nav in enumerate(navs[:5]):
                nav_links = nav.locator('a').all()
                print(f"  Nav {i+1}: {len(nav_links)} links")
            print()

            # Check for common UI patterns
            print("UI PATTERNS DETECTED:")
            patterns = [
                ('Modal/Dialog', 'dialog, [role="dialog"], .modal'),
                ('Dropdown Menu', '[role="menu"], .dropdown-menu'),
                ('Toast/Alert', '[role="alert"], .toast'),
                ('Loading Spinner', '.spinner, .loading, [aria-busy="true"]'),
                ('Card Components', '.card, [class*="card"]'),
                ('Data Tables', 'table, [role="grid"]'),
            ]

            for name, selector in patterns:
                count = len(page.locator(selector).all())
                if count > 0:
                    print(f"  - {name}: {count} found")
            print()

            # Get page title and meta
            title = page.title()
            print(f"PAGE INFO:")
            print(f"  Title: {title}")
            print(f"  URL: {page.url}")
            print()

        except Exception as e:
            print(f"ERROR: {e}")
            page.screenshot(path='/tmp/element_discovery_error.png')
            print("Error screenshot saved to /tmp/element_discovery_error.png")

        finally:
            browser.close()


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
    discover_elements(url)
