import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

/**
 * Creates a Supabase client for server-side operations
 * This client handles cookies for session management
 *
 * Use this in:
 * - Server Components
 * - Route Handlers
 * - Server Actions
 * - Middleware
 */
export async function createServerSupabase() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              // Ensure cookies are NOT httpOnly so client-side JS can read them
              const cookieOptions = {
                ...options,
                httpOnly: false,
              };
              cookieStore.set(name, value, cookieOptions);
            });
          } catch {
            // The `setAll` method was called from a Server Component.
            // This can be ignored if you have middleware refreshing
            // user sessions.
          }
        },
      },
    }
  );
}

/**
 * Creates a Supabase client for middleware
 * Returns both the client and a response object for cookie handling
 */
export function createMiddlewareSupabase(
  request: Request,
  response: Response
) {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return parseCookies(request.headers.get("cookie") ?? "");
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            // Ensure cookies are NOT httpOnly so client-side JS can read them
            const cookieOptions = {
              ...options,
              httpOnly: false,
            };
            response.headers.append(
              "Set-Cookie",
              serializeCookie(name, value, cookieOptions)
            );
          });
        },
      },
    }
  );
}

// Helper to parse cookies from header string
function parseCookies(cookieHeader: string): { name: string; value: string }[] {
  if (!cookieHeader) return [];
  return cookieHeader.split(";").map((cookie) => {
    const [name, ...valueParts] = cookie.trim().split("=");
    return { name, value: valueParts.join("=") };
  });
}

// Helper to serialize cookie for Set-Cookie header
function serializeCookie(
  name: string,
  value: string,
  options?: CookieOptions
): string {
  let cookie = `${name}=${value}`;

  if (options?.maxAge) cookie += `; Max-Age=${options.maxAge}`;
  if (options?.domain) cookie += `; Domain=${options.domain}`;
  if (options?.path) cookie += `; Path=${options.path}`;
  if (options?.secure) cookie += "; Secure";
  if (options?.httpOnly) cookie += "; HttpOnly";
  if (options?.sameSite) cookie += `; SameSite=${options.sameSite}`;

  return cookie;
}
