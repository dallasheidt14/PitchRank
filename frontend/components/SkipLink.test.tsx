import { afterEach, describe, expect, it } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SkipLink } from './SkipLink';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function renderWithMain() {
  container = document.createElement('div');
  document.body.appendChild(container);
  const host = document.createElement('div');
  const main = document.createElement('main');
  main.id = 'main';
  container.append(host, main);
  root = createRoot(host);
  await act(async () => root!.render(React.createElement(SkipLink)));
  return { link: host.querySelector('a')!, main };
}

describe('SkipLink', () => {
  it('focuses the main landmark without following the link, so no history entry is added', async () => {
    const { link, main } = await renderWithMain();
    const historyLength = window.history.length;
    const url = window.location.href;

    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    await act(async () => link.dispatchEvent(click));

    expect(click.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(main);
    expect(window.history.length).toBe(historyLength);
    expect(window.location.href).toBe(url);
  });

  it('makes main focusable only until focus moves on', async () => {
    const { link, main } = await renderWithMain();

    await act(async () => link.click());
    expect(main.getAttribute('tabindex')).toBe('-1');

    await act(async () => main.blur());
    expect(main.hasAttribute('tabindex')).toBe(false);
  });
});
