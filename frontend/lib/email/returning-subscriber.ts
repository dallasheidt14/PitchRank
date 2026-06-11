import { resend } from './resend';

const RETURNING_SUBSCRIBER_HTML = (loginUrl: string) => `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome back to PitchRank</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #10b981; margin: 0;">⚽ PitchRank</h1>
  </div>

  <h2 style="color: #1f2937;">Welcome back!</h2>

  <p>It looks like you already have a PitchRank account with this email address, so we couldn't start a new free trial — trials are for first-time subscribers.</p>

  <p><b>You haven't been charged.</b> To pick up your PitchRank+ subscription again, just log in and choose a monthly or annual plan:</p>

  <div style="text-align: center; margin: 30px 0;">
    <a href="${loginUrl}" style="display: inline-block; background-color: #10b981; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">Log In &amp; Re-Subscribe</a>
  </div>

  <p style="color: #6b7280; font-size: 14px;">Forgot your password? Use the "Forgot password" option on the sign-in page.</p>

  <p style="margin-top: 30px;">See you on the pitch!</p>

  <p style="color: #6b7280; font-size: 14px;">— The PitchRank Team</p>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

  <p style="color: #9ca3af; font-size: 12px; text-align: center;">
    You're receiving this because a checkout was started with your email address.<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>
`;

/**
 * Sent when a returning subscriber starts an anonymous checkout: the trial-only
 * anonymous flow is canceled (no charge) and they're asked to log in, where
 * checkout offers monthly/annual without a trial.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - the cancellation stands even if email fails.
 */
export async function sendReturningSubscriberEmail(email: string): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping returning-subscriber email');
    return false;
  }

  try {
    const loginUrl = `${process.env.NEXT_PUBLIC_SITE_URL}/login?next=/upgrade`;
    const { error } = await resend.emails.send({
      from: 'PitchRank <noreply@mail.pitchrank.io>',
      to: email,
      subject: 'Welcome back — log in to re-subscribe to PitchRank+',
      html: RETURNING_SUBSCRIBER_HTML(loginUrl),
    });

    if (error) {
      console.error('Failed to send returning-subscriber email:', error);
      return false;
    }

    console.log(`Returning-subscriber email sent successfully`);
    return true;
  } catch (err) {
    console.error('Error sending returning-subscriber email:', err);
    return false;
  }
}
