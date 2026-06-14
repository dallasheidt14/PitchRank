import { resend } from './resend';

export type FeedbackCategory = 'cant-find-team' | 'rankings-wrong' | 'wrong-games' | 'bug' | 'other';

export const CATEGORY_LABELS: Record<FeedbackCategory, string> = {
  'cant-find-team': "Can't find my team",
  'rankings-wrong': 'Rankings look wrong',
  'wrong-games': 'Wrong games attached',
  bug: 'Bug or broken page',
  other: 'Other',
};

export type FeedbackIdentity =
  | { kind: 'signed-in'; userId: string; email: string }
  | { kind: 'anonymous'; email?: string };

export interface FeedbackContext {
  pathname: string;
  referrer?: string;
  userAgent?: string;
  viewport?: { w: number; h: number };
  submittedAt: string;
}

export interface SendFeedbackEmailInput {
  category: FeedbackCategory;
  message: string;
  identity: FeedbackIdentity;
  context: FeedbackContext;
  ipMasked: string;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function truncateForSubject(s: string, max = 60): string {
  const oneLine = s.replace(/\s+/g, ' ').trim();
  return oneLine.length <= max ? oneLine : oneLine.slice(0, max) + '…';
}

function buildSubject(category: FeedbackCategory, message: string): string {
  return `[PitchRank Feedback] ${CATEGORY_LABELS[category]} — ${truncateForSubject(message)}`;
}

function buildFromLine(identity: FeedbackIdentity): string {
  if (identity.kind === 'signed-in') {
    return `${identity.email} (signed-in user, id=${identity.userId})`;
  }
  return identity.email ? `${identity.email} (anonymous)` : 'anonymous (no email provided)';
}

function buildHtml(input: SendFeedbackEmailInput): string {
  const { category, message, identity, context, ipMasked } = input;
  const safeMessage = escapeHtml(message);
  const safeFrom = escapeHtml(buildFromLine(identity));
  const safePath = escapeHtml(context.pathname);
  const safeRef = escapeHtml(context.referrer ?? '(none)');
  const safeUa = escapeHtml(context.userAgent ?? '(none)');
  const vp = context.viewport ? `${context.viewport.w}×${context.viewport.h}` : '(unknown)';

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #0B5345; padding: 16px 24px; border-radius: 8px 8px 0 0;">
    <h1 style="color: #F4D03F; margin: 0; font-size: 20px; letter-spacing: 2px;">PITCHRANK FEEDBACK</h1>
  </div>
  <div style="background-color: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
    <table style="width:100%; font-size: 14px; margin-bottom: 16px;">
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Category:</td><td><strong>${CATEGORY_LABELS[category]}</strong></td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">From:</td><td>${safeFrom}</td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Page:</td><td><code>${safePath}</code></td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Submitted:</td><td>${escapeHtml(context.submittedAt)}</td></tr>
    </table>
    <div style="background:#fff; border:1px solid #e5e7eb; border-radius:6px; padding:16px; font-family: ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.5;">${safeMessage}</div>
    <hr style="border:none; border-top:1px solid #e5e7eb; margin: 24px 0;">
    <table style="width:100%; font-size: 12px; color:#9ca3af;">
      <tr><td style="padding: 2px 12px 2px 0;">Referrer:</td><td>${safeRef}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">Viewport:</td><td>${vp}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">User-Agent:</td><td>${safeUa}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">IP:</td><td><code>${escapeHtml(ipMasked)}</code></td></tr>
    </table>
  </div>
</body></html>`;
}

function buildText(input: SendFeedbackEmailInput): string {
  const { category, message, identity, context, ipMasked } = input;
  return [
    `PITCHRANK FEEDBACK`,
    ``,
    `Category:  ${CATEGORY_LABELS[category]}`,
    `From:      ${buildFromLine(identity)}`,
    `Page:      ${context.pathname}`,
    `Submitted: ${context.submittedAt}`,
    ``,
    `--- Message ---`,
    message,
    `---------------`,
    ``,
    `Referrer:   ${context.referrer ?? '(none)'}`,
    `Viewport:   ${context.viewport ? `${context.viewport.w}x${context.viewport.h}` : '(unknown)'}`,
    `User-Agent: ${context.userAgent ?? '(none)'}`,
    `IP:         ${ipMasked}`,
  ].join('\n');
}

/**
 * Send a feedback report email. Returns true on success, false on failure
 * (including when Resend is not configured). Does not throw.
 */
export async function sendFeedbackEmail(input: SendFeedbackEmailInput): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping feedback email');
    return false;
  }

  const replyTo = input.identity.email;

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <feedback@mail.pitchrank.io>',
      to: 'pitchrankio@gmail.com',
      subject: buildSubject(input.category, input.message),
      html: buildHtml(input),
      text: buildText(input),
      ...(replyTo ? { replyTo } : {}),
    });

    if (error) {
      console.error('Failed to send feedback email:', error);
      return false;
    }

    return true;
  } catch (err) {
    console.error('Error sending feedback email:', err);
    return false;
  }
}
