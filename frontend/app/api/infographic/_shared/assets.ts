type SatoriFont = {
  name: 'Oswald' | 'DM Sans';
  data: ArrayBuffer;
  weight: 400 | 700;
  style: 'normal';
};

async function tryLoadFont(
  url: string,
  name: SatoriFont['name'],
  weight: SatoriFont['weight']
): Promise<SatoriFont | null> {
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      console.error(`[loadBrandFonts] ${url} returned ${resp.status}`);
      return null;
    }
    const data = await resp.arrayBuffer();
    if (data.byteLength === 0) {
      console.error(`[loadBrandFonts] ${url} returned empty body`);
      return null;
    }
    return { name, data, weight, style: 'normal' };
  } catch (e) {
    console.error(`[loadBrandFonts] ${url} threw: ${e instanceof Error ? e.message : String(e)}`);
    return null;
  }
}

// Fetch brand fonts from the request origin so local dev and prod both resolve.
// Edge runtime can intermittently fail to fetch self-hosted assets; any font that
// fails is dropped silently (Satori falls back to its default) — a blank result is
// preferable to a 0-byte ImageResponse.
export async function loadBrandFonts(origin: string): Promise<SatoriFont[]> {
  const results = await Promise.all([
    tryLoadFont(`${origin}/fonts/Oswald-Bold.woff`, 'Oswald', 700),
    tryLoadFont(`${origin}/fonts/Oswald-Regular.woff`, 'Oswald', 400),
    tryLoadFont(`${origin}/fonts/DMSans-Bold.woff`, 'DM Sans', 700),
    tryLoadFont(`${origin}/fonts/DMSans-Regular.woff`, 'DM Sans', 400),
  ]);
  return results.filter((f): f is SatoriFont => f !== null);
}

// Transparent wordmark (baked green box removed via color-to-alpha — see
// scripts/make_wordmark.py). PNG, not SVG: Satori does not support SVG in <img>.
// Source is 800x141, so width * WORDMARK_ASPECT gives the matching height.
export function wordmarkUrl(origin: string): string {
  return `${origin}/logos/logo-wordmark.png`;
}
export const WORDMARK_ASPECT = 141 / 800;

// Cache the rendered PNGs at the CDN. Rankings data changes weekly, so a 1h shared
// cache (with day-long stale-while-revalidate) avoids a cold RPC + font fetch + Satori
// render on every Postiz/Beehiiv/link-preview fetch of the same URL.
export const INFOGRAPHIC_CACHE_CONTROL = 'public, s-maxage=3600, stale-while-revalidate=86400';
