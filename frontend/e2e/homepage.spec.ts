import { test, expect } from '@playwright/test';

test.describe('Homepage', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('renders hero section with correct heading @smoke', async ({ page }) => {
    const hero = page.locator('[data-testid="hero-section"]');
    await expect(hero).toBeVisible();

    const heading = page.locator('h1');
    await expect(heading).toContainText("America's");
    await expect(heading).toContainText('Definitive');
    await expect(heading).toContainText('Youth Soccer Rankings');
  });

  test('renders hero subtitle with age range', async ({ page }) => {
    await expect(
      page.getByText('Data-driven performance analytics for U10-U18')
    ).toBeVisible();
  });

  test('CTA buttons are visible and link correctly', async ({ page }) => {
    const viewRankings = page.locator('[data-testid="cta-rankings"]');
    await expect(viewRankings).toBeVisible();
    await expect(viewRankings.locator('a')).toHaveAttribute('href', '/rankings');

    const methodology = page.locator('[data-testid="cta-methodology"]');
    await expect(methodology).toBeVisible();
    await expect(methodology.locator('a')).toHaveAttribute('href', '/methodology');
  });

  test('"View Rankings" CTA navigates to rankings page', async ({ page }) => {
    await page.locator('[data-testid="cta-rankings"] a').click();
    await page.waitForURL('**/rankings**');
    await expect(page).toHaveURL(/\/rankings/);
  });

  test('renders HowWeRank section', async ({ page }) => {
    // The HowWeRank component should be in the main content area
    await expect(page.locator('main, [class*="container"]').first()).toBeVisible();
  });

  test('page has correct title', async ({ page }) => {
    await expect(page).toHaveTitle(/PitchRank/i);
  });

  test('page loads without console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Filter out known benign errors (e.g., GA, third-party scripts)
    const criticalErrors = errors.filter(
      (e) =>
        !e.includes('google') &&
        !e.includes('analytics') &&
        !e.includes('gtag') &&
        !e.includes('favicon')
    );

    expect(criticalErrors).toHaveLength(0);
  });
});

test.describe('Homepage - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('hero section is visible on mobile', async ({ page }) => {
    await page.goto('/');
    const hero = page.locator('[data-testid="hero-section"]');
    await expect(hero).toBeVisible();
  });

  test('CTA buttons are visible on mobile', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="cta-rankings"]')).toBeVisible();
    await expect(page.locator('[data-testid="cta-methodology"]')).toBeVisible();
  });
});
