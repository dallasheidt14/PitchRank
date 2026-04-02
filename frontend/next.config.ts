import type { NextConfig } from 'next';
import bundleAnalyzer from '@next/bundle-analyzer';

const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
});

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Remove console.logs in production builds (keep error/warn for debugging)
  compiler: {
    removeConsole:
      process.env.NODE_ENV === 'production'
        ? {
            exclude: ['error', 'warn'],
          }
        : false,
  },

  // Experimental optimizations for better tree-shaking and bundle size
  experimental: {
    optimizePackageImports: ['recharts', 'lucide-react', 'date-fns'],
  },

  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'images.pitchrank.io',
      },
    ],
  },

  // 301 redirects from non-www to www for SEO canonical URL
  async redirects() {
    return [
      {
        source: '/:path*',
        has: [
          {
            type: 'host',
            value: 'pitchrank.io',
          },
        ],
        destination: 'https://www.pitchrank.io/:path*',
        permanent: true,
      },
    ];
  },

  // Security headers
  async headers() {
    // unsafe-eval is needed for Next.js dev mode (HMR/source maps) but not production
    const cspUnsafeEval = process.env.NODE_ENV === 'production' ? '' : " 'unsafe-eval'";

    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload',
          },
          {
            key: 'Content-Security-Policy',
            value: `default-src 'self'; script-src 'self' 'unsafe-inline'${cspUnsafeEval} https://www.googletagmanager.com https://www.google-analytics.com; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none';`,
          },
        ],
      },
    ];
  },
};

export default withBundleAnalyzer(nextConfig);
