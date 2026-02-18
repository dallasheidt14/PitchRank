import Link from 'next/link';
import { Twitter, Instagram, Facebook, Linkedin } from 'lucide-react';

/**
 * Footer component with social media links, site navigation, and state overview links
 * Includes comprehensive internal linking for SEO
 * Appears on all pages below main content
 */
export function Footer() {
  const currentYear = new Date().getFullYear();

  const socialLinks = [
    {
      name: 'Twitter',
      href: 'https://twitter.com/pitchrank',
      icon: Twitter,
      ariaLabel: 'Follow us on Twitter',
    },
    {
      name: 'Instagram',
      href: 'https://instagram.com/pitchrank',
      icon: Instagram,
      ariaLabel: 'Follow us on Instagram',
    },
    {
      name: 'Facebook',
      href: 'https://facebook.com/pitchrank',
      icon: Facebook,
      ariaLabel: 'Follow us on Facebook',
    },
    {
      name: 'LinkedIn',
      href: 'https://linkedin.com/company/pitchrank',
      icon: Linkedin,
      ariaLabel: 'Follow us on LinkedIn',
    },
  ];

  // Priority states for rankings (highest search volume)
  const priorityStates = [
    { code: 'ca', name: 'California' },
    { code: 'tx', name: 'Texas' },
    { code: 'fl', name: 'Florida' },
    { code: 'ny', name: 'New York' },
    { code: 'nj', name: 'New Jersey' },
    { code: 'az', name: 'Arizona' },
    { code: 'ga', name: 'Georgia' },
    { code: 'pa', name: 'Pennsylvania' },
    { code: 'il', name: 'Illinois' },
    { code: 'nc', name: 'North Carolina' },
    { code: 'wa', name: 'Washington' },
    { code: 'co', name: 'Colorado' },
  ];

  // Age groups for internal linking
  const ageGroups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18'];

  const footerLinks = {
    Rankings: [
      { name: 'National Rankings', href: '/rankings/national' },
      { name: 'Compare Teams', href: '/compare' },
    ],
    Resources: [
      { name: 'Methodology', href: '/methodology' },
      { name: 'Blog', href: '/blog' },
    ],
  };

  return (
    <footer className="border-t border-border bg-muted/30 mt-auto safe-bottom">
      <div className="container mx-auto px-4 py-8 md:py-12">
        {/* Main Footer Content */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 md:gap-8 mb-8">
          {/* Brand Column */}
          <div className="md:col-span-2">
            <Link href="/" className="inline-block mb-4">
              <h3 className="font-display text-xl font-bold uppercase tracking-wide">PitchRank</h3>
            </Link>
            <p className="text-sm text-muted-foreground mb-4 max-w-md">
              Data-powered youth soccer team rankings and performance analytics.
              Compare U10-U18 boys and girls teams nationally and across all 50 states.
            </p>

            {/* Social Media Links */}
            <div className="flex gap-4">
              {socialLinks.map((social) => {
                const Icon = social.icon;
                return (
                  <a
                    key={social.name}
                    href={social.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={social.ariaLabel}
                    className="text-muted-foreground hover:text-foreground transition-colors p-3 sm:p-2 hover:bg-muted rounded-md min-w-[44px] min-h-[44px] flex items-center justify-center"
                  >
                    <Icon className="h-6 w-6 sm:h-5 sm:w-5" />
                  </a>
                );
              })}
            </div>
          </div>

          {/* Rankings Links */}
          <div>
            <h4 className="font-display font-semibold uppercase tracking-wide mb-4">Rankings</h4>
            <ul className="space-y-2">
              {footerLinks.Rankings.map((link) => (
                <li key={link.name}>
                  <Link
                    href={link.href}
                    className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Resources Links */}
          <div>
            <h4 className="font-display font-semibold uppercase tracking-wide mb-4">Resources</h4>
            <ul className="space-y-2">
              {footerLinks.Resources.map((link) => (
                <li key={link.name}>
                  <Link
                    href={link.href}
                    className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* State Rankings Grid - SEO Internal Linking */}
        <div className="mb-8 pt-6 border-t border-border">
          <h4 className="font-display font-semibold uppercase tracking-wide mb-4">Rankings by State</h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
            {priorityStates.map((state) => (
              <Link
                key={state.code}
                href={`/rankings/${state.code}`}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {state.name}
              </Link>
            ))}
          </div>
        </div>

        {/* Age Group Links - SEO Internal Linking */}
        <div className="mb-8">
          <h4 className="font-display font-semibold uppercase tracking-wide mb-4">Rankings by Age</h4>
          <div className="flex flex-wrap gap-3">
            {ageGroups.map((age) => (
              <Link
                key={age}
                href={`/rankings/age/${age}`}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {age.toUpperCase()}
              </Link>
            ))}
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="pt-8 border-t border-border">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground">
              © {currentYear} PitchRank. All rights reserved.
            </p>
            <div className="flex gap-6">
              <Link
                href="/methodology"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Methodology
              </Link>
              <a
                href="mailto:pitchrankio@gmail.com"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Contact
              </a>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
