const ORIGIN = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export async function loadBrandFonts() {
  const [oswaldBold, oswaldReg, dmSansBold, dmSansReg] = await Promise.all([
    fetch(`${ORIGIN}/fonts/Oswald-Bold.woff`).then((r) => r.arrayBuffer()),
    fetch(`${ORIGIN}/fonts/Oswald-Regular.woff`).then((r) => r.arrayBuffer()),
    fetch(`${ORIGIN}/fonts/DMSans-Bold.woff`).then((r) => r.arrayBuffer()),
    fetch(`${ORIGIN}/fonts/DMSans-Regular.woff`).then((r) => r.arrayBuffer()),
  ]);
  return [
    { name: 'Oswald', data: oswaldBold, weight: 700 as const, style: 'normal' as const },
    { name: 'Oswald', data: oswaldReg, weight: 400 as const, style: 'normal' as const },
    { name: 'DM Sans', data: dmSansBold, weight: 700 as const, style: 'normal' as const },
    { name: 'DM Sans', data: dmSansReg, weight: 400 as const, style: 'normal' as const },
  ];
}

// PNG, not SVG: Satori (the @vercel/og renderer) does not support SVG inside <img>.
// SVG logos render as a blank box and the entire ImageResponse returns 0 bytes.
export const LOGO_URL = `${ORIGIN}/logos/logo-primary.png`;
