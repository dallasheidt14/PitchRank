import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const TEAM_PATH = '/teams/11111111-1111-1111-1111-111111111111';

const { mockPush, mockUser } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockUser: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush, refresh: vi.fn() }) }));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: mockUser(), isLoading: false }) }));
vi.mock('../actions', () => ({ updatePassword: vi.fn().mockResolvedValue({}) }));
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import ResetPasswordPage from '../page';

let container: HTMLDivElement;
let root: Root;

async function type(id: string, value: string) {
  const input = container.querySelector(`#${id}`) as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function setPasswordAndFindButton() {
  await act(async () => {
    root.render(<ResetPasswordPage />);
  });
  await type('password', 'a-long-password');
  await type('confirmPassword', 'a-long-password');
  await act(async () => {
    container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  return container.querySelector('button') as HTMLButtonElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('ResetPasswordPage, once the password is set', () => {
  it('opens the team a new buyer tapped', async () => {
    mockUser.mockReturnValue({ app_metadata: { return_to: TEAM_PATH } });

    const button = await setPasswordAndFindButton();
    expect(button.textContent).toBe('Go to your team');

    await act(async () => button.click());
    expect(mockPush).toHaveBeenCalledWith(TEAM_PATH);
  });

  it.each([
    ['no team was tapped', { app_metadata: {} }],
    ['the stored path is not a team page', { app_metadata: { return_to: '//evil.example' } }],
    ['the account has not loaded', null],
  ])('goes to rankings when %s', async (_name, user) => {
    mockUser.mockReturnValue(user);

    const button = await setPasswordAndFindButton();
    expect(button.textContent).toBe('Go to rankings');

    await act(async () => button.click());
    expect(mockPush).toHaveBeenCalledWith('/rankings');
  });
});
