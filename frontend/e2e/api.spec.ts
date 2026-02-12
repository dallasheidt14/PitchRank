import { test, expect } from '@playwright/test';

/**
 * API E2E Tests
 *
 * These tests exercise the API routes directly using Playwright's request context.
 * They do NOT require a browser and can run with the "api" project configuration.
 *
 * Run with: npx playwright test --project=api
 */

test.describe('Team Search API @api', () => {
  test('returns empty array for short query (< 2 chars)', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=a');
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.teams).toEqual([]);
  });

  test('returns empty array for empty query', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=');
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.teams).toEqual([]);
  });

  test('returns teams for valid search query @smoke', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=FC Dallas');
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body).toHaveProperty('teams');
    expect(Array.isArray(body.teams)).toBe(true);
  });

  test('returns teams with expected fields', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=Real Salt Lake');
    expect(response.status()).toBe(200);

    const body = await response.json();
    if (body.teams.length > 0) {
      const team = body.teams[0];
      expect(team).toHaveProperty('team_id_master');
      expect(team).toHaveProperty('team_name');
    }
  });

  test('respects limit parameter', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=FC&limit=5');
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.teams.length).toBeLessThanOrEqual(5);
  });

  test('sanitizes PostgREST injection characters', async ({ request }) => {
    // These characters should be stripped: %_(),.*\
    const response = await request.get('/api/teams/search?q=%25_().*\\test');
    expect(response.status()).toBe(200);

    const body = await response.json();
    // Should not error — sanitization should handle it gracefully
    expect(body).toHaveProperty('teams');
  });

  test('handles special characters without 500 error', async ({ request }) => {
    const queries = [
      "O'Brien",
      'test"injection',
      'a & b',
      '<script>alert(1)</script>',
      "'; DROP TABLE teams; --",
    ];

    for (const q of queries) {
      const response = await request.get(`/api/teams/search?q=${encodeURIComponent(q)}`);
      expect(response.status()).toBeLessThan(500);
    }
  });

  test('max limit is enforced at 100', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=FC&limit=500');
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.teams.length).toBeLessThanOrEqual(100);
  });

  test('filters by gender parameter', async ({ request }) => {
    const response = await request.get('/api/teams/search?q=FC&gender=M');
    expect(response.status()).toBe(200);

    const body = await response.json();
    if (body.teams.length > 0) {
      // All returned teams should have gender M (or Boys/B depending on data model)
      body.teams.forEach((team: { gender: string }) => {
        expect(['M', 'B', 'Boys']).toContain(team.gender);
      });
    }
  });
});

test.describe('Watchlist API @api', () => {
  test('watchlist GET returns 401 for unauthenticated requests', async ({ request }) => {
    const response = await request.get('/api/watchlist');
    // Should require authentication
    expect([401, 403]).toContain(response.status());
  });

  test('watchlist add returns 401 for unauthenticated requests', async ({ request }) => {
    const response = await request.post('/api/watchlist/add', {
      data: { teamId: 'test-id' },
    });
    expect([401, 403]).toContain(response.status());
  });

  test('watchlist remove returns 401 for unauthenticated requests', async ({ request }) => {
    const response = await request.post('/api/watchlist/remove', {
      data: { teamId: 'test-id' },
    });
    expect([401, 403]).toContain(response.status());
  });
});

test.describe('API - General Robustness @api', () => {
  test('non-existent API routes return 404', async ({ request }) => {
    const response = await request.get('/api/nonexistent-endpoint');
    expect(response.status()).toBe(404);
  });

  test('API routes handle OPTIONS (CORS preflight)', async ({ request }) => {
    const response = await request.fetch('/api/teams/search', {
      method: 'OPTIONS',
    });
    // Should not return 500
    expect(response.status()).toBeLessThan(500);
  });

  test('POST to GET-only endpoint returns appropriate error', async ({ request }) => {
    const response = await request.post('/api/teams/search', {
      data: { q: 'test' },
    });
    // Should return 405 Method Not Allowed or similar
    expect([404, 405]).toContain(response.status());
  });
});

test.describe('Page Response Codes @api', () => {
  test('homepage returns 200', async ({ request }) => {
    const response = await request.get('/');
    expect(response.status()).toBe(200);
  });

  test('rankings page returns 200', async ({ request }) => {
    const response = await request.get('/rankings');
    expect(response.status()).toBe(200);
  });

  test('methodology page returns 200', async ({ request }) => {
    const response = await request.get('/methodology');
    expect(response.status()).toBe(200);
  });

  test('login page returns 200', async ({ request }) => {
    const response = await request.get('/login');
    expect(response.status()).toBe(200);
  });

  test('signup page returns 200', async ({ request }) => {
    const response = await request.get('/signup');
    expect(response.status()).toBe(200);
  });

  test('dynamic rankings routes return 200', async ({ request }) => {
    const routes = [
      '/rankings/national/u12/male',
      '/rankings/national/u14/female',
      '/rankings/TX/u12/male',
      '/rankings/CA/u14/female',
    ];

    for (const route of routes) {
      const response = await request.get(route);
      expect(response.status()).toBe(200);
    }
  });
});
