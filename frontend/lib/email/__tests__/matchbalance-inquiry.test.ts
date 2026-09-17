import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
}));

vi.mock('../resend', () => ({
  resend: { emails: { send: mockSend } },
}));

import { sendMatchBalanceInquiryAlert, sendMatchBalanceInquiryConfirmation } from '../matchbalance-inquiry';

const baseLead = {
  name: 'Pat Director',
  email: 'pat@example.com',
  organization: 'Alamo Soccer Events',
  tournamentName: 'Labor Cup 2026',
  eventDates: 'Sep 5-7, 2026',
  teamCount: 180,
  bracketReviewDate: '2026-08-20',
  eventUrl: 'https://system.gotsport.com/org_event/events/12345',
  requestType: 'quote' as const,
  notes: 'We run U9-U19.',
};

describe('sendMatchBalanceInquiryAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSend.mockResolvedValue({ data: { id: 'email-id' }, error: null });
  });

  it('sends from matchbalance@mail.pitchrank.io to the owner inbox, replying to the director', async () => {
    await sendMatchBalanceInquiryAlert(baseLead);
    const call = mockSend.mock.calls[0][0];
    expect(call.from).toBe('PitchRank <matchbalance@mail.pitchrank.io>');
    expect(call.to).toBe('pitchrankio@gmail.com');
    expect(call.replyTo).toBe('pat@example.com');
    expect(call.subject).toBe('MatchBalance inquiry: Labor Cup 2026 (quote)');
  });

  it('lists every field and links to the Leads page', async () => {
    await sendMatchBalanceInquiryAlert(baseLead);
    const { html, text } = mockSend.mock.calls[0][0];
    for (const value of [
      'Pat Director',
      'pat@example.com',
      'Alamo Soccer Events',
      'Labor Cup 2026',
      'Sep 5-7, 2026',
      '180',
      '2026-08-20',
      'https://system.gotsport.com/org_event/events/12345',
      'Quote for the whole event',
      'We run U9-U19.',
    ]) {
      expect(html).toContain(value);
      expect(text).toContain(value);
    }
    expect(html).toContain('/mission-control/leads');
    expect(text).toContain('/mission-control/leads');
  });

  it('escapes HTML in every director-supplied field (all five entities)', async () => {
    const dangerous = `<script>alert(1)</script><img onerror=x src=y> & " '`;
    await sendMatchBalanceInquiryAlert({
      ...baseLead,
      name: dangerous,
      email: dangerous,
      organization: dangerous,
      tournamentName: dangerous,
      eventDates: dangerous,
      bracketReviewDate: dangerous,
      eventUrl: dangerous,
      notes: dangerous,
    });
    const html = mockSend.mock.calls[0][0].html;

    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img onerror');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;img onerror=x src=y&gt;');
    expect(html).toContain('&amp;');
    expect(html).toContain('&quot;');
    expect(html).toContain('&#39;');
  });

  it('marks absent optional fields rather than printing null', async () => {
    await sendMatchBalanceInquiryAlert({
      ...baseLead,
      teamCount: null,
      bracketReviewDate: null,
      eventUrl: null,
      notes: null,
    });
    const { html, text } = mockSend.mock.calls[0][0];
    expect(html).not.toContain('null');
    expect(text).not.toContain('null');
  });

  it('returns true on successful send', async () => {
    expect(await sendMatchBalanceInquiryAlert(baseLead)).toBe(true);
  });

  it('returns false when Resend reports an error', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockSend.mockResolvedValue({ data: null, error: { message: 'domain not verified' } });
    expect(await sendMatchBalanceInquiryAlert(baseLead)).toBe(false);
    errorSpy.mockRestore();
  });

  it('returns false instead of throwing when the send rejects', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockSend.mockRejectedValue(new Error('network down'));
    expect(await sendMatchBalanceInquiryAlert(baseLead)).toBe(false);
    errorSpy.mockRestore();
  });
});

describe('sendMatchBalanceInquiryConfirmation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSend.mockResolvedValue({ data: { id: 'email-id' }, error: null });
  });

  it('sends from matchbalance@mail.pitchrank.io to the director', async () => {
    await sendMatchBalanceInquiryConfirmation(baseLead);
    const call = mockSend.mock.calls[0][0];
    expect(call.from).toBe('PitchRank <matchbalance@mail.pitchrank.io>');
    expect(call.to).toBe('pat@example.com');
    expect(call.subject).toBe('We received your MatchBalance request');
    expect(call.replyTo).toBeUndefined();
  });

  it('sets expectations and quotes no price', async () => {
    await sendMatchBalanceInquiryConfirmation(baseLead);
    const { html, text } = mockSend.mock.calls[0][0];
    for (const body of [html, text]) {
      expect(body).toContain('one business day');
      expect(body).toContain('accepted-team list');
      expect(body).toContain('free');
      expect(body).not.toContain('$');
    }
  });

  it('repeats nothing the submitter typed, since the recipient address is unverified', async () => {
    await sendMatchBalanceInquiryConfirmation({
      ...baseLead,
      name: 'Your account renewed for 499 dollars',
      organization: 'Visit evil.example to cancel',
      tournamentName: 'Call 555-0100 now',
      eventDates: 'Urgent notice',
      eventUrl: 'https://evil.example/login',
      notes: 'Reply with your password',
    });
    const { html, text, subject } = mockSend.mock.calls[0][0];
    for (const value of ['renewed for 499', 'evil.example', '555-0100', 'Urgent notice', 'password']) {
      expect(html).not.toContain(value);
      expect(text).not.toContain(value);
      expect(subject).not.toContain(value);
    }
  });

  it('returns false when Resend reports an error', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockSend.mockResolvedValue({ data: null, error: { message: 'bounced' } });
    expect(await sendMatchBalanceInquiryConfirmation(baseLead)).toBe(false);
    errorSpy.mockRestore();
  });
});

describe('without a Resend key', () => {
  it('both senders return false and do not throw', async () => {
    vi.resetModules();
    vi.doMock('../resend', () => ({ resend: null }));
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const local = await import('../matchbalance-inquiry');

    expect(await local.sendMatchBalanceInquiryAlert(baseLead)).toBe(false);
    expect(await local.sendMatchBalanceInquiryConfirmation(baseLead)).toBe(false);
    warnSpy.mockRestore();
  });
});
