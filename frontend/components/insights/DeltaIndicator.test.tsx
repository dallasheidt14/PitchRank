import { afterEach, describe, expect, it } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { DeltaIndicator } from './InsightModal';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function renderDelta(value: number | null) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(React.createElement(DeltaIndicator, { value }));
    await Promise.resolve();
  });
  return container;
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('DeltaIndicator', () => {
  it('renders a positive change as an improvement', async () => {
    const el = await renderDelta(258);

    expect(el.querySelector('.lucide-trending-up')).not.toBeNull();
    expect(el.querySelector('.lucide-trending-down')).toBeNull();
    expect(el.querySelector('span')!.className).toContain('text-green-600');
    expect(el.textContent).toContain('258');
  });

  it('renders a negative change as a decline', async () => {
    const el = await renderDelta(-90);

    expect(el.querySelector('.lucide-trending-down')).not.toBeNull();
    expect(el.querySelector('.lucide-trending-up')).toBeNull();
    expect(el.querySelector('span')!.className).toContain('text-red-600');
    expect(el.textContent).toContain('90');
  });

  it('renders a neutral marker for zero and null', async () => {
    expect((await renderDelta(0)).querySelector('.lucide-minus')).not.toBeNull();
    await act(async () => root?.unmount());
    container?.remove();

    expect((await renderDelta(null)).querySelector('.lucide-minus')).not.toBeNull();
  });
});
