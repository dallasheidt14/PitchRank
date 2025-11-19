import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Navigation } from "@/components/Navigation";
import { Toaster } from "@/components/ui/Toaster";
import { StructuredData } from "@/components/StructuredData";
import { Footer } from "@/components/Footer";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";

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
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://pitchrank.io"),
  title: {
    default: "PitchRank — Youth Soccer Rankings",
    template: "%s | PitchRank",
  },
  description: "Data-powered youth soccer team rankings and performance analytics. Compare U10-U18 boys and girls teams nationally and across all 50 states.",
  keywords: [
    "youth soccer rankings",
    "soccer team rankings",
    "youth soccer",
    "club soccer rankings",
    "soccer power rankings",
    "U10 soccer",
    "U12 soccer",
    "U14 soccer",
    "U16 soccer",
    "U18 soccer",
    "soccer analytics",
  ],
  authors: [{ name: "PitchRank" }],
  creator: "PitchRank",
  publisher: "PitchRank",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  icons: {
    icon: "/logos/favicon.ico",
    shortcut: "/logos/favicon.ico",
    apple: "/logos/pitchrank-symbol.svg",
  },
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: "PitchRank",
    title: "PitchRank — Youth Soccer Rankings",
    description: "Data-powered youth soccer team rankings and performance analytics. Compare U10-U18 boys and girls teams nationally and across all 50 states.",
    images: [
      {
        url: "/logos/pitchrank-wordmark.svg",
        width: 1200,
        height: 630,
        alt: "PitchRank - Youth Soccer Rankings",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "PitchRank — Youth Soccer Rankings",
    description: "Data-powered youth soccer team rankings and performance analytics. Compare U10-U18 boys and girls teams nationally and across all 50 states.",
    images: ["/logos/pitchrank-wordmark.svg"],
    creator: "@pitchrank",
    site: "@pitchrank",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
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
        {/* Structured Data for SEO */}
        <StructuredData />

        {/* Google Analytics */}
        <GoogleAnalytics measurementId={process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID} />

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
        className={`${geistSans.variable} ${geistMono.variable} antialiased transition-colors duration-300 ease-in-out flex flex-col min-h-screen`}
      >
        <Providers>
          <Navigation />
          <main className="flex-1 bg-background text-foreground">
            {children}
          </main>
          <Footer />
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
