import { resend } from './resend';

const DUPLICATE_PURCHASE_HTML = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>You already have PitchRank+ — we'll refund this purchase</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #10b981; margin: 0;">⚽ PitchRank</h1>
  </div>

  <h2 style="color: #1f2937;">You already have PitchRank+</h2>

  <p>Thanks for your purchase. Your email address already has a PitchRank+ subscription, so you don't need a second one.</p>

  <p><b>We'll refund this purchase within one business day.</b> Nothing else changes: your existing subscription and your access stay exactly as they are.</p>

  <p>If you meant to change your plan, or you have any questions, just reply to this email.</p>

  <p style="margin-top: 30px;">See you on the pitch!</p>

  <p style="color: #6b7280; font-size: 14px;">— The PitchRank Team</p>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

  <p style="color: #9ca3af; font-size: 12px; text-align: center;">
    You're receiving this because a second PitchRank+ purchase was made with your email address.<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>
`;

/**
 * Sent when someone who already holds Premium completes another paid checkout, almost always while
 * signed out. The webhook leaves the purchase in place and the owner refunds it by hand, so this
 * tells the buyer a refund is coming and that their existing subscription is untouched.
 * Returns true if sent successfully, false otherwise. Errors are logged but not thrown.
 */
export async function sendDuplicatePurchaseEmail(email: string): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping duplicate-purchase email');
    return false;
  }

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <noreply@mail.pitchrank.io>',
      to: email,
      subject: "You already have PitchRank+ — we'll refund this purchase",
      html: DUPLICATE_PURCHASE_HTML,
    });

    if (error) {
      console.error('Failed to send duplicate-purchase email:', error);
      return false;
    }

    console.log(`Duplicate-purchase email sent successfully`);
    return true;
  } catch (err) {
    console.error('Error sending duplicate-purchase email:', err);
    return false;
  }
}
