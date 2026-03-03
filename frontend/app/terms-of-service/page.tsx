import { PageHeader } from '@/components/PageHeader';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { Card, CardContent } from '@/components/ui/card';
import Link from 'next/link';
import type { Metadata } from 'next';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: 'Terms of Service for PitchRank.io — youth soccer team rankings and analytics platform.',
  alternates: {
    canonical: `${baseUrl}/terms-of-service`,
  },
  openGraph: {
    title: 'Terms of Service | PitchRank',
    description: 'Terms of Service for PitchRank.io — youth soccer team rankings and analytics platform.',
    url: `${baseUrl}/terms-of-service`,
    siteName: 'PitchRank',
    type: 'website',
  },
  robots: {
    index: true,
    follow: true,
  },
};

const sections = [
  { id: 'description', label: 'Description of Service' },
  { id: 'rankings-disclaimer', label: 'Rankings Disclaimer' },
  { id: 'no-affiliation', label: 'No Affiliation' },
  { id: 'accounts', label: 'Accounts' },
  { id: 'subscriptions', label: 'Subscriptions and Billing' },
  { id: 'acceptable-use', label: 'Acceptable Use' },
  { id: 'intellectual-property', label: 'Intellectual Property' },
  { id: 'limitation-of-liability', label: 'Limitation of Liability' },
  { id: 'indemnification', label: 'Indemnification' },
  { id: 'governing-law', label: 'Governing Law' },
  { id: 'modifications', label: 'Modifications' },
  { id: 'contact', label: 'Contact' },
];

export default function TermsOfServicePage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <BreadcrumbSchema
        items={[{ name: 'Terms of Service', href: '/terms-of-service' }]}
      />
      <PageHeader
        title="Terms of Service"
        description="Effective Date: March 3, 2026"
        showBackButton
        backHref="/"
      />

      <div className="max-w-3xl mx-auto">
        {/* Introduction */}
        <Card variant="flat" className="mb-8">
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              Welcome to PitchRank.io (&quot;PitchRank,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;). PitchRank is operated by:
            </p>
            <address className="mt-4 not-italic text-sm text-foreground leading-relaxed">
              <strong>PitchRank LLC</strong><br />
              14426 N 50th St<br />
              Scottsdale, AZ 85254<br />
              United States<br />
              Email:{' '}
              <a href="mailto:pitchrankio@gmail.com" className="text-primary underline-offset-4 hover:underline">
                pitchrankio@gmail.com
              </a>
            </address>
            <p className="mt-4 text-muted-foreground leading-relaxed">
              By accessing or using PitchRank.io (the &quot;Service&quot;), you agree to these Terms of Service (&quot;Terms&quot;).
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
          {/* 1. Description of Service */}
          <section id="description">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              1. Description of Service
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank provides algorithm-driven youth sports team rankings and analytics through a digital subscription platform.
            </p>
            <p className="text-muted-foreground leading-relaxed mt-2">
              The Service is provided for informational and entertainment purposes only.
            </p>
          </section>

          {/* 2. Rankings Disclaimer */}
          <section id="rankings-disclaimer">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              2. Rankings Disclaimer
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              All rankings and analytics:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Are generated algorithmically</li>
              <li>Are not official standings</li>
              <li>Are not affiliated with or endorsed by any league, club, or governing body unless explicitly stated</li>
              <li>May contain errors, omissions, or delayed updates</li>
              <li>Should not be relied upon for scholarships, recruiting, roster decisions, or club selection</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-3">
              PitchRank LLC makes no guarantee of ranking accuracy or completeness.
            </p>
          </section>

          {/* 3. No Affiliation */}
          <section id="no-affiliation">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              3. No Affiliation
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank LLC operates independently and is not affiliated with any youth soccer organization, tournament operator, league, or governing body unless explicitly stated.
            </p>
          </section>

          {/* 4. Accounts */}
          <section id="accounts">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              4. Accounts
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              If you create an account, you are responsible for:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Maintaining account security</li>
              <li>Keeping login credentials confidential</li>
              <li>All activity under your account</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-3">
              We reserve the right to suspend or terminate accounts that violate these Terms.
            </p>
          </section>

          {/* 5. Subscriptions and Billing */}
          <section id="subscriptions">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              5. Subscriptions and Billing
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              Certain features require paid subscriptions. By purchasing a subscription:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>You authorize recurring charges to your payment method.</li>
              <li>Subscriptions renew automatically unless canceled.</li>
              <li>You may cancel at any time before renewal.</li>
              <li>Payments are securely processed by Stripe.</li>
            </ul>
            <h3 className="font-display text-base font-semibold uppercase tracking-wide mt-5 mb-2">
              Refund Policy
            </h3>
            <p className="text-muted-foreground leading-relaxed">
              All subscription payments are non-refundable unless required by law.
            </p>
          </section>

          {/* 6. Acceptable Use */}
          <section id="acceptable-use">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              6. Acceptable Use
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              You agree not to:
            </p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground leading-relaxed ml-2">
              <li>Use the Service to harass or defame teams or organizations</li>
              <li>Submit false data</li>
              <li>Attempt to manipulate rankings</li>
              <li>Reverse engineer, scrape, or disrupt the Service</li>
              <li>Circumvent subscription access controls</li>
            </ul>
          </section>

          {/* 7. Intellectual Property */}
          <section id="intellectual-property">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              7. Intellectual Property
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              All content, rankings methodology, design, branding, and software are the property of PitchRank LLC.
            </p>
            <p className="text-muted-foreground leading-relaxed mt-2">
              You may not reproduce or distribute content without written permission.
            </p>
          </section>

          {/* 8. Limitation of Liability */}
          <section id="limitation-of-liability">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              8. Limitation of Liability
            </h2>
            <p className="text-muted-foreground leading-relaxed mb-3">
              To the fullest extent permitted by law:
            </p>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank LLC shall not be liable for indirect, incidental, or consequential damages.
            </p>
            <p className="text-muted-foreground leading-relaxed mt-2">
              Total liability shall not exceed the amount paid by you in the previous 12 months (or $100 if no payment was made).
            </p>
          </section>

          {/* 9. Indemnification */}
          <section id="indemnification">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              9. Indemnification
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              You agree to indemnify and hold harmless PitchRank LLC from claims arising from your use of the Service or violation of these Terms.
            </p>
          </section>

          {/* 10. Governing Law */}
          <section id="governing-law">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              10. Governing Law
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              These Terms are governed by the laws of the State of Arizona.
            </p>
            <p className="text-muted-foreground leading-relaxed mt-2">
              Any disputes shall be resolved exclusively in Maricopa County, Arizona.
            </p>
          </section>

          {/* 11. Modifications */}
          <section id="modifications">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              11. Modifications
            </h2>
            <p className="text-muted-foreground leading-relaxed">
              We may update these Terms at any time. Continued use of the Service constitutes acceptance of any revisions.
            </p>
          </section>

          {/* 12. Contact */}
          <section id="contact">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide mb-3 scroll-mt-24">
              12. Contact
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

        {/* Footer link to Privacy Policy */}
        <div className="mt-12 pt-8 border-t border-border text-center">
          <p className="text-sm text-muted-foreground">
            See also our{' '}
            <Link href="/privacy-policy" className="text-primary underline-offset-4 hover:underline font-medium">
              Privacy Policy
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
