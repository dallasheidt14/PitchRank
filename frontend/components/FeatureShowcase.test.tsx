import { describe, expect, it } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { FeatureShowcase } from './FeatureShowcase';

function tiles() {
  const page = document.createElement('div');
  page.innerHTML = renderToStaticMarkup(React.createElement(FeatureShowcase));
  return Array.from(page.querySelectorAll('h3')).map((title) => {
    const tile = title.closest('[data-slot="card"]')!;
    return {
      title: title.textContent,
      href: tile.querySelector('a')!.getAttribute('href'),
      badge: tile.textContent!.includes('PitchRank+'),
    };
  });
}

describe('FeatureShowcase', () => {
  it('sends each tile somewhere different and marks the two subscriber features', () => {
    expect(tiles()).toEqual([
      { title: 'Compare & Predict', href: '/compare', badge: true },
      { title: 'Build Your Watchlist', href: '/watchlist', badge: true },
      { title: 'State Rankings', href: '/rankings', badge: false },
      { title: 'Free Team Report Card', href: '/report-card', badge: false },
    ]);
  });
});
