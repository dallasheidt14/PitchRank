import { describe, it, expect } from 'vitest';
import { getClientIp, checkRateLimit } from '../rateLimit';

function makeRequest(headers: Record<string, string> = {}): Request {
  return new Request('http://localhost/api/anything', { headers });
}

describe('getClientIp', () => {
  it('prefers x-real-ip over x-forwarded-for', () => {
    const req = makeRequest({ 'x-real-ip': '198.51.100.7', 'x-forwarded-for': '203.0.113.9' });

    expect(getClientIp(req)).toBe('198.51.100.7');
  });

  it('takes the first comma-separated x-forwarded-for segment, trimmed', () => {
    const req = makeRequest({ 'x-forwarded-for': '  203.0.113.9 , 70.41.3.18 , 150.172.238.178' });

    expect(getClientIp(req)).toBe('203.0.113.9');
  });

  it("returns 'unknown' when neither header is present", () => {
    expect(getClientIp(makeRequest())).toBe('unknown');
  });
});

describe('checkRateLimit', () => {
  // The limiter keeps a module-level Map keyed by IP, so each test uses a
  // unique key to stay independent of every other test in this file.

  it('allows up to maxRequests within the window, then denies', () => {
    const key = 'rl-allow-then-deny';

    expect(checkRateLimit(key, 3, 60_000)).toBe(true);
    expect(checkRateLimit(key, 3, 60_000)).toBe(true);
    expect(checkRateLimit(key, 3, 60_000)).toBe(true);
    // 4th request exceeds the cap of 3
    expect(checkRateLimit(key, 3, 60_000)).toBe(false);
  });

  it('keys are independent — exhausting one does not affect another', () => {
    const keyA = 'rl-independent-a';
    const keyB = 'rl-independent-b';

    expect(checkRateLimit(keyA, 1, 60_000)).toBe(true);
    expect(checkRateLimit(keyA, 1, 60_000)).toBe(false);

    // keyB has its own counter and is still allowed
    expect(checkRateLimit(keyB, 1, 60_000)).toBe(true);
  });
});
