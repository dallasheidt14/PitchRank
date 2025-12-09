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
          // Extract root domain to ensure cookies work across www and non-www
          const hostname = requestUrl.hostname;
          const rootDomain = hostname.replace(/^www\./, '');
          // Only set domain for known production domains, not for Vercel preview deployments
          const isProductionDomain = hostname === 'pitchrank.io' || hostname === 'www.pitchrank.io';
          const domain = hostname.includes('localhost') ? undefined : (isProductionDomain ? `.${rootDomain}` : undefined);

          console.log("[Auth Callback] setAll called with cookies:", {
            hostname,
            rootDomain,
            domain,
            isProductionDomain,
            cookieCount: cookiesToSet.length,
            cookies: cookiesToSet.map(c => ({
              name: c.name,
              valueLength: c.value?.length,
              originalOptions: c.options
            }))
          });

          cookiesToSet.forEach(({ name, value, options }) => {
            // Ensure cookies are NOT httpOnly so client-side JS can read them
            // Explicitly set path to "/" for app-wide access
            const cookieOptions = {
              ...options,
              httpOnly: false,
              path: "/", // Ensure cookie is accessible across all routes
              ...(domain && { domain }), // Only set domain if defined
            };

            console.log("[Auth Callback] Setting cookie:", {
              name,
              valueLength: value?.length,
              cookieOptions: { ...cookieOptions, value: undefined } // Don't log the actual value
            });

            response.cookies.set(name, value, cookieOptions);
          });

          // Log all cookies on the response after setting
          const allCookies = response.cookies.getAll();
          console.log("[Auth Callback] Response cookies after setAll:", allCookies.map(c => ({
            name: c.name,
            valueLength: c.value?.length
          })));
        },
      },
    }
  );

  // Handle email confirmation (token_hash flow) - for magic links and email verification
  if (token_hash && type) {
    console.log("[Auth Callback] Processing token_hash flow:", { type, tokenHashLength: token_hash.length });

    const { data, error: verifyError } = await supabase.auth.verifyOtp({
      token_hash,
      type: type as "signup" | "email" | "recovery" | "invite" | "magiclink" | "email_change",
    });

    if (verifyError) {
      console.error("[Auth Callback] Token verification error:", verifyError.message);
      const loginUrl = new URL("/login", requestUrl.origin);
      loginUrl.searchParams.set("error", "Email verification failed. Please try again.");
      return NextResponse.redirect(loginUrl);
    }

    console.log("[Auth Callback] verifyOtp success:", {
      hasSession: !!data.session,
      hasUser: !!data.user,
      email: data.user?.email,
    });

    // Explicitly get session to ensure setAll callback is triggered
    // This is necessary because some versions of @supabase/ssr don't trigger setAll on verifyOtp
    const { data: { session } } = await supabase.auth.getSession();
    console.log("[Auth Callback] getSession after verifyOtp:", {
      hasSession: !!session,
      email: session?.user?.email,
    });

    // Final confirmation of cookies on response
    const finalCookies = response.cookies.getAll();
    console.log("[Auth Callback] Final response cookies before redirect:", {
      count: finalCookies.length,
      cookies: finalCookies.map(c => ({ name: c.name, valueLength: c.value?.length })),
      redirectTo: next,
    });

    return response;
  }

  // Handle OAuth/magic link (code exchange flow)
  if (code) {
    console.log("[Auth Callback] Processing code exchange flow");

    const { data, error: exchangeError } = await supabase.auth.exchangeCodeForSession(
      code
    );

    if (exchangeError) {
      console.error("[Auth Callback] Code exchange error:", exchangeError.message);
      const loginUrl = new URL("/login", requestUrl.origin);
      loginUrl.searchParams.set("error", "Failed to complete sign in");
      return NextResponse.redirect(loginUrl);
    }

    console.log("[Auth Callback] Code exchange success:", {
      hasSession: !!data.session,
      hasUser: !!data.user,
      email: data.user?.email,
    });

    // Explicitly get session to ensure setAll callback is triggered
    const { data: { session } } = await supabase.auth.getSession();
    console.log("[Auth Callback] getSession after code exchange:", {
      hasSession: !!session,
      email: session?.user?.email,
    });

    // Final confirmation of cookies on response
    const finalCookies = response.cookies.getAll();
    console.log("[Auth Callback] Final response cookies before redirect:", {
      count: finalCookies.length,
      cookies: finalCookies.map(c => ({ name: c.name, valueLength: c.value?.length })),
      redirectTo: next,
    });

    return response;
  }

  // No code or token_hash - redirect to login
  return NextResponse.redirect(new URL("/login", requestUrl.origin));
}
