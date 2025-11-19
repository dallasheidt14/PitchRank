/**
 * FAQ Schema (Structured Data) for Methodology Page
 * Helps Google display FAQ rich results in search
 */
export function FAQSchema() {
  const faqSchema = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: [
      {
        '@type': 'Question',
        name: 'How are youth soccer rankings calculated on PitchRank?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'PitchRank calculates rankings using a comprehensive power score algorithm that considers multiple factors including win percentage, strength of schedule, goals for and against, recent performance trends, and cross-age game results. Rankings are updated weekly with verified game data.',
        },
      },
      {
        '@type': 'Question',
        name: 'What is a Power Score?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'A Power Score is a numerical value that represents a team\'s overall strength. It\'s calculated using machine learning algorithms that analyze offense, defense, schedule difficulty, and predictive performance patterns. Higher power scores indicate stronger teams.',
        },
      },
      {
        '@type': 'Question',
        name: 'How often are rankings updated?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Rankings are updated weekly with new game results from verified youth soccer leagues and competitions across all 50 states. The system processes new data and recalculates all rankings to reflect the most current performance.',
        },
      },
      {
        '@type': 'Question',
        name: 'What age groups does PitchRank cover?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'PitchRank covers all youth soccer age groups from U10 through U18 for both boys and girls teams. Teams are ranked within their specific age group and gender for fair comparisons.',
        },
      },
      {
        '@type': 'Question',
        name: 'Can teams from different age groups be compared?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Yes! PitchRank uses cross-age scoring technology that allows accurate comparisons even when teams play outside their age bracket. The system adjusts power scores based on age differentials to ensure fair rankings.',
        },
      },
      {
        '@type': 'Question',
        name: 'What is Strength of Schedule (SOS)?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Strength of Schedule (SOS) measures the difficulty of a team\'s opponents. It\'s normalized within each age group and gender on a 0-100 scale, where 0 represents the softest schedule and 100 represents the toughest. Playing stronger opponents improves your SOS rating.',
        },
      },
      {
        '@type': 'Question',
        name: 'Are rankings available for all states?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Yes, PitchRank provides rankings for all 50 U.S. states plus national rankings. Teams can view their national rank as well as their rank within their specific state for local comparisons.',
        },
      },
      {
        '@type': 'Question',
        name: 'How can my team improve its ranking?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Teams can improve their ranking by: 1) Winning consistently, especially against higher-ranked opponents, 2) Scheduling games against stronger teams to improve strength of schedule, 3) Building a strong record over time, and 4) Performing well in cross-age matchups.',
        },
      },
    ],
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(faqSchema),
      }}
    />
  );
}
