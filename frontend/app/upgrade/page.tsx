"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, Zap, Crown, Shield, TrendingUp, Star, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { startCheckout } from "@/lib/stripe/client";
import { useUser } from "@/hooks/useUser";

// Price IDs from Stripe Dashboard (configured via environment variables)
const PRICE_IDS = {
  MONTHLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || "",
  YEARLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || "",
};

const FEATURES = [
  { icon: TrendingUp, text: "Full access to all rankings" },
  { icon: Star, text: "Unlimited team comparisons" },
  { icon: Shield, text: "Advanced analytics & insights" },
  { icon: Zap, text: "Real-time ranking updates" },
  { icon: Pencil, text: "Edit Access - merge duplicate teams, find missing game history" },
];

export default function UpgradePage() {
  const { user, isLoading: userLoading } = useUser();
  const [loadingPlan, setLoadingPlan] = useState<"monthly" | "yearly" | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  const handleUpgrade = async (plan: "monthly" | "yearly") => {
    // If not authenticated, redirect to signup
    if (!user) {
      window.location.href = `/signup?next=/upgrade`;
      return;
    }

    setLoadingPlan(plan);
    setError(null);

    try {
      const priceId = plan === "monthly" ? PRICE_IDS.MONTHLY : PRICE_IDS.YEARLY;
      if (!priceId) {
        console.error("[UpgradePage] Missing Stripe price ID for plan:", plan, { monthly: !!PRICE_IDS.MONTHLY, yearly: !!PRICE_IDS.YEARLY });
        throw new Error("Pricing is not configured. Please contact support.");
      }
      await startCheckout(priceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setLoadingPlan(null);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30">
      <div className="container mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-12">
          <Badge variant="secondary" className="mb-4">
            <Crown className="w-3 h-3 mr-1" />
            Premium
          </Badge>
          <h1 className="text-4xl md:text-5xl font-bold font-display mb-4">
            Upgrade to PitchRank+
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Get unlimited access to advanced rankings, team comparisons, and
            exclusive analytics to make better decisions for your soccer journey.
          </p>
        </div>

        {/* Not Authenticated Message */}
        {!userLoading && !user && (
          <div className="max-w-md mx-auto mb-8 p-4 bg-primary/10 border border-primary/20 rounded-lg text-center">
            <p className="text-sm mb-3">
              Sign up for a free account to upgrade to Premium
            </p>
            <div className="flex gap-3 justify-center">
              <Link href="/signup">
                <Button size="sm" variant="outline">
                  Sign Up
                </Button>
              </Link>
              <Link href="/login">
                <Button size="sm">
                  Sign In
                </Button>
              </Link>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="max-w-md mx-auto mb-8 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-center">
            <p className="text-destructive text-sm">{error}</p>
          </div>
        )}

        {/* Pricing Cards */}
        <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          {/* Monthly Plan */}
          <Card variant="elevated" className="relative">
            <CardHeader>
              <CardTitle className="text-2xl">Monthly</CardTitle>
              <CardDescription>Perfect for trying out premium</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-6">
                <span className="text-4xl font-bold">$6.99</span>
                <span className="text-muted-foreground">/month</span>
              </div>
              <ul className="space-y-3">
                {FEATURES.map((feature, index) => (
                  <li key={index} className="flex items-center gap-3">
                    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center">
                      <Check className="w-3 h-3 text-primary" />
                    </div>
                    <span className="text-sm">{feature.text}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full"
                size="lg"
                variant="outline"
                onClick={() => handleUpgrade("monthly")}
                disabled={loadingPlan !== null}
              >
                {loadingPlan === "monthly" ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">&#9696;</span>
                    Processing...
                  </span>
                ) : (
                  "Subscribe Monthly"
                )}
              </Button>
            </CardFooter>
          </Card>

          {/* Yearly Plan */}
          <Card variant="primary" className="relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2">
              <Badge className="bg-primary text-primary-foreground shadow-lg">
                Save 17% - Best Value
              </Badge>
            </div>
            <CardHeader>
              <CardTitle className="text-2xl">Yearly</CardTitle>
              <CardDescription>2 months free with annual billing</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-6">
                <span className="text-4xl font-bold">$69</span>
                <span className="text-muted-foreground">/year</span>
                <div className="text-sm text-muted-foreground mt-1">
                  <span className="line-through">$83.88</span>
                  <span className="text-primary ml-2">Save $14.88</span>
                </div>
              </div>
              <ul className="space-y-3">
                {FEATURES.map((feature, index) => (
                  <li key={index} className="flex items-center gap-3">
                    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center">
                      <Check className="w-3 h-3 text-primary" />
                    </div>
                    <span className="text-sm">{feature.text}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full"
                size="lg"
                onClick={() => handleUpgrade("yearly")}
                disabled={loadingPlan !== null}
              >
                {loadingPlan === "yearly" ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">&#9696;</span>
                    Processing...
                  </span>
                ) : (
                  <>
                    <Crown className="w-4 h-4 mr-2" />
                    Subscribe Yearly
                  </>
                )}
              </Button>
            </CardFooter>
          </Card>
        </div>

        {/* Trust Badges */}
        <div className="mt-12 text-center">
          <p className="text-sm text-muted-foreground mb-4">
            Secure payment powered by Stripe
          </p>
          <div className="flex items-center justify-center gap-6 text-muted-foreground">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4" />
              <span className="text-xs">SSL Encrypted</span>
            </div>
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4" />
              <span className="text-xs">Cancel Anytime</span>
            </div>
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4" />
              <span className="text-xs">Instant Access</span>
            </div>
          </div>
        </div>

        {/* FAQ Section */}
        <div className="mt-16 max-w-2xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            <div>
              <h3 className="font-semibold mb-2">Can I cancel anytime?</h3>
              <p className="text-muted-foreground text-sm">
                Yes! You can cancel your subscription at any time. Your premium
                access will continue until the end of your current billing
                period.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">
                What payment methods do you accept?
              </h3>
              <p className="text-muted-foreground text-sm">
                We accept all major credit cards (Visa, MasterCard, American
                Express) through our secure payment processor, Stripe.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">
                Will I be charged automatically?
              </h3>
              <p className="text-muted-foreground text-sm">
                Yes, your subscription will automatically renew at the end of
                each billing period. You&apos;ll receive an email reminder before each
                renewal.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
