import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactElement } from 'react';

const { mockCreateServerSupabase, mockVerifyOtp } = vi.hoisted(() => ({
  mockCreateServerSupabase: vi.fn(),
  mockVerifyOtp: vi.fn(),
}));

vi.mock('@/lib/supabase/server', () => ({ createServerSupabase: mockCreateServerSupabase }));
vi.mock('next/navigation', () => ({ redirect: vi.fn() }));

import ConfirmPage from '../page';

function render(params: Record<string, string>) {
  return ConfirmPage({ searchParams: Promise.resolve(params) });
}

/** Collect every node in the returned element tree so we can assert on props. */
function flatten(node: unknown, out: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    node.forEach((child) => flatten(child, out));
    return out;
  }
  if (!node || typeof node !== 'object' || !('props' in node)) {
    return out;
  }
  const element = node as ReactElement<{ children?: unknown }>;
  out.push(element);
  flatten(element.props?.children, out);
  return out;
}

function hiddenInputs(tree: ReactElement[]): Record<string, unknown> {
  const entries = tree
    .filter((el) => el.type === 'input')
    .map((el) => el.props as { name?: string; value?: unknown })
    .filter((props) => typeof props.name === 'string')
    .map((props) => [props.name as string, props.value] as const);
  return Object.fromEntries(entries);
}

describe('ConfirmPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('redeems nothing while rendering — the whole point of the interstitial', async () => {
    await render({ token_hash: 'abc', type: 'recovery', next: '/reset-password' });

    expect(mockCreateServerSupabase).not.toHaveBeenCalled();
    expect(mockVerifyOtp).not.toHaveBeenCalled();
  });

  it('carries the token through to the action in fields the action reads', async () => {
    const tree = flatten(await render({ token_hash: 'abc', type: 'recovery', next: '/reset-password' }));

    expect(hiddenInputs(tree)).toEqual({ token_hash: 'abc', type: 'recovery', next: '/reset-password' });
  });

  it('submits to the confirm action rather than a plain URL', async () => {
    const tree = flatten(await render({ token_hash: 'abc', type: 'recovery' }));
    const form = tree.find((el) => el.type === 'form');

    expect(typeof (form?.props as { action?: unknown }).action).toBe('function');
  });

  it('shows the invalid-link card instead of a dead-end button for an unverifiable type', async () => {
    const tree = flatten(await render({ token_hash: 'abc', type: 'bogus' }));

    expect(tree.some((el) => el.type === 'form')).toBe(false);
    const recoveryLink = tree.find((el) => (el.props as { href?: string }).href === '/forgot-password');
    expect(recoveryLink).toBeDefined();
  });

  it('shows the invalid-link card when the token is missing', async () => {
    const tree = flatten(await render({ type: 'recovery' }));

    expect(tree.some((el) => el.type === 'form')).toBe(false);
  });
});
