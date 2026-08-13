import { resend } from './resend';

const DUPLICATE_SUBSCRIPTION_HTML = (passwordUrl: string) => `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>You're already subscribed to PitchRank+</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #10b981; margin: 0;">⚽ PitchRank</h1>
  </div>

  <h2 style="color: #1f2937;">You're already subscribed</h2>

  <p>You started a PitchRank+ subscription a few minutes ago, so we didn't start a second one.</p>

  <p><b>You have not been charged twice.</b> Your original subscription is active and unchanged.</p>

  <p>If you couldn't get in, it's because your password isn't set yet — that's the only step left:</p>

  <div style="text-align: center; margin: 30px 0;">
    <a href="${passwordUrl}" style="display: inline-block; background-color: #10b981; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">Set Your Password</a>
  </div>

  <p style="color: #6b7280; font-size: 14px;">We also emailed you a set-password link a few minutes ago, subject "Welcome to PitchRank+ — Set Your Password". Either link works.</p>

  <p style="margin-top: 30px;">See you on the pitch!</p>

  <p style="color: #6b7280; font-size: 14px;">— The PitchRank Team</p>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

  <p style="color: #9ca3af; font-size: 12px; text-align: center;">
    You're receiving this because a second checkout was started with your email address.<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>
`;

/**
 * Sent when someone who already has a live subscription starts another anonymous
 * checkout — almost always because anonymous checkout leaves them logged out and
 * they assume the first payment failed. The duplicate is canceled (no charge) and
 * they're pointed at password setup, the step that actually unblocks them.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - the cancellation stands even if email fails.
 */
export async function sendDuplicateSubscriptionEmail(email: string): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping duplicate-subscription email');
    return false;
  }

  try {
    const passwordUrl = `${process.env.NEXT_PUBLIC_SITE_URL}/forgot-password`;
    const { error } = await resend.emails.send({
      from: 'PitchRank <noreply@mail.pitchrank.io>',
      to: email,
      subject: "You're already subscribed — no second charge",
      html: DUPLICATE_SUBSCRIPTION_HTML(passwordUrl),
    });

    if (error) {
      console.error('Failed to send duplicate-subscription email:', error);
      return false;
    }

    console.log(`Duplicate-subscription email sent successfully`);
    return true;
  } catch (err) {
    console.error('Error sending duplicate-subscription email:', err);
    return false;
  }
}
