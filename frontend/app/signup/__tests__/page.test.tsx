// Signup calls supabase.auth.signUp from the browser, so this page's check is what holds new
// passwords to the shared minimum.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockSignUp } = vi.hoisted(() => ({ mockSignUp: vi.fn() }));

vi.mock('@/lib/supabase/client', () => ({
  createClientSupabase: () => ({ auth: { signUp: mockSignUp, resend: vi.fn() } }),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import SignupPage from '../page';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  mockSignUp.mockReset();
});

async function renderPage() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(SignupPage)));
}

async function type(id: string, value: string) {
  const input = container!.querySelector(`#${id}`) as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submitWith(password: string) {
  await renderPage();
  await type('email', 'parent@example.com');
  await type('password', password);
  await type('confirmPassword', password);
  // Dispatching submit skips native minlength validation, the way an old browser or a script would.
  await act(async () => {
    container!.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
}

describe('SignupPage password minimum', () => {
  it('refuses a 7-character password before calling Supabase', async () => {
    await submitWith('abcdefg');

    expect(mockSignUp).not.toHaveBeenCalled();
    expect(container!.querySelector('[data-testid="signup-error"]')!.textContent).toContain('at least 8 characters');
  });

  it('sends an 8-character password on to Supabase', async () => {
    mockSignUp.mockResolvedValue({ data: { user: { identities: [{}] }, session: null }, error: null });

    await submitWith('abcdefgh');

    expect(mockSignUp).toHaveBeenCalledWith(expect.objectContaining({ password: 'abcdefgh' }));
  });

  it('asks the browser for 8 characters in both password fields', async () => {
    await renderPage();

    expect(container!.querySelector('#password')!.getAttribute('minlength')).toBe('8');
    expect(container!.querySelector('#confirmPassword')!.getAttribute('minlength')).toBe('8');
  });
});
