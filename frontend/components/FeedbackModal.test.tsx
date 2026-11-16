import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('next/navigation', () => ({ usePathname: () => '/' }));
const { userState } = vi.hoisted(() => ({
  userState: { user: null as { id: string } | null, isLoading: false },
}));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: userState.user, isLoading: userState.isLoading }) }));

import { FeedbackModal } from './FeedbackModal';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  userState.user = null;
  userState.isLoading = false;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function renderOpen(props: Partial<React.ComponentProps<typeof FeedbackModal>> = {}, { strict = false } = {}) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const modal = <FeedbackModal open onOpenChange={vi.fn()} {...props} />;
  await act(async () => root!.render(strict ? <React.StrictMode>{modal}</React.StrictMode> : modal));
}

function sendButton() {
  return document.querySelector<HTMLButtonElement>('[data-testid="feedback-submit"]')!;
}

describe('FeedbackModal', () => {
  it('starts on the category and message it is opened with, ready to send', async () => {
    await renderOpen({ initialCategory: 'cant-find-team', initialMessage: 'Searched for "phoneix rising". ' });

    expect(document.querySelector<HTMLTextAreaElement>('#feedback-message')!.value).toBe(
      'Searched for "phoneix rising". '
    );
    expect(document.querySelector('[data-testid="feedback-category"]')!.textContent).toBe("I can't find my team");
    expect(sendButton().disabled).toBe(false);
  });

  // useUser sets the user before it stops loading, so a signed-in user is never shown the box.
  it('never asks a signed-in user for an email, while loading or after', async () => {
    userState.isLoading = true;
    await renderOpen();
    expect(document.querySelector('#feedback-email')).toBeNull();

    userState.user = { id: 'user-1' };
    userState.isLoading = false;
    await act(async () => root!.render(<FeedbackModal open onOpenChange={vi.fn()} />));
    expect(document.querySelector('#feedback-email')).toBeNull();
  });

  it('asks a signed-out visitor for an email only once the sign-in check has finished', async () => {
    userState.isLoading = true;
    await renderOpen();
    expect(document.querySelector('#feedback-email')).toBeNull();

    userState.isLoading = false;
    await act(async () => root!.render(<FeedbackModal open onOpenChange={vi.fn()} />));
    expect(document.querySelector('#feedback-email')).not.toBeNull();
  });

  it('starts empty when opened from the feedback button', async () => {
    await renderOpen();

    expect(document.querySelector<HTMLTextAreaElement>('#feedback-message')!.value).toBe('');
    expect(document.querySelector('[data-testid="feedback-category"]')!.textContent).toBe('Select one…');
    expect(sendButton().disabled).toBe(true);
  });

  // Run under StrictMode, whose remount must not leave the report withdrawn.
  it('holds a report sent at once until the dwell window has passed, then sends it', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', fetchMock);
    await renderOpen(
      { initialCategory: 'cant-find-team', initialMessage: 'Searched for "phoneix rising". ' },
      { strict: true }
    );
    vi.useFakeTimers({ now: Date.now() });

    await act(async () => {
      sendButton()
        .closest('form')!
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { context } = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(Date.parse(context.submittedAt) - Date.parse(context.openedAt)).toBeGreaterThanOrEqual(2000);
  });

  it('withdraws a report whose form is closed during the wait, and sends only the one from the reopened form', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', fetchMock);
    const props = { initialCategory: 'cant-find-team' as const, initialMessage: 'Searched for "phoneix rising". ' };
    await renderOpen(props);
    vi.useFakeTimers({ now: Date.now() });
    const submit = () =>
      act(async () => {
        sendButton()
          .closest('form')!
          .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      });

    await submit();
    await act(async () => root!.render(<FeedbackModal open={false} onOpenChange={vi.fn()} {...props} />));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => root!.render(<FeedbackModal open onOpenChange={vi.fn()} {...props} />));
    await submit();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
