import { resend } from './resend';

const WELCOME_EMAIL_HTML = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to PitchRank!</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #10b981; margin: 0;">⚽ PitchRank</h1>
  </div>
  
  <h2 style="color: #1f2937;">Welcome to the PitchRank Newsletter!</h2>
  
  <p>Thanks for subscribing! You're now part of a community that's passionate about youth soccer.</p>
  
  <p>Here's what you can expect:</p>
  
  <ul style="padding-left: 20px;">
    <li><strong>Ranking Updates</strong> – Stay informed when rankings are refreshed</li>
    <li><strong>Youth Soccer Insights</strong> – Analysis and trends from the youth soccer world</li>
    <li><strong>New Features</strong> – Be the first to know about PitchRank updates</li>
  </ul>
  
  <p>In the meantime, check out our <a href="https://pitchrank.io/rankings" style="color: #10b981;">latest rankings</a> or explore our <a href="https://pitchrank.io/blog" style="color: #10b981;">blog</a> for insights.</p>
  
  <p style="margin-top: 30px;">See you on the pitch! ⚽</p>
  
  <p style="color: #6b7280; font-size: 14px;">— The PitchRank Team</p>
  
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
  
  <p style="color: #9ca3af; font-size: 12px; text-align: center;">
    You're receiving this because you subscribed to the PitchRank newsletter.<br>
    <a href="https://pitchrank.io" style="color: #9ca3af;">pitchrank.io</a>
  </p>
</body>
</html>
`;

/**
 * Send a welcome email to a new newsletter subscriber.
 * Returns true if sent successfully, false otherwise.
 * Errors are logged but not thrown - subscription should succeed even if email fails.
 */
export async function sendWelcomeEmail(email: string): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping welcome email');
    return false;
  }

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <newsletter@pitchrank.io>',
      to: email,
      subject: 'Welcome to PitchRank!',
      html: WELCOME_EMAIL_HTML,
    });

    if (error) {
      console.error('Failed to send welcome email:', error);
      return false;
    }

    console.log(`Welcome email sent to ${email}`);
    return true;
  } catch (err) {
    console.error('Error sending welcome email:', err);
    return false;
  }
}
