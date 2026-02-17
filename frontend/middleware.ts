import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

// Routes that require authentication
const PROTECTED_ROUTES = ["/watchlist", "/compare", "/teams"];

// Routes that require premium subscription (subset of protected routes)
const PREMIUM_ROUTES = ["/watchlist", "/compare", "/teams"];

// Auth routes (login/signup pages)
const AUTH_ROUTES = ["/login", "/signup"];

export async function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;

  // SEO: Canonical URL redirect (www → non-www)
  const hostname = request.headers.get("host") || "";
  if (hostname.startsWith("www.")) {
    const url = request.nextUrl.clone();
    url.host = hostname.replace("www.", "");
    return NextResponse.redirect(url, 301);
  }

  // Redirect auth codes to /auth/callback
  const code = searchParams.get("code");
  const tokenHash = searchParams.get("token_hash");

  if ((code || tokenHash) && pathname !== "/auth/callback") {
    const callbackUrl = new URL("/auth/callback", request.url);
    searchParams.forEach((value, key) => {
      callbackUrl.searchParams.set(key, value);
    });
    return NextResponse.redirect(callbackUrl);
  }

  // Create response
  let response = NextResponse.next({
    request: { headers: request.headers },
  });

  // Create Supabase client for middleware
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => {
            request.cookies.set(name, value);
          });
          response = NextResponse.next({
            request: { headers: request.headers },
          });
          cookiesToSet.forEach(({ name, value, options }) => {
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  // Refresh session - REQUIRED for Server Components
  // Call getSession() first to refresh cookies, then getUser() for current user
  const { data: { session } } = await supabase.auth.getSession();
  const { data: { user } } = await supabase.auth.getUser();

  const isProtectedRoute = PROTECTED_ROUTES.some((route) =>
    pathname.startsWith(route)
  );
  const isPremiumRoute = PREMIUM_ROUTES.some((route) =>
    pathname.startsWith(route)
  );
  const isAuthRoute = AUTH_ROUTES.some((route) => pathname.startsWith(route));

  // Redirect unauthenticated users from protected routes
  // For premium routes, redirect to upgrade page (which handles sign up/login)
  // For other protected routes, redirect to login
  if (isProtectedRoute && !user) {
    if (isPremiumRoute) {
      // Premium routes: redirect to upgrade page which can handle sign up/login
      const upgradeUrl = new URL("/upgrade", request.url);
      upgradeUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(upgradeUrl);
    } else {
      // Other protected routes: redirect to login
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }
  }

  // Check premium status for premium routes
  if (isPremiumRoute && user) {
    const { data: profile, error: profileError } = await supabase
      .from("user_profiles")
      .select("plan")
      .eq("id", user.id)
      .single();

    // If profile fetch failed or profile doesn't exist, redirect to upgrade
    // This prevents users from bypassing premium check when profile is null
    if (profileError || !profile) {
      console.warn("[Middleware] Profile not found or error:", profileError?.message);
      return NextResponse.redirect(new URL("/upgrade", request.url));
    }

    // Redirect free users to upgrade page
    // Allow admin and premium users through
    if (profile.plan !== "premium" && profile.plan !== "admin") {
      return NextResponse.redirect(new URL("/upgrade", request.url));
    }
  }

  // Redirect authenticated users from auth routes to rankings (accessible to all users)
  // This prevents redirect loops for free users who would be redirected from /watchlist
  if (isAuthRoute && user) {
    return NextResponse.redirect(new URL("/rankings", request.url));
  }

  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|logos|api|auth/callback).*)",
  ],
};
