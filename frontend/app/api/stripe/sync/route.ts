import { stripe } from "@/lib/stripe/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

/**
 * POST /api/stripe/sync
 *
 * Fallback sync: given a checkout session_id, fetch the subscription from
 * Stripe and update user_profiles. This covers the case where the webhook
 * fails (misconfigured secret, cold-start timeout, etc.).
 *
 * Only the authenticated user who owns the session can call this.
 */
export async function POST(req: Request) {
  try {
    const supabase = await createServerSupabase();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    const { sessionId } = await req.json();
    if (!sessionId || typeof sessionId !== "string") {
      return NextResponse.json({ error: "Missing session_id" }, { status: 400 });
    }

    // Retrieve checkout session from Stripe
    const session = await stripe.checkout.sessions.retrieve(sessionId, {
      expand: ["subscription"],
    });

    if (!session.customer || !session.subscription) {
      return NextResponse.json({ error: "Session has no subscription" }, { status: 400 });
    }

    const customerId = session.customer as string;
    const subscription =
      typeof session.subscription === "string"
        ? await stripe.subscriptions.retrieve(session.subscription)
        : session.subscription;

    const periodEnd =
      subscription.items.data[0]?.current_period_end ??
      Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;

    // Map Stripe status to plan
    const status = subscription.status;
    const plan =
      status === "active" || status === "trialing" || status === "past_due"
        ? "premium"
        : "free";

    // Verify the caller owns this customer by checking their profile
    const { data: profile } = await supabase
      .from("user_profiles")
      .select("stripe_customer_id")
      .eq("id", user.id)
      .single();

    if (profile?.stripe_customer_id && profile.stripe_customer_id !== customerId) {
      return NextResponse.json({ error: "Session does not belong to you" }, { status: 403 });
    }

    // Update user_profiles (same fields as webhook handler)
    const { error: updateError } = await supabase
      .from("user_profiles")
      .update({
        stripe_customer_id: customerId,
        stripe_subscription_id: subscription.id,
        subscription_status: status,
        plan,
        subscription_period_end: new Date(periodEnd * 1000).toISOString(),
        updated_at: new Date().toISOString(),
      })
      .eq("id", user.id);

    if (updateError) {
      console.error("Sync: error updating profile:", updateError);
      return NextResponse.json({ error: "Failed to sync" }, { status: 500 });
    }

    console.log(
      `Sync: updated user ${user.id} -> plan=${plan}, status=${status}, customer=${customerId}`
    );

    return NextResponse.json({
      synced: true,
      plan,
      status,
    });
  } catch (error) {
    console.error("Sync error:", error);
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
