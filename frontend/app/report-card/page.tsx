import type { Metadata } from 'next';
import { ReportCardForm } from '@/components/ReportCardForm';
import { ReportCardPreview } from '@/components/ReportCardPreview';
import { BASE_URL } from '@/lib/constants';

export const metadata: Metadata = {
  title: 'Free Team Report Card',
  description:
    "Get your youth soccer team's free report card — national & state rank, PowerScore, record, trend, and last 5 games. Delivered as a PDF in 60 seconds.",
  alternates: {
    canonical: `${BASE_URL}/report-card`,
  },
  openGraph: {
    title: 'Free Team Report Card | PitchRank',
    description:
      'See where your team really stands. National & state rank, PowerScore, record, and recent results — free PDF in 60 seconds.',
    url: `${BASE_URL}/report-card`,
    siteName: 'PitchRank',
    type: 'website',
  },
};

const STATS = [
  { value: '1.1M+', label: 'Games Analyzed' },
  { value: '126K+', label: 'Teams Ranked' },
  { value: '50', label: 'States Covered' },
];

const FAQS = [
  {
    q: 'Is this really free?',
    a: 'Yes. No credit card, no trial. The report card is a free PDF delivered to your inbox in about 60 seconds.',
  },
  {
    q: 'How accurate are the rankings?',
    a: 'Every team is rated by our proprietary rating engine using real game data from GotSport, MLS NEXT, SincSports, AthleteOne, and TGS — over 1.1 million games across 50 states. Rankings update every Monday.',
  },
  {
    q: 'What if I can’t find my team?',
    a: "Try widening the age or state filter, or check the team's club name. If you still can't find them, they may not have enough scored games yet (we require a few completed matches before rating).",
  },
  {
    q: 'Will you spam me?',
    a: "No. We'll send the report card immediately, then a small handful of follow-up emails with tips for reading the data. Unsubscribe anytime with one click.",
  },
];

export default function ReportCardPage() {
  return (
    <main className="min-h-screen bg-background">
      {/* Hero */}
      <section className="bg-[#0B5345] py-14 md:py-20 px-4 relative overflow-hidden">
        {/* Diagonal stripe motif */}
        <div
          className="absolute inset-0 opacity-10 pointer-events-none"
          style={{
            backgroundImage:
              'repeating-linear-gradient(45deg, #F4D03F, #F4D03F 2px, transparent 2px, transparent 28px)',
          }}
          aria-hidden="true"
        />
        <div className="max-w-4xl mx-auto text-center relative">
          <p className="font-oswald text-xs md:text-sm uppercase tracking-widest text-[#F4D03F] font-bold mb-4">
            Free Team Report Card
          </p>
          <h1 className="font-oswald text-4xl md:text-6xl font-bold text-white tracking-wide mb-5 leading-tight">
            Stop guessing where your team really stands.
          </h1>
          <p className="text-white/90 text-lg md:text-xl max-w-2xl mx-auto">
            A free PDF report card — national & state rank, PowerScore, record, and last 5 games — delivered in about 60
            seconds.
          </p>

          {/* Stats bar */}
          <div className="flex items-center justify-center gap-8 md:gap-14 mt-10">
            {STATS.map((stat) => (
              <div key={stat.label} className="text-center">
                <div className="font-oswald text-2xl md:text-3xl font-bold text-[#F4D03F]">{stat.value}</div>
                <div className="text-[10px] md:text-xs uppercase tracking-wider text-white/70 font-oswald mt-1">
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Form + Preview */}
      <section className="px-4 py-12 md:py-16 -mt-6">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-8 lg:gap-12 items-start">
          <div className="order-2 lg:order-1">
            <ReportCardForm />
          </div>
          <div className="order-1 lg:order-2">
            <div className="lg:sticky lg:top-8">
              <p className="font-oswald text-xs uppercase tracking-widest text-muted-foreground font-bold mb-3 hidden lg:block">
                Here&apos;s what you&apos;ll get
              </p>
              <ReportCardPreview />
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="bg-muted/30 px-4 py-14 md:py-16">
        <div className="max-w-2xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-8">
            Frequently asked
          </h2>
          <div className="space-y-5">
            {FAQS.map((faq) => (
              <details
                key={faq.q}
                className="group bg-background rounded-lg border border-border p-5 [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex items-center justify-between cursor-pointer list-none font-semibold">
                  <span>{faq.q}</span>
                  <span className="ml-4 text-[#0B5345] transition-transform group-open:rotate-45 text-xl leading-none">
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed">{faq.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
