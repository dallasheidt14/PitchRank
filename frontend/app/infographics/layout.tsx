import type { Metadata } from 'next';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Social Media Infographics',
  description: 'Generate shareable youth soccer rankings graphics for Instagram, Twitter, and Facebook. Create top 10 leaderboards, team spotlights, and more.',
  alternates: {
    canonical: `${baseUrl}/infographics`,
  },
  openGraph: {
    title: 'Social Media Infographics | PitchRank',
    description: 'Generate shareable youth soccer rankings graphics for social media.',
    url: `${baseUrl}/infographics`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Social Media Infographics | PitchRank',
    description: 'Generate shareable youth soccer rankings graphics for social media.',
  },
};

export default function InfographicsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
