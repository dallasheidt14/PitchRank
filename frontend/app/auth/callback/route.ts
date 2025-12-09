import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

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

  const cookieStore = await cookies();

  // Create response first so we can set cookies on it
  const redirectUrl = new URL(next, requestUrl.origin);
  const response = NextResponse.redirect(redirectUrl);

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          console.log("[Auth Callback] Setting cookies:", cookiesToSet.map(c => ({
            name: c.name,
            valueLength: c.value?.length,
            options: c.options
          })));
          cookiesToSet.forEach(({ name, value, options }) => {
            // Ensure cookies are NOT httpOnly so client-side JS can read them
            const cookieOptions = {
              ...options,
              httpOnly: false, // Allow client-side access
            };
            response.cookies.set(name, value, cookieOptions);
          });
        },
      },
    }
  );

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

    return response;
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

    return response;
  }

  // No code or token_hash - redirect to login
  return NextResponse.redirect(new URL("/login", requestUrl.origin));
}
