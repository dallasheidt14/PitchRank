"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Menu, X, Star, User, LogOut, LogIn } from "lucide-react";
import { GlobalSearch } from "./GlobalSearch";
import { Button } from "./ui/button";
import { useUser } from "@/hooks/useUser";

export function Navigation() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { user, isLoading, signOut } = useUser();

  const handleSignOut = async () => {
    await signOut();
    setMobileMenuOpen(false);
    // Redirect to home after sign out
    window.location.href = "/";
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 safe-top">
      <div className="container flex h-16 items-center justify-between gap-3 sm:gap-4 px-3 sm:px-4">
        <Link
          href="/"
          className="flex items-center transition-colors duration-300 hover:opacity-80 flex-shrink-0"
          aria-label="PitchRank home"
          onClick={() => setMobileMenuOpen(false)}
        >
          <Image
            src="/logos/logo-primary.svg"
            alt="PitchRank"
            width={200}
            height={50}
            className="h-6 sm:h-8 w-auto"
            sizes="(max-width: 640px) 120px, 200px"
            priority
          />
          <span className="sr-only">PitchRank Home</span>
        </Link>

        {/* Desktop Search */}
        <div className="hidden md:flex flex-1 justify-center max-w-md mx-4">
          <GlobalSearch />
        </div>

        {/* Desktop Navigation */}
        <nav className="hidden lg:flex items-center gap-4 xl:gap-6 flex-shrink-0">
          <Link
            href="/"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Home page"
          >
            Home
          </Link>
          <Link
            href="/rankings"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Rankings page"
          >
            Rankings
          </Link>
          <Link
            href="/compare"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Compare/Predict teams page"
          >
            Compare/Predict
          </Link>
          <Link
            href="/watchlist"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent flex items-center gap-1.5"
            aria-label="Watchlist page"
          >
            <Star className="h-3.5 w-3.5" />
            Watchlist
          </Link>
          <Link
            href="/methodology"
            className="text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-accent"
            aria-label="Methodology page"
          >
            Methodology
          </Link>

          {/* Auth Section */}
          {!isLoading && (
            <>
              {user ? (
                <div className="flex items-center gap-3 ml-2 pl-4 border-l">
                  <span className="text-sm text-muted-foreground truncate max-w-[120px]" title={user.email ?? ""}>
                    {user.email?.split("@")[0]}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSignOut}
                    className="gap-1.5"
                    aria-label="Sign out"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span className="hidden xl:inline">Sign out</span>
                  </Button>
                </div>
              ) : (
                <Link href="/login">
                  <Button variant="outline" size="sm" className="gap-1.5 ml-2">
                    <LogIn className="h-3.5 w-3.5" />
                    Sign in
                  </Button>
                </Link>
              )}
            </>
          )}
        </nav>

        {/* Mobile: Search + Menu Button */}
        <div className="flex lg:hidden items-center gap-2 sm:gap-3">
          <div className="flex-1 min-w-0">
            <GlobalSearch />
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="flex-shrink-0 min-w-[44px] min-h-[44px]"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? (
              <X className="h-6 w-6" />
            ) : (
              <Menu className="h-6 w-6" />
            )}
          </Button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-t bg-background">
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
                        className="w-full text-sm font-semibold uppercase tracking-wide transition-colors duration-300 hover:text-destructive hover:bg-destructive/10 py-3 px-2 rounded-md min-h-[44px] flex items-center gap-2"
                      >
                        <LogOut className="h-4 w-4" />
                        Sign out
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
