import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * GET /auth/callback
 *
 * Handles OAuth and magic link callbacks from Supabase Auth.
 * This route exchanges the auth code for a session and redirects the user.
 */
export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const next = requestUrl.searchParams.get("next") ?? "/watchlist";
  const error = requestUrl.searchParams.get("error");
  const errorDescription = requestUrl.searchParams.get("error_description");

  // Handle auth errors
  if (error) {
    console.error("Auth callback error:", error, errorDescription);
    const loginUrl = new URL("/login", requestUrl.origin);
    loginUrl.searchParams.set(
      "error",
      errorDescription ?? "Authentication failed"
    );
    return NextResponse.redirect(loginUrl);
  }

  // Exchange auth code for session
  if (code) {
    const supabase = await createServerSupabase();
    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(
      code
    );

    if (exchangeError) {
      console.error("Code exchange error:", exchangeError.message);
      const loginUrl = new URL("/login", requestUrl.origin);
      loginUrl.searchParams.set("error", "Failed to complete sign in");
      return NextResponse.redirect(loginUrl);
    }
  }

  // Redirect to the intended destination
  return NextResponse.redirect(new URL(next, requestUrl.origin));
}
