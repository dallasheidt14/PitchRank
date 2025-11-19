"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { GlobalSearch } from "./GlobalSearch";
import { Button } from "./ui/button";

export function Navigation() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 items-center justify-between gap-3 sm:gap-4 px-3 sm:px-4">
        <Link 
          href="/" 
          className="flex items-center transition-colors duration-300 hover:opacity-80 flex-shrink-0"
          aria-label="PitchRank home"
          onClick={() => setMobileMenuOpen(false)}
        >
          <Image
            src="/logos/pitchrank-logo-white.svg"
            alt="PitchRank"
            width={140}
            height={32}
            className="h-6 sm:h-8 w-auto dark:hidden"
            priority
          />
          <Image
            src="/logos/pitchrank-logo-black.svg"
            alt="PitchRank"
            width={140}
            height={32}
            className="h-6 sm:h-8 w-auto hidden dark:block"
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
            className="text-sm font-medium transition-colors duration-300 hover:text-primary"
            aria-label="Home page"
          >
            Home
          </Link>
          <Link
            href="/rankings"
            className="text-sm font-medium transition-colors duration-300 hover:text-primary"
            aria-label="Rankings page"
          >
            Rankings
          </Link>
          <Link
            href="/compare"
            className="text-sm font-medium transition-colors duration-300 hover:text-primary"
            aria-label="Compare teams page"
          >
            Compare
          </Link>
          <Link
            href="/methodology"
            className="text-sm font-medium transition-colors duration-300 hover:text-primary"
            aria-label="Methodology page"
          >
            Methodology
          </Link>
          <ThemeToggle />
        </nav>

        {/* Mobile: Search + Menu Button */}
        <div className="flex lg:hidden items-center gap-2 sm:gap-3">
          <div className="flex-1 max-w-xs">
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
          <nav className="container px-4 py-4 space-y-3">
            <Link
              href="/"
              className="block text-sm font-medium transition-colors duration-300 hover:text-primary py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Home
            </Link>
            <Link
              href="/rankings"
              className="block text-sm font-medium transition-colors duration-300 hover:text-primary py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Rankings
            </Link>
            <Link
              href="/compare"
              className="block text-sm font-medium transition-colors duration-300 hover:text-primary py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Compare
            </Link>
            <Link
              href="/methodology"
              className="block text-sm font-medium transition-colors duration-300 hover:text-primary py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              Methodology
            </Link>
            <div className="pt-2 border-t">
              <ThemeToggle />
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

