import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * GET /auth/callback
 *
 * Handles OAuth, magic link, and email confirmation callbacks from Supabase Auth.
 * This route exchanges the auth code/token for a session and redirects the user.
 */
export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const token_hash = requestUrl.searchParams.get("token_hash");
  const type = requestUrl.searchParams.get("type");
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

  const supabase = await createServerSupabase();

  // Handle email confirmation (token_hash flow)
  if (token_hash && type) {
    const { error: verifyError } = await supabase.auth.verifyOtp({
      token_hash,
      type: type as "signup" | "email" | "recovery" | "invite" | "magiclink" | "email_change",
    });

    if (verifyError) {
      console.error("Token verification error:", verifyError.message);
      const loginUrl = new URL("/login", requestUrl.origin);
      loginUrl.searchParams.set("error", "Email verification failed. Please try again.");
      return NextResponse.redirect(loginUrl);
    }

    // Redirect to watchlist after successful email confirmation
    return NextResponse.redirect(new URL(next, requestUrl.origin));
  }

  // Handle OAuth/magic link (code exchange flow)
  if (code) {
    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(
      code
    );

    if (exchangeError) {
      console.error("Code exchange error:", exchangeError.message);
      const loginUrl = new URL("/login", requestUrl.origin);
      loginUrl.searchParams.set("error", "Failed to complete sign in");
      return NextResponse.redirect(loginUrl);
    }

    return NextResponse.redirect(new URL(next, requestUrl.origin));
  }

  // No code or token_hash - redirect to login
  return NextResponse.redirect(new URL("/login", requestUrl.origin));
}
