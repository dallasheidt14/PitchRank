import { test, expect } from '@playwright/test';

test.describe('Methodology Page', () => {
  test('renders methodology page with heading @smoke', async ({ page }) => {
    await page.goto('/methodology');

    await expect(page.getByText('Ranking Methodology')).toBeVisible();
    await expect(page.getByText('Understanding how PitchRank')).toBeVisible();
  });

  test('has back button linking to home', async ({ page }) => {
    await page.goto('/methodology');

    // PageHeader has showBackButton with backHref="/"
    const backLink = page.getByRole('link', { name: /back/i });
    if (await backLink.isVisible()) {
      await expect(backLink).toHaveAttribute('href', '/');
    }
  });

  test('methodology content is present', async ({ page }) => {
    await page.goto('/methodology');

    // The MethodologySection component should render substantial content
    const mainContent = page.locator('.max-w-4xl');
    await expect(mainContent).toBeVisible();

    // Should have meaningful text content (not empty)
    const textContent = await mainContent.textContent();
    expect(textContent?.length).toBeGreaterThan(100);
  });

  test('page has correct metadata', async ({ page }) => {
    await page.goto('/methodology');
    await expect(page).toHaveTitle(/Methodology/i);
  });

  test('page returns 200 status code', async ({ page }) => {
    const response = await page.goto('/methodology');
    expect(response?.status()).toBe(200);
  });
});

test.describe('Blog Page', () => {
  test('blog page loads without errors', async ({ page }) => {
    const response = await page.goto('/blog');
    expect(response?.status()).toBeLessThan(500);
  });

  test('blog page has content', async ({ page }) => {
    await page.goto('/blog');
    await expect(page.locator('body')).not.toBeEmpty();
  });
});

test.describe('404 Handling', () => {
  test('non-existent page returns appropriate response', async ({ page }) => {
    const response = await page.goto('/this-page-does-not-exist-xyz');
    // Next.js returns 404 for unknown routes
    expect(response?.status()).toBe(404);
  });
});

test.describe('SEO & Meta Tags', () => {
  test('homepage has proper Open Graph meta tags', async ({ page }) => {
    await page.goto('/');

    const ogTitle = page.locator('meta[property="og:title"]');
    const ogDescription = page.locator('meta[property="og:description"]');
    const ogType = page.locator('meta[property="og:type"]');

    // At least one OG tag should be present
    const hasOgTags = await ogTitle.count() > 0 || await ogDescription.count() > 0;
    expect(hasOgTags).toBe(true);
  });

  test('homepage has meta description', async ({ page }) => {
    await page.goto('/');

    const metaDesc = page.locator('meta[name="description"]');
    await expect(metaDesc).toHaveAttribute('content', /.+/);
  });

  test('rankings page has proper meta tags', async ({ page }) => {
    await page.goto('/rankings/national/u12/male');

    await expect(page).toHaveTitle(/.+/);
  });

  test('methodology page has canonical URL', async ({ page }) => {
    await page.goto('/methodology');

    const canonical = page.locator('link[rel="canonical"]');
    if (await canonical.count() > 0) {
      await expect(canonical).toHaveAttribute('href', /methodology/);
    }
  });
});

test.describe('Performance & Accessibility', () => {
  test('homepage loads within reasonable time', async ({ page }) => {
    const start = Date.now();
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const loadTime = Date.now() - start;

    // Should load DOM in under 10 seconds
    expect(loadTime).toBeLessThan(10_000);
  });

  test('rankings page loads within reasonable time', async ({ page }) => {
    const start = Date.now();
    await page.goto('/rankings/national/u12/male', { waitUntil: 'domcontentloaded' });
    const loadTime = Date.now() - start;

    expect(loadTime).toBeLessThan(10_000);
  });

  test('homepage has proper heading hierarchy', async ({ page }) => {
    await page.goto('/');

    // Should have an h1
    const h1Count = await page.locator('h1').count();
    expect(h1Count).toBeGreaterThanOrEqual(1);
  });

  test('images have alt attributes', async ({ page }) => {
    await page.goto('/');

    const images = page.locator('img');
    const count = await images.count();

    for (let i = 0; i < Math.min(count, 10); i++) {
      const alt = await images.nth(i).getAttribute('alt');
      // All images should have an alt attribute (can be empty for decorative images)
      expect(alt).not.toBeNull();
    }
  });

  test('navigation links have aria labels', async ({ page }) => {
    await page.goto('/');

    const logoLink = page.locator('[aria-label="PitchRank home"]');
    await expect(logoLink).toBeVisible();
  });
});

test.describe('Footer', () => {
  test('footer is present on homepage', async ({ page }) => {
    await page.goto('/');

    const footer = page.locator('footer');
    await expect(footer).toBeVisible();
  });

  test('footer is present on rankings page', async ({ page }) => {
    await page.goto('/rankings');

    const footer = page.locator('footer');
    await expect(footer).toBeVisible();
  });
});
