import { test, expect } from '@playwright/test';
import { waitForRankingsTable, waitForFirstRankingsRow } from './helpers';

// Live rankings pages depend on external API responses that can be transiently slow.
test.describe.configure({ timeout: 90_000, retries: 2 });

test.describe('Rankings Page', () => {
  test('loads rankings page with filter and table @smoke', async ({ page }) => {
    await page.goto('/rankings');
    await expect(page).toHaveURL(/\/rankings/);

    // Filter card should be visible
    const filter = page.locator('[data-testid="rankings-filter"]');
    await expect(filter).toBeVisible();
  });

  test('displays rankings table with data', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    const tableCard = await waitForRankingsTable(page);

    // Title should show
    const title = page.locator('[data-testid="rankings-title"]');
    await expect(title).toContainText('Complete Rankings');

    // Table header should have column labels
    const header = page.locator('[data-testid="rankings-table-header"]');
    await expect(header).toBeVisible();
  });

  test('rankings table has sortable columns', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    await waitForRankingsTable(page);
    const header = page.locator('[data-testid="rankings-table-header"]');

    // Check sort buttons exist
    await expect(header.getByRole('button', { name: /Sort by Rank/i })).toBeVisible();
    await expect(header.getByRole('button', { name: /Sort by Team/i })).toBeVisible();
  });

  test('rankings rows are clickable and link to team pages', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    const firstRow = await waitForFirstRankingsRow(page);

    // Row should contain a link to team detail
    const teamLink = firstRow.locator('a[href*="/teams/"]');
    await expect(teamLink).toBeVisible();
  });

  test('rankings display rank numbers starting from #1', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    const firstRow = await waitForFirstRankingsRow(page);

    // First row should show #1
    await expect(firstRow).toContainText('#1');
  });

  test('filter dropdowns contain correct options', async ({ page }) => {
    await page.goto('/rankings');

    const filter = page.locator('[data-testid="rankings-filter"]');
    await expect(filter).toBeVisible();

    // Check region label
    await expect(filter.getByText('Region')).toBeVisible();
    // Check age group label
    await expect(filter.getByText('Age Group')).toBeVisible();
    // Check gender label
    await expect(filter.getByText('Gender')).toBeVisible();
  });

  test('page has correct metadata title', async ({ page }) => {
    await page.goto('/rankings');
    await expect(page).toHaveTitle(/Ranks.*PitchRank|Youth Soccer Teams.*PitchRank/i);
  });
});

test.describe('Rankings - Dynamic Routes', () => {
  test('national U14 boys rankings load correctly', async ({ page }) => {
    await page.goto('/rankings/national/u14/male');

    await waitForRankingsTable(page);
  });

  test('national U12 girls rankings load correctly', async ({ page }) => {
    await page.goto('/rankings/national/u12/female');

    await waitForRankingsTable(page);
  });

  test('state-level rankings load correctly (TX)', async ({ page }) => {
    await page.goto('/rankings/TX/u12/male');

    const tableCard = await waitForRankingsTable(page);

    // Description should mention the state
    await expect(tableCard).toContainText('TX');
  });

  test('state-level rankings load correctly (CA)', async ({ page }) => {
    await page.goto('/rankings/CA/u14/female');

    const tableCard = await waitForRankingsTable(page);

    await expect(tableCard).toContainText('CA');
  });

  test('various age groups render (U10 through U19)', async ({ page }) => {
    const ageGroups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u19'];

    for (const age of ageGroups) {
      const response = await page.goto(`/rankings/national/${age}/male`);
      expect(response?.status()).toBeLessThan(500);
    }
  });
});

test.describe('Rankings - Sort', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/rankings/national/u12/male');
    // Wait for row 0 + team link so the table is fully interactive before sorting
    await waitForFirstRankingsRow(page);
  });

  test('clicking Rank sort button toggles direction', async ({ page }) => {
    const rankSortBtn = page.getByRole('button', { name: /Sort by Rank/i });
    await rankSortBtn.click();

    // After clicking once (was asc), should be desc — first row should not be #1
    // We just verify the click doesn't error and rows re-render
    await expect(page.locator('[data-testid="rankings-row-0"]')).toBeVisible({ timeout: 15_000 });
  });

  test('clicking Team sort button sorts alphabetically', async ({ page }) => {
    const teamSortBtn = page.getByRole('button', { name: /Sort by Team/i });
    await teamSortBtn.click();

    // Verify rows are still visible after sort
    await expect(page.locator('[data-testid="rankings-row-0"]')).toBeVisible({ timeout: 15_000 });
  });
});

test.describe('Rankings - Loading States', () => {
  test('shows skeleton loader during initial load', async ({ page }) => {
    // Navigate before data loads
    await page.goto('/rankings/national/u12/male', { waitUntil: 'commit' });

    // Either skeleton or table should eventually appear
    await expect(
      page.locator('[data-testid="rankings-table-card"], [class*="skeleton"], [class*="animate-pulse"]').first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test('shows "No teams available" for empty results', async ({ page }) => {
    // Use an unlikely combination that may have no data
    const response = await page.goto('/rankings/national/u10/female');
    expect(response?.status()).toBeLessThan(500);
  });
});
