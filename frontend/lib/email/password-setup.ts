import { resend } from './resend';

const PASSWORD_SETUP_HTML = (setupUrl: string) => `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to PitchRank+</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 32px;">
    <img src="https://pitchrank.io/logos/icon-512.png" width="56" height="56" alt="PitchRank" style="display: inline-block; border-radius: 12px;">
    <h1 style="color: #052E27; font-size: 28px; margin: 12px 0 0;">PitchRank</h1>
    <p style="color: #666; font-size: 14px; margin: 6px 0 0;">Youth Soccer Rankings</p>
  </div>

  <h2 style="color: #1a1a1a; font-size: 20px;">Welcome to PitchRank+!</h2>

  <p style="color: #444;">Your PitchRank+ subscription is now active. You have full access to team detail pages, AI insights, head-to-head comparisons, your watchlist, and more.</p>

  <p style="color: #444;">To log in, set your password using the button below:</p>

  <div style="text-align: center; margin: 32px 0;">
    <a href="${setupUrl}" style="display: inline-block; background-color: #052E27; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 16px;">Set Your Password</a>
  </div>

  <p style="color: #6b7280; font-size: 14px;">This link works on any device and expires in 24 hours. If it expires, use the "Forgot password" option on the sign-in page.</p>

  <p style="margin-top: 30px; color: #444;">See you on the pitch!</p>

  <p style="color: #6b7280; font-size: 14px;">— The PitchRank Team</p>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

  <p style="color: #9ca3af; font-size: 12px; text-align: center;">
    You're receiving this because you subscribed to PitchRank+.<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>
`;

/**
 * Send a password-setup email to a new subscriber who checked out anonymously.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - subscription should activate even if email fails.
 */
export async function sendPasswordSetupEmail(email: string, setupUrl: string): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping password setup email');
    return false;
  }

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <noreply@mail.pitchrank.io>',
      to: email,
      subject: 'Welcome to PitchRank+ — Set Your Password',
      html: PASSWORD_SETUP_HTML(setupUrl),
    });

    if (error) {
      console.error('Failed to send password setup email:', error);
      return false;
    }

    console.log(`Password setup email sent successfully`);
    return true;
  } catch (err) {
    console.error('Error sending password setup email:', err);
    return false;
  }
}
