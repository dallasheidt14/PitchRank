import type { Metadata } from 'next';
import { ReportCardForm } from '@/components/ReportCardForm';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Free Team Report Card',
  description:
    "Get your team's free season report card — rankings, trends, and insights powered by PitchRank's 13-layer algorithm. 25,000+ teams. Updated weekly.",
  alternates: {
    canonical: `${baseUrl}/report-card`,
  },
  openGraph: {
    title: 'Free Team Report Card | PitchRank',
    description:
      "See how your team stacks up. Rankings, strength profile, and recent results — powered by 25K+ teams and a 13-layer algorithm.",
    url: `${baseUrl}/report-card`,
    siteName: 'PitchRank',
    type: 'website',
  },
};

export default function ReportCardPage() {
  return (
    <main className="min-h-screen bg-background">
      {/* Hero section */}
      <section className="bg-[#0B5345] py-16 px-4">
        <div className="max-w-2xl mx-auto text-center">
          <h1 className="font-oswald text-4xl md:text-5xl font-bold text-[#F4D03F] mb-4 tracking-wide">
            Your team&apos;s report card is ready.
          </h1>
          <p className="text-white/90 text-lg md:text-xl max-w-xl mx-auto">
            Rankings, trends, and insights — powered by 25K+ teams and a 13-layer algorithm. Free. Delivered in seconds.
          </p>
        </div>
      </section>

      {/* Form section */}
      <section className="px-4 -mt-8">
        <div className="max-w-md mx-auto">
          <ReportCardForm />
        </div>
      </section>

      {/* Social proof / info */}
      <section className="max-w-2xl mx-auto px-4 py-12 text-center">
        <div className="grid grid-cols-3 gap-6 mb-8">
          <div>
            <p className="font-oswald text-2xl font-bold text-foreground">25,000+</p>
            <p className="text-sm text-muted-foreground">Teams ranked</p>
          </div>
          <div>
            <p className="font-oswald text-2xl font-bold text-foreground">13</p>
            <p className="text-sm text-muted-foreground">Algorithm layers</p>
          </div>
          <div>
            <p className="font-oswald text-2xl font-bold text-foreground">Weekly</p>
            <p className="text-sm text-muted-foreground">Updates</p>
          </div>
        </div>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          Your report card includes national rank, state rank, PowerScore, strength profile, season record, and recent results. All from real game data.
        </p>
      </section>
    </main>
  );
}
