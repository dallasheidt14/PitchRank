import { MetadataRoute } from 'next';
import { US_STATES } from '@/lib/constants';

/**
 * Dynamic sitemap generation for PitchRank
 * Generates URLs for all static pages, ranking combinations, and team pages
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

  // Age groups available in the system
  const ageGroups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18'];

  // Genders (URL format)
  const genders = ['male', 'female'];

  // Regions: national + all US states
  const regions = ['national', ...US_STATES.map(state => state.code)];

  // Static pages with high priority
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
    {
      url: `${baseUrl}/compare`,
      lastModified: new Date(),
      changeFrequency: 'weekly',
      priority: 0.7,
    },
    {
      url: `${baseUrl}/methodology`,
      lastModified: new Date(),
      changeFrequency: 'monthly',
      priority: 0.6,
    },
  ];

  // Generate all ranking page URLs (region × ageGroup × gender)
  // Total: 51 regions × 9 age groups × 2 genders = 918 URLs
  const rankingPages: MetadataRoute.Sitemap = [];

  for (const region of regions) {
    for (const ageGroup of ageGroups) {
      for (const gender of genders) {
        rankingPages.push({
          url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
          lastModified: new Date(),
          changeFrequency: 'weekly', // Rankings update weekly
          priority: region === 'national' ? 0.8 : 0.7, // National rankings slightly higher priority
        });
      }
    }
  }

  // Combine all pages
  const allPages = [...staticPages, ...rankingPages];

  return allPages;
}
