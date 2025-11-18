import type { NextConfig } from "next";

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

  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'images.pitchrank.com',
      },
    ],
  },
};

export default nextConfig;
