import type { NextConfig } from "next";
import bundleAnalyzer from '@next/bundle-analyzer';

const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
});

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Remove console.logs in production builds (keep error/warn for debugging)
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production'
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

  // Security headers
  async headers() {
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
        ],
      },
    ];
  },
};

export default withBundleAnalyzer(nextConfig);
