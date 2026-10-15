import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockPathname } = vi.hoisted(() => ({ mockPathname: { current: '/' } }));

vi.mock('next/navigation', () => ({ usePathname: () => mockPathname.current }));

import { Breadcrumbs } from './Breadcrumbs';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function renderAt(pathname: string) {
  mockPathname.current = pathname;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(Breadcrumbs, { showHomeIcon: false })));
}

function linkHrefs(): string[] {
  return Array.from(container!.querySelectorAll('nav a')).map((a) => a.getAttribute('href')!);
}

function currentCrumb(): string {
  return container!.querySelector('[aria-current="page"]')!.textContent!;
}

function schemaItems(): string[] {
  const schema = JSON.parse(container!.querySelector('script[type="application/ld+json"]')!.textContent!);
  return schema.itemListElement.map((item: { item: string }) => new URL(item.item).pathname);
}

describe('Breadcrumbs on a rankings board', () => {
  it('folds the age into the board crumb, since no page lives at /rankings/<region>/<age>', async () => {
    await renderAt('/rankings/az/u13/male');

    expect(linkHrefs()).toEqual(['/', '/rankings', '/rankings/az']);
    expect(currentCrumb()).toBe('U13 Boys');
    expect(schemaItems()).toEqual(['/', '/rankings', '/rankings/az', '/rankings/az/u13/male']);
  });

  it('labels a national girls board the same way', async () => {
    await renderAt('/rankings/national/u19/female');

    expect(linkHrefs()).toEqual(['/', '/rankings', '/rankings/national']);
    expect(currentCrumb()).toBe('U19 Girls');
  });

  it('leaves a state overview ending in the state', async () => {
    await renderAt('/rankings/az');

    expect(linkHrefs()).toEqual(['/', '/rankings']);
    expect(currentCrumb()).toBe('Arizona');
  });
});
