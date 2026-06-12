'use server';

import { createServerSupabase } from '@/lib/supabase/server';

export async function updatePassword(password: string): Promise<{ error: string | null }> {
  if (!password || password.length < 8) {
    return { error: 'Password must be at least 8 characters long' };
  }

  const supabase = await createServerSupabase();

  // Require the session established by the recovery link before touching the
  // password, and keep failure responses generic — raw Supabase error strings
  // stay in the server logs
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { error: 'Your reset link has expired. Please request a new one.' };
  }

  const { error } = await supabase.auth.updateUser({ password });

  if (error) {
    console.error('[reset-password] updateUser failed:', error.code, error.message);
    if (error.code === 'same_password') {
      return { error: 'New password must be different from your current password.' };
    }
    return { error: 'Could not update password. Please request a new reset link and try again.' };
  }

  return { error: null };
}
