#!/usr/bin/env python3
"""
PitchRank Frontend Audit - Comprehensive testing for PitchRank app.

Tests:
- Public pages load correctly
- Navigation works
- Rankings display correctly
- Search functionality
- Interactive components
- Mobile responsiveness

Usage:
    python pitchrank_audit.py [--base-url URL] [--verbose]

    # With server helper (recommended):
    python scripts/with_server.py --server "cd frontend && npm run dev" --port 3000 \
        -- python examples/pitchrank_audit.py
"""

import sys
import argparse
from typing import List, Tuple
from playwright.sync_api import sync_playwright, Page, expect


class PitchRankAuditor:
    """Comprehensive auditor for PitchRank frontend."""

    def __init__(self, base_url: str, verbose: bool = False):
        self.base_url = base_url.rstrip('/')
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.errors: List[Tuple[str, str]] = []

    def log(self, msg: str):
        if self.verbose:
            print(f"    {msg}")

    def test(self, name: str, condition: bool, error_msg: str = ""):
        """Record a test result."""
        if condition:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            print(f"  [FAIL] {name}")
            if error_msg:
                print(f"         {error_msg}")
                self.errors.append((name, error_msg))

    def audit_home_page(self, page: Page):
        """Audit the home page."""
        print("\n--- Home Page ---")

        page.goto(f"{self.base_url}/")
        page.wait_for_load_state('networkidle')

        # Check main elements
        self.test("Has navigation", page.locator('nav').count() > 0)
        self.test("Has main heading", page.locator('h1').count() > 0)
        self.test("Has footer", page.locator('footer').count() > 0)

        # Check for key content sections
        hero = page.locator('section, [class*="hero"], main').first
        self.test("Has hero/main section", hero.count() > 0 if hasattr(hero, 'count') else True)

        # Check navigation links
        nav_links = page.locator('nav a').all()
        self.test("Navigation has links", len(nav_links) > 0)
        self.log(f"Found {len(nav_links)} navigation links")

        # Check for call-to-action buttons
        cta_buttons = page.locator('a[href*="ranking"], a[href*="login"], button').all()
        self.test("Has CTA buttons", len(cta_buttons) > 0)

        page.screenshot(path='/tmp/audit_home.png', full_page=True)

    def audit_rankings_page(self, page: Page):
        """Audit the rankings page."""
        print("\n--- Rankings Page ---")

        page.goto(f"{self.base_url}/rankings")
        page.wait_for_load_state('networkidle')

        # Wait for rankings to load (might be async)
        page.wait_for_timeout(2000)

        # Check for rankings content
        has_table = page.locator('table').count() > 0
        has_list = page.locator('[class*="ranking"], [class*="list"]').count() > 0
        self.test("Has rankings display", has_table or has_list)

        # Check for filter controls
        filters = page.locator('select, [role="combobox"], [class*="filter"]').all()
        self.test("Has filter controls", len(filters) > 0)
        self.log(f"Found {len(filters)} filter controls")

        # Check for team entries
        team_links = page.locator('a[href*="/teams/"]').all()
        self.test("Shows team links", len(team_links) > 0)
        self.log(f"Found {len(team_links)} team links")

        page.screenshot(path='/tmp/audit_rankings.png', full_page=True)

    def audit_teams_page(self, page: Page):
        """Audit the teams page."""
        print("\n--- Teams Page ---")

        page.goto(f"{self.base_url}/teams")
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)

        # Check for search functionality
        search_input = page.locator('input[type="search"], input[placeholder*="earch"], input[name*="search"]')
        self.test("Has search input", search_input.count() > 0)

        # Check for team listings
        team_cards = page.locator('[class*="team"], [class*="card"], a[href*="/teams/"]').all()
        self.test("Shows team entries", len(team_cards) > 0)
        self.log(f"Found {len(team_cards)} team entries")

        page.screenshot(path='/tmp/audit_teams.png', full_page=True)

    def audit_login_page(self, page: Page):
        """Audit the login page."""
        print("\n--- Login Page ---")

        page.goto(f"{self.base_url}/login")
        page.wait_for_load_state('networkidle')

        # Check for login form elements
        email_input = page.locator('input[type="email"], input[name="email"], input[placeholder*="mail"]')
        self.test("Has email input", email_input.count() > 0)

        password_input = page.locator('input[type="password"]')
        self.test("Has password input", password_input.count() > 0)

        submit_btn = page.locator('button[type="submit"], button:has-text("Login"), button:has-text("Sign")')
        self.test("Has submit button", submit_btn.count() > 0)

        # Check for signup link
        signup_link = page.locator('a[href*="signup"], a:has-text("Sign up"), a:has-text("Register")')
        self.test("Has signup link", signup_link.count() > 0)

        page.screenshot(path='/tmp/audit_login.png', full_page=True)

    def audit_methodology_page(self, page: Page):
        """Audit the methodology page."""
        print("\n--- Methodology Page ---")

        page.goto(f"{self.base_url}/methodology")
        page.wait_for_load_state('networkidle')

        # Check for content
        headings = page.locator('h1, h2').all()
        self.test("Has headings", len(headings) > 0)

        paragraphs = page.locator('p').all()
        self.test("Has explanatory content", len(paragraphs) > 0)

        page.screenshot(path='/tmp/audit_methodology.png', full_page=True)

    def audit_navigation(self, page: Page):
        """Test navigation between pages."""
        print("\n--- Navigation Tests ---")

        page.goto(f"{self.base_url}/")
        page.wait_for_load_state('networkidle')

        # Test clicking on Rankings link
        rankings_link = page.locator('a[href*="ranking"]').first
        if rankings_link.count() > 0:
            rankings_link.click()
            page.wait_for_load_state('networkidle')
            self.test("Rankings link works", '/ranking' in page.url)
        else:
            self.test("Rankings link exists", False, "No rankings link found")

        # Go back to home
        page.goto(f"{self.base_url}/")
        page.wait_for_load_state('networkidle')

        # Test Login link
        login_link = page.locator('a[href*="login"]').first
        if login_link.count() > 0:
            login_link.click()
            page.wait_for_load_state('networkidle')
            self.test("Login link works", '/login' in page.url)
        else:
            self.test("Login link exists", False, "No login link found")

    def audit_mobile_responsiveness(self, page: Page):
        """Test mobile viewport."""
        print("\n--- Mobile Responsiveness ---")

        # Set mobile viewport
        page.set_viewport_size({'width': 375, 'height': 667})
        page.goto(f"{self.base_url}/")
        page.wait_for_load_state('networkidle')

        # Check for mobile menu (hamburger)
        mobile_menu = page.locator('[class*="mobile"], [class*="hamburger"], button[aria-label*="menu"], [class*="menu-toggle"]')
        has_responsive = mobile_menu.count() > 0

        # Check if navigation is visible or hidden
        nav = page.locator('nav')
        nav_visible = nav.is_visible() if nav.count() > 0 else False

        self.test("Has mobile layout", has_responsive or nav_visible)

        page.screenshot(path='/tmp/audit_mobile.png', full_page=True)

        # Reset viewport
        page.set_viewport_size({'width': 1920, 'height': 1080})

    def audit_console_errors(self, page: Page) -> List[str]:
        """Check for JavaScript errors."""
        print("\n--- Console Error Check ---")

        errors = []

        def on_console(msg):
            if msg.type == 'error':
                errors.append(msg.text)

        def on_pageerror(error):
            errors.append(str(error))

        page.on('console', on_console)
        page.on('pageerror', on_pageerror)

        # Visit key pages
        pages_to_check = ['/', '/rankings', '/teams', '/methodology']

        for path in pages_to_check:
            try:
                page.goto(f"{self.base_url}{path}")
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(1000)
            except Exception as e:
                errors.append(f"Navigation error on {path}: {e}")

        self.test("No JavaScript errors", len(errors) == 0,
                  f"Found {len(errors)} errors" if errors else "")

        if errors and self.verbose:
            for err in errors[:5]:
                print(f"    ERROR: {err[:100]}")

        return errors

    def run_full_audit(self):
        """Run the complete audit."""
        print("=" * 60)
        print("PITCHRANK FRONTEND AUDIT")
        print(f"Base URL: {self.base_url}")
        print("=" * 60)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()

            try:
                self.audit_home_page(page)
                self.audit_rankings_page(page)
                self.audit_teams_page(page)
                self.audit_login_page(page)
                self.audit_methodology_page(page)
                self.audit_navigation(page)
                self.audit_mobile_responsiveness(page)
                self.audit_console_errors(page)

            except Exception as e:
                print(f"\nFATAL ERROR: {e}")
                page.screenshot(path='/tmp/audit_fatal_error.png')
                self.failed += 1

            finally:
                browser.close()

        # Print summary
        print("\n" + "=" * 60)
        print("AUDIT SUMMARY")
        print("=" * 60)
        print(f"\nPassed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Total:  {self.passed + self.failed}")

        if self.errors:
            print("\nErrors:")
            for name, msg in self.errors:
                print(f"  - {name}: {msg}")

        print("\nScreenshots saved to /tmp/audit_*.png")
        print("=" * 60)

        return self.failed == 0


def main():
    parser = argparse.ArgumentParser(description="PitchRank Frontend Auditor")
    parser.add_argument('--base-url', default='http://localhost:3000',
                        help='Base URL for testing')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    auditor = PitchRankAuditor(base_url=args.base_url, verbose=args.verbose)
    success = auditor.run_full_audit()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
