'use client';

import Link from 'next/link';
import { ChevronRight, Home } from 'lucide-react';
import { usePathname } from 'next/navigation';
import { useMemo } from 'react';

interface BreadcrumbItem {
  label: string;
  href: string;
}

interface BreadcrumbsProps {
  /**
   * Custom breadcrumb items (overrides auto-generation)
   */
  items?: BreadcrumbItem[];
  /**
   * Show home icon instead of "Home" text
   */
  showHomeIcon?: boolean;
}

// State code to full name mapping for breadcrumbs
const STATE_NAMES: Record<string, string> = {
  al: 'Alabama', ak: 'Alaska', az: 'Arizona', ar: 'Arkansas', ca: 'California',
  co: 'Colorado', ct: 'Connecticut', de: 'Delaware', fl: 'Florida', ga: 'Georgia',
  hi: 'Hawaii', id: 'Idaho', il: 'Illinois', in: 'Indiana', ia: 'Iowa',
  ks: 'Kansas', ky: 'Kentucky', la: 'Louisiana', me: 'Maine', md: 'Maryland',
  ma: 'Massachusetts', mi: 'Michigan', mn: 'Minnesota', ms: 'Mississippi', mo: 'Missouri',
  mt: 'Montana', ne: 'Nebraska', nv: 'Nevada', nh: 'New Hampshire', nj: 'New Jersey',
  nm: 'New Mexico', ny: 'New York', nc: 'North Carolina', nd: 'North Dakota', oh: 'Ohio',
  ok: 'Oklahoma', or: 'Oregon', pa: 'Pennsylvania', ri: 'Rhode Island', sc: 'South Carolina',
  sd: 'South Dakota', tn: 'Tennessee', tx: 'Texas', ut: 'Utah', vt: 'Vermont',
  va: 'Virginia', wa: 'Washington', wv: 'West Virginia', wi: 'Wisconsin', wy: 'Wyoming',
};

/**
 * Breadcrumb navigation component with structured data
 * Automatically generates breadcrumbs from current path or accepts custom items
 * Includes BreadcrumbList schema for SEO
 */
export function Breadcrumbs({ items, showHomeIcon = true }: BreadcrumbsProps) {
  const pathname = usePathname();

  const breadcrumbs = useMemo<BreadcrumbItem[]>(() => {
    if (items) return items;

    // Auto-generate breadcrumbs from pathname
    const paths = pathname.split('/').filter(Boolean);
    const crumbs: BreadcrumbItem[] = [{ label: 'Home', href: '/' }];

    let currentPath = '';
    paths.forEach((path, index) => {
      currentPath += `/${path}`;

      // Format label
      let label = path;
      const lowerPath = path.toLowerCase();

      // Special formatting for common paths
      if (path === 'rankings') {
        label = 'Rankings';
      } else if (path === 'teams') {
        label = 'Teams';
      } else if (path === 'compare') {
        label = 'Compare';
      } else if (path === 'methodology') {
        label = 'Methodology';
      } else if (path === 'age') {
        label = 'Age Groups';
      } else if (path === 'national') {
        label = 'National';
      } else if (path.match(/^u\d+$/i)) {
        // Age groups (u12, u14, etc.)
        label = path.toUpperCase();
      } else if (path === 'male') {
        label = 'Boys';
      } else if (path === 'female') {
        label = 'Girls';
      } else if (path.length === 2 && STATE_NAMES[lowerPath]) {
        // State codes - show full state name
        label = STATE_NAMES[lowerPath];
      } else if (path.length === 2) {
        // Unknown 2-letter code, just uppercase
        label = path.toUpperCase();
      }

      crumbs.push({ label, href: currentPath });
    });

    return crumbs;
  }, [pathname, items]);

  // Generate structured data (BreadcrumbList schema)
  const structuredData = useMemo(() => {
    const baseUrl = typeof window !== 'undefined'
      ? `${window.location.protocol}//${window.location.host}`
      : process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

    return {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: breadcrumbs.map((crumb, index) => ({
        '@type': 'ListItem',
        position: index + 1,
        name: crumb.label,
        item: `${baseUrl}${crumb.href}`,
      })),
    };
  }, [breadcrumbs]);

  if (breadcrumbs.length <= 1) {
    return null; // Don't show breadcrumbs on home page
  }

  return (
    <>
      {/* Structured Data */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(structuredData),
        }}
      />

      {/* Breadcrumb Navigation */}
      <nav aria-label="Breadcrumb" className="mb-4">
        <ol className="flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
          {breadcrumbs.map((crumb, index) => {
            const isLast = index === breadcrumbs.length - 1;
            const isHome = index === 0;

            return (
              <li key={crumb.href} className="flex items-center gap-2">
                {index > 0 && (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                )}

                {isLast ? (
                  <span className="font-medium text-foreground" aria-current="page">
                    {isHome && showHomeIcon ? (
                      <Home className="h-4 w-4" aria-label="Home" />
                    ) : (
                      crumb.label
                    )}
                  </span>
                ) : (
                  <Link
                    href={crumb.href}
                    className="hover:text-foreground transition-colors"
                  >
                    {isHome && showHomeIcon ? (
                      <Home className="h-4 w-4" aria-label="Home" />
                    ) : (
                      crumb.label
                    )}
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
      </nav>
    </>
  );
}
