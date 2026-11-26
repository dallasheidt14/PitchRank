'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowRight, X } from 'lucide-react';
import { useInCampaignPeriod, useLivePromotion } from '@/hooks/useLivePromotion';
import { recordClickAttribution } from '@/lib/attribution';
import { trackPromotionEvent } from '@/lib/events';
import { formatCountdown, isInSaleAudience } from '@/lib/promotions';

/** Set on `<html>` while the banner shows; `globals.css` adds the banner's height to `--site-header-height`. */
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
  const linkClass =
    'flex shrink-0 items-center gap-1 rounded-md bg-primary px-2 py-1.5 text-xs font-bold uppercase tracking-wide text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 md:px-3';
  const claimLabel = (
    <>
      Claim<span className="hidden md:inline"> Offer</span>
      <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
    </>
  );

  return (
    <div
      role="region"
      aria-label={promotion.copy.cardLabel}
      data-testid="promotion-banner"
      className="pt-[var(--promo-banner-pad-top)] pb-2 bg-accent text-primary"
    >
      <div className="container relative mx-auto flex h-10 items-center justify-center gap-2 pl-2 pr-10 sm:pl-10 md:gap-3 md:px-11">
        <p className="min-w-0 truncate font-semibold">
          <span className="font-display text-sm md:text-base font-bold uppercase md:tracking-wide">
            {promotion.copy.bannerLabel}
          </span>{' '}
          <span className="hidden md:inline text-[15px]">{promotion.copy.bannerDesktop}</span>
          <span className="md:hidden text-[13px]">{promotion.copy.bannerMobile}</span>
          <span
            className="hidden lg:inline-block ml-3 rounded-full bg-primary px-2.5 py-0.5 align-middle text-xs tabular-nums text-accent"
            data-testid="promotion-banner-countdown"
          >
            Ends in {formatCountdown(remainingMs)}
          </span>
        </p>
        {onUpgradePage ? (
          <a href={href} onClick={onClaim} className={linkClass}>
            {claimLabel}
          </a>
        ) : (
          <Link href={href} onClick={onClaim} className={linkClass}>
            {claimLabel}
          </Link>
        )}
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss the sale banner"
          className="absolute right-0 top-0 flex h-10 w-10 items-center justify-center rounded text-primary/80 hover:text-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
