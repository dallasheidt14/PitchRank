import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import type { QueryClient } from '@tanstack/react-query';

const { serverFlag } = vi.hoisted(() => ({ serverFlag: { isServer: false } }));

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    get isServer() {
      return serverFlag.isServer;
    },
  };
});

type Provider = (props: { children: React.ReactNode }) => React.ReactNode;

async function clientFromRender(loadProvider?: () => Promise<Provider>): Promise<QueryClient> {
  const Provider = loadProvider ? await loadProvider() : (await import('./data-providers')).RankingsDataProviders;
  const { useQueryClient } = await import('@tanstack/react-query');
  const seen: QueryClient[] = [];
  function Capture() {
    const client = useQueryClient();
    useEffect(() => {
      seen.push(client);
    }, [client]);
    return null;
  }
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(Provider, null, React.createElement(Capture))));
  await act(async () => root.unmount());
  return seen[0];
}

afterEach(() => {
  serverFlag.isServer = false;
  vi.resetModules();
});

describe('RankingsDataProviders', () => {
  it('keeps one query client for the whole browser session', async () => {
    const first = await clientFromRender();
    const second = await clientFromRender();

    expect(second).toBe(first);
  });

  it('gives every server render its own client', async () => {
    serverFlag.isServer = true;

    const first = await clientFromRender();
    const second = await clientFromRender();

    expect(second).not.toBe(first);
  });

  it('is what the rankings layout mounts, so Back from a team page finds the cohort cached', async () => {
    const loadLayout = async () => (await import('./rankings/layout')).default;

    const first = await clientFromRender(loadLayout);
    const second = await clientFromRender(loadLayout);

    expect(second).toBe(first);
  });
});
