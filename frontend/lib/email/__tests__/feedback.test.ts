import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
}));

vi.mock('../resend', () => ({
  resend: { emails: { send: mockSend } },
}));

import { sendFeedbackEmail, CATEGORY_LABELS } from '../feedback';

const baseInput = {
  category: 'rankings-wrong' as const,
  message: 'My U14 team is ranked too low',
  identity: { kind: 'signed-in' as const, userId: 'user-123', email: 'coach@example.com' },
  context: {
    pathname: '/teams/abc-u14-boys',
    referrer: 'https://google.com',
    userAgent: 'Mozilla/5.0',
    viewport: { w: 1280, h: 800 },
    submittedAt: '2026-05-06T18:42:00.000Z',
  },
  ipMasked: '192.168.1.x',
};

describe('sendFeedbackEmail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSend.mockResolvedValue({ data: { id: 'email-id' }, error: null });
  });

  it('sends from feedback@mail.pitchrank.io to pitchrankio@gmail.com', async () => {
    await sendFeedbackEmail(baseInput);
    const call = mockSend.mock.calls[0][0];
    expect(call.from).toBe('PitchRank <feedback@mail.pitchrank.io>');
    expect(call.to).toBe('pitchrankio@gmail.com');
  });

  it('subject contains category label and message snippet', async () => {
    await sendFeedbackEmail(baseInput);
    const subject = mockSend.mock.calls[0][0].subject;
    expect(subject).toContain('[PitchRank Feedback]');
    expect(subject).toContain(CATEGORY_LABELS['rankings-wrong']);
    expect(subject).toContain('My U14 team is ranked too low');
  });

  it('truncates long messages in subject to 60 chars + ellipsis', async () => {
    const longMsg = 'a'.repeat(200);
    await sendFeedbackEmail({ ...baseInput, message: longMsg });
    const subject = mockSend.mock.calls[0][0].subject;

    // Subject must end with the ellipsis when truncation occurs.
    expect(subject.endsWith('…')).toBe(true);
    // Exactly 60 'a's followed by the ellipsis, not 59 and not 61.
    expect(subject).toContain(`${CATEGORY_LABELS['rankings-wrong']} — ${'a'.repeat(60)}…`);
    expect(subject).not.toContain('a'.repeat(61) + '…');
  });

  it('escapes HTML in the user message body (all five entities)', async () => {
    const dangerous = `<script>alert(1)</script><img onerror=x src=y> & " '`;
    await sendFeedbackEmail({ ...baseInput, message: dangerous });
    const html = mockSend.mock.calls[0][0].html;

    // None of the raw injection vectors should appear.
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img onerror');

    // All five entity escapes should be present.
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;img onerror=x src=y&gt;');
    expect(html).toContain('&amp;');
    expect(html).toContain('&quot;');
    expect(html).toContain('&#39;');
  });

  it('sets replyTo to user.email for signed-in submitters', async () => {
    await sendFeedbackEmail(baseInput);
    expect(mockSend.mock.calls[0][0].replyTo).toBe('coach@example.com');
  });

  it('sets replyTo to anonymous email when provided', async () => {
    await sendFeedbackEmail({
      ...baseInput,
      identity: { kind: 'anonymous', email: 'anon@example.com' },
    });
    expect(mockSend.mock.calls[0][0].replyTo).toBe('anon@example.com');
  });

  it('omits replyTo when anonymous with no email', async () => {
    await sendFeedbackEmail({
      ...baseInput,
      identity: { kind: 'anonymous' },
    });
    expect(mockSend.mock.calls[0][0].replyTo).toBeUndefined();
  });

  it('returns false and does not throw when resend is null', async () => {
    vi.resetModules();
    vi.doMock('../resend', () => ({ resend: null }));
    const { sendFeedbackEmail: localSend } = await import('../feedback');
    const result = await localSend(baseInput);
    expect(result).toBe(false);
  });

  it('returns true on successful send', async () => {
    const result = await sendFeedbackEmail(baseInput);
    expect(result).toBe(true);
  });
});
