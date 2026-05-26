import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { FAQSchema } from '@/components/FAQSchema';
import {
  Star,
  Brain,
  Cpu,
  Link,
  Calendar,
  Globe,
  UserPlus,
  HelpCircle,
  Target,
  CheckCircle,
  TrendingUp,
  Shield,
  Activity,
  Clock,
  Anchor,
  Database,
  MapPin,
  Scale,
} from 'lucide-react';

/**
 * MethodologySection component - explains the PitchRank ranking methodology
 *
 * 10-section layout covering data sourcing, core engine, cross-league calibration,
 * sparse-schedule handling, ML layer, synthesis, cadence, FAQ, and promise.
 */
export function MethodologySection() {
  return (
    <>
      <FAQSchema />
      <div className="space-y-8">
        {/* Section 1 — Hero */}
        <Card variant="primary">
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Star className="size-6 text-accent" />
              How PitchRank Rankings Work
            </h2>
            <CardDescription className="text-base">
              Creating the fairest, most accurate youth soccer rankings in the country
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank uses a two-part rating system that analyzes every game from multiple angles — opponent quality,
              competitiveness, schedule strength, and performance trends. The result is a ranking that&apos;s stable,
              consistent, and extremely hard to manipulate. Whether your team plays in a top national league or a
              competitive state circuit, the system evaluates you on the same terms.
            </p>
          </CardContent>
        </Card>

        {/* Section 2 — Where Our Data Comes From */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Database className="size-6 text-primary" />
              Where Our Data Comes From
            </h2>
            <CardDescription>The foundation of accurate rankings is comprehensive data</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <p className="text-muted-foreground leading-relaxed">
              Accurate rankings start with accurate data. PitchRank collects verified game results from tournaments,
              league play, showcases, and cross-state events — pulling from multiple platforms so we&apos;re never
              locked to a single data source. This gives us broader coverage than any platform-specific ranking system.
            </p>

            <div className="grid gap-4">
              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Globe className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Multi-Source Collection
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Game results from tournaments, league play, showcases, and cross-state events. Not locked to any
                    single platform — we pull from wherever competitive youth soccer is played.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Shield className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Verification & Deduplication
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Every game result is verified and deduplicated to prevent double-counting. When a game appears in
                    multiple data sources, we reconcile it into a single clean record.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <MapPin className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Coverage</h4>
                  <p className="text-sm text-muted-foreground">
                    All 50 states, U10 through U19, boys and girls. Thousands of competitive teams tracked across the
                    country.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Activity className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Daily Ingestion</h4>
                  <p className="text-sm text-muted-foreground">
                    New game results flow in daily as tournaments and leagues report scores. The data pipeline never
                    stops.
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Section 3 — The Core Rating Engine */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Brain className="size-6 text-primary" />
              The Core Rating Engine
            </h2>
            <CardDescription>The foundation of every PitchRank score</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <p className="text-muted-foreground leading-relaxed">
              At the heart of PitchRank is a powerful rating engine that understands the game the way coaches do — by
              looking deeper than scores. Here&apos;s what it takes into account:
            </p>

            <div className="grid gap-4">
              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <CheckCircle className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Quality of Opponents
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Your results are measured through the lens of who you played. A win against a top-10 team in your
                    state carries far more weight than a win against an unranked opponent. This prevents teams from
                    inflating their record against weak competition.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Activity className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    How Competitive You Were
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    A 1–0 battle against a powerhouse says more than a 10–0 cruise. The system evaluates the margin and
                    context of each result, not just wins and losses.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <TrendingUp className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Strength of Schedule
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Your record is only half the story. Who you earned it against is the rest. Two teams can have
                    identical records, but if one earned theirs against nationally-ranked opponents and the other played
                    only local recreation teams, their ratings will reflect that difference.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Shield className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Offensive & Defensive Behavior
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Your performance patterns matter — not just the scoreboard. Teams that consistently create scoring
                    opportunities and limit opponents earn recognition beyond the final score.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Clock className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Recency</h4>
                  <p className="text-sm text-muted-foreground">
                    Yesterday&apos;s form matters more than last season&apos;s form. Recent games carry more weight, so
                    a team on a hot streak will see that reflected in their rating faster than in systems that weight
                    all games equally.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Anchor className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Stability</h4>
                  <p className="text-sm text-muted-foreground">
                    Consistent teams get recognized. Fluky results don&apos;t define you. The system is designed to
                    reward sustained performance over a string of games, not overreact to a single upset.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-6 p-4 rounded-lg bg-primary/10 border border-primary/20">
              <p className="text-sm font-medium text-foreground">
                <strong>The result?</strong> A true, data-driven measure of team strength — not just a tally of wins and
                losses.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Section 4 — Cross-League Strength Calibration */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Scale className="size-6 text-primary" />
              Cross-League Strength Calibration
            </h2>
            <CardDescription>Comparing teams fairly across different leagues and platforms</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <p className="text-muted-foreground leading-relaxed">
              Teams play in different leagues — ECNL, GA, state leagues, independent clubs. Comparing across them
              requires calibration. Our system handles this automatically by using cross-league games as calibration
              anchors.
            </p>

            <div className="grid gap-4">
              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <TrendingUp className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    League-Strength Calibration
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    The system recognizes that leagues vary in overall competitiveness and adjusts accordingly. A strong
                    record in an elite league means more than the same record in a less competitive one.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Globe className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Tournament Cross-Pollination
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    When teams from different leagues meet at tournaments, those head-to-head results directly calibrate
                    cross-league strength. These matchups are the anchors that connect separate ecosystems.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Link className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    The Network Effect
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    The more cross-league games played, the more accurate comparisons become. By mid-season, even teams
                    that have never played each other can be compared through chains of shared opponents.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Target className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Seasonal Convergence
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Early-season rankings have wider uncertainty because teams haven&apos;t played enough cross-league
                    games. As the season progresses and more connections form, the system gets sharper and more
                    confident.
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Section 5 — How We Handle Teams With Few Games */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <UserPlus className="size-6 text-primary" />
              How We Handle Teams With Few Games
            </h2>
            <CardDescription>Fair treatment for new and developing teams</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <p className="text-muted-foreground leading-relaxed">
              Every team starts somewhere. Our system is designed to give new and light-data teams a fair runway without
              inflating or penalizing them before enough evidence exists.
            </p>

            <div className="grid gap-4">
              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Shield className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Conservative Starting Point
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    New teams begin with a neutral rating — not inflated, not penalized. This means they won&apos;t
                    appear artificially high or low before enough games have been played.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Activity className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Confidence & Uncertainty
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    With fewer games, the system assigns wider uncertainty to a team&apos;s rating. The rating exists
                    but carries less confidence. As more games are played against rated opponents, that uncertainty
                    narrows.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <CheckCircle className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Minimum Games Threshold
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    Teams need a minimum number of verified games before appearing in official rankings. This prevents a
                    single fluky result from producing a misleading placement.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <TrendingUp className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">
                    Gradual Convergence
                  </h4>
                  <p className="text-sm text-muted-foreground">
                    As a team plays more games against rated opponents, their rating stabilizes and their ranking
                    becomes increasingly reliable. There are no shortcuts — the system rewards evidence.
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Section 6 — The Machine Learning Layer */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Cpu className="size-6 text-primary" />
              The Machine Learning Layer
            </h2>
            <CardDescription>The &quot;smarts&quot; that identify rising teams</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground leading-relaxed">
              Once core strength is established, the ML layer evaluates how a team is trending. It asks:{' '}
              <em>&quot;Given what we know about both teams… did this result feel expected, or surprising?&quot;</em>
            </p>

            <div className="space-y-3 my-4">
              <div className="flex items-start gap-3 p-3 rounded-lg bg-green-500/10 border border-green-500/20">
                <TrendingUp className="size-5 text-green-600 shrink-0 mt-0.5" />
                <p className="text-sm text-foreground">
                  If a team consistently <strong>overperforms</strong> expectations → they&apos;re climbing. For
                  example, if a team rated #30 in their state consistently beats teams rated #10–#15, the ML layer
                  detects that pattern and adjusts their rating upward — even before they&apos;ve played enough games
                  for the core engine to catch up.
                </p>
              </div>
              <div className="flex items-start gap-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                <Activity className="size-5 text-red-600 shrink-0 mt-0.5" />
                <p className="text-sm text-foreground">
                  If they regularly <strong>underperform</strong> → the system takes notice and adjusts accordingly.
                </p>
              </div>
            </div>

            <p className="text-muted-foreground leading-relaxed">
              The ML adjustment is intentionally small — it fine-tunes rather than overrides. A massive upset in a
              single game won&apos;t swing a rating, but a consistent pattern of exceeding expectations will.
            </p>

            <p className="text-muted-foreground leading-relaxed">
              The core engine measures where a team has been. The ML layer anticipates where they&apos;re going.
            </p>
          </CardContent>
        </Card>

        {/* Section 7 — How It All Comes Together */}
        <Card variant="accent">
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Link className="size-6 text-accent" />
              How It All Comes Together
            </h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground leading-relaxed">Our final rankings combine both components:</p>

            <div className="grid sm:grid-cols-2 gap-4 my-4">
              <div className="p-4 rounded-lg bg-background border">
                <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">Core Performance</h4>
                <p className="text-sm text-muted-foreground">The foundation</p>
              </div>
              <div className="p-4 rounded-lg bg-background border">
                <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">ML Trend Adjustment</h4>
                <p className="text-sm text-muted-foreground">The fine-tuning</p>
              </div>
            </div>

            <p className="text-muted-foreground leading-relaxed">
              The final PowerScore is a single number that captures both proven strength and emerging trajectory. This
              blend creates a ranking that&apos;s:
            </p>

            <ul className="grid sm:grid-cols-2 gap-2 text-sm text-muted-foreground">
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Stable week to week
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Fair to every team
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Impossible to &quot;game&quot;
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Reflective of real on-field strength
              </li>
              <li className="flex items-center gap-2 sm:col-span-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Constantly learning as new games come in
              </li>
            </ul>
          </CardContent>
        </Card>

        {/* Section 8 — Update Cadence & Data Freshness */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Calendar className="size-6 text-primary" />
              Update Cadence & Data Freshness
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed mb-4">
              Game results flow into our system daily as tournaments and leagues report scores. Every Monday morning,
              the entire ranking network recalculates with the latest data.
            </p>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                New results feed the engine
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Strength of schedule updates
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Cross-state comparisons tighten
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="size-4 text-primary shrink-0" />
                Machine learning picks up new trends
              </li>
            </ul>
            <p className="text-foreground font-medium mt-4">The rankings get sharper every single week.</p>
          </CardContent>
        </Card>

        {/* Section 9 — Frequently Asked Questions */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <HelpCircle className="size-6 text-primary" />
              Frequently Asked Questions
            </h2>
          </CardHeader>
          <CardContent className="space-y-6">
            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Is this easy to manipulate?
              </h4>
              <p className="text-sm text-muted-foreground">
                No. Schedule strength, consistency patterns, and ML comparisons prevent &quot;gaming the system.&quot;
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Does winning by a lot help?
              </h4>
              <p className="text-sm text-muted-foreground">Only when the opponent is strong. Context is everything.</p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Why doesn&apos;t one game swing our ranking?
              </h4>
              <p className="text-sm text-muted-foreground">
                Because long-term patterns matter more than isolated results.
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Can we report missing games?
              </h4>
              <p className="text-sm text-muted-foreground">
                Yes — tap the Missing Games button and we&apos;ll automatically find and add them.
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                How does PitchRank compare teams across different leagues?
              </h4>
              <p className="text-sm text-muted-foreground">
                Our system calibrates league strength automatically. When teams from different leagues meet at
                tournaments, those head-to-head results anchor cross-league comparisons. The more inter-league games
                played, the more accurate these comparisons become.
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                How accurate are rankings for teams that have only played a few games?
              </h4>
              <p className="text-sm text-muted-foreground">
                Rankings for newer teams carry wider uncertainty. We require a minimum number of verified games before a
                team appears in official rankings, and even then, their rating stabilizes further with each additional
                game. Early-season rankings should be treated as directional, not definitive.
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Where does PitchRank get its game data?
              </h4>
              <p className="text-sm text-muted-foreground">
                We collect verified game results from tournaments, leagues, showcases, and cross-state events across all
                50 states. Our data pipeline pulls from multiple sources — we are not locked to any single tournament
                platform, which gives us broader coverage than platform-specific ranking systems.
              </p>
            </div>

            <div>
              <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-2">
                Can teams from different states be compared fairly?
              </h4>
              <p className="text-sm text-muted-foreground">
                Yes. Cross-state tournaments and national events create direct connections between state ecosystems. A
                team from Arizona that plays in a California tournament creates a bridge that links both states&apos;
                rankings. The more cross-state play, the more accurate interstate comparisons become.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Section 10 — The PitchRank Promise */}
        <Card variant="primary">
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Target className="size-6 text-accent" />
              The PitchRank Promise
            </h2>
          </CardHeader>
          <CardContent>
            <div className="text-center space-y-2 mb-4">
              <p className="text-lg font-display font-semibold uppercase tracking-wide">Smart rankings.</p>
              <p className="text-lg font-display font-semibold uppercase tracking-wide">Fair rankings.</p>
              <p className="text-lg font-display font-semibold uppercase tracking-wide">Real rankings.</p>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank blends statistical truth with real-world performance to show where teams actually stand — not
              where inflated scores or easy schedules would put them.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
