import { resend } from './resend';

function buildReportCardHtml(
  teamName: string,
  rankNational: number | null,
  rankState: number | null,
  state: string | null,
  powerScore: number | null,
  percentile: number,
  record: string,
  rankChange30d: number | null
): string {
  const rankChangeText =
    rankChange30d != null && rankChange30d !== 0
      ? rankChange30d > 0
        ? `<span style="color: #10B981;">▲${rankChange30d} this month</span>`
        : `<span style="color: #EF4444;">▼${Math.abs(rankChange30d)} this month</span>`
      : '';

  const stateRankLine =
    rankState != null && state ? `State Rank: <strong>#${rankState}</strong> in ${state.toUpperCase()}<br>` : '';

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
      <p style="margin: 0 0 4px 0; font-weight: bold; font-size: 15px;">${teamName}</p>
      <p style="margin: 0; font-size: 14px; color: #6B7280;">
        National Rank: <strong>#${rankNational ?? '—'}</strong> ${rankChangeText}<br>
        ${stateRankLine}
        PowerScore: <strong>${powerScore != null ? powerScore.toFixed(2) : '—'}</strong> (top ${percentile}% nationally)<br>
        Record: <strong>${record}</strong>
      </p>
    </div>

    <p style="font-size: 14px; color: #374151;">The full report card has your strength profile, recent results, and schedule difficulty breakdown. It's attached to this email.</p>

    <p style="font-size: 14px; color: #374151;">Over the next few days, I'll send you a few emails about what these numbers mean and how to use them. Rankings are more useful when you know what to look for.</p>

    <p style="font-size: 14px; color: #374151;"><strong>Quick question:</strong> What are you most curious about — how your team compares to others, or where they're trending?</p>

    <p style="font-size: 14px; color: #374151;">Hit reply and let me know.</p>

    <p style="font-size: 14px; color: #374151;">— PitchRank</p>
  </div>

  <div style="margin-top: 20px; padding: 16px; background-color: #0B5345; border-radius: 6px; text-align: center;">
    <p style="color: #ffffff; margin: 0 0 8px 0; font-size: 13px;">Want the full picture? Head-to-head comparisons, predictive analytics, and weekly alerts.</p>
    <a href="https://pitchrank.io/upgrade" style="display: inline-block; background-color: #F4D03F; color: #0B5345; padding: 10px 24px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 14px;">Start Your Free Trial</a>
    <p style="color: #1a6b5c; margin: 8px 0 0 0; font-size: 11px;">7 days free · $6.99/mo · Cancel anytime</p>
  </div>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">

  <p style="color: #9ca3af; font-size: 11px; text-align: center;">
    Rankings powered by PitchRank's 13-layer algorithm · 25,000+ teams · Updated weekly<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>`;
}

/**
 * Send a report card email with PDF attachment.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - lead capture should succeed even if email fails.
 */
export async function sendReportCardEmail(
  email: string,
  teamName: string,
  rankNational: number | null,
  rankState: number | null,
  state: string | null,
  powerScore: number | null,
  percentile: number,
  record: string,
  rankChange30d: number | null,
  pdfBuffer: Buffer
): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping report card email');
    return false;
  }

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <reports@mail.pitchrank.io>',
      to: email,
      subject: "Your team's report card is inside",
      html: buildReportCardHtml(
        teamName,
        rankNational,
        rankState,
        state,
        powerScore,
        percentile,
        record,
        rankChange30d
      ),
      attachments: [
        {
          filename: `${teamName.replace(/[^a-zA-Z0-9 ]/g, '').replace(/\s+/g, '-')}-Report-Card.pdf`,
          content: pdfBuffer,
        },
      ],
    });

    if (error) {
      console.error('Failed to send report card email:', error);
      return false;
    }

    console.log(`Report card email sent to ${email} for team ${teamName}`);
    return true;
  } catch (err) {
    console.error('Error sending report card email:', err);
    return false;
  }
}
