import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Navigation } from "@/components/Navigation";
import { Toaster } from "@/components/ui/Toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  fallback: ["system-ui", "sans-serif"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  fallback: ["ui-monospace", "monospace"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://pitchrank.com"),
  title: "PitchRank — Youth Soccer Rankings",
  description: "Data-powered youth soccer team rankings and performance analytics.",
  icons: {
    icon: "/logos/favicon.ico",
    shortcut: "/logos/favicon.ico",
  },
  openGraph: {
    title: "PitchRank — Youth Soccer Rankings",
    description: "Data-powered youth soccer team rankings and performance analytics.",
    images: ["/logos/pitchrank-wordmark.svg"],
  },
};

export const viewport: Viewport = {
  themeColor: "#101828",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Favicon */}
        <link rel="icon" href="/logos/favicon.ico" sizes="any" />
        <link rel="shortcut icon" href="/logos/favicon.ico" />

        {/* SEO Meta Tags */}
        <meta name="description" content="Data-powered youth soccer team rankings and performance analytics." />

        {/* Optional: social/SEO icons */}
        <meta property="og:image" content="/logos/pitchrank-wordmark.svg" />
        <meta property="og:title" content="PitchRank — Youth Soccer Rankings" />
        <meta property="og:description" content="Data-powered youth soccer team rankings and performance analytics." />

        {/* Prevent Flash of Theme (FOT) by applying theme before React hydration */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  const theme = localStorage.getItem('theme');
                  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  const shouldBeDark = theme === 'dark' || (!theme && prefersDark);
                  if (shouldBeDark) {
                    document.documentElement.classList.add('dark');
                  }
                } catch (e) {
                  // Graceful degradation if localStorage is unavailable
                }
              })();
            `,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased transition-colors duration-300 ease-in-out`}
      >
        <Providers>
          <Navigation />
          <main className="min-h-screen bg-background text-foreground">
            {children}
          </main>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
