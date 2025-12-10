"use client";

import { useState } from "react";
import { Crown, CreditCard, Calendar, AlertCircle, ExternalLink } from "lucide-react";
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
import { useUser, hasPremiumAccess, type UserProfile } from "@/hooks/useUser";
import { openCustomerPortal } from "@/lib/stripe/client";
import Link from "next/link";

interface SubscriptionStatusProps {
  profile: UserProfile;
}

function formatDate(dateString: string | null): string {
  if (!dateString) return "N/A";
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function getStatusColor(status: string | null): string {
  switch (status) {
    case "active":
    case "trialing":
      return "bg-green-500/10 text-green-600 border-green-500/20";
    case "past_due":
      return "bg-yellow-500/10 text-yellow-600 border-yellow-500/20";
    case "canceled":
      return "bg-red-500/10 text-red-600 border-red-500/20";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export function SubscriptionStatus({ profile }: SubscriptionStatusProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isPremium = hasPremiumAccess(profile);

  const handleManageSubscription = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await openCustomerPortal();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open billing portal");
      setIsLoading(false);
    }
  };

  // Admin users don't need subscription management
  if (profile.plan === "admin") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Crown className="w-5 h-5 text-primary" />
            Admin Access
          </CardTitle>
          <CardDescription>
            You have full admin access to all features.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // Free user - show upgrade prompt
  if (!isPremium) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Crown className="w-5 h-5" />
            Subscription
          </CardTitle>
          <CardDescription>
            You&apos;re currently on the free plan
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Upgrade to PitchRank+ for unlimited access to all rankings, team
            comparisons, and advanced analytics.
          </p>
        </CardContent>
        <CardFooter>
          <Button asChild>
            <Link href="/upgrade">
              <Crown className="w-4 h-4 mr-2" />
              Upgrade to Premium
            </Link>
          </Button>
        </CardFooter>
      </Card>
    );
  }

  // Premium user - show subscription details
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Crown className="w-5 h-5 text-primary" />
            PitchRank+ Subscription
          </CardTitle>
          <Badge className={getStatusColor(profile.subscription_status)}>
            {profile.subscription_status || "Unknown"}
          </Badge>
        </div>
        <CardDescription>
          Manage your premium subscription
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Subscription details */}
        <div className="grid gap-3">
          <div className="flex items-center gap-3 text-sm">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <span className="text-muted-foreground">Next billing date:</span>
            <span className="font-medium">
              {formatDate(profile.subscription_period_end)}
            </span>
          </div>
          {profile.stripe_customer_id && (
            <div className="flex items-center gap-3 text-sm">
              <CreditCard className="w-4 h-4 text-muted-foreground" />
              <span className="text-muted-foreground">Payment method:</span>
              <span className="font-medium">Manage in billing portal</span>
            </div>
          )}
        </div>

        {/* Past due warning */}
        {profile.subscription_status === "past_due" && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
            <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-yellow-600">
                Payment Failed
              </p>
              <p className="text-xs text-yellow-600/80 mt-1">
                Please update your payment method to continue your subscription.
              </p>
            </div>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}
      </CardContent>
      <CardFooter className="flex gap-3">
        <Button
          variant="outline"
          onClick={handleManageSubscription}
          disabled={isLoading || !profile.stripe_customer_id}
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin">&#9696;</span>
              Loading...
            </span>
          ) : (
            <>
              <ExternalLink className="w-4 h-4 mr-2" />
              Manage Billing
            </>
          )}
        </Button>
      </CardFooter>
    </Card>
  );
}

/**
 * Standalone component that fetches user data itself
 * Use when you don't have access to the profile from a parent component
 */
export function SubscriptionStatusWithData() {
  const { profile, isLoading } = useUser();

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <div className="h-6 w-48 bg-muted animate-pulse rounded" />
          <div className="h-4 w-32 bg-muted animate-pulse rounded mt-2" />
        </CardHeader>
        <CardContent>
          <div className="h-20 bg-muted animate-pulse rounded" />
        </CardContent>
      </Card>
    );
  }

  if (!profile) {
    return null;
  }

  return <SubscriptionStatus profile={profile} />;
}
