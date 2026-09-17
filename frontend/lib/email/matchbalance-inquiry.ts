import type { CreateEmailOptions } from 'resend';
import { resend } from './resend';
import { BASE_URL } from '@/lib/constants';
import { MATCHBALANCE_REQUEST_LABELS, type MatchBalanceRequestType } from '@/lib/matchbalance';

export interface MatchBalanceLeadEmail {
  name: string;
  email: string;
  organization: string;
  tournamentName: string;
  eventDates: string;
  teamCount: number | null;
  bracketReviewDate: string | null;
  eventUrl: string | null;
  requestType: MatchBalanceRequestType;
  notes: string | null;
}

const FROM = 'PitchRank <matchbalance@mail.pitchrank.io>';

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function leadFields(lead: MatchBalanceLeadEmail): Array<[string, string]> {
  return [
    ['Name', lead.name],
    ['Email', lead.email],
    ['Organization', lead.organization],
    ['Tournament', lead.tournamentName],
    ['Event dates', lead.eventDates],
    ['Teams', lead.teamCount === null ? '(not given)' : String(lead.teamCount)],
    ['Bracket review', lead.bracketReviewDate ?? '(not given)'],
    ['Event link', lead.eventUrl ?? '(not given)'],
    ['Request', MATCHBALANCE_REQUEST_LABELS[lead.requestType]],
  ];
}

function buildAlertHtml(lead: MatchBalanceLeadEmail): string {
  const rows = leadFields(lead)
    .map(
      ([label, value]) =>
        `<tr><td style="padding: 4px 12px 4px 0; color:#6b7280; vertical-align: top;">${label}:</td><td>${escapeHtml(value)}</td></tr>`
    )
    .join('\n      ');
  const leadsUrl = `${BASE_URL}/mission-control/leads`;

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #0B5345; padding: 16px 24px; border-radius: 8px 8px 0 0;">
    <h1 style="color: #F4D03F; margin: 0; font-size: 20px; letter-spacing: 2px;">MATCHBALANCE INQUIRY</h1>
  </div>
  <div style="background-color: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
    <table style="width:100%; font-size: 14px; margin-bottom: 16px;">
      ${rows}
    </table>
    <div style="background:#fff; border:1px solid #e5e7eb; border-radius:6px; padding:16px; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.5;">${escapeHtml(lead.notes ?? '(no notes)')}</div>
    <p style="font-size: 13px; margin-top: 16px;">Reply to this email to answer the director directly. All inquiries: <a href="${leadsUrl}" style="color: #0B5345;">${leadsUrl}</a></p>
  </div>
</body></html>`;
}

function buildAlertText(lead: MatchBalanceLeadEmail): string {
  return [
    `MATCHBALANCE INQUIRY`,
    ``,
    ...leadFields(lead).map(([label, value]) => `${`${label}:`.padEnd(16)}${value}`),
    ``,
    `--- Notes ---`,
    lead.notes ?? '(no notes)',
    `-------------`,
    ``,
    `Reply to this email to answer the director directly.`,
    `All inquiries: ${BASE_URL}/mission-control/leads`,
  ].join('\n');
}

// The recipient address is unverified, so nothing the submitter typed goes in this
// email: echoing a name or tournament would let anyone send PitchRank-branded text to
// any inbox.
const CONFIRMATION_HTML = `<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #0B5345; padding: 16px 24px; border-radius: 8px 8px 0 0;">
    <h1 style="color: #F4D03F; margin: 0; font-size: 20px; letter-spacing: 2px;">MATCHBALANCE</h1>
  </div>
  <div style="padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
    <p>We received your MatchBalance request. We&#39;ll reply within one business day.</p>
    <p>If you already have the accepted-team list, reply to this email with it attached, or send us the event link. That is everything we need to start.</p>
    <p>Your first sample is free: one age group and gender from your tournament, so you can see the sheet with your own teams before deciding anything.</p>
    <p style="margin-top: 30px; color: #6b7280; font-size: 14px;">— The PitchRank Team</p>
  </div>
</body></html>`;

const CONFIRMATION_TEXT = [
  `We received your MatchBalance request. We'll reply within one business day.`,
  ``,
  `If you already have the accepted-team list, reply to this email with it attached, or send us the event link. That is everything we need to start.`,
  ``,
  `Your first sample is free: one age group and gender from your tournament, so you can see the sheet with your own teams before deciding anything.`,
  ``,
  `— The PitchRank Team`,
].join('\n');

async function send(kind: 'alert' | 'confirmation', email: CreateEmailOptions): Promise<boolean> {
  if (!resend) {
    console.warn(`Resend not configured - skipping MatchBalance inquiry ${kind}`);
    return false;
  }

  try {
    const { error } = await resend.emails.send(email);

    if (error) {
      console.error(`Failed to send MatchBalance inquiry ${kind}:`, error);
      return false;
    }

    return true;
  } catch (err) {
    console.error(`Error sending MatchBalance inquiry ${kind}:`, err);
    return false;
  }
}

/**
 * Returns true on success, false on failure (including when Resend is not
 * configured). Does not throw.
 */
export async function sendMatchBalanceInquiryAlert(lead: MatchBalanceLeadEmail): Promise<boolean> {
  return send('alert', {
    from: FROM,
    to: 'pitchrankio@gmail.com',
    subject: `MatchBalance inquiry: ${lead.tournamentName} (${lead.requestType})`,
    html: buildAlertHtml(lead),
    text: buildAlertText(lead),
    replyTo: lead.email,
  });
}

/**
 * Names no event price: each event is quoted individually. Returns true on success,
 * false on failure. Does not throw.
 */
export async function sendMatchBalanceInquiryConfirmation(lead: MatchBalanceLeadEmail): Promise<boolean> {
  return send('confirmation', {
    from: FROM,
    to: lead.email,
    subject: 'We received your MatchBalance request',
    html: CONFIRMATION_HTML,
    text: CONFIRMATION_TEXT,
  });
}
