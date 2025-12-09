import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);

  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/watchlist";
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

  // Handle magic link (token_hash flow)
  if (token_hash && type) {
    const { error: verifyError } = await supabase.auth.verifyOtp({
      token_hash,
      type: type as "magiclink" | "signup" | "recovery" | "invite" | "email_change",
    });

    if (verifyError) {
      console.error("[Auth Callback] Verify OTP error:", verifyError.message);
      return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(verifyError.message)}`);
    }

    return NextResponse.redirect(`${origin}${next}`);
  }

  // Handle OAuth/PKCE (code exchange flow)
  if (code) {
    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);

    if (exchangeError) {
      console.error("[Auth Callback] Code exchange error:", exchangeError.message);
      return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(exchangeError.message)}`);
    }

    return NextResponse.redirect(`${origin}${next}`);
  }

  // No valid auth params
  return NextResponse.redirect(`${origin}/login`);
}
