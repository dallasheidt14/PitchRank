import { MetadataRoute } from 'next';
import { US_STATES, AGE_GROUPS, BASE_URL_WWW, PITCHRANK_TEAM_AUTHOR_PATH } from '@/lib/constants';
import { getAllBlogSlugs } from '@/lib/blog';

/**
 * Dynamic sitemap generation for PitchRank
 * Generates URLs for all PUBLIC pages only
 *
 * NOTE: Auth-gated pages (/teams, /compare, /watchlist) are excluded
 * because Googlebot cannot authenticate and will get redirected.
 * This causes "Page with redirect" issues in Search Console.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = BASE_URL_WWW;

  // Age groups available in the system
  const ageGroups = AGE_GROUPS;

  // Genders (URL format)
  const genders = ['male', 'female'];

  // Regions: national + all US states
  const regions = ['national', ...US_STATES.map((state) => state.code)];

  // Static PUBLIC pages only (no auth-gated pages)
  const staticPages: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 1.0,
    },
    {
      url: `${baseUrl}/rankings`,
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 0.9,
    },
    // NOTE: /compare is auth-gated, excluded from sitemap
    {
      url: `${baseUrl}/methodology`,
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 0.6,
    },
    {
      url: `${baseUrl}/blog`,
      lastModified: new Date(),
      changeFrequency: 'weekly',
      priority: 0.7,
    },
    {
      url: `${baseUrl}${PITCHRANK_TEAM_AUTHOR_PATH}`,
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 0.4,
    },
  ];

  // Blog post pages
  const blogSlugs = getAllBlogSlugs();
  const blogPages: MetadataRoute.Sitemap = blogSlugs.map((slug) => ({
    url: `${baseUrl}/blog/${slug}`,
    lastModified: new Date(),
    changeFrequency: 'monthly' as const,
    priority: 0.6,
  }));

  // State/national landing pages (e.g., /rankings/ca, /rankings/national)
  // These are content-rich server-rendered overview pages — important for SEO
  const regionLandingPages: MetadataRoute.Sitemap = regions.map((region) => ({
    url: `${baseUrl}/rankings/${region}`,
    lastModified: new Date(),
    changeFrequency: 'weekly' as const,
    priority: region === 'national' ? 0.9 : 0.8,
  }));

  // Generate all ranking page URLs (region × ageGroup × gender)
  const rankingPages: MetadataRoute.Sitemap = [];

  for (const region of regions) {
    for (const ageGroup of ageGroups) {
      for (const gender of genders) {
        rankingPages.push({
          url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
          lastModified: new Date(),
          changeFrequency: 'weekly',
          priority: region === 'national' ? 0.8 : 0.7,
        });
      }
    }
  }

  // Combine all pages
  const allPages = [...staticPages, ...blogPages, ...regionLandingPages, ...rankingPages];

  return allPages;
}
