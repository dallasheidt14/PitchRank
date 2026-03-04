import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);

  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  const code = searchParams.get("code");
  // Default to /rankings instead of /watchlist to avoid redirecting free users to premium route
  const next = searchParams.get("next") ?? "/rankings";
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  // Handle auth errors from Supabase
  if (error) {
    console.error("[Auth Callback] Error:", error, errorDescription);
    return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(errorDescription ?? error)}`);
  }

  const cookieStore = await cookies();

  // Create Supabase client - let it handle cookies automatically
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        },
      },
    }
  );

  // Handle magic link / email confirmation (token_hash flow)
  if (token_hash && type) {
    const { error: verifyError } = await supabase.auth.verifyOtp({
      token_hash,
      type: type as "magiclink" | "signup" | "recovery" | "invite" | "email_change" | "email",
    });

    if (verifyError) {
      console.error("[Auth Callback] Verify OTP error:", verifyError.message);
      return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(verifyError.message)}`);
    }

    // For password recovery, redirect to the reset password page
    if (type === "recovery") {
      return NextResponse.redirect(`${origin}/reset-password`);
    }

    return NextResponse.redirect(`${origin}${next}`);
  }

  // Handle OAuth/PKCE (code exchange flow)
  if (code) {
    const isRecovery = type === "recovery" || cookieStore.get("password_reset_pending")?.value === "true";
    if (isRecovery) {
      cookieStore.set("password_reset_pending", "", { path: "/", maxAge: 0 });
    }

    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);

    if (exchangeError) {
      console.error("[Auth Callback] Code exchange error:", exchangeError.message);

      // When PKCE code exchange fails (e.g., user opened the email confirmation
      // link in a different browser/tab where the code_verifier cookie is missing),
      // the email is still confirmed by Supabase — only the session creation failed.
      // Redirect to login with a success message so the user can sign in manually.
      const isCodeVerifierError = exchangeError.message.toLowerCase().includes("code verifier")
        || exchangeError.message.toLowerCase().includes("code_verifier")
        || exchangeError.message.toLowerCase().includes("pkce");

      if (isCodeVerifierError) {
        return NextResponse.redirect(
          `${origin}/login?message=${encodeURIComponent("Email confirmed! Please sign in with your password.")}`
        );
      }

      return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(exchangeError.message)}`);
    }

    // For recovery, redirect to reset-password page
    if (isRecovery) {
      return NextResponse.redirect(`${origin}/reset-password`);
    }

    return NextResponse.redirect(`${origin}${next}`);
  }

  // No valid auth params
  return NextResponse.redirect(`${origin}/login`);
}
