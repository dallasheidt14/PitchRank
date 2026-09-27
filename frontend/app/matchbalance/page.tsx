import type { Metadata } from 'next';
import Image from 'next/image';
import {
  ArrowRight,
  ArrowUp,
  BarChart3,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  Flag,
  RefreshCw,
  ShieldCheck,
  Target,
  UsersRound,
} from 'lucide-react';
import { MatchBalanceInquiryForm } from '@/components/MatchBalanceInquiryForm';
import { BlogFAQSchema } from '@/components/BlogFAQSchema';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { FAQ } from '@/lib/blog-faqs';
import { BASE_URL } from '@/lib/constants';
import EVENT_PRICING from '@/lib/matchbalance-pricing.json';

export const metadata: Metadata = {
  title: 'MatchBalance Tournament Seeding',
  description:
    'MatchBalance turns PitchRank PowerScores and tournament-specific matchup analysis into a practical seeding cheat sheet for tournament directors.',
  alternates: {
    canonical: `${BASE_URL}/matchbalance`,
  },
  openGraph: {
    title: 'MatchBalance Tournament Seeding | PitchRank',
    description:
      'Rankings tell you who is stronger. MatchBalance shows tournament directors what that means for the field in front of them.',
    url: `${BASE_URL}/matchbalance`,
    siteName: 'PitchRank',
    type: 'website',
    // A page-level openGraph replaces the root one wholesale, image included.
    images: [{ url: '/opengraph-image.png', width: 1200, height: 630, alt: 'PitchRank — Youth Soccer Rankings' }],
  },
};

export const revalidate = 3600;

const CAPABILITIES = [
  {
    icon: BarChart3,
    number: '01',
    title: 'MatchBalance Seed review',
    body: 'PowerScore creates the starting order. MatchBalance then looks for cases where the nearby matchup evidence consistently supports reviewing a team higher. One unusual matchup is not enough: a move proposal must hold up against the same nearby teams and pass multiple safeguards.',
    footer: 'PowerScore remains visible and remains the ordering baseline.',
  },
  {
    icon: Flag,
    number: '02',
    title: 'Competitive Breaks',
    body: 'Not every difference between two seeds matters equally. MatchBalance identifies places where a meaningful PowerScore step is also supported by nearby matchup evidence, giving directors a quick visual guide to where a natural flight boundary may exist.',
    footer: 'A recommendation—not a mandatory division.',
  },
  {
    icon: UsersRound,
    number: '03',
    title: 'Very-close groups',
    body: 'Sometimes the useful answer is that the exact order matters less. MatchBalance identifies small ranges that stay within strict matchup limits so you can spend your time on the placement decisions with meaningful competitive consequences.',
    footer: 'Close does not mean identical or interchangeable.',
  },
  {
    icon: ShieldCheck,
    number: '04',
    title: 'Matchup risk, not just rank difference',
    body: 'MatchBalance compares every eligible pairing using PitchRank’s matchup model. It considers projected goal separation and four-goal blowout risk, so a group cannot look competitive on average while one team is badly overmatched.',
    footer: 'Every eligible pairing is checked, not just adjacent seeds.',
  },
];

const STEPS = [
  {
    title: 'Send us your tournament field',
    body: 'Send your accepted-team list or event link. We match the teams to PitchRank and organize each age group and gender.',
  },
  {
    title: 'PowerScore establishes the baseline',
    body: 'Each team begins in its normal PitchRank PowerScore order. MatchBalance does not alter the published PowerScore.',
  },
  {
    title: 'MatchBalance analyzes the field',
    body: 'We compare the teams throughout the cohort to find competitive matchups, material reversals, very-close ranges, supported Competitive Breaks and teams with limited evidence. Strong local-consensus evidence is raised as a move proposal for review.',
  },
  {
    title: 'You receive the seeding cheat sheet',
    body: 'Your package shows the suggested seed order, original PowerScore context, supported strength breaks and teams that need manual placement. You remain in control of flights, brackets and tournament structure.',
  },
];

const DELIVERABLES = [
  {
    icon: FileText,
    title: 'A sheet for every covered cohort',
    body: 'Each age group and gender receives its own tournament-specific seeding cheat sheet with suggested seeds, PitchRank PowerScores, supported strength markers, limited-history warnings and requested-flight context when available.',
  },
  {
    icon: FileSpreadsheet,
    title: 'An editable team file',
    body: 'Receive the same tournament field in an editable format for your internal bracket and placement workflow.',
  },
  {
    icon: RefreshCw,
    title: 'One update before bracket review',
    body: 'Your package includes one consolidated refresh for late entries, withdrawals and updated PitchRank information before your bracket review.',
  },
];

const CONTEXT_POINTS = [
  'MatchBalance does not automatically create divisions, brackets or schedules.',
  'Competitive Breaks are advisory, and very-close groups are not claims that teams are identical.',
  'Teams with insufficient information are identified for manual placement instead of being guessed into the field.',
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
    <main className="min-h-screen overflow-x-clip bg-[#f7f6f1] text-[#14231f]">
      <BreadcrumbSchema
        items={[
          { name: 'Home', href: '/' },
          { name: 'MatchBalance', href: '/matchbalance' },
        ]}
      />
      <BlogFAQSchema faqs={FAQS} />

      {/* Hero */}
      <section className="relative isolate overflow-hidden bg-[#083f35] px-4 py-16 text-white md:py-24 lg:py-28">
        <div
          className="pointer-events-none absolute inset-0 -z-10 opacity-[0.16]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,.22) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.22) 1px, transparent 1px)',
            backgroundSize: '54px 54px',
            maskImage: 'linear-gradient(to right, black, transparent 78%)',
          }}
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -right-32 -top-36 -z-10 h-[34rem] w-[34rem] rounded-full border-[96px] border-[#f4d03f]/10"
          aria-hidden="true"
        />

        <div className="mx-auto grid max-w-7xl items-center gap-12 lg:grid-cols-[1.08fr_.92fr] lg:gap-16">
          <div>
            <p className="mb-5 font-oswald text-sm font-bold uppercase tracking-[0.24em] text-[#f4d03f]">
              For tournament directors
            </p>
            <h1 className="max-w-4xl font-oswald text-5xl font-bold uppercase leading-[0.98] tracking-[-0.025em] text-white sm:text-6xl lg:text-7xl">
              Rankings tell you who&apos;s stronger.
              <span className="mt-2 block text-[#f4d03f]">MatchBalance tells you how to seed them.</span>
            </h1>
            <p className="mt-7 max-w-2xl text-xl font-medium leading-relaxed text-white/95">
              A rankings list is only the starting point.
            </p>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-white/75 md:text-lg">
              MatchBalance starts with PitchRank PowerScores, analyzes how every team in the field projects against the
              others, identifies teams in the same competitive range, flags meaningful strength breaks and raises a seed
              adjustment for review only when the nearby matchup evidence consistently supports it.
            </p>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-white/75 md:text-lg">
              The result is a tournament seeding cheat sheet built to help you make better placement decisions—not just
              another list of rankings.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
              <a
                href="#inquiry"
                className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[#f4d03f] px-6 font-bold text-[#083f35] transition-colors hover:bg-[#f7dc6f]"
              >
                Request a free sample
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </a>
              <a
                href="#sample"
                className="inline-flex h-12 items-center justify-center rounded-md border border-white/25 px-6 font-semibold text-white transition-colors hover:bg-white/10"
              >
                View the sample sheet
              </a>
            </div>
          </div>

          <div className="relative mx-auto w-full max-w-xl lg:mx-0">
            <div className="absolute -inset-4 -z-10 rotate-2 rounded-3xl bg-[#f4d03f]/15" aria-hidden="true" />
            <div className="overflow-hidden rounded-2xl border border-white/15 bg-white text-[#14231f] shadow-2xl shadow-black/25">
              <div className="flex items-center justify-between bg-[#062f28] px-5 py-4 text-white sm:px-6">
                <div>
                  <p className="font-oswald text-lg font-bold uppercase tracking-wide">Field snapshot</p>
                  <p className="text-xs text-white/60">Illustrative U14 Boys review</p>
                </div>
                <span className="rounded-full bg-[#f4d03f] px-3 py-1 text-xs font-bold text-[#083f35]">12 teams</span>
              </div>
              <div className="grid grid-cols-[3.25rem_1fr_auto] border-b border-[#d9e0dc] bg-[#edf2ef] px-5 py-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#5f6f69] sm:px-6">
                <span>Seed</span>
                <span>Team</span>
                <span>PowerScore</span>
              </div>
              {[
                ['1', 'Northstar SC', '78.4'],
                ['2', 'Capital United', '76.9'],
                ['3', 'Riverside FC', '75.8'],
              ].map(([seed, team, score]) => (
                <div
                  key={seed}
                  className="grid grid-cols-[3.25rem_1fr_auto] items-center border-b border-[#e3e8e5] px-5 py-4 sm:px-6"
                >
                  <span className="font-oswald text-xl font-bold text-[#0b5345]">{seed}</span>
                  <span className="font-semibold">{team}</span>
                  <span className="font-mono text-sm font-bold">{score}</span>
                </div>
              ))}
              <div className="flex items-center gap-3 border-b border-[#e5ca45] bg-[#fff7cc] px-5 py-3 text-xs font-bold uppercase tracking-[0.14em] text-[#695800] sm:px-6">
                <span className="h-px flex-1 bg-[#d6b900]" />
                Competitive break
                <span className="h-px flex-1 bg-[#d6b900]" />
              </div>
              {[
                ['4', 'Union Academy', '69.1'],
                ['5', 'City Select', '68.6'],
                ['6', 'Valley FC', '68.2'],
              ].map(([seed, team, score]) => (
                <div
                  key={seed}
                  className="grid grid-cols-[3.25rem_1fr_auto] items-center border-b border-[#e3e8e5] px-5 py-3.5 last:border-0 sm:px-6"
                >
                  <span className="font-oswald text-lg font-bold text-[#0b5345]">{seed}</span>
                  <span className="font-semibold">{team}</span>
                  <span className="font-mono text-sm font-bold">{score}</span>
                </div>
              ))}
              <div className="flex items-center justify-between gap-4 bg-[#edf6f2] px-5 py-3 text-sm sm:px-6">
                <span className="font-semibold text-[#0b5345]">Very close: seeds 4–6</span>
                <span className="text-xs text-[#5f6f69]">Review as one competitive neighborhood</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* More than a rankings sheet */}
      <section className="px-4 py-16 md:py-24">
        <div className="mx-auto grid max-w-6xl items-center gap-10 lg:grid-cols-[.9fr_1.1fr] lg:gap-20">
          <div>
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">
              More than a rankings sheet
            </p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase leading-tight tracking-tight text-[#0a332c] md:text-5xl">
              A ranking tells you 1 through 20.
              <span className="block text-[#0b5345]">MatchBalance explains what those numbers mean.</span>
            </h2>
          </div>
          <div className="space-y-5 text-lg leading-relaxed text-[#4d5d57]">
            <p>Two teams can sit next to each other in a ranking and still be a poor competitive matchup.</p>
            <p>Other teams may be separated by several ranking positions but project to play extremely close games.</p>
            <p>
              MatchBalance looks beyond the ranking number and analyzes the actual tournament field. For every age group
              and gender, we use PitchRank as the baseline and evaluate projected matchups across the cohort before
              producing placement guidance.
            </p>
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="bg-white px-4 py-16 md:py-24">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">
              What MatchBalance does
            </p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight text-[#0a332c] md:text-5xl">
              It turns a list into placement evidence.
            </h2>
          </div>
          <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border border-[#dfe6e2] bg-[#dfe6e2] md:grid-cols-2">
            {CAPABILITIES.map((item) => (
              <article key={item.title} className="relative bg-white p-7 md:p-9">
                <div className="flex items-center justify-between">
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#e8f1ed] text-[#0b5345]">
                    <item.icon className="h-6 w-6" aria-hidden="true" />
                  </span>
                  <span className="font-oswald text-4xl font-bold text-[#e5ebe8]">{item.number}</span>
                </div>
                <h3 className="mt-6 font-oswald text-2xl font-bold uppercase tracking-wide text-[#0a332c]">
                  {item.title}
                </h3>
                <p className="mt-3 leading-relaxed text-[#5b6964]">{item.body}</p>
                <p className="mt-5 border-l-2 border-[#f4d03f] pl-3 text-sm font-semibold text-[#0b5345]">
                  {item.footer}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="bg-[#0a332c] px-4 py-16 text-white md:py-24">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#f4d03f]">How it works</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight md:text-5xl">
              From accepted teams to a director-ready starting point.
            </h2>
          </div>
          <ol className="mt-12 grid gap-8 md:grid-cols-2 lg:grid-cols-4 lg:gap-0">
            {STEPS.map((step, index) => (
              <li
                key={step.title}
                className="relative border-white/15 lg:border-l lg:px-7 lg:first:border-l-0 lg:first:pl-0"
              >
                <span className="font-oswald text-5xl font-bold text-[#f4d03f]">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h3 className="mt-4 font-oswald text-xl font-bold uppercase tracking-wide">{step.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-white/68">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Difference */}
      <section className="px-4 py-16 md:py-24">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">The difference</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight text-[#0a332c] md:text-5xl">
              Rankings are one input. Seeding is the decision.
            </h2>
          </div>

          <div className="mt-12 grid items-stretch gap-6 lg:grid-cols-[1fr_auto_1fr]">
            <div className="rounded-2xl border border-[#d9e1dd] bg-white p-7 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#71807b]">Traditional ranking sheet</p>
              <div className="mt-6 space-y-3">
                {['Team A', 'Team B', 'Team C', 'Team D', 'Team E'].map((team, index) => (
                  <div key={team} className="flex items-center gap-4 rounded-lg bg-[#f4f6f5] px-4 py-3">
                    <span className="font-oswald text-xl font-bold text-[#73817c]">{index + 1}</span>
                    <span className="font-semibold">{team}</span>
                  </div>
                ))}
              </div>
              <p className="mt-6 text-sm leading-relaxed text-[#6b7873]">
                A clean order, but no context about the gaps.
              </p>
            </div>

            <div className="hidden items-center justify-center lg:flex" aria-hidden="true">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#f4d03f] text-[#0b5345]">
                <ArrowRight className="h-5 w-5" />
              </span>
            </div>

            <div className="overflow-hidden rounded-2xl border border-[#0b5345]/20 bg-white shadow-xl shadow-[#0b5345]/8">
              <div className="bg-[#0b5345] px-7 py-5 text-white">
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#f4d03f]">MatchBalance context</p>
                <p className="mt-1 font-oswald text-2xl font-bold uppercase">The decisions worth reviewing</p>
              </div>
              <div className="space-y-5 p-7">
                <div className="rounded-xl border border-[#dce6e1] p-4">
                  <div className="flex items-start gap-3">
                    <ArrowUp className="mt-0.5 h-5 w-5 text-[#0b7a5a]" aria-hidden="true" />
                    <div>
                      <p className="font-semibold">Review Team C for a possible move above Team B</p>
                      <p className="mt-1 text-sm text-[#65736e]">
                        The same nearby comparisons consistently support it.
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs font-bold uppercase tracking-[0.15em] text-[#695800]">
                  <span className="h-px flex-1 bg-[#d6b900]" />
                  Competitive break after seed 3
                  <span className="h-px flex-1 bg-[#d6b900]" />
                </div>
                <div className="rounded-xl bg-[#eaf3ef] p-4">
                  <div className="flex items-start gap-3">
                    <UsersRound className="mt-0.5 h-5 w-5 text-[#0b5345]" aria-hidden="true" />
                    <div>
                      <p className="font-semibold text-[#0b5345]">Very close: seeds 4–6</p>
                      <p className="mt-1 text-sm text-[#65736e]">
                        Focus less on the exact order and more on where the group belongs.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Deliverables */}
      <section className="border-y border-[#dce3df] bg-white px-4 py-16 md:py-24">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">What you get</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight text-[#0a332c] md:text-5xl">
              Practical files for the way you already build brackets.
            </h2>
          </div>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {DELIVERABLES.map((item) => (
              <article key={item.title} className="rounded-2xl border border-[#dfe6e2] bg-[#f8faf9] p-7">
                <item.icon className="h-8 w-8 text-[#0b5345]" aria-hidden="true" />
                <h3 className="mt-5 font-oswald text-xl font-bold uppercase tracking-wide text-[#0a332c]">
                  {item.title}
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-[#61706a]">{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="bg-[#edf2ef] px-4 py-16 md:py-24">
        <div className="mx-auto max-w-5xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">Pricing</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight text-[#0a332c] md:text-5xl">
              One clear price for the work you need.
            </h2>
          </div>
          <div className="mt-10 grid gap-6 lg:grid-cols-[1.15fr_.85fr]">
            <Card className="overflow-hidden border-[#d3ddd8] shadow-none" variant="flat">
              <CardContent className="p-0">
                <div className="bg-[#0b5345] px-6 py-5 text-white">
                  <p className="font-oswald text-2xl font-bold uppercase tracking-wide">Whole tournament</p>
                  <p className="mt-1 text-sm text-white/65">Every covered age group and gender</p>
                </div>
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

            <Card className="overflow-hidden border-[#d3ddd8] shadow-none" variant="flat">
              <CardContent className="p-0">
                <div className="bg-[#f4d03f] px-6 py-5 text-[#0a332c]">
                  <p className="font-oswald text-2xl font-bold uppercase tracking-wide">À la carte</p>
                  <p className="mt-1 text-sm text-[#475650]">For part of your tournament</p>
                </div>
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
          </div>
          <div className="mt-8 grid gap-3 text-center text-sm text-[#52615b] md:grid-cols-2">
            <p>
              <span className="font-semibold text-[#0a332c]">Every package includes:</span> MatchBalance PDF, editable
              team file and one update before bracket review.
            </p>
            <p>
              <span className="font-semibold text-[#0a332c]">Free sample:</span> one age group + gender from your
              tournament.
            </p>
          </div>
        </div>
      </section>

      {/* Why + important context */}
      <section className="px-4 py-16 md:py-24">
        <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-2">
          <div className="rounded-2xl bg-[#f4d03f] p-8 md:p-10">
            <Target className="h-9 w-9 text-[#0b5345]" aria-hidden="true" />
            <p className="mt-7 font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">
              Why MatchBalance
            </p>
            <h2 className="mt-3 font-oswald text-3xl font-bold uppercase leading-tight tracking-tight text-[#0a332c] md:text-4xl">
              The goal isn&apos;t to perfectly rank every team. It&apos;s to create better competitive matchups.
            </h2>
            <p className="mt-5 leading-relaxed text-[#3f4d48]">
              PitchRank provides a stable measure of team strength. MatchBalance adds tournament-specific matchup
              analysis on top of it, surfacing the decisions that deserve your attention so you spend less time
              researching teams one by one.
            </p>
          </div>

          <div className="rounded-2xl bg-[#0a332c] p-8 text-white md:p-10">
            <ShieldCheck className="h-9 w-9 text-[#f4d03f]" aria-hidden="true" />
            <p className="mt-7 font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#f4d03f]">
              Important context
            </p>
            <h2 className="mt-3 font-oswald text-3xl font-bold uppercase leading-tight tracking-tight md:text-4xl">
              MatchBalance assists the director. It doesn&apos;t replace the director.
            </h2>
            <ul className="mt-6 space-y-4">
              {CONTEXT_POINTS.map((point) => (
                <li key={point} className="flex gap-3 text-sm leading-relaxed text-white/72">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[#f4d03f]" aria-hidden="true" />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
            <p className="mt-7 border-t border-white/15 pt-6 font-semibold text-white">
              You make the final decisions. MatchBalance gives you better evidence to make them.
            </p>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="bg-white px-4 py-16 md:py-24">
        <div className="mx-auto max-w-3xl">
          <div className="text-center">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">Questions</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase tracking-tight text-[#0a332c] md:text-5xl">
              Frequently asked
            </h2>
          </div>
          <div className="mt-10 space-y-4">
            {FAQS.map((faq) => (
              <details
                key={faq.question}
                className="group rounded-xl border border-[#dce4e0] bg-[#f9fbfa] p-5 [&_summary::-webkit-details-marker]:hidden"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-[#0a332c]">
                  <span>{faq.question}</span>
                  <span className="text-xl leading-none text-[#0b5345] transition-transform group-open:rotate-45">
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-[#61706a]">{faq.answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Sample */}
      <section id="sample" className="scroll-mt-16 bg-[#e9efec] px-4 py-16 md:py-24">
        <div className="mx-auto grid max-w-6xl items-center gap-12 lg:grid-cols-[.8fr_1.2fr] lg:gap-16">
          <div>
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">Sample sheet</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase leading-tight tracking-tight text-[#0a332c] md:text-5xl">
              See what a MatchBalance sheet actually shows.
            </h2>
            <p className="mt-5 text-lg leading-relaxed text-[#586761]">
              Don&apos;t just look at another ranking list. See how MatchBalance turns a tournament field into a
              practical seeding cheat sheet with suggested seeds, PowerScore context, supported strength breaks and
              placement guidance.
            </p>
            <a
              href="/matchbalance/sample-u14-boys.pdf"
              className="mt-8 inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[#0b5345] px-6 font-bold text-white transition-colors hover:bg-[#083f35]"
            >
              View the sample MatchBalance sheet
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </a>
            <p className="mt-3 text-xs text-[#72817b]">U14 Boys · San Antonio Labor Cup 2026 · PDF</p>
          </div>
          <a
            href="/matchbalance/sample-u14-boys.pdf"
            className="group block overflow-hidden rounded-xl border border-[#cad6d0] bg-white p-2 shadow-2xl shadow-[#0b5345]/12"
            aria-label="Open the sample MatchBalance sheet PDF"
          >
            <Image
              src="/matchbalance/sample-u14-boys.png"
              width={1224}
              height={760}
              sizes="(max-width: 1024px) 100vw, 650px"
              alt="Competitive Break excerpt from the MatchBalance U14 Boys seeding sheet for the San Antonio Labor Cup 2026"
              className="h-auto w-full rounded-lg transition-transform duration-300 group-hover:scale-[1.01]"
            />
          </a>
        </div>
      </section>

      {/* Final CTA + inquiry */}
      <section id="inquiry" className="scroll-mt-16 bg-white px-4 py-16 md:py-24">
        <div className="mx-auto grid max-w-6xl items-start gap-12 lg:grid-cols-[.8fr_1.2fr] lg:gap-16">
          <div className="lg:sticky lg:top-24">
            <p className="font-oswald text-sm font-bold uppercase tracking-[0.2em] text-[#0b5345]">Free sample</p>
            <h2 className="mt-3 font-oswald text-4xl font-bold uppercase leading-tight tracking-tight text-[#0a332c] md:text-5xl">
              Give us one age group. See what MatchBalance finds.
            </h2>
            <p className="mt-5 text-lg leading-relaxed text-[#586761]">
              Send us your accepted-team list or tournament link and we&apos;ll prepare a free sample for one age group
              and gender.
            </p>
            <p className="mt-4 font-semibold text-[#0b5345]">
              See the difference between having rankings and having a seeding system.
            </p>
            <div className="mt-8 space-y-3 border-t border-[#dfe6e2] pt-6 text-sm text-[#65736e]">
              <p className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-[#0b5345]" aria-hidden="true" /> One age group + gender
              </p>
              <p className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-[#0b5345]" aria-hidden="true" /> Your actual tournament field
              </p>
              <p className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-[#0b5345]" aria-hidden="true" /> Reply within one business day
              </p>
            </div>
          </div>
          <MatchBalanceInquiryForm />
        </div>
      </section>
    </main>
  );
}
