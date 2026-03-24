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
      const tableCard = page.locator('[data-testid="rankings-table-card"]');
      await expect(tableCard).toBeVisible({ timeout: RANKINGS_LOAD_TIMEOUT });
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
 * Wait for the rankings table card, header, AND the first data row to be visible.
 * Use this when a test needs to interact with actual row content.
 */
export async function waitForFirstRankingsRow(page: Page) {
  await waitForRankingsTable(page);
  const firstRow = page.locator('[data-testid="rankings-row-0"]');
  await expect(firstRow).toBeVisible({ timeout: 15_000 });
  return firstRow;
}
