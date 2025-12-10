"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Crown, ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { launchConfetti } from "@/components/ui/confetti";

export default function UpgradeSuccessPage() {
  const [showConfetti, setShowConfetti] = useState(false);

  useEffect(() => {
    // Trigger confetti animation on mount
    if (!showConfetti) {
      setShowConfetti(true);
      launchConfetti();
    }
  }, [showConfetti]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30 flex items-center justify-center p-4">
      <Card variant="elevated" className="max-w-lg w-full text-center">
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
                Full access to all rankings
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-4 h-4 text-primary flex-shrink-0" />
                Unlimited team comparisons
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-4 h-4 text-primary flex-shrink-0" />
                Advanced analytics & insights
              </li>
              <li className="flex items-center gap-2">
                <Check className="w-4 h-4 text-primary flex-shrink-0" />
                Real-time ranking updates
              </li>
            </ul>
          </div>

          {/* CTA Buttons */}
          <div className="flex flex-col gap-3">
            <Button size="lg" asChild>
              <Link href="/watchlist">
                Go to Your Watchlist
                <ArrowRight className="w-4 h-4 ml-2" />
              </Link>
            </Button>
            <Button variant="outline" size="lg" asChild>
              <Link href="/rankings">
                Explore Rankings
              </Link>
            </Button>
          </div>

          {/* Receipt Note */}
          <p className="text-xs text-muted-foreground">
            A receipt has been sent to your email address. You can manage your
            subscription at any time from your account settings.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
