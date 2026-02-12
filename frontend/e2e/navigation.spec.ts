import { test, expect } from '@playwright/test';

test.describe('Navigation - Desktop', () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('renders main navigation header @smoke', async ({ page }) => {
    const nav = page.locator('[data-testid="main-navigation"]');
    await expect(nav).toBeVisible();
  });

  test('logo links to homepage', async ({ page }) => {
    const logoLink = page.locator('[aria-label="PitchRank home"]');
    await expect(logoLink).toBeVisible();
    await expect(logoLink).toHaveAttribute('href', '/');
  });

  test('desktop nav contains all primary links @smoke', async ({ page }) => {
    const desktopNav = page.locator('[data-testid="desktop-nav"]');

    await expect(desktopNav.locator('[data-testid="nav-home"]')).toBeVisible();
    await expect(desktopNav.locator('[data-testid="nav-rankings"]')).toBeVisible();
    await expect(desktopNav.locator('[data-testid="nav-compare"]')).toBeVisible();
    await expect(desktopNav.locator('[data-testid="nav-watchlist"]')).toBeVisible();
    await expect(desktopNav.locator('[data-testid="nav-methodology"]')).toBeVisible();
    await expect(desktopNav.locator('[data-testid="nav-blog"]')).toBeVisible();
  });

  test('nav links have correct href attributes', async ({ page }) => {
    await expect(page.locator('[data-testid="nav-home"]')).toHaveAttribute('href', '/');
    await expect(page.locator('[data-testid="nav-rankings"]')).toHaveAttribute('href', '/rankings');
    await expect(page.locator('[data-testid="nav-compare"]')).toHaveAttribute('href', '/compare');
    await expect(page.locator('[data-testid="nav-watchlist"]')).toHaveAttribute('href', '/watchlist');
    await expect(page.locator('[data-testid="nav-methodology"]')).toHaveAttribute('href', '/methodology');
    await expect(page.locator('[data-testid="nav-blog"]')).toHaveAttribute('href', '/blog');
  });

  test('sign-in button is visible for unauthenticated users', async ({ page }) => {
    // Wait for auth loading to finish
    const signInLink = page.locator('[data-testid="nav-signin"]');
    await expect(signInLink).toBeVisible({ timeout: 10_000 });
    await expect(signInLink).toHaveAttribute('href', '/login');
  });

  test('navigation to Rankings page works', async ({ page }) => {
    await page.locator('[data-testid="nav-rankings"]').click();
    await page.waitForURL('**/rankings**');
    await expect(page).toHaveURL(/\/rankings/);
  });

  test('navigation to Methodology page works', async ({ page }) => {
    await page.locator('[data-testid="nav-methodology"]').click();
    await page.waitForURL('**/methodology**');
    await expect(page).toHaveURL(/\/methodology/);
  });

  test('navigation to Blog page works', async ({ page }) => {
    await page.locator('[data-testid="nav-blog"]').click();
    await page.waitForURL('**/blog**');
    await expect(page).toHaveURL(/\/blog/);
  });

  test('navigation is sticky (stays at top on scroll)', async ({ page }) => {
    const nav = page.locator('[data-testid="main-navigation"]');

    // Scroll down
    await page.evaluate(() => window.scrollBy(0, 500));
    await page.waitForTimeout(300);

    await expect(nav).toBeVisible();
    await expect(nav).toBeInViewport();
  });
});

test.describe('Navigation - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('mobile hamburger menu is visible', async ({ page }) => {
    const menuToggle = page.locator('[data-testid="mobile-menu-toggle"]');
    await expect(menuToggle).toBeVisible();
  });

  test('desktop nav is hidden on mobile', async ({ page }) => {
    const desktopNav = page.locator('[data-testid="desktop-nav"]');
    await expect(desktopNav).not.toBeVisible();
  });

  test('mobile menu opens and shows all links', async ({ page }) => {
    // Menu should be closed initially
    const mobileMenu = page.locator('[data-testid="mobile-menu"]');
    await expect(mobileMenu).not.toBeVisible();

    // Open menu
    await page.locator('[data-testid="mobile-menu-toggle"]').click();
    await expect(mobileMenu).toBeVisible();

    // Verify all navigation links are present
    await expect(mobileMenu.getByText('Home')).toBeVisible();
    await expect(mobileMenu.getByText('Rankings')).toBeVisible();
    await expect(mobileMenu.getByText('Compare/Predict')).toBeVisible();
    await expect(mobileMenu.getByText('Watchlist')).toBeVisible();
    await expect(mobileMenu.getByText('Methodology')).toBeVisible();
    await expect(mobileMenu.getByText('Blog')).toBeVisible();
  });

  test('mobile menu closes when a link is clicked', async ({ page }) => {
    await page.locator('[data-testid="mobile-menu-toggle"]').click();
    const mobileMenu = page.locator('[data-testid="mobile-menu"]');
    await expect(mobileMenu).toBeVisible();

    // Click Rankings link
    await mobileMenu.getByText('Rankings').click();
    await expect(mobileMenu).not.toBeVisible();
  });

  test('mobile menu toggles closed on second click', async ({ page }) => {
    const menuToggle = page.locator('[data-testid="mobile-menu-toggle"]');
    const mobileMenu = page.locator('[data-testid="mobile-menu"]');

    // Open
    await menuToggle.click();
    await expect(mobileMenu).toBeVisible();

    // Close
    await menuToggle.click();
    await expect(mobileMenu).not.toBeVisible();
  });

  test('mobile sign-in link is visible for unauthenticated users', async ({ page }) => {
    await page.locator('[data-testid="mobile-menu-toggle"]').click();
    const mobileMenu = page.locator('[data-testid="mobile-menu"]');
    await expect(mobileMenu.getByText('Sign in')).toBeVisible({ timeout: 10_000 });
  });
});
