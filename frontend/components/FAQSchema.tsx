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
          text: 'PitchRank uses a two-part rating system: a Core Rating Engine that evaluates opponent quality, competitiveness, strength of schedule, offensive/defensive behavior, recency, and stability; and a Machine Learning Layer that identifies teams trending up or down based on performance vs. expectations. Rankings are updated weekly with verified game data.',
        },
      },
      {
        '@type': 'Question',
        name: 'What is a Power Score?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: "A Power Score is a numerical value that represents a team's overall strength. It's calculated using machine learning algorithms that analyze offense, defense, schedule difficulty, and predictive performance patterns. Higher power scores indicate stronger teams.",
        },
      },
      {
        '@type': 'Question',
        name: 'Is it easy to manipulate the rankings?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'No. Schedule strength, consistency patterns, and ML comparisons prevent "gaming the system." The system looks at the quality of opponents, long-term patterns, and context of each result.',
        },
      },
      {
        '@type': 'Question',
        name: 'Does winning by a lot help my ranking?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Only when the opponent is strong. Context is everything. A 1-0 battle against a powerhouse says more than a 10-0 cruise against a weak team.',
        },
      },
      {
        '@type': 'Question',
        name: "Why doesn't one game swing our ranking?",
        acceptedAnswer: {
          '@type': 'Answer',
          text: "Because long-term patterns matter more than isolated results. PitchRank's stability feature ensures consistent teams get recognized and fluky results don't define you.",
        },
      },
      {
        '@type': 'Question',
        name: 'How often are rankings updated?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Rankings are updated every Monday morning. The entire network refreshes with new results, strength of schedule updates, cross-state comparisons tighten, and machine learning picks up new trends.',
        },
      },
      {
        '@type': 'Question',
        name: 'What is Strength of Schedule (SOS)?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: "Strength of Schedule (SOS) measures the difficulty of a team's opponents. Your record is only half the story - who you earned it against is the rest. It's normalized within each age group and gender on a 0-100 scale.",
        },
      },
      {
        '@type': 'Question',
        name: 'How does PitchRank handle new or light-data teams?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'New teams start conservatively, then rise as results come in. No inflated placements. No artificial penalties. Just a fair runway to show who you really are.',
        },
      },
      {
        '@type': 'Question',
        name: 'Can we report missing games?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: "Yes - tap the Missing Games button and we'll automatically find and add them to the system.",
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
        name: 'How does cross-state comparison work?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: "One of PitchRank's biggest strengths is how quickly the system builds connections. Tournaments across different states, national events, and cross-regional play all tie together to create a nationally interconnected ranking ecosystem.",
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
