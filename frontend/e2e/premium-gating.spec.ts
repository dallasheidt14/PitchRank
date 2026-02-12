import { test, expect } from '@playwright/test';

test.describe('Premium Route Gating - Unauthenticated', () => {
  test('accessing /watchlist redirects unauthenticated users to /upgrade @smoke', async ({ page }) => {
    await page.goto('/watchlist');

    // Middleware should redirect to /upgrade for premium routes when not authenticated
    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/upgrade/);
  });

  test('accessing /compare redirects unauthenticated users to /upgrade', async ({ page }) => {
    await page.goto('/compare');

    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/upgrade/);
  });

  test('accessing /teams/some-id redirects unauthenticated users to /upgrade', async ({ page }) => {
    await page.goto('/teams/test-team-id');

    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/upgrade/);
  });

  test('upgrade redirect preserves the original destination as query param', async ({ page }) => {
    await page.goto('/watchlist');

    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    // The middleware adds ?next=/watchlist
    await expect(page).toHaveURL(/next=/);
  });
});

test.describe('Public Routes - No Redirect', () => {
  test('homepage is accessible without authentication @smoke', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/$/);
  });

  test('rankings page is accessible without authentication @smoke', async ({ page }) => {
    const response = await page.goto('/rankings');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/rankings/);
  });

  test('methodology page is accessible without authentication', async ({ page }) => {
    const response = await page.goto('/methodology');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/methodology/);
  });

  test('blog page is accessible without authentication', async ({ page }) => {
    const response = await page.goto('/blog');
    expect(response?.status()).toBeLessThan(500);
  });

  test('login page is accessible without authentication', async ({ page }) => {
    const response = await page.goto('/login');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/login/);
  });

  test('signup page is accessible without authentication', async ({ page }) => {
    const response = await page.goto('/signup');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/signup/);
  });

  test('dynamic rankings routes are accessible without authentication', async ({ page }) => {
    const response = await page.goto('/rankings/national/u12/male');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/rankings\/national\/u12\/male/);
  });
});

test.describe('Upgrade Page', () => {
  test('upgrade page loads and shows subscription options', async ({ page }) => {
    const response = await page.goto('/upgrade');
    expect(response?.status()).toBe(200);

    // Should display upgrade/pricing content
    await expect(page.locator('body')).not.toBeEmpty();
  });
});
