import { createServerSupabase } from "@/lib/supabase/server";
import type { User } from "@supabase/supabase-js";

/**
 * User profile from user_profiles table
 */
export interface UserProfile {
  id: string;
  email: string | null;
  plan: "free" | "premium" | "admin";
  created_at: string;
  updated_at: string;
}

/**
 * Combined user data from Supabase Auth and user_profiles
 */
export interface AuthUser extends User {
  profile: UserProfile | null;
}

/**
 * Get the current authenticated user with their profile
 *
 * Use this in Server Components to get the logged-in user:
 *
 * ```tsx
 * import { getUser } from "@/lib/auth/getUser";
 *
 * export default async function ProtectedPage() {
 *   const user = await getUser();
 *   if (!user) redirect("/login");
 *   return <div>Hello {user.email}</div>;
 * }
 * ```
 *
 * @returns The authenticated user with their profile, or null if not logged in
 */
export async function getUser(): Promise<AuthUser | null> {
  const supabase = await createServerSupabase();

  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();

  if (authError || !user) {
    return null;
  }

  // Fetch the user's profile from user_profiles table
  const { data: profile, error: profileError } = await supabase
    .from("user_profiles")
    .select("*")
    .eq("id", user.id)
    .single();

  if (profileError) {
    // Log the error but don't fail - profile might not exist yet
    console.warn("Error fetching user profile:", profileError.message);
  }

  return {
    ...user,
    profile: profile ?? null,
  };
}

/**
 * Get only the user session (lighter than getUser)
 * Use when you only need to check if user is authenticated
 */
export async function getSession() {
  const supabase = await createServerSupabase();
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession();

  if (error) {
    console.warn("Error getting session:", error.message);
    return null;
  }

  return session;
}
