import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * GET /logout
 *
 * Signs the user out and redirects to the home page.
 * Can also accept a `next` query parameter for custom redirect.
 */
export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const next = requestUrl.searchParams.get("next") ?? "/";

  const supabase = await createServerSupabase();
  if (supabase) {
    await supabase.auth.signOut();
  }

  // Redirect to the specified page or home
  return NextResponse.redirect(new URL(next, requestUrl.origin));
}

/**
 * POST /logout
 *
 * Alternative logout via POST request (useful for forms)
 */
export async function POST(request: Request) {
  const requestUrl = new URL(request.url);

  const supabase = await createServerSupabase();
  if (supabase) {
    await supabase.auth.signOut();
  }

  return NextResponse.redirect(new URL("/", requestUrl.origin));
}
