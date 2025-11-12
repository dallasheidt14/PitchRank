"use client";

import Image from "next/image";
import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";

export function Navigation() {
  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 items-center justify-between px-4">
        <Link 
          href="/" 
          className="flex items-center space-x-2 transition-colors duration-300 hover:opacity-80"
          aria-label="PitchRank home"
        >
          <Image
            src="/logos/pitchrank-symbol.svg"
            alt="PitchRank Logo"
            width={32}
            height={32}
            className="dark:hidden"
          />
          <Image
            src="/logos/pitchrank-logo-dark.png"
            alt="PitchRank Logo"
            width={120}
            height={32}
            className="hidden dark:block"
          />
          <span className="sr-only">PitchRank Home</span>
        </Link>
        
        <nav className="flex items-center gap-6">
          <Link
            href="/"
            className="text-sm font-medium transition-colors duration-300 hover:text-primary"
            aria-label="Home page"
          >
            Home
          </Link>
          <Link
            href="/rankings/national/u12/male"
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
      </div>
    </header>
  );
}

