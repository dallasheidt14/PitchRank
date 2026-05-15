'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Check, Zap, Crown, Shield, TrendingUp, Star, Pencil, BarChart3, Eye, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { startCheckout } from '@/lib/stripe/client';
import { useUser } from '@/hooks/useUser';
import { trackUpgradePageViewed, trackPlanSelected, trackCheckoutInitiated } from '@/lib/events';

// Price IDs from Stripe Dashboard (configured via environment variables)
const PRICE_IDS = {
  MONTHLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || '',
  YEARLY: process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || '',
};

const FEATURES = [
  {
    icon: TrendingUp,
    title: 'Full Rankings Access',
    text: "See every team's PowerScore, national & state rank across all age groups",
  },
  { icon: Star, title: 'Team Comparisons', text: 'Head-to-head comparison tool with win probability predictions' },
  { icon: BarChart3, title: 'AI Insights', text: 'Season Truth, consistency scores, and team persona analysis' },
  { icon: Eye, title: 'Watchlist', text: 'Track your favorite teams with real-time rank change alerts' },
  { icon: Pencil, title: 'Edit Access', text: 'Merge duplicate teams and find missing game history' },
];

const SOCIAL_PROOF_STATS = [
  { value: '1.1M+', label: 'Games Analyzed' },
  { value: '126K+', label: 'Teams Ranked' },
  { value: '50', label: 'States Covered' },
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
  const [loadingPlan, setLoadingPlan] = useState<'monthly' | 'yearly' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<'monthly' | 'yearly'>('yearly');

  const source = searchParams.get('next') || searchParams.get('source') || 'direct';
  const pageViewTracked = useRef(false);

  // Track page view once per mount, regardless of param changes
  useEffect(() => {
    if (pageViewTracked.current) return;
    pageViewTracked.current = true;
    trackUpgradePageViewed({ source });
  }, [source]);

  const handleUpgrade = async (plan: 'monthly' | 'yearly') => {
    // Wait for auth state to resolve (user or null)
    if (userLoading) return;

    trackPlanSelected({
      plan,
      price: plan === 'monthly' ? 6.99 : 69.99,
      source,
    });

    setLoadingPlan(plan);
    setError(null);

    try {
      const priceId = plan === 'monthly' ? PRICE_IDS.MONTHLY : PRICE_IDS.YEARLY;
      if (!priceId) {
        console.error('[UpgradePage] Missing Stripe price ID for plan:', plan, {
          monthly: !!PRICE_IDS.MONTHLY,
          yearly: !!PRICE_IDS.YEARLY,
        });
        throw new Error('Pricing is not configured. Please contact support.');
      }
      trackCheckoutInitiated({ plan, price: plan === 'monthly' ? 6.99 : 69.99 });
      await startCheckout(priceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
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
            Stop guessing where your team really stands.
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Real game data on every team your kid plays — across every league. PitchRank+ gives you the full picture for
            a $10,000+ club decision.
          </p>
        </div>

        {/* Social Proof Bar */}
        <div className="flex items-center justify-center gap-8 md:gap-12 mb-10">
          {SOCIAL_PROOF_STATS.map((stat) => (
            <div key={stat.label} className="text-center">
              <div className="text-2xl md:text-3xl font-bold font-display text-primary">{stat.value}</div>
              <div className="text-xs text-muted-foreground">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Error Message */}
        {error && (
          <div className="max-w-md mx-auto mb-8 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-center">
            <p className="text-destructive text-sm">{error}</p>
          </div>
        )}

        {/* Plan Toggle (Mobile-Friendly) */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <button
            onClick={() => setSelectedPlan('monthly')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedPlan === 'monthly'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setSelectedPlan('yearly')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors relative ${
              selectedPlan === 'yearly'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
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
              selectedPlan === 'monthly' ? 'ring-2 ring-primary' : ''
            }`}
            onClick={() => setSelectedPlan('monthly')}
          >
            <CardHeader>
              <CardTitle className="text-2xl">Monthly</CardTitle>
              <CardDescription>Month-to-month flexibility</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-2">
                <span className="text-4xl font-bold">$6.99</span>
                <span className="text-muted-foreground">/month</span>
              </div>
              <p className="text-sm text-green-600 font-medium mb-1">7-day free trial</p>
              <p className="text-xs text-muted-foreground mb-4">After trial: $6.99/month. Cancel anytime.</p>
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
            <CardFooter className="flex flex-col gap-2">
              <Button
                className="w-full"
                size="lg"
                variant={selectedPlan === 'monthly' ? 'default' : 'outline'}
                onClick={(e) => {
                  e.stopPropagation();
                  handleUpgrade('monthly');
                }}
                disabled={loadingPlan !== null || userLoading}
              >
                {loadingPlan === 'monthly' ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">&#9696;</span>
                    Processing...
                  </span>
                ) : (
                  <>
                    Start Free Trial
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </>
                )}
              </Button>
              <p className="text-xs text-muted-foreground">7-day free trial · Cancel anytime</p>
            </CardFooter>
          </Card>

          {/* Yearly Plan */}
          <Card
            variant="primary"
            className={`relative cursor-pointer transition-all ${
              selectedPlan === 'yearly' ? 'ring-2 ring-primary' : ''
            }`}
            onClick={() => setSelectedPlan('yearly')}
          >
            <div className="absolute -top-3 left-1/2 -translate-x-1/2">
              <Badge className="bg-green-600 text-white shadow-lg">Best Value — 2 Months Free</Badge>
            </div>
            <CardHeader>
              <CardTitle className="text-2xl">Yearly</CardTitle>
              <CardDescription>Best value for serious soccer families</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-2">
                <span className="text-4xl font-bold">$69.99</span>
                <span className="text-muted-foreground">/year</span>
                <div className="text-sm text-muted-foreground mt-1">
                  That&apos;s just <span className="font-semibold text-foreground">$5.83/mo</span>{' '}
                  <span className="line-through">$83.88</span>
                  <span className="text-green-600 font-medium ml-1">Save $13.89</span>
                </div>
                <p className="text-xs text-muted-foreground mt-2 italic">
                  Less than one tournament weekend — for a full year of clarity on a $10,000+ decision.
                </p>
              </div>
              <p className="text-sm text-green-600 font-medium mb-1">7-day free trial</p>
              <p className="text-xs text-muted-foreground mb-4">After trial: $69.99/year. Cancel anytime.</p>
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
            <CardFooter className="flex flex-col gap-2">
              <Button
                className="w-full"
                size="lg"
                onClick={(e) => {
                  e.stopPropagation();
                  handleUpgrade('yearly');
                }}
                disabled={loadingPlan !== null || userLoading}
              >
                {loadingPlan === 'yearly' ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin">&#9696;</span>
                    Processing...
                  </span>
                ) : (
                  <>
                    <Crown className="w-4 h-4 mr-2" />
                    Start Free Trial — Best Value
                  </>
                )}
              </Button>
              <p className="text-xs text-muted-foreground">7-day free trial · Cancel anytime</p>
            </CardFooter>
          </Card>
        </div>

        {/* Trust Badges */}
        <div className="mt-10 text-center">
          <p className="text-sm text-muted-foreground mb-4">Secure payment powered by Stripe</p>
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
          {!userLoading && !user && (
            <p className="mt-6 text-xs text-muted-foreground">
              Already a PitchRank+ member?{' '}
              <Link href="/login?next=/upgrade" className="text-primary hover:underline">
                Sign in to manage your subscription
              </Link>
            </p>
          )}
        </div>

        {/* Feature Comparison: Free vs Premium */}
        <div className="mt-16 max-w-2xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8 font-display">Free vs PitchRank+</h2>
          <div className="border rounded-lg overflow-hidden">
            <div className="grid grid-cols-3 bg-muted/50 px-4 py-3 text-sm font-medium">
              <span>Feature</span>
              <span className="text-center">Free</span>
              <span className="text-center text-primary">PitchRank+</span>
            </div>
            {[
              { feature: 'View Rankings', free: true, premium: true },
              { feature: 'Team Detail Pages', free: false, premium: true },
              { feature: 'AI Insights', free: false, premium: true },
              { feature: 'Team Comparisons', free: false, premium: true },
              { feature: 'Watchlist', free: false, premium: true },
              { feature: 'Match Predictions', free: false, premium: true },
              { feature: 'Edit/Merge Teams', free: false, premium: true },
            ].map((row, index) => (
              <div
                key={index}
                className={`grid grid-cols-3 px-4 py-3 text-sm ${index % 2 === 0 ? 'bg-background' : 'bg-muted/20'}`}
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
          <h2 className="text-2xl font-bold text-center mb-8 font-display">Frequently Asked Questions</h2>
          <div className="space-y-6">
            <div>
              <h3 className="font-semibold mb-2">Can I cancel anytime?</h3>
              <p className="text-muted-foreground text-sm">
                Yes! You can cancel your subscription at any time. Your premium access will continue until the end of
                your current billing period. No questions asked.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">What payment methods do you accept?</h3>
              <p className="text-muted-foreground text-sm">
                We accept all major credit cards (Visa, MasterCard, American Express) through our secure payment
                processor, Stripe.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">Will I be charged automatically?</h3>
              <p className="text-muted-foreground text-sm">
                Yes, your subscription will automatically renew at the end of each billing period. You&apos;ll receive
                an email reminder before each renewal.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">How often are rankings updated?</h3>
              <p className="text-muted-foreground text-sm">
                Rankings are recalculated every Monday using our proprietary rating engine. We process data from
                126,000+ teams and 1.1M+ games across all major youth soccer platforms.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">Can I switch between monthly and yearly?</h3>
              <p className="text-muted-foreground text-sm">
                Yes! You can switch plans at any time from your account settings. If you switch to yearly, you&apos;ll
                receive a prorated credit for any remaining time on your monthly plan.
              </p>
            </div>
          </div>
        </div>

        {/* Final CTA */}
        <div className="mt-16 text-center pb-8">
          <h2 className="text-2xl md:text-3xl font-bold font-display mb-4">
            Don&apos;t make a $10K club decision on a hunch.
          </h2>
          <p className="text-muted-foreground mb-6 max-w-lg mx-auto">
            Start your free 7-day trial. See where your team really stands before next tryouts.
          </p>
          <Button
            size="lg"
            onClick={() => handleUpgrade(selectedPlan)}
            disabled={loadingPlan !== null || userLoading}
            className="px-8"
          >
            <Crown className="w-4 h-4 mr-2" />
            Start Free 7-Day Trial
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
          <p className="text-xs text-muted-foreground mt-3">
            7-day free trial. Cancel anytime. No commitment required.
          </p>
        </div>
      </div>
    </div>
  );
}
