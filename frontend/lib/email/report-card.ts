import { resend } from './resend';
import { escapeHtml } from './feedback';
import { BASE_URL } from '@/lib/constants';
import { formatPowerScore } from '@/lib/utils';
import {
  PREMIUM_BENEFITS,
  TRIAL_TERMS,
  formatRankMovement,
  reportCardUpgradeUrl,
  reportFooter,
  stateDisplayName,
} from '@/lib/reports/report-card';

export interface ReportCardEmailInput {
  email: string;
  teamId: string;
  teamName: string;
  rankNational: number | null;
  rankState: number | null;
  state: string | null;
  powerScore: number | null;
  topPct: number | null;
  record: string;
  rankChange30d: number | null;
  gamesLabel: string;
  pdfBuffer: Buffer;
}

function buildReportCardHtml({
  teamId,
  teamName,
  rankNational,
  rankState,
  state,
  powerScore,
  topPct,
  record,
  rankChange30d,
  gamesLabel,
}: Omit<ReportCardEmailInput, 'email' | 'pdfBuffer'>): string {
  const rankMovement = formatRankMovement(rankChange30d);
  const rankChangeText =
    rankMovement != null && rankChange30d != null
      ? rankChange30d > 0
        ? `<span style="color: #10B981;">▲ ${rankMovement}</span>`
        : `<span style="color: #EF4444;">▼ ${rankMovement}</span>`
      : '';

  const stateName = stateDisplayName(state);
  const stateRankLine =
    rankState != null && stateName ? `State Rank: <strong>#${rankState}</strong> in ${stateName}<br>` : '';

  const benefitItems = PREMIUM_BENEFITS.map((benefit) => `<li>${benefit}</li>`).join('');

  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Team Report Card</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #0B5345; padding: 16px 24px; border-radius: 8px 8px 0 0;">
    <h1 style="color: #F4D03F; margin: 0; font-size: 22px; letter-spacing: 2px;">PITCHRANK</h1>
  </div>

  <div style="background-color: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
    <p style="margin: 0 0 16px 0; font-size: 16px;">Your team's report card is ready.</p>

    <div style="background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; margin-bottom: 16px;">
      <p style="margin: 0 0 4px 0; font-weight: bold; font-size: 15px;">${escapeHtml(teamName)}</p>
      <p style="margin: 0; font-size: 14px; color: #6B7280;">
        National Rank: <strong>#${rankNational ?? '—'}</strong>${topPct != null ? ` (top ${topPct}% nationally)` : ''}<br>
        ${rankChangeText ? `${rankChangeText}<br>` : ''}
        ${stateRankLine}
        PowerScore: <strong>${formatPowerScore(powerScore)}</strong><br>
        Recent record: <strong>${record}</strong>
      </p>
    </div>

    <p style="font-size: 14px; color: #374151;">The full report card is attached to this email. It has your national and state rank, PowerScore, recent record, 30-day rank change, and your last 5 games with opponents and scores.</p>

    <p style="font-size: 14px; color: #374151;">Over the next few days, I'll send you a few emails about what these numbers mean and how to use them. Rankings are more useful when you know what to look for.</p>

    <p style="font-size: 14px; color: #374151;"><strong>Quick question:</strong> What are you most curious about — how your team compares to others, or where they're trending?</p>

    <p style="font-size: 14px; color: #374151;">Hit reply and let me know.</p>

    <p style="font-size: 14px; color: #374151;">— PitchRank</p>
  </div>

  <div style="margin-top: 20px; padding: 16px; background-color: #0B5345; border-radius: 6px; text-align: center;">
    <p style="color: #F4D03F; margin: 0 0 8px 0; font-size: 14px; font-weight: bold;">Go further with PitchRank+</p>
    <ul style="color: #ffffff; margin: 0 0 12px 0; padding: 0; list-style: none; font-size: 13px;">${benefitItems}</ul>
    <a href="${reportCardUpgradeUrl(teamId, 'email')}" style="display: inline-block; background-color: #F4D03F; color: #0B5345; padding: 10px 24px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 14px;">Start your free 7-day trial</a>
    <p style="color: #cfe3dc; margin: 8px 0 0 0; font-size: 11px;">${TRIAL_TERMS}</p>
  </div>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">

  <p style="color: #9ca3af; font-size: 11px; text-align: center;">
    ${reportFooter(gamesLabel)}<br>
    <a href="${BASE_URL}" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>`;
}

/**
 * Send a report card email with PDF attachment.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - lead capture should succeed even if email fails.
 */
export async function sendReportCardEmail({ email, pdfBuffer, ...card }: ReportCardEmailInput): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping report card email');
    return false;
  }

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <reports@mail.pitchrank.io>',
      to: email,
      subject: "Your team's report card is inside",
      html: buildReportCardHtml(card),
      attachments: [
        {
          filename: `${card.teamName.replace(/[^a-zA-Z0-9 ]/g, '').replace(/\s+/g, '-')}-Report-Card.pdf`,
          content: pdfBuffer,
        },
      ],
    });

    if (error) {
      console.error('Failed to send report card email:', error);
      return false;
    }

    console.log(`Report card email sent to ${email} for team ${card.teamName}`);
    return true;
  } catch (err) {
    console.error('Error sending report card email:', err);
    return false;
  }
}
