import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { InfoButton, InfoTooltip } from './info-tooltip';
import { TooltipProvider } from './tooltip';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function pointerIsTouch(isTouch: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query) =>
      ({
        matches: isTouch && query === '(hover: none) and (pointer: coarse)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList
  );
}

async function renderTooltip(side: 'right' | 'top') {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root!.render(
      React.createElement(
        TooltipProvider,
        null,
        React.createElement(
          InfoTooltip,
          {
            side,
            trigger: React.createElement(InfoButton, { label: 'About Consistency' }),
          } as React.ComponentProps<typeof InfoTooltip>,
          'How predictable this team is.'
        )
      )
    )
  );
  return container.querySelector('button')!;
}

function openPanel(): HTMLElement | null {
  return document.querySelector('[data-slot="info-tooltip-content"]');
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
});

describe('InfoButton', () => {
  it('is a named button that does not submit forms', async () => {
    pointerIsTouch(false);
    const button = await renderTooltip('top');

    expect(button.getAttribute('type')).toBe('button');
    expect(button.getAttribute('aria-label')).toBe('About Consistency');
  });
});

describe('InfoTooltip on a touch screen', () => {
  it('opens on tap, capped to the screen width', async () => {
    pointerIsTouch(true);
    const button = await renderTooltip('top');
    expect(openPanel()).toBeNull();

    await act(async () => button.click());

    expect(openPanel()!.textContent).toContain('How predictable this team is.');
    expect(openPanel()!.className).toContain('max-w-[min(20rem,var(--radix-popper-available-width))]');
    expect(button.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens below a trigger that asked for a side, since a side panel cannot slide on screen', async () => {
    pointerIsTouch(true);
    const button = await renderTooltip('right');

    await act(async () => button.click());

    expect(openPanel()!.getAttribute('data-side')).toBe('bottom');
  });

  it('keeps a top placement', async () => {
    pointerIsTouch(true);
    const button = await renderTooltip('top');

    await act(async () => button.click());

    expect(openPanel()!.getAttribute('data-side')).toBe('top');
  });
});

describe('InfoTooltip with a mouse or keyboard', () => {
  it('does not open the tap panel on click', async () => {
    pointerIsTouch(false);
    const button = await renderTooltip('right');

    await act(async () => button.click());

    expect(openPanel()).toBeNull();
    expect(button.hasAttribute('aria-expanded')).toBe(false);
  });

  it('opens the hover tooltip, capped to the screen width, when the trigger takes focus', async () => {
    pointerIsTouch(false);
    const button = await renderTooltip('right');

    await act(async () => button.focus());

    const tooltip = document.querySelector('[data-slot="tooltip-content"]')!;
    expect(tooltip.textContent).toContain('How predictable this team is.');
    expect(tooltip.className).toContain('max-w-[min(20rem,var(--radix-popper-available-width))]');
  });
});
