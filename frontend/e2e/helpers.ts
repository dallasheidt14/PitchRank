import { expect, type Page } from '@playwright/test';

export const RANKINGS_LOAD_TIMEOUT = 30_000;

/**
 * Wait for the rankings table container and header to become visible.
 * Retries up to 3 times with a full page reload between attempts.
 */
export async function waitForRankingsTable(page: Page) {
  let lastError: unknown;

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const t0 = Date.now();
      const tableCard = page.locator('[data-testid="rankings-table-card"]');
      await expect(tableCard).toBeVisible({ timeout: RANKINGS_LOAD_TIMEOUT });
      console.log(`[rankings-helper] table card visible in ${Date.now() - t0}ms (attempt ${attempt + 1})`);

      await expect(page.locator('[data-testid="rankings-table-header"]')).toBeVisible({
        timeout: 10_000,
      });
      return tableCard;
    } catch (error) {
      lastError = error;
      if (attempt < 2) {
        await page.waitForTimeout(3_000);
        await page.reload({ waitUntil: 'domcontentloaded' });
      }
    }
  }

  throw lastError;
}

/**
 * Wait for the rankings table card, header, first data row, AND a visible
 * team link inside row 0. This ensures the page is fully interactive before
 * tests proceed to click or read row content.
 */
export async function waitForFirstRankingsRow(page: Page) {
  const t0 = Date.now();
  await waitForRankingsTable(page);

  const firstRow = page.locator('[data-testid="rankings-row-0"]');
  await expect(firstRow).toBeVisible({ timeout: 15_000 });
  console.log(`[rankings-helper] row-0 visible in ${Date.now() - t0}ms`);

  // Ensure the team link inside row 0 is rendered — proves the row is
  // fully hydrated, not just a skeleton placeholder.
  const teamLink = firstRow.locator('a[href*="/teams/"]');
  await expect(teamLink).toBeVisible({ timeout: 10_000 });
  console.log(`[rankings-helper] row-0 team link visible in ${Date.now() - t0}ms`);

  return firstRow;
}
