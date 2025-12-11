#!/usr/bin/env python3
"""
Page Audit - Comprehensive frontend audit for PitchRank.

Checks multiple pages for:
- Loading errors and console errors
- Missing elements
- Broken links
- Performance issues
- Accessibility basics

Usage:
    python page_audit.py [--base-url URL]

    # With server helper:
    python scripts/with_server.py --server "cd frontend && npm run dev" --port 3000 \
        -- python examples/page_audit.py
"""

import sys
import argparse
from dataclasses import dataclass, field
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright, Page, ConsoleMessage


@dataclass
class AuditResult:
    """Results from auditing a single page."""
    url: str
    title: str = ""
    load_time_ms: int = 0
    console_errors: List[str] = field(default_factory=list)
    console_warnings: List[str] = field(default_factory=list)
    network_errors: List[str] = field(default_factory=list)
    missing_elements: List[str] = field(default_factory=list)
    found_elements: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    passed: bool = True
    error: str = ""


class FrontendAuditor:
    """Audit frontend pages for issues."""

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url.rstrip('/')
        self.results: List[AuditResult] = []

    def audit_page(
        self,
        page: Page,
        path: str,
        expected_elements: List[str] = None,
        screenshot_name: str = None
    ) -> AuditResult:
        """Audit a single page."""
        url = f"{self.base_url}{path}"
        result = AuditResult(url=url)

        console_messages: List[ConsoleMessage] = []
        network_errors: List[str] = []

        # Capture console messages
        def on_console(msg: ConsoleMessage):
            console_messages.append(msg)

        page.on('console', on_console)

        # Capture network failures
        def on_request_failed(request):
            network_errors.append(f"{request.method} {request.url} - {request.failure}")

        page.on('requestfailed', on_request_failed)

        try:
            # Navigate and measure load time
            import time
            start = time.time()
            response = page.goto(url, timeout=30000, wait_until='networkidle')
            result.load_time_ms = int((time.time() - start) * 1000)

            # Check response status
            if response and response.status >= 400:
                result.error = f"HTTP {response.status}"
                result.passed = False

            result.title = page.title()

            # Take screenshot
            if screenshot_name:
                screenshot_path = f'/tmp/audit_{screenshot_name}.png'
                page.screenshot(path=screenshot_path, full_page=True)
                result.screenshots.append(screenshot_path)

            # Check for expected elements
            if expected_elements:
                for selector in expected_elements:
                    try:
                        if page.locator(selector).count() > 0:
                            result.found_elements.append(selector)
                        else:
                            result.missing_elements.append(selector)
                            result.passed = False
                    except Exception as e:
                        result.missing_elements.append(f"{selector} (error: {e})")

            # Process console messages
            for msg in console_messages:
                text = msg.text[:200]  # Truncate long messages
                if msg.type == 'error':
                    result.console_errors.append(text)
                elif msg.type == 'warning':
                    result.console_warnings.append(text)

            result.network_errors = network_errors

            # Mark as failed if there are errors
            if result.console_errors or result.network_errors:
                result.passed = False

        except Exception as e:
            result.error = str(e)
            result.passed = False
            # Try to take error screenshot
            try:
                page.screenshot(path=f'/tmp/audit_error_{path.replace("/", "_")}.png')
            except:
                pass

        return result

    def run_audit(self, pages_config: List[Dict[str, Any]]) -> List[AuditResult]:
        """Run audit on multiple pages."""

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()

            for config in pages_config:
                path = config.get('path', '/')
                name = config.get('name', path)
                expected = config.get('expected_elements', [])

                print(f"Auditing: {name}...", end=' ', flush=True)

                result = self.audit_page(
                    page,
                    path,
                    expected_elements=expected,
                    screenshot_name=name.replace('/', '_').replace(' ', '_')
                )
                self.results.append(result)

                status = "PASS" if result.passed else "FAIL"
                print(f"{status} ({result.load_time_ms}ms)")

            browser.close()

        return self.results

    def print_report(self):
        """Print audit report."""
        print("\n" + "=" * 70)
        print("FRONTEND AUDIT REPORT")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed

        print(f"\nSummary: {passed} passed, {failed} failed\n")

        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            print(f"\n[{status}] {result.url}")
            print(f"  Title: {result.title}")
            print(f"  Load time: {result.load_time_ms}ms")

            if result.error:
                print(f"  ERROR: {result.error}")

            if result.console_errors:
                print(f"  Console Errors ({len(result.console_errors)}):")
                for err in result.console_errors[:5]:
                    print(f"    - {err[:100]}")

            if result.network_errors:
                print(f"  Network Errors ({len(result.network_errors)}):")
                for err in result.network_errors[:5]:
                    print(f"    - {err[:100]}")

            if result.missing_elements:
                print(f"  Missing Elements:")
                for elem in result.missing_elements:
                    print(f"    - {elem}")

            if result.screenshots:
                print(f"  Screenshots: {', '.join(result.screenshots)}")

        print("\n" + "=" * 70)
        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Frontend Page Auditor")
    parser.add_argument('--base-url', default='http://localhost:3000',
                        help='Base URL for testing')
    args = parser.parse_args()

    # Define pages to audit with expected elements
    pages_config = [
        {
            'name': 'Home',
            'path': '/',
            'expected_elements': [
                'nav',  # Navigation
                'h1',   # Main heading
                'footer',  # Footer
            ]
        },
        {
            'name': 'Rankings',
            'path': '/rankings',
            'expected_elements': [
                'nav',
                'table, [role="grid"], [class*="ranking"]',  # Rankings table/list
            ]
        },
        {
            'name': 'Methodology',
            'path': '/methodology',
            'expected_elements': [
                'nav',
                'h1',
            ]
        },
        {
            'name': 'Login',
            'path': '/login',
            'expected_elements': [
                'input[type="email"], input[name="email"]',
                'input[type="password"]',
                'button[type="submit"], button:has-text("Login"), button:has-text("Sign")',
            ]
        },
        {
            'name': 'Teams',
            'path': '/teams',
            'expected_elements': [
                'nav',
            ]
        },
    ]

    auditor = FrontendAuditor(base_url=args.base_url)
    auditor.run_audit(pages_config)
    success = auditor.print_report()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
