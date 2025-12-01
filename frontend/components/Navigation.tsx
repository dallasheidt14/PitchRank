"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Menu, X, Star } from "lucide-react";
import { GlobalSearch } from "./GlobalSearch";
import { Button } from "./ui/button";

export function Navigation() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
          </nav>
        </div>
      )}
    </header>
  );
}

