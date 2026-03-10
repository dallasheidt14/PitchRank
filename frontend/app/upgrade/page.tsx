"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Check,
  Zap,
  Crown,
  Shield,
  TrendingUp,
  Star,
  Pencil,
  BarChart3,
  Eye,
  ArrowRight,
} from "lucide-react";
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
import { trackUpgradePageViewed, trackPlanSelected, trackCheckoutInitiated } from "@/lib/events";

// Price IDs from Stripe Dashboard (configured via environment variables)
const PRICE_IDS = {
  MONTHLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || "",
  YEARLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || "",
};

const FEATURES = [
  { icon: TrendingUp, title: "Full Rankings Access", text: "See every team's PowerScore, national & state rank across all age groups" },
  { icon: Star, title: "Team Comparisons", text: "Head-to-head comparison tool with win probability predictions" },
  { icon: BarChart3, title: "AI Insights", text: "Season Truth, consistency scores, and team persona analysis" },
  { icon: Eye, title: "Watchlist", text: "Track your favorite teams with real-time rank change alerts" },
  { icon: Pencil, title: "Edit Access", text: "Merge duplicate teams and find missing game history" },
];

const SOCIAL_PROOF_STATS = [
  { value: "25,000+", label: "Teams Ranked" },
  { value: "500+", label: "Clubs Covered" },
  { value: "Weekly", label: "Updated Rankings" },
];

const TESTIMONIALS = [
  {
    quote: "PitchRank+ gave us the edge to find the right competition level for our son. The insights are incredible.",
    author: "Soccer Parent",
    detail: "ECNL U14 Boys",
  },
  {
    quote: "I use the comparison tool every week before games. Knowing our opponent's consistency score helps us prepare.",
    author: "Club Coach",
    detail: "GA Premier",
  },
  {
    quote: "The watchlist feature saves me hours of research. I can track every team in our bracket from one place.",
    author: "Tournament Director",
    detail: "Southwest Region",
  },
];

export default function UpgradePage() {
  return (
    <Suspense>
      <UpgradePageContent />
    </Suspense>
  );
}

function UpgradePageContent() {
  const { user, isLoading: userLoading } = useUser();
  const searchParams = useSearchParams();
  const [loadingPlan, setLoadingPlan] = useState<"monthly" | "yearly" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<"monthly" | "yearly">("yearly");

  const source = searchParams.get("next") || searchParams.get("source") || "direct";

  // Track page view on mount
  useEffect(() => {
    trackUpgradePageViewed({ source });
  }, [source]);

  const handleUpgrade = async (plan: "monthly" | "yearly") => {
    // If not authenticated, redirect to signup
    if (!user) {
      window.location.href = `/signup?next=/upgrade`;
      return;
    }

    trackPlanSelected({
      plan,
      price: plan === "monthly" ? 6.99 : 69,
      source,
    });

    setLoadingPlan(plan);
    setError(null);

    try {
      const priceId = plan === "monthly" ? PRICE_IDS.MONTHLY : PRICE_IDS.YEARLY;
      if (!priceId) {
        console.error("[UpgradePage] Missing Stripe price ID for plan:", plan, { monthly: !!PRICE_IDS.MONTHLY, yearly: !!PRICE_IDS.YEARLY });
        throw new Error("Pricing is not configured. Please contact support.");
      }
      trackCheckoutInitiated({ plan, price: plan === "monthly" ? 6.99 : 69 });
      await startCheckout(priceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setLoadingPlan(null);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30">
      <div className="container mx-auto px-4 py-12 md:py-16">
        {/* Header */}
        <div className="text-center mb-10">
          <Badge variant="secondary" className="mb-4">
            <Crown className="w-3 h-3 mr-1" />
            Premium
          </Badge>
          <h1 className="text-4xl md:text-5xl font-bold font-display mb-4">
            Upgrade to PitchRank+
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            The most comprehensive youth soccer analytics platform. Make smarter decisions
            for your player&apos;s journey with data that coaches and parents trust.
          </p>
        </div>

        {/* Social Proof Bar */}
        <div className="flex items-center justify-center gap-8 md:gap-12 mb-10">
          {SOCIAL_PROOF_STATS.map((stat) => (
            <div key={stat.label} className="text-center">
              <div className="text-2xl md:text-3xl font-bold font-display text-primary">
                {stat.value}
              </div>
              <div className="text-xs text-muted-foreground">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Not Authenticated Message */}
        {!userLoading && !user && (
          <div className="max-w-md mx-auto mb-8 p-4 bg-primary/10 border border-primary/20 rounded-lg text-center">
            <p className="text-sm mb-3">
              Sign up for a free account to upgrade to Premium
            </p>
            <div className="flex gap-3 justify-center">
              <Link href="/signup?next=/upgrade">
                <Button size="sm">
                  Create Free Account
                </Button>
              </Link>
              <Link href="/login?next=/upgrade">
                <Button size="sm" variant="outline">
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

        {/* Plan Toggle (Mobile-Friendly) */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <button
            onClick={() => setSelectedPlan("monthly")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedPlan === "monthly"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setSelectedPlan("yearly")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors relative ${
              selectedPlan === "yearly"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            Yearly
            <span className="absolute -top-2 -right-2 bg-green-500 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">
              -17%
            </span>
          </button>
        </div>

        {/* Pricing Cards */}
        <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          {/* Monthly Plan */}
          <Card
            variant="elevated"
            className={`relative cursor-pointer transition-all ${
              selectedPlan === "monthly" ? "ring-2 ring-primary" : ""
            }`}
            onClick={() => setSelectedPlan("monthly")}
          >
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
                  <li key={index} className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center mt-0.5">
                      <Check className="w-3 h-3 text-primary" />
                    </div>
                    <div>
                      <span className="text-sm font-medium">{feature.title}</span>
                      <p className="text-xs text-muted-foreground">{feature.text}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full"
                size="lg"
                variant={selectedPlan === "monthly" ? "default" : "outline"}
                onClick={(e) => {
                  e.stopPropagation();
                  handleUpgrade("monthly");
                }}
                disabled={loadingPlan !== null}
              >
                {loadingPlan === "monthly" ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">&#9696;</span>
                    Processing...
                  </span>
                ) : (
                  <>
                    Get Started
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </>
                )}
              </Button>
            </CardFooter>
          </Card>

          {/* Yearly Plan */}
          <Card
            variant="primary"
            className={`relative cursor-pointer transition-all ${
              selectedPlan === "yearly" ? "ring-2 ring-primary" : ""
            }`}
            onClick={() => setSelectedPlan("yearly")}
          >
            <div className="absolute -top-3 left-1/2 -translate-x-1/2">
              <Badge className="bg-green-600 text-white shadow-lg">
                Most Popular - Save 17%
              </Badge>
            </div>
            <CardHeader>
              <CardTitle className="text-2xl">Yearly</CardTitle>
              <CardDescription>Best value for serious soccer families</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-6">
                <span className="text-4xl font-bold">$69</span>
                <span className="text-muted-foreground">/year</span>
                <div className="text-sm text-muted-foreground mt-1">
                  That&apos;s just <span className="font-semibold text-foreground">$5.75/mo</span>
                  {" "}
                  <span className="line-through">$83.88</span>
                  <span className="text-green-600 font-medium ml-1">Save $14.88</span>
                </div>
              </div>
              <ul className="space-y-3">
                {FEATURES.map((feature, index) => (
                  <li key={index} className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center mt-0.5">
                      <Check className="w-3 h-3 text-primary" />
                    </div>
                    <div>
                      <span className="text-sm font-medium">{feature.title}</span>
                      <p className="text-xs text-muted-foreground">{feature.text}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full"
                size="lg"
                onClick={(e) => {
                  e.stopPropagation();
                  handleUpgrade("yearly");
                }}
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
                    Get Started - Best Value
                  </>
                )}
              </Button>
            </CardFooter>
          </Card>
        </div>

        {/* Trust Badges */}
        <div className="mt-10 text-center">
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

        {/* Testimonials Section */}
        <div className="mt-16 max-w-4xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8 font-display">
            Trusted by Soccer Families Nationwide
          </h2>
          <div className="grid md:grid-cols-3 gap-6">
            {TESTIMONIALS.map((testimonial, index) => (
              <Card key={index} variant="elevated" className="text-left">
                <CardContent className="pt-6">
                  <div className="flex gap-1 mb-3">
                    {[...Array(5)].map((_, i) => (
                      <Star key={i} className="w-4 h-4 fill-yellow-400 text-yellow-400" />
                    ))}
                  </div>
                  <p className="text-sm text-muted-foreground mb-4 italic">
                    &ldquo;{testimonial.quote}&rdquo;
                  </p>
                  <div>
                    <p className="text-sm font-medium">{testimonial.author}</p>
                    <p className="text-xs text-muted-foreground">{testimonial.detail}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Feature Comparison: Free vs Premium */}
        <div className="mt-16 max-w-2xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8 font-display">
            Free vs PitchRank+
          </h2>
          <div className="border rounded-lg overflow-hidden">
            <div className="grid grid-cols-3 bg-muted/50 px-4 py-3 text-sm font-medium">
              <span>Feature</span>
              <span className="text-center">Free</span>
              <span className="text-center text-primary">PitchRank+</span>
            </div>
            {[
              { feature: "View Rankings", free: true, premium: true },
              { feature: "Team Detail Pages", free: false, premium: true },
              { feature: "AI Insights", free: false, premium: true },
              { feature: "Team Comparisons", free: false, premium: true },
              { feature: "Watchlist", free: false, premium: true },
              { feature: "Match Predictions", free: false, premium: true },
              { feature: "Edit/Merge Teams", free: false, premium: true },
            ].map((row, index) => (
              <div
                key={index}
                className={`grid grid-cols-3 px-4 py-3 text-sm ${
                  index % 2 === 0 ? "bg-background" : "bg-muted/20"
                }`}
              >
                <span>{row.feature}</span>
                <span className="text-center">
                  {row.free ? (
                    <Check className="w-4 h-4 text-green-500 mx-auto" />
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </span>
                <span className="text-center">
                  <Check className="w-4 h-4 text-primary mx-auto" />
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* FAQ Section */}
        <div className="mt-16 max-w-2xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8 font-display">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            <div>
              <h3 className="font-semibold mb-2">Can I cancel anytime?</h3>
              <p className="text-muted-foreground text-sm">
                Yes! You can cancel your subscription at any time. Your premium
                access will continue until the end of your current billing
                period. No questions asked.
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
            <div>
              <h3 className="font-semibold mb-2">
                How often are rankings updated?
              </h3>
              <p className="text-muted-foreground text-sm">
                Rankings are recalculated every Monday using our 13-layer algorithm
                (v53e + ML). We process data from 25,000+ teams across all major
                youth soccer platforms weekly.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">
                Can I switch between monthly and yearly?
              </h3>
              <p className="text-muted-foreground text-sm">
                Yes! You can switch plans at any time from your account settings.
                If you switch to yearly, you&apos;ll receive a prorated credit for any
                remaining time on your monthly plan.
              </p>
            </div>
          </div>
        </div>

        {/* Final CTA */}
        <div className="mt-16 text-center pb-8">
          <h2 className="text-2xl md:text-3xl font-bold font-display mb-4">
            Ready to get the full picture?
          </h2>
          <p className="text-muted-foreground mb-6 max-w-lg mx-auto">
            Join thousands of soccer families using PitchRank+ to make smarter decisions.
          </p>
          <Button
            size="lg"
            onClick={() => handleUpgrade(selectedPlan)}
            disabled={loadingPlan !== null}
            className="px-8"
          >
            <Crown className="w-4 h-4 mr-2" />
            {selectedPlan === "yearly" ? "Start for $5.75/mo" : "Start for $6.99/mo"}
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
          <p className="text-xs text-muted-foreground mt-3">
            Cancel anytime. No commitment required.
          </p>
        </div>
      </div>
    </div>
  );
}
