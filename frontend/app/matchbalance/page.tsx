import type { Metadata } from 'next';
import Image from 'next/image';
import { FileText, FileSpreadsheet, RefreshCw } from 'lucide-react';
import { MatchBalanceInquiryForm } from '@/components/MatchBalanceInquiryForm';
import { BlogFAQSchema } from '@/components/BlogFAQSchema';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { BASE_URL } from '@/lib/constants';
import type { FAQ } from '@/lib/blog-faqs';
import EVENT_PRICING from '@/lib/matchbalance-pricing.json';

export const metadata: Metadata = {
  title: 'MatchBalance Tournament Seeding Sheets',
  description:
    'MatchBalance gives tournament directors a ranked seeding sheet for every age group and gender, built from PitchRank ratings, before the bracket meeting. Fixed prices and a free sample.',
  alternates: {
    canonical: `${BASE_URL}/matchbalance`,
  },
  openGraph: {
    title: 'MatchBalance Tournament Seeding Sheets | PitchRank',
    description:
      'A ranked seeding sheet for every age group and gender in your tournament, built from PitchRank ratings. Fixed prices, free sample.',
    url: `${BASE_URL}/matchbalance`,
    siteName: 'PitchRank',
    type: 'website',
    // A page-level openGraph replaces the root one wholesale, image included.
    images: [{ url: '/opengraph-image.png', width: 1200, height: 630, alt: 'PitchRank — Youth Soccer Rankings' }],
  },
};

export const revalidate = 3600;

const DELIVERABLES = [
  {
    icon: FileText,
    title: 'A PDF sheet for every age group',
    body: 'Each covered age group and gender gets its own sheet: teams grouped into tiers of the closest projected matchups, with close calls and teams that need manual placement flagged for your review.',
  },
  {
    icon: FileSpreadsheet,
    title: 'An editable team file',
    body: 'The same teams as a CSV you can sort, annotate and bring into your own bracket work.',
  },
  {
    icon: RefreshCw,
    title: 'One update before your bracket review',
    body: 'One consolidated refresh that picks up late entries, withdrawals and the latest weekly ratings.',
  },
];

const STEPS = [
  'Send us your accepted-team list or event link.',
  'Receive a free sample: one age group and gender from your tournament.',
  'Receive one fixed price for your whole event.',
  'Receive the package, plus one update before your bracket review.',
];

const COHORT_PRICING = [
  { cohorts: '1 cohort', price: '$49' },
  { cohorts: '3 cohorts', price: '$129' },
  { cohorts: '6 cohorts', price: '$239' },
];

const FAQS: FAQ[] = [
  {
    question: 'Which age groups are supported?',
    answer:
      'Every age group PitchRank ranks: U10 through U19, boys and girls. Send your whole list either way; any team PitchRank has no current rank for still appears on the sheet.',
  },
  {
    question: 'What happens to teams PitchRank has no current rank for?',
    answer:
      'They stay on the sheet in their own section, marked for manual placement. PitchRank has no current rank for these teams, so nothing is guessed for them; you place them using recent results, prior division or club input.',
  },
  {
    question: 'How quickly will I hear back?',
    answer:
      'We reply to every request within one business day. Delivery timing depends on your event and your bracket review date, so we confirm it in your quote.',
  },
  {
    question: 'What does the update cover?',
    answer:
      'One consolidated refresh of your package before your bracket review. It picks up late entries and withdrawals and re-reads the latest weekly PitchRank ratings.',
  },
  {
    question: 'What do you need from me to get started?',
    answer:
      'Your accepted-team list, or a link to your event page. A list exported from any registration platform works. You do not need to collect team resumes or past results for us.',
  },
  {
    question: 'What does MatchBalance not do?',
    answer:
      'It does not place teams, build brackets or schedules, or contact clubs. It gives you evidence about each team; every flight and bracket decision stays with you.',
  },
];

export default function MatchBalancePage() {
  return (
    <main className="min-h-screen bg-background">
      <BreadcrumbSchema
        items={[
          { name: 'Home', href: '/' },
          { name: 'MatchBalance', href: '/matchbalance' },
        ]}
      />
      <BlogFAQSchema faqs={FAQS} />

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
            For tournament directors
          </p>
          <h1 className="font-oswald text-4xl md:text-6xl font-bold text-white tracking-wide mb-5 leading-tight">
            Seed your tournament without the team-by-team research.
          </h1>
          <p className="text-white/90 text-lg md:text-xl max-w-2xl mx-auto">
            Skip the hours spent digging through team resumes and old scores. MatchBalance lines up every accepted team
            in each age group and gender using PitchRank ratings built from real game results, so your bracket review
            starts from evidence.
          </p>
          <a
            href="#inquiry"
            className="inline-flex items-center justify-center mt-8 rounded-md bg-[#F4D03F] px-6 h-11 font-semibold text-[#0B5345] hover:bg-[#f7dc6f] transition-colors"
          >
            Request a free sample
          </a>
        </div>
      </section>

      {/* What you get */}
      <section className="px-4 py-12 md:py-16">
        <div className="max-w-6xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-8">What you get</h2>
          <div className="grid gap-6 md:grid-cols-3">
            {DELIVERABLES.map((item) => (
              <Card key={item.title} className="border-0 shadow-lg">
                <CardContent className="p-6">
                  <item.icon className="w-8 h-8 text-[#0B5345] mb-3" aria-hidden="true" />
                  <h3 className="font-oswald text-xl font-bold tracking-wide mb-2">{item.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{item.body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="text-center text-muted-foreground mt-8 max-w-2xl mx-auto">
            You keep full control of flights and brackets. MatchBalance does not place teams; it gives you the evidence
            to place them.
          </p>
        </div>
      </section>

      {/* Sample */}
      <section className="bg-muted/30 px-4 py-14 md:py-16">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold tracking-wide mb-3">See a real sheet</h2>
          <p className="text-muted-foreground mb-8">U13 Boys from the San Antonio Labor Cup 2026, page one.</p>
          <a
            href="/matchbalance/sample-u13-boys.pdf"
            className="block rounded-lg border border-border bg-background shadow-xl overflow-hidden"
          >
            <Image
              src="/matchbalance/sample-u13-boys.png"
              width={1224}
              height={1584}
              sizes="(max-width: 800px) 100vw, 768px"
              alt="Page one of the MatchBalance seeding sheet for U13 Boys at the San Antonio Labor Cup 2026"
              className="w-full h-auto"
            />
          </a>
          <a
            href="/matchbalance/sample-u13-boys.pdf"
            className="inline-block mt-6 text-[#0B5345] font-semibold underline underline-offset-2 hover:no-underline"
          >
            Download the full sample PDF
          </a>
        </div>
      </section>

      {/* How it works */}
      <section className="px-4 py-12 md:py-16">
        <div className="max-w-3xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-8">How it works</h2>
          <ol className="space-y-4">
            {STEPS.map((step, index) => (
              <li key={step} className="flex items-start gap-4">
                <span className="flex-shrink-0 w-9 h-9 rounded-full bg-[#0B5345] text-[#F4D03F] font-oswald font-bold flex items-center justify-center">
                  {index + 1}
                </span>
                <span className="pt-1.5">{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Pricing */}
      <section className="bg-muted/30 px-4 py-14 md:py-16">
        <div className="max-w-2xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-8">
            MatchBalance Pricing
          </h2>
          <Card variant="flat">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Total teams</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {EVENT_PRICING.map((row) => (
                    <TableRow key={row.teams}>
                      <TableCell>{row.teams}</TableCell>
                      <TableCell className="text-right font-semibold">{row.price}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <p className="italic text-center text-muted-foreground mt-10 mb-3">
            Need help with only part of your tournament?
          </p>
          <h3 className="font-oswald text-2xl font-bold text-center tracking-wide mb-4">À la carte</h3>
          <Card variant="flat">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cohorts</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {COHORT_PRICING.map((row) => (
                    <TableRow key={row.cohorts}>
                      <TableCell>{row.cohorts}</TableCell>
                      <TableCell className="text-right font-semibold">{row.price}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <p className="text-center mt-8">
            <span className="font-semibold">Every package includes:</span> MatchBalance PDF, editable team file, and one
            update before your bracket review.
          </p>
          <p className="text-center mt-2">
            <span className="font-semibold">Free sample:</span> one age group + gender from your tournament.
          </p>
        </div>
      </section>

      {/* FAQ */}
      <section className="px-4 py-14 md:py-16">
        <div className="max-w-2xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-8">
            Frequently asked
          </h2>
          <div className="space-y-5">
            {FAQS.map((faq) => (
              <details
                key={faq.question}
                className="group bg-background rounded-lg border border-border p-5 [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex items-center justify-between cursor-pointer list-none font-semibold">
                  <span>{faq.question}</span>
                  <span className="ml-4 text-[#0B5345] transition-transform group-open:rotate-45 text-xl leading-none">
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed">{faq.answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Inquiry */}
      <section id="inquiry" className="bg-muted/30 px-4 py-14 md:py-16 scroll-mt-16">
        <div className="max-w-2xl mx-auto">
          <h2 className="font-oswald text-3xl md:text-4xl font-bold text-center tracking-wide mb-3">
            Ask about your tournament
          </h2>
          <p className="text-center text-muted-foreground mb-8">
            Tell us about your event. We reply within one business day.
          </p>
          <MatchBalanceInquiryForm />
        </div>
      </section>
    </main>
  );
}
