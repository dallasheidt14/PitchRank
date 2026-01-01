/**
 * BreadcrumbList Schema component
 * Helps AI search engines understand page hierarchy and navigation context
 * Critical for LLM retrieval - provides clear path structure for citations
 */

interface BreadcrumbItem {
  name: string;
  url: string;
}

interface BreadcrumbSchemaProps {
  items: BreadcrumbItem[];
}

/**
 * Generates JSON-LD BreadcrumbList schema for SEO and AI search optimization
 * @param items - Array of breadcrumb items with name and URL
 *
 * @example
 * <BreadcrumbSchema items={[
 *   { name: 'Home', url: 'https://pitchrank.io' },
 *   { name: 'Rankings', url: 'https://pitchrank.io/rankings' },
 *   { name: 'California', url: 'https://pitchrank.io/rankings/california/u12/boys' }
 * ]} />
 */
export function BreadcrumbSchema({ items }: BreadcrumbSchemaProps) {
  if (!items || items.length === 0) return null;

  const breadcrumbSchema = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: item.url,
    })),
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(breadcrumbSchema),
      }}
    />
  );
}

/**
 * Helper to generate breadcrumbs for ranking pages
 */
export function getRankingsBreadcrumbs(
  region: string,
  ageGroup: string,
  gender: string,
  baseUrl: string = 'https://pitchrank.io'
): BreadcrumbItem[] {
  const regionDisplay = region === 'national' ? 'National' : region.toUpperCase();
  const ageDisplay = ageGroup.toUpperCase();
  const genderDisplay = gender.charAt(0).toUpperCase() + gender.slice(1);

  return [
    { name: 'Home', url: baseUrl },
    { name: 'Rankings', url: `${baseUrl}/rankings` },
    {
      name: `${ageDisplay} ${genderDisplay} - ${regionDisplay}`,
      url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
    },
  ];
}

/**
 * Helper to generate breadcrumbs for team pages
 */
export function getTeamBreadcrumbs(
  teamName: string,
  teamId: string,
  stateCode?: string,
  ageGroup?: string,
  gender?: string,
  baseUrl: string = 'https://pitchrank.io'
): BreadcrumbItem[] {
  const crumbs: BreadcrumbItem[] = [
    { name: 'Home', url: baseUrl },
    { name: 'Rankings', url: `${baseUrl}/rankings` },
  ];

  // Add state-level crumb if available
  if (stateCode && ageGroup && gender) {
    const stateDisplay = stateCode.toUpperCase();
    crumbs.push({
      name: `${stateDisplay} Rankings`,
      url: `${baseUrl}/rankings/${stateCode.toLowerCase()}/${ageGroup.toLowerCase()}/${gender.toLowerCase()}`,
    });
  }

  // Add team as final crumb
  crumbs.push({
    name: teamName,
    url: `${baseUrl}/teams/${teamId}`,
  });

  return crumbs;
}
