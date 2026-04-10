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
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #10b981; margin: 0;">⚽ PitchRank</h1>
  </div>

  <h2 style="color: #1f2937;">Welcome to PitchRank+!</h2>

  <p>Your premium subscription is now active. You have full access to team detail pages, AI insights, comparisons, watchlist, and more.</p>

  <p>To log in and access your account, set your password using the link below:</p>

  <div style="text-align: center; margin: 30px 0;">
    <a href="${setupUrl}" style="display: inline-block; background-color: #10b981; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;">Set Your Password</a>
  </div>

  <p style="color: #6b7280; font-size: 14px;">This link expires in 24 hours. If it expires, you can use the "Forgot password" option on the sign-in page.</p>

  <p style="margin-top: 30px;">See you on the pitch!</p>

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
