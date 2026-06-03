// Design tokens for the social infographics — ported from the canvas infographic system.

export const DIMENSIONS = {
  instagram: { width: 1080, height: 1080 },
  story: { width: 1080, height: 1920 },
  twitter: { width: 1200, height: 675 },
} as const;

export type PlatformKey = keyof typeof DIMENSIONS;

export const COLORS = {
  forestGreen: '#0B5345',
  darkGreen: '#052E27',
  electricYellow: '#F4D03F',
  brightWhite: '#FDFEFE',
  date: '#AAB7B2',
  club: '#9FB4AD',
  label: '#7E938C',
  divider: '#0E6552',
  rowDim: 'rgba(255,255,255,0.05)',
  rowTop3: 'rgba(244,208,63,0.16)',
  rowBorderDim: 'rgba(255,255,255,0.18)',
  climber: '#7BE38B',
  faller: '#F1948A',
} as const;

// Gold / silver / bronze for ranks 1-3.
export const MEDAL = ['#F4D03F', '#C0C0C0', '#CD7F32'] as const;

export function platformDims(platform: string) {
  return DIMENSIONS[platform as PlatformKey] ?? DIMENSIONS.instagram;
}

// PowerScore is stored 0-1; display on the public 0-100 scale with 2 decimals.
export function formatScore(p: number | null | undefined): string {
  return p == null ? '--' : (p * 100).toFixed(2);
}

export function formatRecord(w?: number, l?: number, d?: number): string {
  return `${w ?? 0}-${l ?? 0}-${d ?? 0}`;
}
