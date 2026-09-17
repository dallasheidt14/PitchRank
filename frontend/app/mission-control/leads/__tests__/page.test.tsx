import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactElement, ReactNode } from 'react';
import type { MatchBalanceLead, MatchBalanceLeads } from '@/lib/admin/matchbalance-leads';

const fetchMatchBalanceLeads = vi.fn();
vi.mock('@/lib/admin/matchbalance-leads', () => ({
  fetchMatchBalanceLeads: () => fetchMatchBalanceLeads(),
}));

import MatchBalanceLeadsPage from '../page';

/** Flatten a server component's element tree to its visible text and string props. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  const element = node as ReactElement<{ children?: ReactNode }>;
  if (typeof element === 'object' && 'props' in element) {
    return Object.values(element.props ?? {})
      .map((value) =>
        typeof value === 'string' || typeof value === 'number' ? String(value) : textOf(value as ReactNode)
      )
      .join(' ');
  }
  return '';
}

function lead(over: Partial<MatchBalanceLead> = {}): MatchBalanceLead {
  return {
    id: 'lead-1',
    created_at: '2026-09-10T19:00:00Z',
    updated_at: '2026-09-10T19:00:00Z',
    name: 'Pat Director',
    email: 'pat@example.com',
    organization: 'Alamo Soccer Events',
    tournament_name: 'Labor Cup',
    event_dates: 'Oct 3-4',
    team_count: 120,
    bracket_review_date: null,
    event_url: null,
    request_type: 'quote',
    notes: null,
    source_ip_masked: '203.0.113.x',
    status: 'new',
    ...over,
  };
}

async function render(leads: MatchBalanceLead[]): Promise<string> {
  const data: MatchBalanceLeads = { leads, total: leads.length, thisWeek: leads.length, awaitingReply: 1, errors: [] };
  fetchMatchBalanceLeads.mockResolvedValue(data);
  return textOf(await MatchBalanceLeadsPage());
}

beforeEach(() => {
  fetchMatchBalanceLeads.mockReset();
});

describe('MatchBalance Leads page', () => {
  it('shows a bracket review date on its own calendar day, not shifted into Phoenix time', async () => {
    const text = await render([lead({ bracket_review_date: '2026-09-16' })]);

    expect(text).toContain('Sep 16, 2026');
    expect(text).not.toContain('Sep 15, 2026');
  });

  it('encodes a submitted address so a mail client cannot read extra recipients or headers from it', async () => {
    const text = await render([
      lead({ id: 'bcc', email: 'director@example.com?bcc=attacker%40example.net' }),
      lead({ id: 'comma', email: 'director@example.com,attacker@example.net' }),
    ]);

    expect(text).toContain('mailto:director@example.com%3Fbcc%3Dattacker%2540example.net');
    expect(text).toContain('mailto:director%40example.com%2Cattacker@example.net');
    expect(text).not.toContain('mailto:director@example.com?bcc');
  });

  it('keeps an ordinary address readable as mailto:local@domain', async () => {
    const text = await render([lead()]);

    expect(text).toContain('mailto:pat@example.com');
  });

  it('labels the request type the way the form and owner email do', async () => {
    const text = await render([lead({ request_type: 'quote' }), lead({ id: 'lead-2', request_type: 'sample' })]);

    expect(text).toContain('Quote for the whole event');
    expect(text).toContain('Free sample');
  });
});
