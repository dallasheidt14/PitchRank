import { defineConfig, devices } from '@playwright/test';

/**
 * PitchRank E2E Test Configuration
 *
 * Tests run against the live pitchrank.io site by default.
 * Override with PLAYWRIGHT_BASE_URL env var for local/staging testing.
 *
 * Usage:
 *   npx playwright test                    # Run all tests against pitchrank.io
 *   PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test  # Run against local dev
 *   npx playwright test --grep @smoke      # Run smoke tests only
 *   npx playwright test --grep @api        # Run API tests only (no browser needed)
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'https://pitchrank.io',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Accept cookies and follow redirects
    ignoreHTTPSErrors: true,
    // Realistic viewport
    viewport: { width: 1280, height: 720 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
    // API tests don't need a browser
    {
      name: 'api',
      testMatch: /api\.spec\.ts/,
      use: {
        baseURL: process.env.PLAYWRIGHT_BASE_URL || 'https://pitchrank.io',
      },
    },
  ],
});
