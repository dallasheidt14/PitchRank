'use server';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { createServerSupabase } from '@/lib/supabase/server';
import { isVerifiableOtpType, safeNextPath } from '@/lib/auth/emailTokens';

/**
 * Redeem an emailed one-time token. Reached only by the POST behind the button
 * on /auth/confirm, never by rendering that page, so a link scanner's GET
 * cannot spend the token before the recipient clicks.
 */
export async function confirmEmailLink(formData: FormData) {
  const tokenHash = String(formData.get('token_hash') ?? '');
  const type = String(formData.get('type') ?? '');
  const next = safeNextPath(String(formData.get('next') ?? ''));

  if (!tokenHash || !isVerifiableOtpType(type)) {
    redirect(`/login?error=${encodeURIComponent('This link is not valid. Please request a new one.')}`);
  }

  const supabase = await createServerSupabase();
  const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type });

  if (error) {
    // Don't surface raw Supabase error text to the user.
    console.error('[auth/confirm] Verify OTP error:', error.code, error.message);
    redirect(
      `/login?error=${encodeURIComponent('That link has expired or was already used. Please request a new one.')}`
    );
  }

  if (type === 'recovery') {
    // forgot-password sets password_reset_pending for 24h so the callback can
    // route a bare PKCE code to /reset-password. The reset is done, so clear it:
    // a stale flag reclassifies any unrelated OAuth sign-in in this browser as a
    // recovery for the rest of the day. The callback clears it on its own paths.
    (await cookies()).set('password_reset_pending', '', { path: '/', maxAge: 0 });
    redirect('/reset-password');
  }

  redirect(next);
}
