import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';
import type { ReactElement } from 'react';

const { fontOptions } = vi.hoisted(() => ({ fontOptions: new Map<string, Record<string, unknown>>() }));

vi.mock('next/font/google', () => {
  const loader = (options: { variable: string } & Record<string, unknown>) => {
    fontOptions.set(options.variable, options);
    return { variable: `font-var${options.variable}`, className: '' };
  };
  return { Oswald: loader, DM_Sans: loader, JetBrains_Mono: loader };
});
vi.mock('./providers', () => ({ SiteProviders: () => null }));
vi.mock('@/components/Navigation', () => ({ Navigation: () => null }));
vi.mock('@/components/ui/Toaster', () => ({ Toaster: () => null }));
vi.mock('@/components/StructuredData', () => ({ StructuredData: () => null }));
vi.mock('@/components/Footer', () => ({ Footer: () => null }));
vi.mock('@/components/GoogleAnalytics', () => ({ GoogleAnalytics: () => null }));
vi.mock('@/components/MetaPixel', () => ({ MetaPixel: () => null }));
vi.mock('@/components/GoogleAds', () => ({ GoogleAds: () => null }));
vi.mock('@/components/WebVitalsReporter', () => ({ WebVitalsReporter: () => null }));

import RootLayout from './layout';

function themeBlock(): string {
  const css = readFileSync(path.join(__dirname, 'globals.css'), 'utf-8');
  return css.match(/@theme inline \{([\s\S]*?)\n\}/)?.[1] ?? '';
}

describe('RootLayout fonts', () => {
  // Tailwind resolves the default body and mono fonts on <html>, so a font variable left on <body>
  // silently drops body text to the system font, with no error anywhere.
  it('declares every font variable the theme reads on <html>', () => {
    const referenced = [...themeBlock().matchAll(/var\((--font-[a-z-]+)\)/g)].map((match) => match[1]).sort();
    expect(referenced).toEqual(['--font-dm-sans', '--font-jetbrains-mono', '--font-oswald']);

    const tree = RootLayout({ children: null }) as ReactElement<{ className?: string }>;

    expect(tree.type).toBe('html');
    const classes = (tree.props.className ?? '').split(/\s+/);
    for (const variable of referenced) expect(classes).toContain(`font-var${variable}`);
  });

  // The production (Turbopack) build emits a font's size-matched "<Font> Fallback" face only when
  // the call passes no `fallback`. Mono opts out: its generated stand-in would be scaled Arial.
  it('lets next/font size-match the fallback for the text fonts and not for mono', () => {
    expect([...fontOptions.keys()].sort()).toEqual(['--font-dm-sans', '--font-jetbrains-mono', '--font-oswald']);
    for (const variable of ['--font-dm-sans', '--font-oswald']) {
      const options = fontOptions.get(variable);
      expect(options).not.toHaveProperty('fallback');
      expect(options?.adjustFontFallback).not.toBe(false);
    }
    expect(fontOptions.get('--font-jetbrains-mono')?.fallback).toEqual(['ui-monospace', 'monospace']);
  });

  it('ends every theme font token in a generic family', () => {
    const tokens = Object.fromEntries(
      [...themeBlock().matchAll(/(--font-[a-z]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()])
    );
    expect(tokens).toEqual({
      '--font-sans': 'var(--font-dm-sans), system-ui, sans-serif',
      '--font-mono': 'var(--font-jetbrains-mono), ui-monospace, monospace',
      '--font-display': 'var(--font-oswald), system-ui, sans-serif',
    });
  });
});
