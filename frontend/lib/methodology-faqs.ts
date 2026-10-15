import type { FAQ } from '@/lib/blog-faqs';
import { MIN_RANKED_GAMES } from '@/lib/constants';

/** The Methodology page's FAQ: rendered on the page and, from the same list, as its FAQPage structured data. */
export const METHODOLOGY_FAQS: FAQ[] = [
  {
    question: 'Is this easy to manipulate?',
    answer: 'No. Schedule strength, consistency patterns, and ML comparisons prevent "gaming the system."',
  },
  {
    question: 'Does winning by a lot help?',
    answer: 'Only when the opponent is strong. Context is everything.',
  },
  {
    question: "Why doesn't one game swing our ranking?",
    answer: 'Because long-term patterns matter more than isolated results.',
  },
  {
    question: 'Can we report missing games?',
    answer: "Yes — tap the Missing Games button and we'll automatically find and add them.",
  },
  {
    question: 'How does PitchRank compare teams across different leagues?',
    answer:
      'Our system calibrates league strength automatically. When teams from different leagues meet at tournaments, those head-to-head results anchor cross-league comparisons. The more inter-league games played, the more accurate these comparisons become.',
  },
  {
    question: 'How accurate are rankings for teams that have only played a few games?',
    answer: `Rankings for newer teams carry wider uncertainty. We require at least ${MIN_RANKED_GAMES} verified games in the last 12 months before a team appears in official rankings, and even then, their rating stabilizes further with each additional game. Early-season rankings should be treated as directional, not definitive.`,
  },
  {
    question: 'Where does PitchRank get its game data?',
    answer:
      'We collect verified game results from tournaments, leagues, showcases, and cross-state events across all 50 states. Our data pipeline pulls from multiple sources — we are not locked to any single tournament platform, which gives us broader coverage than platform-specific ranking systems.',
  },
  {
    question: 'Can teams from different states be compared fairly?',
    answer:
      "Yes. Cross-state tournaments and national events create direct connections between state ecosystems. A team from Arizona that plays in a California tournament creates a bridge that links both states' rankings. The more cross-state play, the more accurate interstate comparisons become.",
  },
];
