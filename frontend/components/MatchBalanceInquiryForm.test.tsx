import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MatchBalanceInquiryForm } from './MatchBalanceInquiryForm';

const OPENED = '2026-09-17T16:00:00.000Z';
const SUBMITTED = '2026-09-17T16:00:05.000Z';

let root: Root;
let container: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

function respond(status: number, body: unknown) {
  fetchMock.mockResolvedValue({ status, ok: status >= 200 && status < 300, json: async () => body });
}

// Inputs are controlled, so set the value through the native setter React tracks
// and dispatch the 'input' event React maps onChange to.
async function fill(selector: string, value: string) {
  const field = container.querySelector(selector) as HTMLInputElement | HTMLTextAreaElement;
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setValue = Object.getOwnPropertyDescriptor(prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function fillRequired() {
  await fill('#mb-name', '  Pat Director  ');
  await fill('#mb-email', 'pat@example.com');
  await fill('#mb-organization', 'Alamo Soccer Events');
  await fill('#mb-tournament', 'Labor Cup 2026');
  await fill('#mb-dates', 'Sep 5-7, 2026');
}

async function submit() {
  vi.setSystemTime(new Date(SUBMITTED));
  const form = container.querySelector('form') as HTMLFormElement;
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
}

function sentBody(): Record<string, unknown> {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe('/api/matchbalance-inquiry');
  expect(init.method).toBe('POST');
  expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
  return JSON.parse(init.body as string);
}

beforeEach(async () => {
  // Only Date is faked, so openedAt is pinned to render time while React's own
  // scheduling keeps real timers.
  vi.useFakeTimers({ now: new Date(OPENED), toFake: ['Date'] });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(MatchBalanceInquiryForm));
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('MatchBalanceInquiryForm', () => {
  it('sends every field the route reads, with a numeric team count and the time the form opened', async () => {
    respond(201, { ok: true });
    await fillRequired();
    await fill('#mb-team-count', '180');
    await fill('#mb-bracket-review', '2026-08-20');
    await fill('#mb-event-url', 'https://example.com/cup');
    await fill('#mb-notes', 'We run U9-U19.');
    await act(async () => {
      (container.querySelector('input[name="requestType"][value="quote"]') as HTMLInputElement).click();
    });

    await submit();

    expect(sentBody()).toEqual({
      name: 'Pat Director',
      email: 'pat@example.com',
      organization: 'Alamo Soccer Events',
      tournamentName: 'Labor Cup 2026',
      eventDates: 'Sep 5-7, 2026',
      teamCount: 180,
      bracketReviewDate: '2026-08-20',
      eventUrl: 'https://example.com/cup',
      requestType: 'quote',
      notes: 'We run U9-U19.',
      openedAt: OPENED,
      submittedAt: SUBMITTED,
    });
    expect(container.textContent).toContain('Request received');
  });

  it('leaves blank optional fields and the empty honeypot out of the body', async () => {
    respond(201, { ok: true });
    await fillRequired();

    await submit();

    expect(sentBody()).toEqual({
      name: 'Pat Director',
      email: 'pat@example.com',
      organization: 'Alamo Soccer Events',
      tournamentName: 'Labor Cup 2026',
      eventDates: 'Sep 5-7, 2026',
      requestType: 'sample',
      openedAt: OPENED,
      submittedAt: SUBMITTED,
    });
  });

  it('tells the director to wait an hour when the route rate-limits them, and keeps their entries', async () => {
    respond(429, { error: 'rate_limited' });
    await fillRequired();

    await submit();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Too many requests, try again in an hour.');
    expect((container.querySelector('#mb-tournament') as HTMLInputElement).value).toBe('Labor Cup 2026');
  });

  it('shows the route error message and keeps the form filled', async () => {
    respond(500, { error: 'Could not save your request. Please email pitchrankio@gmail.com instead.' });
    await fillRequired();

    await submit();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      'Could not save your request. Please email pitchrankio@gmail.com instead.'
    );
    expect(container.textContent).not.toContain('Request received');
  });

  it('hides the honeypot from screen readers', () => {
    const honeypot = container.querySelector('#mb-website') as HTMLInputElement;

    expect(honeypot.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(honeypot.tabIndex).toBe(-1);
  });
});
