import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const { mockUsePathname, mockUseSearchParams } = vi.hoisted(() => ({
  mockUsePathname: vi.fn(),
  mockUseSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock('next/navigation', () => ({
  usePathname: mockUsePathname,
  useSearchParams: mockUseSearchParams,
}));

// Render Script's children so the inline bootstrap is inspectable as markup.
vi.mock('next/script', () => ({
  default: ({ children }: { children?: React.ReactNode }) => <script>{children}</script>,
}));

import { SECRET_QUERY_PARAMS, SECRET_QUERY_PATHS } from '@/lib/constants';
import { GoogleAds } from '../GoogleAds';
import { MetaPixel } from '../MetaPixel';
import { GoogleAnalytics } from '../GoogleAnalytics';

const SECRET_PATHS = [...SECRET_QUERY_PATHS];
const LIVE_TOKEN = 'live-token-value';

describe('analytics never receive URL-borne credentials', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSearchParams.mockReturnValue(new URLSearchParams());
  });

  it('lists both bearer credentials that ride in a query string', () => {
    expect(SECRET_QUERY_PARAMS).toContain('session_id');
    expect(SECRET_QUERY_PARAMS).toContain('token_hash');
  });

  it('lists every page that renders with a credential in its URL', () => {
    expect(SECRET_QUERY_PATHS).toContain('/upgrade/success');
    expect(SECRET_QUERY_PATHS).toContain('/auth/confirm');
  });

  describe.each(SECRET_PATHS)('on %s', (path) => {
    beforeEach(() => {
      mockUsePathname.mockReturnValue(path);
    });

    it('GoogleAds emits nothing', () => {
      expect(renderToStaticMarkup(<GoogleAds conversionId="AW-123" />)).toBe('');
    });

    it('MetaPixel emits nothing', () => {
      expect(renderToStaticMarkup(<MetaPixel pixelId="123" />)).toBe('');
    });

    it('GoogleAnalytics emits nothing — gtag.js would re-read location on history navigation', () => {
      expect(renderToStaticMarkup(<GoogleAnalytics measurementId="G-123" />)).toBe('');
    });
  });

  it('GoogleAnalytics strips every secret param from its bootstrap on an ordinary page', () => {
    mockUsePathname.mockReturnValue('/rankings');

    const markup = renderToStaticMarkup(<GoogleAnalytics measurementId="G-123" />);

    // The bootstrap must delete the params by list, not by a hardcoded subset.
    for (const param of SECRET_QUERY_PARAMS) {
      expect(markup).toContain(param);
    }
    expect(markup).toContain('sanitized.searchParams.delete(p)');
    expect(markup).toContain('page_location: sanitized.toString()');
  });

  it('GoogleAnalytics pins page_location rather than letting GA4 derive it', () => {
    mockUsePathname.mockReturnValue('/rankings');

    const markup = renderToStaticMarkup(<GoogleAnalytics measurementId="G-123" />);

    expect(markup).not.toContain('page_location: window.location.href');
  });

  it('the generated bootstrap is valid JS that removes the credentials', () => {
    mockUsePathname.mockReturnValue('/rankings');
    const markup = renderToStaticMarkup(<GoogleAnalytics measurementId="G-123" />);
    const deleteLine = markup.split('\n').find((line) => line.includes('searchParams.delete'))!;

    const sanitized = new URL(`https://x.test/rankings?token_hash=${LIVE_TOKEN}&session_id=abc&keep=1`);
    // Executing the emitted statement proves the interpolation is well-formed.
    new Function('sanitized', deleteLine)(sanitized);

    expect(sanitized.toString()).not.toContain(LIVE_TOKEN);
    expect(sanitized.toString()).not.toContain('session_id');
    expect(sanitized.toString()).toContain('keep=1');
  });

  it('GoogleAds still renders on an ordinary page', () => {
    mockUsePathname.mockReturnValue('/rankings');

    expect(renderToStaticMarkup(<GoogleAds conversionId="AW-123" />)).not.toBe('');
  });
});
