"use client";

import { createBrowserClient } from "@supabase/ssr";

/**
 * Creates a Supabase client for client-side operations
 *
 * Use this in:
 * - Client Components (use client)
 * - Event handlers
 * - Client-side effects
 */
export function createClientSupabase() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        // Explicitly handle cookie reading on the client
        getAll() {
          if (typeof document === "undefined") return [];

          const cookies = document.cookie.split(";").map((cookie) => {
            const [name, ...valueParts] = cookie.trim().split("=");
            return { name, value: valueParts.join("=") };
          });

          // Debug: log what cookies we're reading
          const sbCookies = cookies.filter(c => c.name.startsWith("sb-"));
          if (sbCookies.length > 0) {
            console.log("[Supabase Client] Found auth cookies:", sbCookies.map(c => ({
              name: c.name,
              valueLength: c.value?.length
            })));
          }

          return cookies;
        },
        setAll(cookiesToSet) {
          // On the browser, we just set document.cookie
          cookiesToSet.forEach(({ name, value, options }) => {
            let cookie = `${name}=${value}`;
            if (options?.maxAge) cookie += `; max-age=${options.maxAge}`;
            if (options?.path) cookie += `; path=${options.path}`;
            if (options?.domain) cookie += `; domain=${options.domain}`;
            if (options?.sameSite) cookie += `; samesite=${options.sameSite}`;
            if (options?.secure) cookie += "; secure";
            document.cookie = cookie;
          });
        },
      },
      cookieOptions: {
        path: "/",
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
      },
    }
  );
}
