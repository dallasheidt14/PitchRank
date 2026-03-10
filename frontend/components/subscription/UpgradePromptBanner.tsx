"use client";

import Link from "next/link";
import { Crown, ArrowRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { trackPaywallUpgradeClicked } from "@/lib/events";

interface UpgradePromptBannerProps {
  /** The feature being gated */
  feature: string;
  /** Short headline */
  headline?: string;
  /** Descriptive text */
  description?: string;
  /** Where this banner appears (for analytics) */
  location: string;
  /** Whether the banner can be dismissed */
  dismissible?: boolean;
  /** Compact mode for inline use */
  compact?: boolean;
}

export function UpgradePromptBanner({
  feature,
  headline = "Unlock Premium Features",
  description,
  location,
  dismissible = false,
  compact = false,
}: UpgradePromptBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const handleClick = () => {
    trackPaywallUpgradeClicked({ feature, location });
  };

  if (compact) {
    return (
      <div className="flex items-center gap-3 px-4 py-2.5 bg-primary/5 border border-primary/10 rounded-lg">
        <Crown className="w-4 h-4 text-primary flex-shrink-0" />
        <span className="text-sm text-muted-foreground flex-1">
          {description || `${feature} is a premium feature`}
        </span>
        <Link href={`/upgrade?source=${encodeURIComponent(location)}`} onClick={handleClick}>
          <Button size="sm" variant="outline" className="text-xs whitespace-nowrap">
            Upgrade
            <ArrowRight className="w-3 h-3 ml-1" />
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="relative bg-gradient-to-r from-primary/5 via-primary/10 to-primary/5 border border-primary/20 rounded-lg p-6 text-center">
      {dismissible && (
        <button
          onClick={() => setDismissed(true)}
          className="absolute top-3 right-3 text-muted-foreground hover:text-foreground"
          aria-label="Dismiss"
        >
          <X className="w-4 h-4" />
        </button>
      )}
      <Crown className="w-8 h-8 text-primary mx-auto mb-3" />
      <h3 className="font-semibold text-lg mb-2">{headline}</h3>
      <p className="text-sm text-muted-foreground mb-4 max-w-md mx-auto">
        {description ||
          `Get full access to ${feature.toLowerCase()} and all premium analytics with PitchRank+.`}
      </p>
      <Link href={`/upgrade?source=${encodeURIComponent(location)}`} onClick={handleClick}>
        <Button size="default">
          <Crown className="w-4 h-4 mr-2" />
          Upgrade to PitchRank+
          <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </Link>
      <p className="text-xs text-muted-foreground mt-3">
        Starting at $5.75/mo. Cancel anytime.
      </p>
    </div>
  );
}
