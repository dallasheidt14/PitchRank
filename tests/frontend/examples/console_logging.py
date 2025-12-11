#!/usr/bin/env python3
"""
Console Logging - Capture and analyze browser console output.

Navigates to pages and captures all console messages (logs, warnings, errors).
Useful for debugging and finding client-side issues.

Usage:
    python console_logging.py [URL] [--watch]

    # With server helper:
    python scripts/with_server.py --server "cd frontend && npm run dev" --port 3000 \
        -- python examples/console_logging.py http://localhost:3000
"""

import sys
import argparse
from datetime import datetime
from playwright.sync_api import sync_playwright


def capture_console(url: str, watch_mode: bool = False, duration: int = 30):
    """Capture console messages from a page."""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"\n{'='*60}")
        print(f"Console Logger: {url}")
        print(f"{'='*60}\n")

        messages = []
        errors = []
        warnings = []

        def on_console(msg):
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            text = msg.text[:500]  # Truncate long messages

            entry = {
                'time': timestamp,
                'type': msg.type,
                'text': text,
                'location': msg.location
            }

            if msg.type == 'error':
                errors.append(entry)
                print(f"[{timestamp}] ERROR: {text}")
            elif msg.type == 'warning':
                warnings.append(entry)
                print(f"[{timestamp}] WARN: {text}")
            else:
                messages.append(entry)
                if watch_mode:  # Only print in watch mode
                    print(f"[{timestamp}] {msg.type.upper()}: {text[:100]}")

        def on_pageerror(error):
            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] PAGE ERROR: {error}")
            errors.append({
                'time': timestamp,
                'type': 'pageerror',
                'text': str(error)
            })

        page.on('console', on_console)
        page.on('pageerror', on_pageerror)

        try:
            print(f"Navigating to {url}...")
            page.goto(url, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=30000)

            if watch_mode:
                print(f"\nWatching for {duration} seconds... (Ctrl+C to stop)\n")
                import time
                try:
                    time.sleep(duration)
                except KeyboardInterrupt:
                    print("\nStopped watching.")
            else:
                # Just wait a bit for any async errors
                page.wait_for_timeout(3000)

            # Take screenshot
            screenshot_path = '/tmp/console_logging.png'
            page.screenshot(path=screenshot_path)
            print(f"\nScreenshot saved: {screenshot_path}")

        except Exception as e:
            print(f"\nERROR during navigation: {e}")

        finally:
            browser.close()

        # Print summary
        print(f"\n{'='*60}")
        print("CONSOLE SUMMARY")
        print(f"{'='*60}")
        print(f"\nTotal messages: {len(messages)}")
        print(f"Warnings: {len(warnings)}")
        print(f"Errors: {len(errors)}")

        if errors:
            print(f"\n--- ERRORS ({len(errors)}) ---")
            for err in errors:
                print(f"\n[{err['time']}] {err['text'][:300]}")
                if 'location' in err and err['location']:
                    loc = err['location']
                    print(f"  at {loc.get('url', '')}:{loc.get('lineNumber', '')}:{loc.get('columnNumber', '')}")

        if warnings:
            print(f"\n--- WARNINGS ({len(warnings)}) ---")
            for warn in warnings[:10]:  # Limit to 10
                print(f"\n[{warn['time']}] {warn['text'][:200]}")
            if len(warnings) > 10:
                print(f"  ... and {len(warnings) - 10} more warnings")

        return len(errors) == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Browser Console Logger")
    parser.add_argument('url', nargs='?', default='http://localhost:3000',
                        help='URL to monitor')
    parser.add_argument('--watch', '-w', action='store_true',
                        help='Watch mode - keep monitoring for a duration')
    parser.add_argument('--duration', '-d', type=int, default=30,
                        help='Duration in seconds for watch mode (default: 30)')

    args = parser.parse_args()

    success = capture_console(args.url, watch_mode=args.watch, duration=args.duration)
    sys.exit(0 if success else 1)
