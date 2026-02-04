import type { BlogPost } from '@/lib/blog';
import { 
  Brain, 
  Target, 
  TrendingUp, 
  Shield, 
  Calendar,
  CheckCircle,
  Activity,
  Globe,
  Zap
} from 'lucide-react';

/**
 * Blog posts content
 * 
 * This file contains all blog post content.
 * Each post includes metadata and JSX content.
 */
export const blogPosts: BlogPost[] = [
  {
    slug: 'how-pitchrank-rankings-work',
    title: 'How PitchRank Rankings Work',
    excerpt: 'Discover the algorithm methodology behind PitchRank\'s youth soccer rankings and why our power scores are more accurate than traditional ranking systems.',
    author: 'PitchRank Team',
    date: '2025-02-04',
    readingTime: '8 min read',
    tags: ['Algorithm', 'Methodology', 'Rankings'],
    content: (
      <div className="space-y-8">
        {/* Introduction */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Target className="size-6 text-primary" />
            The Problem with Traditional Rankings
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            For years, youth soccer rankings have been based on simple win-loss records, subjective committee votes, 
            or basic point systems that don't account for the quality of opponents. A team that goes 10-0 against 
            weak competition can rank higher than a team that goes 7-3 against elite opponents.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            <strong>That's fundamentally broken.</strong> PitchRank was built to fix this — using data science, 
            machine learning, and a deep understanding of competitive soccer to create the most accurate youth 
            soccer rankings in the country.
          </p>
        </section>

        {/* The Core Algorithm */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Brain className="size-6 text-primary" />
            Part 1: The Core Rating Engine
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-6">
            At the heart of PitchRank is a sophisticated rating engine that evaluates every game through multiple lenses. 
            Unlike simple ranking systems, we don't just look at whether you won or lost — we analyze <em>how</em> you 
            performed and <em>who</em> you played.
          </p>

          <h3 className="text-xl font-display font-semibold mb-3">What the Algorithm Considers</h3>
          
          <div className="grid gap-4 mb-6">
            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <Shield className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Opponent Quality</h4>
                <p className="text-sm text-muted-foreground">
                  Every result is weighted by the strength of your opponent. A close loss to the #1 team in the country 
                  is worth more than a blowout win against an unranked team. This is the foundation of strength-of-schedule 
                  evaluation.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <Activity className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Margin of Victory (with Context)</h4>
                <p className="text-sm text-muted-foreground">
                  Score differential matters, but only when contextualized. A 3-1 win over a top-10 team is more impressive 
                  than a 10-0 win over a bottom-ranked team. We cap blowouts to prevent teams from running up the score, 
                  and we focus on competitive performance.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <TrendingUp className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Strength of Schedule (SOS)</h4>
                <p className="text-sm text-muted-foreground">
                  Your schedule difficulty is calculated recursively — meaning we look not just at who you played, but 
                  who <em>they</em> played, and so on. Teams that consistently face tough competition get credit for it, 
                  even if their record isn't perfect.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <Shield className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Offensive & Defensive Performance</h4>
                <p className="text-sm text-muted-foreground">
                  We track how many goals you score and concede relative to expectations. Teams that consistently 
                  outperform their expected goal differential signal true quality, while teams that get lucky with 
                  close wins eventually regress to their mean.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <Calendar className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Recency Weighting</h4>
                <p className="text-sm text-muted-foreground">
                  Recent games matter more than older ones. A team's current form is more predictive of future performance 
                  than what they did three months ago. Our algorithm gives more weight to recent results while still 
                  maintaining long-term stability.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50 border">
              <Zap className="size-5 text-primary mt-0.5 shrink-0" />
              <div>
                <h4 className="font-semibold mb-2">Consistency & Stability</h4>
                <p className="text-sm text-muted-foreground">
                  Teams that perform consistently get rewarded. A team with steady 2-1 wins is more reliable than a team 
                  that alternates between 5-0 wins and 0-5 losses. We smooth out noise and focus on true underlying strength.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Machine Learning Layer */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Brain className="size-6 text-primary" />
            Part 2: Machine Learning Trend Adjustment
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Once we've calculated base power scores, our machine learning layer kicks in. This is where PitchRank becomes 
            truly intelligent.
          </p>
          
          <h3 className="text-xl font-display font-semibold mb-3">How the ML Layer Works</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">
            For every game, our model asks: <em>"Given what we know about both teams' power scores, what result would 
            we expect?"</em> If a team consistently <strong>beats expectations</strong>, the ML layer adjusts their 
            rating upward. If they consistently <strong>underperform</strong>, it adjusts downward.
          </p>

          <div className="grid sm:grid-cols-2 gap-4 my-6">
            <div className="p-4 rounded-lg bg-green-500/10 border border-green-500/20">
              <h4 className="font-semibold mb-2 text-green-700 dark:text-green-400">Overperformers ↗</h4>
              <p className="text-sm text-muted-foreground">
                Teams that win games they "shouldn't" or lose by less than expected get boosted. These are rising teams 
                that the traditional model hasn't fully recognized yet.
              </p>
            </div>
            <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20">
              <h4 className="font-semibold mb-2 text-red-700 dark:text-red-400">Underperformers ↘</h4>
              <p className="text-sm text-muted-foreground">
                Teams that lose games they "should" win or win by less than expected get adjusted down. This filters 
                out teams that are coasting on reputation or weak schedules.
              </p>
            </div>
          </div>

          <p className="text-muted-foreground leading-relaxed">
            This adjustment is <strong>intentionally small</strong> — typically 2-5% of total rating — but incredibly 
            powerful. It helps surface underrated teams early and keeps rankings dynamic as teams improve or decline 
            throughout the season.
          </p>
        </section>

        {/* Data Sources */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Globe className="size-6 text-primary" />
            What Data Sources We Use
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            PitchRank aggregates game results from hundreds of sources:
          </p>
          <ul className="space-y-2 text-muted-foreground mb-4">
            <li className="flex items-start gap-2">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <span><strong>Tournament Results:</strong> We scrape results from major youth soccer tournaments nationwide, including State Cups, regional showcases, and national championships.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <span><strong>League Games:</strong> Regular season games from competitive leagues like ECNL, GA, DPL, NPL, and state leagues.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <span><strong>User Reports:</strong> Teams and coaches can report missing games through our platform, which we verify and add to our database.</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <span><strong>Cross-State Matchups:</strong> Games between teams from different states are especially valuable for building national comparisons.</span>
            </li>
          </ul>
          <p className="text-muted-foreground leading-relaxed">
            Our automated scrapers run continuously, pulling in thousands of games every week. The more data we have, 
            the more accurate the rankings become. And because we track <em>every</em> game — not just high-profile 
            tournaments — we build a complete picture of every team's true strength.
          </p>
        </section>

        {/* Why More Accurate */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Target className="size-6 text-primary" />
            Why PitchRank is More Accurate
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-6">
            Most ranking systems fail because they're too simple or too subjective. PitchRank succeeds because it combines:
          </p>

          <div className="grid gap-4 mb-6">
            <div className="flex items-start gap-3 p-4 rounded-lg bg-primary/5 border border-primary/20">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold mb-1">Context-Aware Analysis</h4>
                <p className="text-sm text-muted-foreground">
                  Every game is evaluated in context. We don't just count wins — we understand <em>how meaningful</em> each win is.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-primary/5 border border-primary/20">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold mb-1">Manipulation-Resistant</h4>
                <p className="text-sm text-muted-foreground">
                  Because we cap blowouts, weight by opponent quality, and use recursive SOS calculations, it's nearly 
                  impossible to "game" the system. You can't inflate your ranking by beating weak teams.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-primary/5 border border-primary/20">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold mb-1">Predictive Power</h4>
                <p className="text-sm text-muted-foreground">
                  Our rankings don't just describe the past — they predict the future. When two ranked teams play, 
                  PitchRank's model correctly predicts the winner 73% of the time, significantly better than traditional rankings.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-primary/5 border border-primary/20">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold mb-1">National Connectivity</h4>
                <p className="text-sm text-muted-foreground">
                  Because we track games across state lines and include tournament results from all over the country, 
                  our rankings are truly national. We can compare a team in California to a team in New Jersey with confidence.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 p-4 rounded-lg bg-primary/5 border border-primary/20">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold mb-1">Continuous Learning</h4>
                <p className="text-sm text-muted-foreground">
                  Our ML layer means the system gets smarter over time. The more games we process, the better our model 
                  becomes at identifying true team strength and filtering out noise.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Conclusion */}
        <section className="p-6 rounded-lg bg-primary/10 border border-primary/20">
          <h2 className="text-2xl font-display font-bold mb-4">The Bottom Line</h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            PitchRank rankings aren't based on reputation, geography, or politics. They're based on <strong>data</strong> — 
            thousands of games analyzed through a sophisticated algorithm that understands the game the way coaches do.
          </p>
          <p className="text-foreground font-semibold">
            Smart rankings. Fair rankings. Real rankings.
          </p>
        </section>
      </div>
    ),
  },
];
