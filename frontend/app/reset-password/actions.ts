'use server';

import { createServerSupabase } from '@/lib/supabase/server';

export async function updatePassword(password: string): Promise<{ error: string | null }> {
  if (!password || password.length < 8) {
    return { error: 'Password must be at least 8 characters long' };
  }

  const supabase = await createServerSupabase();

  const { error } = await supabase.auth.updateUser({ password });

  if (error) {
    return { error: error.message };
  }

  return { error: null };
}
