/**
 * FAQ data for state-specific blog posts.
 * Used to render FAQPage structured data for rich snippet eligibility.
 * Keyed by blog post slug.
 */

export interface FAQ {
  question: string;
  answer: string;
}

export const BLOG_FAQS: Record<string, FAQ[]> = {
  'texas-youth-soccer-rankings-guide': [
    {
      question: 'How are Texas youth soccer teams ranked?',
      answer:
        'PitchRank ranks Texas teams using a PowerScore algorithm that evaluates game-by-game results, strength of schedule, goal differential, recency, and consistency. Rankings are updated every Monday with real game data from 9,460+ Texas teams.',
    },
    {
      question: 'How many youth soccer teams are ranked in Texas?',
      answer:
        'PitchRank tracks over 9,460 youth soccer teams in Texas across all age groups from U10 to U19, including FC Dallas, Solar SC, Albion Hurricanes, Lonestar, Challenge SC, and hundreds more clubs.',
    },
    {
      question: 'How often are Texas soccer rankings updated?',
      answer:
        'Texas youth soccer rankings are updated every Monday morning with the latest game results from the previous week.',
    },
    {
      question: 'What is a good PowerScore for a Texas youth soccer team?',
      answer:
        'A PowerScore of 0.85+ is elite/national-level, 0.70-0.84 is top competitive tier, 0.50-0.69 is solid competitive, and 0.30-0.49 is developing. Scores are on a 0.0 to 1.0 scale.',
    },
    {
      question: 'Can Texas youth soccer rankings help with college recruiting?',
      answer:
        'Rankings provide context for college coaches evaluating players. Division I coaches notice teams in the top 5% nationally, while Division II looks at the top 15-20%. However, individual highlight video, academics, and showcase attendance matter more than team rankings alone.',
    },
  ],
  'california-youth-soccer-rankings-guide': [
    {
      question: 'How are California youth soccer teams ranked?',
      answer:
        'PitchRank ranks California teams using a PowerScore algorithm that evaluates game-by-game results, strength of schedule, goal differential, recency, and consistency. Rankings are updated every Monday with real game data from 15,693+ California teams.',
    },
    {
      question: 'How many youth soccer teams are ranked in California?',
      answer:
        'PitchRank tracks over 15,693 youth soccer teams in California — more than any other state. This includes LA Galaxy Academy, San Diego Surf, Beach FC, and hundreds more clubs across all age groups from U10 to U19.',
    },
    {
      question: 'How often are California soccer rankings updated?',
      answer:
        'California youth soccer rankings are updated every Monday morning with the latest game results from the previous week.',
    },
    {
      question: 'What is a good PowerScore for a California youth soccer team?',
      answer:
        "A PowerScore of 0.85+ is elite/national-level, 0.70-0.84 is top competitive tier, 0.50-0.69 is solid competitive, and 0.30-0.49 is developing. Given California's depth of competition, even a 0.60 is impressive.",
    },
    {
      question: 'How do California youth soccer rankings compare to other states?',
      answer:
        'California has the most ranked teams of any state (15,693+). Cross-state comparison works through tournaments and national events that connect California teams to the rest of the country, creating a nationally interconnected ranking ecosystem.',
    },
  ],
  'michigan-youth-soccer-rankings-guide': [
    {
      question: 'How are Michigan youth soccer teams ranked?',
      answer:
        'PitchRank ranks Michigan teams using a PowerScore algorithm that evaluates game-by-game results, strength of schedule, goal differential, recency, and consistency. Rankings are updated every Monday with real game data.',
    },
    {
      question: 'What are the top youth soccer clubs in Michigan?',
      answer:
        'Major Michigan youth soccer clubs include Michigan Hawks, Vardar SC, Detroit City FC Youth, Crew SC, Michigan Wolves, FC Alliance, and Rush Michigan. Rankings vary by age group — check PitchRank for current standings.',
    },
    {
      question: 'How often are Michigan soccer rankings updated?',
      answer:
        'Michigan youth soccer rankings are updated every Monday morning with the latest game results from the previous week.',
    },
    {
      question: 'What is a good PowerScore for a Michigan youth soccer team?',
      answer:
        'A PowerScore of 0.85+ is elite/national-level, 0.70-0.84 is top competitive tier, 0.50-0.69 is solid competitive, and 0.30-0.49 is developing. Scores are on a 0.0 to 1.0 scale.',
    },
    {
      question: 'Does indoor soccer season affect Michigan rankings?',
      answer:
        'Indoor season can cause mid-winter ranking dips since fewer outdoor games are tracked. However, Michigan teams often surge in spring rankings as indoor training translates to improved outdoor performance.',
    },
  ],
  'colorado-youth-soccer-rankings-guide': [
    {
      question: 'How are Colorado youth soccer teams ranked?',
      answer:
        'PitchRank ranks Colorado teams using a PowerScore algorithm that evaluates game-by-game results, strength of schedule, goal differential, recency, and consistency. Rankings are updated every Monday with real game data.',
    },
    {
      question: 'What are the top youth soccer clubs in Colorado?',
      answer:
        'Major Colorado youth soccer clubs include Colorado Rapids Youth, Real Colorado, Colorado Storm, Colorado Rush, and Pride Soccer Club. Rankings vary by age group — check PitchRank for current standings.',
    },
    {
      question: 'How often are Colorado soccer rankings updated?',
      answer:
        'Colorado youth soccer rankings are updated every Monday morning with the latest game results from the previous week.',
    },
    {
      question: 'What is a good PowerScore for a Colorado youth soccer team?',
      answer:
        'A PowerScore of 0.85+ is elite/national-level, 0.70-0.84 is top competitive tier, 0.50-0.69 is solid competitive, and 0.30-0.49 is developing. Scores are on a 0.0 to 1.0 scale.',
    },
    {
      question: 'Does altitude affect Colorado soccer rankings?',
      answer:
        'Altitude itself does not directly factor into rankings. However, Colorado teams that train at elevation often have a fitness advantage in tournaments at lower altitudes, which can lead to better results and higher rankings over time.',
    },
  ],
  'arizona-youth-soccer-rankings-guide': [
    {
      question: 'How are Arizona youth soccer teams ranked?',
      answer:
        'PitchRank ranks Arizona teams using a PowerScore algorithm that evaluates game-by-game results, strength of schedule, goal differential, recency, and consistency. Rankings are updated every Monday with real game data from 1,940+ Arizona teams.',
    },
    {
      question: 'What are the top youth soccer clubs in Arizona?',
      answer:
        'Major Arizona youth soccer clubs include Phoenix Rising FC, CCV Stars, FBSL, Arizona Arsenal, RSL Arizona (South, North, Southern divisions), Next Level Soccer AZ, and FC Tucson. Rankings vary by age group.',
    },
    {
      question: 'How often are Arizona soccer rankings updated?',
      answer:
        'Arizona youth soccer rankings are updated every Monday morning with the latest game results from the previous week.',
    },
    {
      question: 'What is a good PowerScore for an Arizona youth soccer team?',
      answer:
        'A PowerScore of 0.85+ is elite/national-level, 0.70-0.84 is top competitive tier, 0.50-0.69 is solid competitive, and 0.30-0.49 is developing. Scores are on a 0.0 to 1.0 scale.',
    },
    {
      question: 'How does Arizona compare to California and Texas in youth soccer?',
      answer:
        "Arizona has 1,940+ ranked teams compared to California (15,693+) and Texas (9,460+). While smaller in volume, Arizona's top clubs compete nationally. Cross-state tournaments connect Arizona teams to the broader national ranking ecosystem.",
    },
  ],
};
