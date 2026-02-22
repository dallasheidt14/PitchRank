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
  Zap,
  MapPin,
  Users,
  HelpCircle,
  GraduationCap,
  AlertTriangle
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
  {
    slug: 'california-youth-soccer-rankings-guide',
    title: "California Youth Soccer Rankings: The Complete Parent's Guide (2026)",
    excerpt: "From LA Galaxy to San Diego Surf, we're tracking 15,693 California teams. Here's everything parents need to know about youth soccer rankings in CA.",
    author: 'PitchRank Team',
    date: '2026-02-21',
    readingTime: '9 min read',
    tags: ['California', 'Youth Soccer', 'Rankings', 'Parent Guide'],
    content: (
      <div className="space-y-8">
        {/* Introduction */}
        <section>
          <p className="text-lg text-muted-foreground leading-relaxed mb-4">
            California isn't just the biggest state for youth soccer — it's the <strong>epicenter</strong>. With MLS Next academies, ECNL powerhouses, and hundreds of competitive clubs from San Diego to Sacramento, navigating the California youth soccer landscape can feel overwhelming.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">
            We're tracking <strong>15,693 California teams</strong> — more than any other ranking system. That's every age group from U9 to U19, every region, every level of play. Whether you're in Orange County wondering if your club is competitive with LA's best, or in the Bay Area comparing San Jose to Peninsula clubs, this guide gives you the clarity you need.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            Here's everything California soccer parents need to know about youth soccer rankings in 2026 — backed by real data, not hype.
          </p>
        </section>

        {/* Why Rankings Matter */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Target className="size-6 text-primary" />
            Why California Soccer Rankings Matter More Than Anywhere Else
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            California produces more Division I college soccer players and professional prospects than any other state. The competition is fierce, and the opportunities are massive — if you know where to find them.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">But here's the challenge: with <strong>15,693 teams</strong> competing across the state, how do you know where your child actually stands? Rankings solve three critical problems:</p>
          <div className="grid gap-3 mb-4">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Regional reality checks</strong> — Your SoCal team might be dominant locally, but how do they stack up against Bay Area clubs? NorCal powerhouses? San Diego's elite academies?</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>College recruiting context</strong> — California is crawling with college scouts. Rankings help you understand if your child is at the level that attracts Division I attention</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Club comparison</strong> — When choosing between Surf, Slammers, Pateadores, or a local club, rankings help you evaluate development quality</p>
            </div>
          </div>
        </section>

        {/* California Landscape */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <MapPin className="size-6 text-primary" />
            The California Youth Soccer Landscape
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">Major California Soccer Clubs</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">Based on our database of 15,693 teams, here are California's largest youth soccer organizations:</p>
          
          <div className="grid gap-2 mb-6">
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>United SoCal</strong> (254 teams) — One of Southern California's largest competitive programs</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Pateadores Soccer Club</strong> (235 teams) — Orange County powerhouse with deep academy structure</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Total Futbol Academy</strong> (197 teams) — Growing rapidly across Southern California</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Rebels Soccer Club</strong> (194 teams) — Strong competitive presence</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Sporting California USA</strong> (191 teams) — Part of the Sporting network</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>San Diego Surf Soccer Club</strong> (178 teams) — Nationally recognized ECNL program</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>CDA Slammers</strong> (165 teams) — Elite development pathway to professional</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Beach Futbol Club</strong> (159 teams) — Strong SoCal competitive program</span>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">California's Soccer Regions</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">California's youth soccer scene divides into distinct regions, each with its own character:</p>
          
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Southern California (SoCal)</h4>
              <p className="text-sm text-muted-foreground">LA, Orange County, Inland Empire — The densest concentration of elite clubs. LA Galaxy, LAFC, Pateadores, Strikers, and dozens more. Year-round training weather. Massive tournament scene.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">San Diego</h4>
              <p className="text-sm text-muted-foreground">Home to San Diego Surf, Nomads, Albion, and emerging clubs. Strong ECNL representation. Border proximity creates unique cross-regional competition.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Bay Area (NorCal)</h4>
              <p className="text-sm text-muted-foreground">San Jose Earthquakes Academy, De Anza Force, Bay Oaks, Mustang SC. Tech-forward parent community. Growing MLS Next presence.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Central Valley & Sacramento</h4>
              <p className="text-sm text-muted-foreground">Sacramento Republic FC Academy leading the region. Emerging talent pool with lower cost than coastal regions.</p>
            </div>
          </div>
        </section>

        {/* Age Group Breakdown */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Activity className="size-6 text-primary" />
            California Teams by Age Group
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Our database tracks California teams across 12 age groups. Here's the breakdown:
          </p>
          
          <div className="grid sm:grid-cols-3 gap-3 mb-6">
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">2,244</p>
              <p className="text-sm text-muted-foreground">U13 teams</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">2,226</p>
              <p className="text-sm text-muted-foreground">U12 teams</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">2,113</p>
              <p className="text-sm text-muted-foreground">U11 teams</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">1,975</p>
              <p className="text-sm text-muted-foreground">U14 teams</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">1,735</p>
              <p className="text-sm text-muted-foreground">U15 teams</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border text-center">
              <p className="text-2xl font-bold text-primary">1,648</p>
              <p className="text-sm text-muted-foreground">U16 teams</p>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
            <p className="text-sm"><strong>Key insight:</strong> U12-U14 is the most competitive age range with the most teams. This is when players often move from recreational to competitive soccer, creating intense competition for roster spots at top clubs.</p>
          </div>
        </section>

        {/* How Rankings Work */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Brain className="size-6 text-primary" />
            How California Soccer Rankings Actually Work
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">What PitchRank Tracks for California Teams</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Most ranking systems only track ECNL and MLS Next — the elite tiers. That misses 90%+ of California's youth soccer players. PitchRank is different.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-6">We track:</p>
          
          <div className="grid gap-3 mb-6">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Activity className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Every level of play</strong> — MLS Next, ECNL, GA, DPL, NPL, Coast Soccer League, Presidio League, NorCal Premier, SCDSL, and more</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Globe className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>15,693 California teams</strong> — from elite to developmental</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Calendar className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>12 age groups</strong> from U8 through U19</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Shield className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Cross-regional games</strong> — When SoCal plays NorCal at Surf Cup, we capture it</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">The Algorithm Explained (Simply)</h3>
          <div className="grid gap-3 mb-4">
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">1</span>
              <p className="text-sm text-muted-foreground"><strong>Base score</strong> — Wins, losses, draws, and goal differential create the foundation</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">2</span>
              <p className="text-sm text-muted-foreground"><strong>Strength of schedule</strong> — Beating San Diego Surf boosts your ranking more than beating a developmental squad</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">3</span>
              <p className="text-sm text-muted-foreground"><strong>Recency</strong> — Last month's games matter more than January's games from a year ago</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">4</span>
              <p className="text-sm text-muted-foreground"><strong>Consistency</strong> — Teams that perform steadily rank higher than inconsistent rollercoasters</p>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-muted/50 border">
            <h4 className="font-semibold mb-2">PowerScore Scale (0.0 to 1.0)</h4>
            <div className="grid gap-1 text-sm">
              <p><strong className="text-green-600">0.85+</strong> = Elite national-level team (top ECNL/MLS Next)</p>
              <p><strong className="text-blue-600">0.70-0.84</strong> = Top competitive tier (strong ECNL/GA)</p>
              <p><strong className="text-yellow-600">0.50-0.69</strong> = Solid competitive team (DPL/NPL)</p>
              <p><strong className="text-orange-600">0.30-0.49</strong> = Developing/mid-level (league play)</p>
              <p><strong className="text-muted-foreground">Below 0.30</strong> = Recreational or limited data</p>
            </div>
          </div>
        </section>

        {/* SoCal vs NorCal */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <TrendingUp className="size-6 text-primary" />
            SoCal vs NorCal: The Great California Soccer Divide
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            It's the debate that never ends: Is Southern California or Northern California better for youth soccer? Here's what the data tells us:
          </p>

          <div className="grid sm:grid-cols-2 gap-4 mb-6">
            <div className="p-4 rounded-lg bg-orange-500/10 border border-orange-500/20">
              <h4 className="font-semibold mb-2 text-orange-700 dark:text-orange-400">Southern California Advantages</h4>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• Higher volume of elite clubs</li>
                <li>• More MLS Next & ECNL teams</li>
                <li>• Year-round outdoor training</li>
                <li>• Major showcase tournaments (Surf Cup)</li>
                <li>• Dense college scout presence</li>
              </ul>
            </div>
            <div className="p-4 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <h4 className="font-semibold mb-2 text-blue-700 dark:text-blue-400">Northern California Advantages</h4>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• Less roster-hopping culture</li>
                <li>• Stronger player loyalty/development</li>
                <li>• Less burnout-inducing competition</li>
                <li>• Growing academy system</li>
                <li>• Easier college commute for showcases</li>
              </ul>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
            <p className="text-sm"><strong>The truth:</strong> Both regions produce elite talent. The "best" region depends on your goals. If your child wants the most competitive environment with the most exposure, SoCal has more options. If you want strong development without the hyper-competitive pressure, NorCal clubs often provide better balance.</p>
          </div>
        </section>

        {/* Elite Pathways */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Zap className="size-6 text-primary" />
            California's Elite Player Pathways
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">Understanding the Development Tiers</h3>
          <div className="grid gap-3 mb-6">
            <div className="p-4 rounded-lg border border-green-500/30 bg-green-500/5">
              <h4 className="font-semibold text-green-700 dark:text-green-400 mb-2">Tier 1: Professional Academies</h4>
              <p className="text-sm text-muted-foreground">LA Galaxy Academy, LAFC Academy, San Jose Earthquakes Academy, Sacramento Republic FC Academy. Free to play, highest level, direct pathway to professional.</p>
            </div>
            <div className="p-4 rounded-lg border border-blue-500/30 bg-blue-500/5">
              <h4 className="font-semibold text-blue-700 dark:text-blue-400 mb-2">Tier 2: MLS Next & ECNL</h4>
              <p className="text-sm text-muted-foreground">San Diego Surf, CDA Slammers, Pateadores, LA Surf, Real So Cal. Elite competition, national showcases, strong college exposure. Typical cost: $3,000-5,000/year.</p>
            </div>
            <div className="p-4 rounded-lg border border-yellow-500/30 bg-yellow-500/5">
              <h4 className="font-semibold text-yellow-700 dark:text-yellow-400 mb-2">Tier 3: GA, DPL, NPL</h4>
              <p className="text-sm text-muted-foreground">Girls Academy, Discovery Premier League, National Premier League. Strong competition, good development. Typical cost: $2,000-4,000/year.</p>
            </div>
            <div className="p-4 rounded-lg border border-gray-500/30 bg-gray-500/5">
              <h4 className="font-semibold text-gray-700 dark:text-gray-400 mb-2">Tier 4: State & Regional Leagues</h4>
              <p className="text-sm text-muted-foreground">Coast Soccer League, Presidio League, SCDSL, NorCal Premier. Competitive soccer without elite-level travel/cost. Great for development focus.</p>
            </div>
          </div>
        </section>

        {/* College Recruiting */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <GraduationCap className="size-6 text-primary" />
            California Soccer Rankings and College Recruiting
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">California's College Soccer Advantage</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">
            California has more NCAA Division I soccer programs than any other state — UCLA, Stanford, Cal, USC, San Diego State, Santa Clara, Pepperdine, and many more. That means more local recruiting, more showcase attendance, and more opportunities.
          </p>

          <div className="grid gap-3 mb-6">
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division I recruiting</strong> — Coaches actively scout California's top 5% of teams. If you're ranked in the top 500 nationally, you're on their radar.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division II recruiting</strong> — Cal State schools, UC San Diego, and others recruit from the top 15-20% of California teams.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division III recruiting</strong> — Rankings matter less than academics, character, and video highlights.</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">The California Showcases That Matter</h3>
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm font-semibold">Surf Cup (San Diego)</p>
              <p className="text-xs text-muted-foreground">The biggest showcase in the country. College coaches flock here.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm font-semibold">Las Vegas Cup/Players Showcase</p>
              <p className="text-xs text-muted-foreground">Major recruiting event for California teams.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm font-semibold">Blues Cup (San Diego)</p>
              <p className="text-xs text-muted-foreground">Strong regional showcase with college scouts.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm font-semibold">Santa Barbara Kickoff</p>
              <p className="text-xs text-muted-foreground">Season opener with NorCal/SoCal crossover.</p>
            </div>
          </div>
        </section>

        {/* Choosing a Team */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <HelpCircle className="size-6 text-primary" />
            How to Use Rankings When Choosing a California Club
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">Questions to Ask Club Directors</h3>
          <div className="grid gap-3 mb-6">
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"What's your player development philosophy?"</strong><br/>Listen for: Individual development over team results, age-appropriate training, playing time policies.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"How do you handle the competitive pressure of California soccer?"</strong><br/>Good clubs acknowledge burnout risks and have strategies to prevent it.</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"Where have your players gone after club soccer?"</strong><br/>Track record of college placements, academy promotions, or simply happy, well-adjusted players.</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">The California Club Selection Checklist</h3>
          <div className="grid gap-2 mb-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Team ranking within 50-100 positions of appropriate level</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Commute time you can sustain 3-4x per week</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Budget alignment (elite CA clubs: $5,000-8,000/year all-in)</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Playing time guarantee (ask directly)</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Coach credentials and turnover history</span>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <HelpCircle className="size-6 text-primary" />
            Common California Soccer Ranking Questions
          </h2>
          
          <div className="grid gap-4">
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"We moved from another state. How do California teams compare?"</h4>
              <p className="text-sm text-muted-foreground">California is consistently ranked as the most competitive state for youth soccer. A mid-level California team often matches elite teams from smaller states. Give your child time to adjust — the level is higher than almost anywhere.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"Is it worth paying $8,000/year for an elite club?"</h4>
              <p className="text-sm text-muted-foreground"><strong>It depends.</strong> If your child is getting meaningful minutes, high-quality coaching, and appropriate competition, yes. If they're sitting the bench to boost the club's ranking, absolutely not. Rankings help you evaluate — but playing time matters more than club prestige.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"Should my 10-year-old play for the highest-ranked team possible?"</h4>
              <p className="text-sm text-muted-foreground"><strong>No.</strong> At U10/U11, development and enjoyment matter infinitely more than rankings. Put them where they'll play 50+ minutes per game, develop skills, and love soccer. Rankings become more relevant at U14+ when college recruiting starts.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"Why isn't my team ranked if we're winning everything?"</h4>
              <p className="text-sm text-muted-foreground">Rankings require game data. If your league or tournament results aren't being reported to major platforms, we may not have visibility. You can report missing games through PitchRank to ensure your team gets credit.</p>
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="p-6 rounded-lg bg-primary/10 border border-primary/20">
          <h2 className="text-2xl font-display font-bold mb-4">Find Your California Team's Ranking</h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Ready to see where your team stands among California's <strong>15,693 tracked teams</strong>? Visit <strong>PitchRank.io</strong>, search for your club and age group, and get the data-backed perspective you need.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Whether your child plays for San Diego Surf, a Bay Area academy, an Orange County powerhouse, or your local recreational club — rankings give you clarity on where they stand and where they could go.
          </p>
          <p className="text-foreground font-semibold">
            Because in California's crowded youth soccer market, knowledge is power. And knowing where your team truly ranks is the first step to making smarter decisions.
          </p>
        </section>
      </div>
    ),
  },
  {
    slug: 'arizona-youth-soccer-rankings-guide',
    title: "Arizona Youth Soccer Rankings: The Complete Parent's Guide (2026)",
    excerpt: "Confused about Arizona soccer rankings? Here's what every parent needs to know about youth soccer team rankings in AZ, from Phoenix to Tucson.",
    author: 'PitchRank Team',
    date: '2026-02-21',
    readingTime: '8 min read',
    tags: ['Arizona', 'Youth Soccer', 'Rankings', 'Parent Guide'],
    content: (
      <div className="space-y-8">
        {/* Introduction */}
        <section>
          <p className="text-lg text-muted-foreground leading-relaxed mb-4">
            Your kid's team just finished the fall season with a respectable record. But here's the question that keeps Arizona soccer parents up at night: <strong>How good is my child's team, really?</strong>
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Is that U13 squad in Scottsdale actually better than the Phoenix team you lost to? Should you be looking at RSL Arizona or sticking with your current club? And what do those rankings you see online actually <em>mean</em>?
          </p>
          <p className="text-muted-foreground leading-relaxed">
            If you've searched "Arizona soccer rankings" and felt more confused than when you started, you're not alone. Here's everything Arizona parents need to know about youth soccer rankings in 2026 — no jargon, just straight answers.
          </p>
        </section>

        {/* Why Rankings Matter */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Target className="size-6 text-primary" />
            Why Arizona Soccer Rankings Matter
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Arizona's youth soccer scene has exploded over the past decade. We're tracking <strong>1,940 teams across the state</strong> — from U9 recreational squads to U19 elite players heading to college. That's Phoenix Rising FC's youth academy, CCV Stars, FBSL, Arizona Arsenal, and hundreds more clubs competing across 11 age groups.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">Rankings give you three things traditional standings can't:</p>
          <div className="grid gap-3 mb-4">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Context beyond your league</strong> — Your team might dominate the East Valley league, but how do they stack up against Tucson's top clubs?</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Informed club decisions</strong> — When your child outgrows their current team, rankings help identify the right level of competition</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border">
              <CheckCircle className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Realistic college planning</strong> — If college soccer is the goal, you need to know where your team truly ranks</p>
            </div>
          </div>
        </section>

        {/* Arizona Landscape */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <MapPin className="size-6 text-primary" />
            The Arizona Youth Soccer Landscape
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">Major Arizona Soccer Clubs</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">Based on our database, here are the largest youth soccer organizations in Arizona:</p>
          
          <div className="grid gap-2 mb-6">
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Phoenix Rising FC</strong> (132 teams) — The state's professional club's youth academy</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>CCV Stars</strong> (111 teams) — One of the Valley's largest competitive programs</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>FBSL</strong> (109 teams) — Strong presence across age groups</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>Arizona Arsenal Soccer Club</strong> (93 teams) — Known for competitive development</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>RSL Arizona</strong> (189 teams combined) — Real Salt Lake's Arizona pipeline</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded bg-muted/30">
              <Users className="size-4 text-primary" />
              <span className="text-sm"><strong>FC Tucson Youth Soccer</strong> (60 teams) — Anchoring Southern Arizona</span>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">Geographic Soccer Regions</h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Phoenix Metro</h4>
              <p className="text-sm text-muted-foreground">Scottsdale, Tempe, Chandler, Mesa — Highest concentration of elite clubs and year-round play</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Tucson</h4>
              <p className="text-sm text-muted-foreground">Growing competitive scene with FC Tucson leading development</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">Flagstaff/Northern AZ</h4>
              <p className="text-sm text-muted-foreground">Smaller but passionate programs with elevation training advantages</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">East Valley</h4>
              <p className="text-sm text-muted-foreground">Rapidly growing soccer community with new clubs emerging</p>
            </div>
          </div>
        </section>

        {/* How Rankings Work */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <Brain className="size-6 text-primary" />
            How Arizona Soccer Rankings Actually Work
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">What PitchRank Tracks for Arizona Teams</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Most ranking systems only count tournament games or require clubs to self-report results. That creates blind spots — and rankings that favor clubs with bigger marketing budgets.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-6">PitchRank is different. We track:</p>
          
          <div className="grid gap-3 mb-6">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Activity className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Every game we can find</strong> — League play, tournaments, friendlies, showcases</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Globe className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Game-by-game results</strong> across all 1,940 Arizona teams</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Calendar className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>11 age groups</strong> from U9 through U19</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
              <Shield className="size-5 text-primary shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Opponent strength</strong> — Beating RSL Arizona's top U15 team means more than beating a developmental squad</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">The Algorithm Explained (Simply)</h3>
          <div className="grid gap-3 mb-4">
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">1</span>
              <p className="text-sm text-muted-foreground"><strong>Base score</strong> — Wins, losses, draws, and goal differential give us a starting point</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">2</span>
              <p className="text-sm text-muted-foreground"><strong>Strength of schedule</strong> — Beating strong teams boosts your ranking; losing to weak teams hurts</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">3</span>
              <p className="text-sm text-muted-foreground"><strong>Recency</strong> — Games from last month matter more than games from 10 months ago</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">4</span>
              <p className="text-sm text-muted-foreground"><strong>Consistency</strong> — Teams that perform steadily rank higher than teams with wild swings</p>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-muted/50 border">
            <h4 className="font-semibold mb-2">PowerScore Scale (0.0 to 1.0)</h4>
            <div className="grid gap-1 text-sm">
              <p><strong className="text-green-600">0.85+</strong> = Elite national-level team</p>
              <p><strong className="text-blue-600">0.70-0.84</strong> = Top competitive tier</p>
              <p><strong className="text-yellow-600">0.50-0.69</strong> = Solid competitive team</p>
              <p><strong className="text-orange-600">0.30-0.49</strong> = Developing/mid-level</p>
              <p><strong className="text-muted-foreground">Below 0.30</strong> = Recreational or limited data</p>
            </div>
          </div>
        </section>

        {/* What Rankings Mean */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <TrendingUp className="size-6 text-primary" />
            What Your Arizona Team's Ranking Really Means
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">State vs National Rankings</h3>
          <div className="grid sm:grid-cols-2 gap-4 mb-6">
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">State Rank</h4>
              <p className="text-sm text-muted-foreground">Where your team stands among Arizona's ~1,940 teams</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">National Rank</h4>
              <p className="text-sm text-muted-foreground">Where you stand among all teams in your age group nationally</p>
            </div>
          </div>
          
          <div className="p-4 rounded-lg bg-primary/10 border border-primary/20 mb-6">
            <p className="text-sm"><strong>Reality check:</strong> Being top 50 in Arizona is genuinely good. Being top 500 nationally is excellent. Being top 100 nationally? Your team is elite.</p>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">What Rankings DON'T Tell You</h3>
          <div className="grid gap-3">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <AlertTriangle className="size-5 text-yellow-600 shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Individual player development</strong> — A top-ranked team might not be the best fit for your child's growth</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <AlertTriangle className="size-5 text-yellow-600 shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Coaching quality</strong> — Some lower-ranked teams have better developmental coaches than higher-ranked "win-now" teams</p>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <AlertTriangle className="size-5 text-yellow-600 shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground"><strong>Team culture</strong> — Your kid's enjoyment and mental health matter more than ranking</p>
            </div>
          </div>
        </section>

        {/* Choosing a Team */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <HelpCircle className="size-6 text-primary" />
            How to Use Rankings When Choosing a Team
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">The Right Questions to Ask Club Directors</h3>
          <div className="grid gap-3 mb-6">
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"How do you use rankings in player development?"</strong><br/>Good answer: "We track them to ensure competitive balance." Bad answer: "Rankings are all that matter."</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"What's the average ranking of teams you play?"</strong><br/>Reveals if they're scheduling appropriately challenging competition</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm text-muted-foreground"><strong>"How have your team's rankings trended?"</strong><br/>Upward trends suggest good development; flat or declining suggests stagnation</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">Finding the Right Competition Level</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">The best team for your child isn't always the highest-ranked team. It's the team that:</p>
          <div className="grid gap-2 mb-4">
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Plays opponents 10-20 ranking positions above AND below them</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Gives your child meaningful playing time (30+ minutes per game)</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Challenges them without crushing their confidence</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle className="size-4 text-primary" />
              <span className="text-sm text-muted-foreground">Aligns with your family's travel/financial capacity</span>
            </div>
          </div>
        </section>

        {/* College Recruiting */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <GraduationCap className="size-6 text-primary" />
            Arizona Soccer Rankings and College Recruiting
          </h2>
          
          <h3 className="text-xl font-display font-semibold mb-3">The Reality Check</h3>
          <div className="grid gap-3 mb-6">
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division I recruiting</strong> — Coaches notice teams ranked in the <strong>top 5% nationally</strong> (very elite)</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division II recruiting</strong> — Top 15-20% nationally gets attention, but individual performance matters more</p>
            </div>
            <div className="p-3 rounded-lg bg-muted/50 border">
              <p className="text-sm"><strong>Division III recruiting</strong> — Rankings barely matter; coaches focus on academics, character, and fit</p>
            </div>
          </div>

          <h3 className="text-xl font-display font-semibold mb-3">What Actually Matters More</h3>
          <p className="text-muted-foreground leading-relaxed mb-4">College coaches told us they prioritize:</p>
          <div className="grid gap-2">
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">1</span>
              <p className="text-sm text-muted-foreground"><strong>Individual video</strong> — Highlight reels of YOUR child, not team stats</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">2</span>
              <p className="text-sm text-muted-foreground"><strong>Academic eligibility</strong> — GPA and test scores filter out players before rankings ever matter</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">3</span>
              <p className="text-sm text-muted-foreground"><strong>Showcase attendance</strong> — Surf Cup, Vegas Cup, ECNL playoffs (where scouts actually are)</p>
            </div>
            <div className="flex items-start gap-3">
              <span className="flex items-center justify-center size-6 rounded-full bg-primary text-primary-foreground text-sm font-bold shrink-0">4</span>
              <p className="text-sm text-muted-foreground"><strong>Direct contact</strong> — Emails to coaches with video links beat high rankings</p>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section>
          <h2 className="text-2xl font-display font-bold mb-4 flex items-center gap-3">
            <HelpCircle className="size-6 text-primary" />
            Common Arizona Soccer Ranking Questions
          </h2>
          
          <div className="grid gap-4">
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"My team dominates our local league but has a mediocre ranking. Why?"</h4>
              <p className="text-sm text-muted-foreground">You're likely playing weaker competition. Rankings adjust for opponent strength, so beating weaker teams by 5 goals doesn't boost your ranking as much as narrowly beating a strong team.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"Should my U11 player be on the highest-ranked team possible?"</h4>
              <p className="text-sm text-muted-foreground"><strong>No.</strong> At U11, development and playing time matter WAY more than rankings. Put them on a team where they'll get 50+ minutes per game, not a top-ranked team where they'll sit the bench.</p>
            </div>
            <div className="p-4 rounded-lg bg-muted/50 border">
              <h4 className="font-semibold mb-2">"Can my club game the rankings by only playing weak teams?"</h4>
              <p className="text-sm text-muted-foreground">Short answer: No. Our algorithm detects this and penalizes teams that avoid strong competition. You can't fake strength of schedule.</p>
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="p-6 rounded-lg bg-primary/10 border border-primary/20">
          <h2 className="text-2xl font-display font-bold mb-4">Check Your Arizona Team's Ranking</h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Ready to see where your team stands? Visit <strong>PitchRank.io</strong>, search for your club and age group, and track your team's progress throughout the season.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Whether your child plays for Phoenix Rising FC, CCV Stars, Arizona Arsenal, or your local recreational club, rankings give you clarity on where they stand — and where they could go next.
          </p>
          <p className="text-foreground font-semibold">
            Because at the end of the day, rankings aren't about bragging rights. They're about making informed decisions that help your child develop, compete at the right level, and — most importantly — enjoy the beautiful game.
          </p>
        </section>
      </div>
    ),
  },
];
