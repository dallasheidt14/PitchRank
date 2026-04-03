import type { Metadata } from 'next';
import { BASE_URL } from '@/lib/constants';

export const metadata: Metadata = {
  title: 'Social Media Infographics',
  description:
    'Generate shareable youth soccer rankings graphics for Instagram, Twitter, and Facebook. Create top 10 leaderboards, team spotlights, and more.',
  alternates: {
    canonical: `${BASE_URL}/infographics`,
  },
  openGraph: {
    title: 'Social Media Infographics | PitchRank',
    description: 'Generate shareable youth soccer rankings graphics for social media.',
    url: `${BASE_URL}/infographics`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Social Media Infographics | PitchRank',
    description: 'Generate shareable youth soccer rankings graphics for social media.',
  },
};

export default function InfographicsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
