"use client";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, Crown, ArrowRight, Sparkles, Search, Eye, BarChart3, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { launchConfetti } from "@/components/ui/confetti";
import { trackSubscriptionCompleted } from "@/lib/events";

const ONBOARDING_STEPS = [
  {
    icon: Search,
    title: "Find Your Team",
    description: "Search for your player's team in rankings",
    href: "/rankings",
    cta: "Browse Rankings",
  },
  {
    icon: Eye,
    title: "Add to Watchlist",
    description: "Track rank changes and get insights",
    href: "/watchlist",
    cta: "Go to Watchlist",
  },
  {
    icon: BarChart3,
    title: "Compare Teams",
    description: "Head-to-head analysis with predictions",
    href: "/compare",
    cta: "Compare Teams",
  },
];

export default function UpgradeSuccessPage() {
  return (
    <Suspense>
      <UpgradeSuccessContent />
    </Suspense>
  );
}

function UpgradeSuccessContent() {
  const searchParams = useSearchParams();
  const [showConfetti, setShowConfetti] = useState(false);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<"syncing" | "synced" | "error" | null>(null);

  useEffect(() => {
    // Trigger confetti animation on mount
    if (!showConfetti) {
      setShowConfetti(true);
      launchConfetti();
      trackSubscriptionCompleted();
    }
  }, [showConfetti]);

  // Sync subscription status from Stripe as webhook fallback
  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    if (!sessionId || syncStatus) return;

    setSyncStatus("syncing");
    fetch("/api/stripe/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.synced) {
          setSyncStatus("synced");
          console.log(`Subscription synced: plan=${data.plan}, status=${data.status}`);
        } else {
          console.error("Sync failed:", data.error);
          setSyncStatus("error");
        }
      })
      .catch((err) => {
        console.error("Sync fetch error:", err);
        setSyncStatus("error");
      });
  }, [searchParams, syncStatus]);

  const handleShare = async () => {
    const shareData = {
      title: "PitchRank - Youth Soccer Rankings",
      text: "Check out PitchRank for comprehensive youth soccer rankings and analytics!",
      url: "https://www.pitchrank.io",
    };

    if (navigator.share) {
      try {
        await navigator.share(shareData);
      } catch (_err) {
        // User cancelled share dialog - no action needed
      }
    } else {
      // Fallback: copy to clipboard
      try {
        await navigator.clipboard.writeText(shareData.url);
        setShareStatus("Link copied!");
        setTimeout(() => setShareStatus(null), 2000);
      } catch (_err) {
        setShareStatus("Could not copy link");
        setTimeout(() => setShareStatus(null), 2000);
      }
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full space-y-6">
        <Card variant="elevated" className="text-center">
          <CardHeader className="pb-4">
            {/* Success Icon */}
            <div className="mx-auto mb-6 relative">
              <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center">
                <div className="w-14 h-14 rounded-full bg-primary flex items-center justify-center">
                  <Check className="w-8 h-8 text-primary-foreground" strokeWidth={3} />
                </div>
              </div>
              <div className="absolute -top-1 -right-1">
                <Sparkles className="w-6 h-6 text-yellow-500" />
              </div>
            </div>

            <CardTitle className="text-3xl font-display flex items-center justify-center gap-2">
              <Crown className="w-8 h-8 text-primary" />
              Welcome to PitchRank+
            </CardTitle>
            <CardDescription className="text-base mt-2">
              Your subscription is now active. You have full access to all premium
              features.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-6">
            {/* Benefits Reminder */}
            <div className="bg-muted/50 rounded-lg p-4 text-left">
              <h3 className="font-semibold mb-3 text-sm">
                You now have access to:
              </h3>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  Full access to all rankings &amp; team detail pages
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  Unlimited team comparisons with win predictions
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  AI-powered insights (persona, consistency, trends)
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  Watchlist with real-time rank tracking
                </li>
              </ul>
            </div>

            {/* Receipt Note */}
            <p className="text-xs text-muted-foreground">
              A receipt has been sent to your email address. You can manage your
              subscription at any time from your account settings.
            </p>
          </CardContent>
        </Card>

        {/* Onboarding Steps */}
        <div>
          <h3 className="text-lg font-semibold text-center mb-4">
            Get started in 3 steps
          </h3>
          <div className="grid gap-4 md:grid-cols-3">
            {ONBOARDING_STEPS.map((step, index) => (
              <Card key={index} variant="elevated" className="text-center">
                <CardContent className="pt-6 pb-4">
                  <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-3">
                    <step.icon className="w-5 h-5 text-primary" />
                  </div>
                  <h4 className="font-medium text-sm mb-1">{step.title}</h4>
                  <p className="text-xs text-muted-foreground mb-3">
                    {step.description}
                  </p>
                  <Button variant="outline" size="sm" asChild className="text-xs">
                    <Link href={step.href}>
                      {step.cta}
                      <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Share CTA */}
        <div className="text-center">
          <p className="text-sm text-muted-foreground mb-2">
            Know other soccer parents or coaches?
          </p>
          <Button variant="outline" size="sm" onClick={handleShare}>
            <Share2 className="w-4 h-4 mr-2" />
            {shareStatus || "Share PitchRank"}
          </Button>
        </div>
      </div>
    </div>
  );
}
