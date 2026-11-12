import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
}));

vi.mock('../resend', () => ({
  resend: { emails: { send: mockSend } },
}));

import { sendReportCardEmail, type ReportCardEmailInput } from '../report-card';

const TEAM_ID = 'eddb44d8-310e-4863-901c-513ba477ff8b';

const send = (overrides: Partial<ReportCardEmailInput> = {}) =>
  sendReportCardEmail({
    email: 'parent@example.com',
    teamId: TEAM_ID,
    teamName: 'SCSA Eleven U13B Red',
    rankNational: 20,
    rankState: 1,
    state: 'IN',
    powerScore: 0.48473,
    topPct: 1,
    record: '25-4-1',
    rankChange30d: 293,
    gamesLabel: '1.1M+',
    pdfBuffer: Buffer.from('pdf'),
    ...overrides,
  });

const sentHtml = () => mockSend.mock.calls[0][0].html as string;

describe('sendReportCardEmail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSend.mockResolvedValue({ data: { id: 'email-id' }, error: null });
  });

  it('sends to the requester with the PDF attached', async () => {
    await send();
    const message = mockSend.mock.calls[0][0];
    expect(message.to).toBe('parent@example.com');
    expect(message.attachments).toEqual([
      { filename: 'SCSA-Eleven-U13B-Red-Report-Card.pdf', content: Buffer.from('pdf') },
    ]);
  });

  it('shows PowerScore on the site scale', async () => {
    await send();
    expect(sentHtml()).toContain('PowerScore: <strong>48.47</strong>');
  });

  it('puts the top percent beside the national rank', async () => {
    await send();
    expect(sentHtml()).toContain('National Rank: <strong>#20</strong> (top 1% nationally)');
  });

  it('leaves the top percent out when the cohort could not be counted', async () => {
    await send({ topPct: null });
    expect(sentHtml()).toContain('National Rank: <strong>#20</strong><br>');
    expect(sentHtml()).not.toContain('nationally');
  });

  it('labels the 30-day movement in words', async () => {
    await send();
    expect(sentHtml()).toContain('▲ Up 293 spots in the last 30 days');
  });

  it('shows a drop in red with a down arrow', async () => {
    await send({ rankChange30d: -4 });
    expect(sentHtml()).toContain('<span style="color: #EF4444;">▼ Down 4 spots in the last 30 days</span>');
  });

  it('shows the state rank under the state name, as the PDF does', async () => {
    await send();
    expect(sentHtml()).toContain('State Rank: <strong>#1</strong> in Indiana');
  });

  it('shows a state outside the 50 boards under its code', async () => {
    await send({ state: 'DC' });
    expect(sentHtml()).toContain('State Rank: <strong>#1</strong> in DC');
  });

  it('omits the state rank line for a team with no state, though the fallback RPC still ranks it', async () => {
    await send({ state: null, rankState: 1 });
    expect(sentHtml()).not.toContain('State Rank');
  });

  it('omits the state rank line when there is none', async () => {
    await send({ rankState: null });
    expect(sentHtml()).not.toContain('State Rank');
  });

  it('labels the record as recent, as the PDF does', async () => {
    await send();
    expect(sentHtml()).toContain('Recent record: <strong>25-4-1</strong>');
  });

  it('describes only what the attached PDF contains', async () => {
    await send();
    const html = sentHtml();
    expect(html).toContain('your last 5 games with opponents and scores');
    expect(html).not.toContain('strength profile');
    expect(html).not.toContain('schedule difficulty');
  });

  it('renders markup in a team name as text', async () => {
    await send({ teamName: '<a href="https://evil.example">Win</a> & Co' });
    const html = sentHtml();
    expect(html).toContain('&lt;a href=&quot;https://evil.example&quot;&gt;Win&lt;/a&gt; &amp; Co');
    expect(html).not.toContain('<a href="https://evil.example">');
  });

  it('makes the same offer as the PDF, with the team carried to the upgrade page', async () => {
    await send();
    const html = sentHtml();
    expect(html).toContain(
      `href="https://www.pitchrank.io/upgrade?next=/teams/${TEAM_ID}&utm_source=report-card&utm_medium=email&utm_campaign=free-report-card"`
    );
    expect(html).toContain('<li>Compare your team side by side with any opponent</li>');
    expect(html).toContain('Free for 7 days, then $6.99/month or $69.99/year. Cancel anytime.');
    expect(html).not.toContain('predictive analytics');
  });

  it('counts games from the live figure rather than a fixed claim', async () => {
    await send();
    const html = sentHtml();
    expect(html).toContain('PitchRank · 1.1M+ games analyzed · Rankings update every week');
    expect(html).not.toContain('25,000+ teams');
  });
});
