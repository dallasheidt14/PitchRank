const ORIGIN = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

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

export async function loadBrandFonts(): Promise<SatoriFont[]> {
  // Edge runtime can intermittently fail to fetch self-hosted assets. Any font
  // that fails to load is dropped silently; Satori falls back to its default
  // for that family. A blank result is preferable to a 0-byte ImageResponse.
  const results = await Promise.all([
    tryLoadFont(`${ORIGIN}/fonts/Oswald-Bold.woff`, 'Oswald', 700),
    tryLoadFont(`${ORIGIN}/fonts/Oswald-Regular.woff`, 'Oswald', 400),
    tryLoadFont(`${ORIGIN}/fonts/DMSans-Bold.woff`, 'DM Sans', 700),
    tryLoadFont(`${ORIGIN}/fonts/DMSans-Regular.woff`, 'DM Sans', 400),
  ]);
  return results.filter((f): f is SatoriFont => f !== null);
}

// PNG, not SVG: Satori (the @vercel/og renderer) does not support SVG inside <img>.
// SVG logos render as a blank box and the entire ImageResponse returns 0 bytes.
export const LOGO_URL = `${ORIGIN}/logos/logo-primary.png`;

// Explicit logo dimensions matching the source PNG's 5.67:1 aspect ratio.
// Satori rejects `height="auto"` and silently fails the entire ImageResponse.
export const LOGO_WIDTH = { default: 280, story: 360 } as const;
export const LOGO_HEIGHT = { default: 49, story: 63 } as const;
