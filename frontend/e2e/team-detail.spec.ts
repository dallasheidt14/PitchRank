import { test, expect } from '@playwright/test';

test.describe('Team Detail Page - Access Control', () => {
  test('redirects unauthenticated users to /upgrade', async ({ page }) => {
    // Team detail pages are premium-gated
    await page.goto('/teams/some-team-id');

    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/upgrade/);
  });

  test('preserves team path in redirect query', async ({ page }) => {
    await page.goto('/teams/test-team-123');

    await page.waitForURL('**/upgrade**', { timeout: 10_000 });
    await expect(page).toHaveURL(/next=.*teams/);
  });
});

test.describe('Team Detail Page - Response Codes', () => {
  test('team detail route does not return 500', async ({ request }) => {
    // Even without auth, the route should not crash — it should redirect
    const response = await request.get('/teams/test-id', {
      maxRedirects: 0,
    });
    // Should be a redirect (302/307) to /upgrade, not a 500
    expect(response.status()).toBeLessThan(500);
  });
});

test.describe('Team Detail - Rankings Integration', () => {
  test('team links in rankings table point to correct team URLs', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    // Wait for rankings to load
    const firstRow = page.locator('[data-testid="rankings-row-0"]');
    await expect(firstRow).toBeVisible({ timeout: 15_000 });

    // Get the team link href
    const teamLink = firstRow.locator('a[href*="/teams/"]');
    const href = await teamLink.getAttribute('href');

    // Should be a valid team URL with query params
    expect(href).toMatch(/\/teams\/[a-zA-Z0-9-]+/);
    expect(href).toContain('region=');
    expect(href).toContain('ageGroup=');
    expect(href).toContain('gender=');
  });
});
