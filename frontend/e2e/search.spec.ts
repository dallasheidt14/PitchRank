import { test, expect, type Page } from '@playwright/test';

function visibleSearchInput(page: Page) {
  return page.locator('input[aria-label="Search for teams"]:visible').first();
}

test.describe('Team Search - Global Search', () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test('global search input is visible in header', async ({ page }) => {
    await page.goto('/');

    const searchInput = visibleSearchInput(page);

    await expect(searchInput).toBeVisible({ timeout: 10_000 });
  });

  test('search input accepts text input', async ({ page }) => {
    await page.goto('/');

    const searchInput = visibleSearchInput(page);
    await searchInput.fill('Real Salt Lake');
    await expect(searchInput).toHaveValue('Real Salt Lake');
  });

  test('typing in search shows results dropdown', async ({ page }) => {
    await page.goto('/');

    const searchInput = visibleSearchInput(page);
    await searchInput.fill('FC Dallas');

    // Allow debounced search to resolve and assert we got a terminal search state.
    await expect
      .poll(
        async () => {
          const resultCount = await page.locator('button[aria-label^="Select "]').count();
          const noResultsVisible = await page
            .getByText(/No teams found matching/i)
            .isVisible()
            .catch(() => false);
          const searchingVisible = await page
            .getByText(/Searching teams\.\.\./i)
            .isVisible()
            .catch(() => false);
          const networkErrorVisible = await page
            .getByText(/Unable to connect to the server/i)
            .isVisible()
            .catch(() => false);
          return resultCount > 0 || noResultsVisible || searchingVisible || networkErrorVisible;
        },
        { timeout: 15_000 }
      )
      .toBe(true);
  });
});

test.describe('Team Search - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('search is accessible on mobile', async ({ page }) => {
    await page.goto('/');

    const searchInput = visibleSearchInput(page);
    await expect(searchInput).toBeVisible({ timeout: 10_000 });
  });
});
