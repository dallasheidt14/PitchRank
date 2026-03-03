import { PageHeader } from '@/components/PageHeader';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { Card, CardContent } from '@/components/ui/card';
import Link from 'next/link';
import type { Metadata } from 'next';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description: 'Privacy Policy for PitchRank.io — how we collect, use, and protect your information.',
  alternates: {
    canonical: `${baseUrl}/privacy-policy`,
  },
  openGraph: {
    title: 'Privacy Policy | PitchRank',
    description: 'Privacy Policy for PitchRank.io — how we collect, use, and protect your information.',
    url: `${baseUrl}/privacy-policy`,
    siteName: 'PitchRank',
    type: 'website',
  },
  robots: {
    index: true,
    follow: true,
  },
};

const sections = [
  { id: 'information-we-collect', label: 'Information We Collect' },
  { id: 'public-team-data', label: 'Public Team Data' },
  { id: 'how-we-use-information', label: 'How We Use Information' },
  { id: 'data-sharing', label: 'Data Sharing' },
  { id: 'data-security', label: 'Data Security' },
  { id: 'data-retention', label: 'Data Retention' },
  { id: 'your-rights', label: 'Your Rights' },
  { id: 'childrens-privacy', label: "Children's Privacy" },
  { id: 'changes', label: 'Changes to This Policy' },
  { id: 'contact', label: 'Contact' },
];

export default function PrivacyPolicyPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <BreadcrumbSchema
        items={[{ name: 'Privacy Policy', href: '/privacy-policy' }]}
      />
      <PageHeader
        title="Privacy Policy"
        description="Effective Date: March 3, 2026"
        showBackButton
        backHref="/"
      />

      <div className="max-w-3xl mx-auto">
        {/* Introduction */}
        <Card variant="flat" className="mb-8">
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank LLC (&quot;PitchRank,&quot; &quot;we,&quot; &quot;us,&quot; &quot;our&quot;) respects your privacy. This policy explains how we collect, use, and protect your information when you use PitchRank.io.
            </p>
          </CardContent>
        </Card>

        {/* Table of Contents */}
        <nav aria-label="Table of contents" className="mb-10">
          <h2 className="font-display text-lg font-semibold uppercase tracking-wide mb-3">
            Contents
          </h2>
          <ol className="grid grid-cols-1 sm:grid-cols-2 gap-1">
            {sections.map((section, i) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="text-sm text-muted-foreground hover:text-primary transition-colors"
                >
                  {i + 1}. {section.label}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {/* Sections */}
        <div className="space-y-10">
          {/* 1. Information We Collect */}
          <section id="information-we-collect">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              1. Information We Collect
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              We may collect the following types of information:
            </p>

            <h3 className="font-display text-base font-semibold uppercase tracking-wide mt-5 mb-2">
              Account Information
            </h3>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Name</li>
              <li>Email address</li>
              <li>Login credentials</li>
            </ul>

            <h3 className="font-display text-base font-semibold uppercase tracking-wide mt-5 mb-2">
              Payment Information
            </h3>
            <p className="text-muted-foreground leading-relaxed">
              Payments are processed by Stripe. We do not store full credit card numbers.
            </p>

            <h3 className="font-display text-base font-semibold uppercase tracking-wide mt-5 mb-2">
              Usage Data
            </h3>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>IP address</li>
              <li>Browser type</li>
              <li>Device information</li>
              <li>Pages visited</li>
              <li>Interaction data</li>
            </ul>
          </section>

          {/* 2. Public Team Data */}
          <section id="public-team-data">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              2. Public Team Data
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              PitchRank displays:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Team names</li>
              <li>Club names</li>
              <li>Match results</li>
              <li>Rankings</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-3">
              We do not collect or publish personal information about individual players.
            </p>
          </section>

          {/* 3. How We Use Information */}
          <section id="how-we-use-information">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              3. How We Use Information
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              We use information to:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Provide and maintain the Service</li>
              <li>Process subscriptions</li>
              <li>Improve platform performance</li>
              <li>Prevent fraud</li>
              <li>Respond to inquiries</li>
            </ul>
          </section>

          {/* 4. Data Sharing */}
          <section id="data-sharing">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              4. Data Sharing
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              We may share data with:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Payment processors (Stripe)</li>
              <li>Hosting providers</li>
              <li>Analytics providers</li>
              <li>Legal authorities if required by law</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-3 font-medium text-foreground">
              We do not sell personal data.
            </p>
          </section>

          {/* 5. Data Security */}
          <section id="data-security">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              5. Data Security
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              We implement reasonable safeguards to protect information. No system is completely secure.
            </p>
          </section>

          {/* 6. Data Retention */}
          <section id="data-retention">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              6. Data Retention
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              We retain account information as long as necessary to:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Provide services</li>
              <li>Comply with legal obligations</li>
              <li>Resolve disputes</li>
            </ul>
          </section>

          {/* 7. Your Rights */}
          <section id="your-rights">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              7. Your Rights
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              You may request:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Access to your account data</li>
              <li>Corrections</li>
              <li>Deletion of your account</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-3">
              Requests may be sent to{' '}
              <a href="mailto:pitchrankio@gmail.com" className="text-primary underline-offset-4 hover:underline">
                pitchrankio@gmail.com
              </a>
            </p>
          </section>

          {/* 8. Children's Privacy */}
          <section id="childrens-privacy">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              8. Children&apos;s Privacy
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank is not directed toward children under 13. We do not knowingly collect personal information from children under 13.
            </p>
          </section>

          {/* 9. Changes to This Policy */}
          <section id="changes">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              9. Changes to This Policy
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              We may update this Privacy Policy periodically. Continued use of the Service indicates acceptance of updates.
            </p>
          </section>

          {/* 10. Contact */}
          <section id="contact">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              10. Contact
            </h2>
            <address className="not-italic text-muted-foreground leading-relaxed">
              <strong className="text-foreground">PitchRank LLC</strong><br />
              14426 N 50th St<br />
              Scottsdale, AZ 85254<br />
              Email:{' '}
              <a href="mailto:pitchrankio@gmail.com" className="text-primary underline-offset-4 hover:underline">
                pitchrankio@gmail.com
              </a>
            </address>
          </section>
        </div>

        {/* Footer link to Terms */}
        <div className="mt-12 pt-8 border-t border-border text-center">
          <p className="text-sm text-muted-foreground">
            See also our{' '}
            <Link href="/terms-of-service" className="text-primary underline-offset-4 hover:underline font-medium">
              Terms of Service
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
