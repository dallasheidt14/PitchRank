import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FAQSchema } from '@/components/FAQSchema';
import {
  Star,
  Brain,
  Cpu,
  Link,
  Calendar,
  Globe,
  UserPlus,
  Eye,
  HelpCircle,
  Target,
  CheckCircle,
  TrendingUp,
  Shield,
  Activity,
  Clock,
  Anchor,
} from 'lucide-react';

/**
 * MethodologySection component - explains the PitchRank ranking methodology
 */
export function MethodologySection() {
  return (
    <>
      <FAQSchema />
      <div className="space-y-8">
        {/* Introduction */}
        <Card variant="primary">
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Star className="size-6 text-accent" />
              PitchRank Methodology
            </h2>
            <CardDescription className="text-base">
              Creating the fairest, most accurate youth soccer rankings in the country
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              PitchRank was built for one purpose: to create the fairest, most accurate youth soccer rankings in the country.
              We do that using a two-part rating system that looks at every game from multiple angles while staying stable,
              consistent, and extremely hard to manipulate.
            </p>
          </CardContent>
        </Card>

        {/* Part 1: Core Rating Engine */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Brain className="size-6 text-primary" />
              Part 1: The Core Rating Engine
            </h2>
            <CardDescription>
              The foundation of every PitchRank score
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <p className="text-muted-foreground leading-relaxed">
              At the heart of PitchRank is a powerful engine that understands the game the way coaches do —
              by looking deeper than scores. Here&apos;s what it takes into account:
            </p>

            <div className="grid gap-4">
              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <CheckCircle className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Quality of Opponents</h4>
                  <p className="text-sm text-muted-foreground">
                    Your results are measured through the lens of who you played. Beat a top team? That matters.
                    Roll over a struggling one? Not as much.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Activity className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">How Competitive You Were</h4>
                  <p className="text-sm text-muted-foreground">
                    A 1–0 battle against a powerhouse says more than a 10–0 cruise.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <TrendingUp className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Strength of Schedule (SOS)</h4>
                  <p className="text-sm text-muted-foreground">
                    Your record is only half the story. Who you earned it against is the rest.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Shield className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Offensive & Defensive Behavior</h4>
                  <p className="text-sm text-muted-foreground">
                    Your performance patterns matter — not just the scoreboard.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Clock className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Recency</h4>
                  <p className="text-sm text-muted-foreground">
                    Yesterday&apos;s form matters more than last season&apos;s form.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 p-4 rounded-lg bg-muted/50">
                <Anchor className="size-5 text-primary mt-0.5 shrink-0" />
                <div>
                  <h4 className="font-display font-semibold uppercase tracking-wide text-sm mb-1">Stability</h4>
                  <p className="text-sm text-muted-foreground">
                    Consistent teams get recognized. Fluky results don&apos;t define you.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-6 p-4 rounded-lg bg-primary/10 border border-primary/20">
              <p className="text-sm font-medium text-foreground">
                <strong>The result?</strong> A true, data-driven measure of team strength — not just a tally of wins and losses.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Part 2: Machine Learning Layer */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Cpu className="size-6 text-primary" />
              Part 2: The Machine Learning Layer
            </h2>
            <CardDescription>
              The &quot;smarts&quot; that identify rising teams
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground leading-relaxed">
              Once we understand how strong a team is, our system evaluates how a team is trending.
              This is where machine learning comes in.
            </p>

            <p className="text-muted-foreground leading-relaxed">
              It looks at every game and asks: <em>&quot;Given what we know about both teams…
              did this result feel expected, or surprising?&quot;</em>
            </p>

            <div className="space-y-3 my-4">
              <div className="flex items-center gap-3 p-3 rounded-lg bg-green-500/10 border border-green-500/20">
                <TrendingUp className="size-5 text-green-600 shrink-0" />
                <p className="text-sm text-foreground">
                  If a team consistently <strong>overperforms</strong> expectations → they&apos;re climbing.
                </p>
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                <Activity className="size-5 text-red-600 shrink-0" />
                <p className="text-sm text-foreground">
                  If they regularly <strong>underperform</strong> → the system takes notice.
                </p>
              </div>
            </div>

            <p className="text-muted-foreground leading-relaxed">
              This adjustment is intentionally small, but incredibly powerful.
              It helps surface underrated teams — and filter out misleading results.
            </p>
          </CardContent>
        </Card>

        {/* How It All Comes Together */}
        <Card variant="accent">
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Link className="size-6 text-accent" />
              How It All Comes Together
            </h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground leading-relaxed">
              Our final rankings combine both components:
            </p>

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
              This blend creates a ranking that&apos;s:
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

            <p className="text-foreground font-medium mt-4">
              It&apos;s the closest thing youth soccer has to a true rating system.
            </p>
          </CardContent>
        </Card>

        {/* Updated Every Monday */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Calendar className="size-6 text-primary" />
              Updated Every Monday
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed mb-4">
              Every Monday morning, the entire network refreshes:
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
            <p className="text-foreground font-medium mt-4">
              The rankings get sharper every single week.
            </p>
          </CardContent>
        </Card>

        {/* Connected Across States */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Globe className="size-6 text-primary" />
              Connected Across States, Leagues & Events
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              One of PitchRank&apos;s biggest strengths is how quickly the system builds connections.
              Tournament in Arizona meets tournament in Texas. Teams cross into California.
              National events tie everything together.
            </p>
            <p className="text-foreground font-medium mt-4">
              The more teams play, the more accurate — and nationally interconnected — the entire ranking ecosystem becomes.
            </p>
          </CardContent>
        </Card>

        {/* New Teams */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <UserPlus className="size-6 text-primary" />
              How We Handle New or Light-Data Teams
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              New teams start conservatively, then rise as results come in.
              No inflated placements. No artificial penalties.
              Just a fair runway to show who you really are.
            </p>
          </CardContent>
        </Card>

        {/* Transparent But Proprietary */}
        <Card>
          <CardHeader>
            <h2 className="leading-none font-semibold flex items-center gap-3">
              <Eye className="size-6 text-primary" />
              Transparent. But Proprietary.
            </h2>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground leading-relaxed">
              We tell you what matters — opponents, schedule strength, consistency, and performance trends —
              but we do not share the exact formulas, weights, or internal parameters.
            </p>
            <p className="text-foreground font-medium mt-4">
              That&apos;s our secret sauce. And it&apos;s what keeps PitchRank ahead of the curve.
            </p>
          </CardContent>
        </Card>

        {/* FAQ */}
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
              <p className="text-sm text-muted-foreground">
                Only when the opponent is strong. Context is everything.
              </p>
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
          </CardContent>
        </Card>

        {/* The PitchRank Promise */}
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
              PitchRank blends statistical truth with real-world performance to show where teams actually stand —
              not where inflated scores or easy schedules would put them.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
