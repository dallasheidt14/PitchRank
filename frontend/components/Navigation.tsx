'use client';

import { useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Menu, X, Star, User, LogOut, LogIn } from 'lucide-react';
import { GlobalSearch, GLOBAL_SEARCH_INPUT_IDS } from './GlobalSearch';
import { FeedbackTrigger } from './FeedbackTrigger';
import { Button } from './ui/button';
import { useUser } from '@/hooks/useUser';

export function Navigation() {
  const router = useRouter();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const { user, isLoading, signOut } = useUser();

  const handleSignOut = async () => {
    try {
      setIsSigningOut(true);
      await signOut();
      setMobileMenuOpen(false);
      // Use router for client-side navigation instead of full page reload
      router.push('/');
      router.refresh();
    } catch (error) {
      console.error('Sign out error:', error);
      // Fallback to the logout endpoint if client signOut fails (POST only —
      // GET logout is not exposed, to prevent forced-logout CSRF)
      await fetch('/logout', { method: 'POST' });
      router.push('/');
      router.refresh();
    } finally {
      setIsSigningOut(false);
    }
  };

  return (
    <header
      data-testid="main-navigation"
      className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 safe-top"
    >
      <div className="container flex h-16 items-center justify-between gap-3 sm:gap-4 px-3 sm:px-4">
        <Link
          href="/"
          className="flex items-center transition-colors duration-300 hover:opacity-80 flex-shrink-0"
          aria-label="PitchRank home"
          onClick={() => setMobileMenuOpen(false)}
        >
          <Image
            src="/logos/logo-primary.svg"
            alt="PitchRank - Youth Soccer Rankings"
            width={200}
            height={50}
            className="h-6 sm:h-8 w-auto"
            sizes="(max-width: 640px) 120px, 200px"
            priority
          />
          <span className="sr-only">PitchRank Home</span>
        </Link>

        {/* Desktop Search */}
        <div className="hidden lg:flex flex-1 justify-center max-w-md mx-4">
          <GlobalSearch inputId={GLOBAL_SEARCH_INPUT_IDS.desktop} />
        </div>

        {/* Desktop Navigation */}
        <nav data-testid="desktop-nav" className="hidden lg:flex items-center gap-3 xl:gap-6 flex-shrink-0">
          <Link
            href="/"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Home page"
            data-testid="nav-home"
          >
            Home
          </Link>
          <Link
            href="/rankings"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Rankings page"
            data-testid="nav-rankings"
          >
            Rankings
          </Link>
          <Link
            href="/compare"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Compare/Predict teams page"
            data-testid="nav-compare"
          >
            Compare/Predict
          </Link>
          <Link
            href="/watchlist"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent flex items-center gap-1.5"
            aria-label="Watchlist page"
            data-testid="nav-watchlist"
          >
            <Star className="h-3.5 w-3.5" />
            Watchlist
          </Link>
          <Link
            href="/methodology"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Methodology page"
            data-testid="nav-methodology"
          >
            Methodology
          </Link>
          <Link
            href="/blog"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Blog page"
            data-testid="nav-blog"
          >
            Blog
          </Link>

          <FeedbackTrigger />

          {/* Auth Section */}
          {!isLoading && (
            <>
              {user ? (
                <div className="flex items-center gap-3 ml-2 pl-4 border-l">
                  <span
                    className="hidden xl:block text-sm text-muted-foreground truncate max-w-[120px]"
                    title={user.email ?? ''}
                  >
                    {user.email?.split('@')[0]}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSignOut}
                    disabled={isSigningOut}
                    className="gap-1.5 relative z-10"
                    aria-label="Sign out"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span className="hidden xl:inline">{isSigningOut ? 'Signing out...' : 'Sign out'}</span>
                  </Button>
                </div>
              ) : (
                <Button asChild variant="outline" size="sm" className="gap-1.5 ml-2">
                  <Link href="/login" data-testid="nav-signin" aria-label="Sign in">
                    <LogIn className="h-3.5 w-3.5" />
                    <span className="hidden xl:inline">Sign in</span>
                  </Link>
                </Button>
              )}
            </>
          )}
        </nav>

        {/* Mobile: Search + Menu Button (feedback lives in the menu so the search hint fits) */}
        <div className="flex lg:hidden items-center gap-2 sm:gap-3">
          <div className="flex-1 min-w-0">
            <GlobalSearch inputId={GLOBAL_SEARCH_INPUT_IDS.mobile} />
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="flex-shrink-0 min-w-[44px] min-h-[44px]"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
            data-testid="mobile-menu-toggle"
          >
            {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </Button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-t bg-background" data-testid="mobile-menu">
          <nav className="container px-4 py-4 space-y-1">
            <Link
              href="/"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              Home
            </Link>
            <Link
              href="/rankings"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              Rankings
            </Link>
            <Link
              href="/compare"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              Compare/Predict
            </Link>
            <Link
              href="/watchlist"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center gap-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              <Star className="h-4 w-4" />
              Watchlist
            </Link>
            <Link
              href="/methodology"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              Methodology
            </Link>
            <Link
              href="/blog"
              className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center"
              onClick={() => setMobileMenuOpen(false)}
            >
              Blog
            </Link>
            <FeedbackTrigger variant="menu" />

            {/* Mobile Auth Section */}
            <div className="pt-4 mt-4 border-t">
              {!isLoading && (
                <>
                  {user ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground">
                        <User className="h-4 w-4" />
                        <span className="truncate">{user.email}</span>
                      </div>
                      <button
                        onClick={handleSignOut}
                        disabled={isSigningOut}
                        className="w-full text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-destructive hover:bg-destructive/10 py-3 px-2 rounded-md min-h-[44px] flex items-center gap-2 disabled:opacity-50"
                      >
                        <LogOut className="h-4 w-4" />
                        {isSigningOut ? 'Signing out...' : 'Sign out'}
                      </button>
                    </div>
                  ) : (
                    <Link
                      href="/login"
                      className="block text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent hover:bg-accent/10 py-3 px-2 rounded-md min-h-[44px] flex items-center gap-2"
                      onClick={() => setMobileMenuOpen(false)}
                    >
                      <LogIn className="h-4 w-4" />
                      Sign in
                    </Link>
                  )}
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
