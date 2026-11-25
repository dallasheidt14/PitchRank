'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { X } from 'lucide-react';
import { useInCampaignPeriod, useLivePromotion } from '@/hooks/useLivePromotion';
import { recordClickAttribution } from '@/lib/attribution';
import { trackPromotionEvent } from '@/lib/events';
import { formatCountdown, isInSaleAudience } from '@/lib/promotions';

/** Set on `<html>` while the banner shows; `globals.css` grows `--site-header-height` by the banner's 2.5rem. */
const PROMO_BANNER_VISIBLE_CLASS = 'promo-banner-visible';

const DISMISSED_KEY = 'pitchrank_promo_banner_dismissed';

/** The viewer as Navigation's own `useUser()` call sees it; the banner never fetches a session itself. */
interface PromotionBannerProps {
  user: unknown;
  profile: { plan: string } | null;
  isLoading: boolean;
  error: unknown;
}

/** The sale this session dismissed, if any. */
function readDismissedId(): string | null {
  try {
    return window.sessionStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

/** The sale, one line pinned above the menu. Outside a campaign period nothing below mounts, so no page asks for it. */
export function PromotionBanner(props: PromotionBannerProps) {
  return useInCampaignPeriod() ? <LivePromotionBanner {...props} /> : null;
}

function LivePromotionBanner({ user, profile, isLoading, error }: PromotionBannerProps) {
  const pathname = usePathname();
  const { promotion, isLive, preview, remainingMs } = useLivePromotion({ profile });
  // Only ever rendered on the client (useInCampaignPeriod is false on the server), so storage is readable here.
  const [dismissedId, setDismissedId] = useState(readDismissedId);
  const viewTracked = useRef(false);

  const visible =
    isLive &&
    promotion !== null &&
    dismissedId !== promotion.id &&
    // A buyer who just paid while signed out would otherwise be invited to buy again.
    pathname !== '/upgrade/success' &&
    isInSaleAudience({ user, profile, isLoading, error, preview });

  useEffect(() => {
    if (!visible) return;
    document.documentElement.classList.add(PROMO_BANNER_VISIBLE_CLASS);
    return () => document.documentElement.classList.remove(PROMO_BANNER_VISIBLE_CLASS);
  }, [visible]);

  useEffect(() => {
    if (!visible || !promotion || viewTracked.current) return;
    viewTracked.current = true;
    trackPromotionEvent(promotion, 'banner_view', { source: 'banner' });
  }, [visible, promotion]);

  if (!visible || !promotion) return null;

  const onUpgradePage = pathname === '/upgrade';
  const href = onUpgradePage
    ? '#sale'
    : `/upgrade?campaign=${encodeURIComponent(promotion.campaign)}&source=banner${preview ? '&promo_preview=1' : ''}`;
  const onClaim = () => {
    // On /upgrade the link only scrolls, so the page's own URL never says the banner sent them.
    recordClickAttribution({ campaign: promotion.campaign, source: 'banner' });
    trackPromotionEvent(promotion, 'banner_click', { source: 'banner' });
  };
  const dismiss = () => {
    try {
      window.sessionStorage.setItem(DISMISSED_KEY, promotion.id);
    } catch {
      // Storage can be unavailable (private browsing); the banner still hides for this page load.
    }
    setDismissedId(promotion.id);
  };
  const linkClass = 'shrink-0 font-semibold text-accent underline-offset-4 hover:underline';

  return (
    <div
      role="region"
      aria-label={promotion.copy.cardLabel}
      data-testid="promotion-banner"
      className="safe-top bg-primary text-primary-foreground"
    >
      <div className="container mx-auto flex h-10 items-center gap-3 px-3 sm:px-4 text-sm">
        <p className="min-w-0 flex-1 truncate">
          <span className="hidden md:inline font-display font-semibold tracking-wide">
            {promotion.copy.bannerDesktop}
          </span>
          <span className="md:hidden font-display font-semibold">{promotion.copy.bannerMobile}</span>
          <span className="hidden md:inline ml-3 tabular-nums text-accent" data-testid="promotion-banner-countdown">
            Ends in {formatCountdown(remainingMs)}
          </span>
        </p>
        {onUpgradePage ? (
          <a href={href} onClick={onClaim} className={linkClass}>
            Claim Offer
          </a>
        ) : (
          <Link href={href} onClick={onClaim} className={linkClass}>
            Claim Offer
          </Link>
        )}
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss the sale banner"
          className="shrink-0 -mr-2 flex h-10 w-10 items-center justify-center rounded text-primary-foreground/80 hover:text-primary-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
