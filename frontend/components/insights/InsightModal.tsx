"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Brain,
  Target,
  Swords,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  AlertCircle,
  ExternalLink,
  Flame,
  Snowflake,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  TeamInsightsResponse,
  SeasonTruthInsight,
  ConsistencyInsight,
  PersonaInsight,
  FormSignal,
} from "@/lib/insights/types";
import Link from "next/link";

interface InsightModalProps {
  isOpen: boolean;
  onClose: () => void;
  teamId: string;
  teamName: string;
}

/**
 * Modal component for displaying team insights
 * Premium-only feature showing:
 * - Season Truth Summary
 * - Consistency Score
 * - Team Persona Label
 */
export function InsightModal({
  isOpen,
  onClose,
  teamId,
  teamName,
}: InsightModalProps) {
  const [insights, setInsights] = useState<TeamInsightsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/insights/${teamId}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to fetch insights");
      }

      setInsights(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load insights");
    } finally {
      setIsLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    if (isOpen && teamId) {
      fetchInsights();
    }
  }, [isOpen, teamId, fetchInsights]);

  const seasonTruth = insights?.insights.find(
    (i) => i.type === "season_truth"
  ) as SeasonTruthInsight | undefined;

  const consistency = insights?.insights.find(
    (i) => i.type === "consistency_score"
  ) as ConsistencyInsight | undefined;

  const persona = insights?.insights.find(
    (i) => i.type === "persona"
  ) as PersonaInsight | undefined;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <Brain className="h-5 w-5 text-primary" />
            Team Insights
          </DialogTitle>
          <DialogDescription className="text-base">
            {teamName}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">
              Generating insights...
            </p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" size="sm" onClick={fetchInsights}>
              Try Again
            </Button>
          </div>
        ) : (
          <div className="space-y-6 py-2">
            {/* Season Truth Summary */}
            {seasonTruth && (
              <div className="bg-gradient-to-br from-primary/5 to-primary/10 border border-primary/20 rounded-xl p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Brain className="h-5 w-5 text-primary" />
                  <h3 className="font-semibold text-lg">Season Truth</h3>
                </div>
                <p className="text-foreground leading-relaxed">
                  {seasonTruth.text}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {/* Rank Trajectory Badge - based on perf_centered */}
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium",
                      seasonTruth.details.rankTrajectory === "rising"
                        ? "bg-green-500/20 text-green-700 dark:text-green-400"
                        : seasonTruth.details.rankTrajectory === "falling"
                          ? "bg-red-500/20 text-red-700 dark:text-red-400"
                          : "bg-muted text-muted-foreground"
                    )}
                  >
                    {seasonTruth.details.rankTrajectory === "rising" && <TrendingUp className="h-3 w-3" />}
                    {seasonTruth.details.rankTrajectory === "falling" && <TrendingDown className="h-3 w-3" />}
                    {seasonTruth.details.rankTrajectory === "rising"
                      ? "Rank Rising"
                      : seasonTruth.details.rankTrajectory === "falling"
                        ? "Rank Falling"
                        : "Rank Stable"}
                  </span>
                  {/* SOS Badge - informational context only */}
                  <span className="text-xs px-2.5 py-1 rounded-full bg-muted text-muted-foreground font-medium">
                    SOS: {seasonTruth.details.sosPercentile}th percentile
                  </span>
                  {/* Form Signal Badge - only show notable streaks */}
                  {seasonTruth.details.formSignal &&
                   (seasonTruth.details.formSignal === "hot_streak" || seasonTruth.details.formSignal === "cold_streak") && (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium",
                        seasonTruth.details.formSignal === "hot_streak"
                          ? "bg-orange-500/20 text-orange-700 dark:text-orange-400"
                          : "bg-blue-500/20 text-blue-700 dark:text-blue-400"
                      )}
                    >
                      {seasonTruth.details.formSignal === "hot_streak" && <Flame className="h-3 w-3" />}
                      {seasonTruth.details.formSignal === "cold_streak" && <Snowflake className="h-3 w-3" />}
                      {seasonTruth.details.formSignal === "hot_streak" ? "Hot Streak" : "Cold Streak"}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Consistency Score */}
            {consistency && (
              <div className="bg-gradient-to-br from-blue-500/5 to-blue-500/10 border border-blue-500/20 rounded-xl p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Target className="h-5 w-5 text-blue-500" />
                    <h3 className="font-semibold text-lg">Consistency Score</h3>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-3xl font-bold font-mono",
                        consistency.score >= 75
                          ? "text-green-600 dark:text-green-400"
                          : consistency.score >= 55
                            ? "text-blue-600 dark:text-blue-400"
                            : consistency.score >= 35
                              ? "text-amber-600 dark:text-amber-400"
                              : "text-red-600 dark:text-red-400"
                      )}
                    >
                      {consistency.score}
                    </span>
                    <span className="text-muted-foreground text-sm">/100</span>
                  </div>
                </div>

                {/* Score bar */}
                <div className="h-3 bg-muted rounded-full overflow-hidden mb-3">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      consistency.score >= 75
                        ? "bg-green-500"
                        : consistency.score >= 55
                          ? "bg-blue-500"
                          : consistency.score >= 35
                            ? "bg-amber-500"
                            : "bg-red-500"
                    )}
                    style={{ width: `${consistency.score}%` }}
                  />
                </div>

                <p
                  className={cn(
                    "text-sm font-medium capitalize",
                    consistency.label === "very reliable"
                      ? "text-green-600 dark:text-green-400"
                      : consistency.label === "moderately reliable"
                        ? "text-blue-600 dark:text-blue-400"
                        : consistency.label === "unpredictable"
                          ? "text-amber-600 dark:text-amber-400"
                          : "text-red-600 dark:text-red-400"
                  )}
                >
                  {consistency.label}
                </p>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="bg-background/50 rounded p-2 text-center">
                    <p className="text-muted-foreground">Goal Diff Variance</p>
                    <p className="font-mono font-medium">
                      {consistency.details.goalDifferentialStdDev.toFixed(1)}
                    </p>
                  </div>
                  <div className="bg-background/50 rounded p-2 text-center">
                    <p className="text-muted-foreground">Streak Fragment</p>
                    <p className="font-mono font-medium">
                      {(consistency.details.streakFragmentation * 100).toFixed(0)}%
                    </p>
                  </div>
                  <div className="bg-background/50 rounded p-2 text-center">
                    <p className="text-muted-foreground">Power Volatility</p>
                    <p className="font-mono font-medium">
                      {(consistency.details.powerScoreVolatility * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Persona Label */}
            {persona && (
              <div
                className={cn(
                  "rounded-xl p-5 border",
                  persona.label === "Giant Killer"
                    ? "bg-gradient-to-br from-purple-500/5 to-purple-500/10 border-purple-500/20"
                    : persona.label === "Flat Track Bully"
                      ? "bg-gradient-to-br from-orange-500/5 to-orange-500/10 border-orange-500/20"
                      : persona.label === "Gatekeeper"
                        ? "bg-gradient-to-br from-cyan-500/5 to-cyan-500/10 border-cyan-500/20"
                        : "bg-gradient-to-br from-gray-500/5 to-gray-500/10 border-gray-500/20"
                )}
              >
                <div className="flex items-center gap-2 mb-3">
                  <Swords
                    className={cn(
                      "h-5 w-5",
                      persona.label === "Giant Killer"
                        ? "text-purple-500"
                        : persona.label === "Flat Track Bully"
                          ? "text-orange-500"
                          : persona.label === "Gatekeeper"
                            ? "text-cyan-500"
                            : "text-gray-500"
                    )}
                  />
                  <h3 className="font-semibold text-lg">Team Persona</h3>
                </div>

                <div
                  className={cn(
                    "inline-flex items-center gap-2 px-4 py-2 rounded-lg mb-3 font-display text-lg font-bold",
                    persona.label === "Giant Killer"
                      ? "bg-purple-500/20 text-purple-700 dark:text-purple-300"
                      : persona.label === "Flat Track Bully"
                        ? "bg-orange-500/20 text-orange-700 dark:text-orange-300"
                        : persona.label === "Gatekeeper"
                          ? "bg-cyan-500/20 text-cyan-700 dark:text-cyan-300"
                          : "bg-gray-500/20 text-gray-700 dark:text-gray-300"
                  )}
                >
                  {persona.label === "Giant Killer" && "🗡️"}
                  {persona.label === "Flat Track Bully" && "💪"}
                  {persona.label === "Gatekeeper" && "🛡️"}
                  {persona.label === "Wildcard" && "🃏"}
                  {persona.label}
                </div>

                <p className="text-foreground/90 leading-relaxed">
                  {persona.explanation}
                </p>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="bg-background/50 rounded-lg p-3">
                    <p className="text-muted-foreground text-xs mb-1">
                      vs Higher Ranked
                    </p>
                    <p className="font-semibold">
                      {persona.details.winsVsHigherRanked}/
                      {persona.details.totalVsHigherRanked} wins
                      <span className="text-muted-foreground font-normal ml-1">
                        ({persona.details.winRateVsTop}%)
                      </span>
                    </p>
                  </div>
                  <div className="bg-background/50 rounded-lg p-3">
                    <p className="text-muted-foreground text-xs mb-1">
                      vs Lower Ranked
                    </p>
                    <p className="font-semibold">
                      {persona.details.winsVsLowerRanked}/
                      {persona.details.totalVsLowerRanked} wins
                      <span className="text-muted-foreground font-normal ml-1">
                        ({persona.details.winRateVsBottom}%)
                      </span>
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* View Full Profile Link */}
            <div className="pt-2">
              <Link href={`/teams/${teamId}`}>
                <Button variant="outline" className="w-full gap-2">
                  View Full Team Profile
                  <ExternalLink className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Compact insight preview for watchlist cards
 */
export function InsightPreview({
  insight,
}: {
  insight: SeasonTruthInsight | ConsistencyInsight | PersonaInsight;
}) {
  if (insight.type === "persona") {
    const persona = insight as PersonaInsight;
    return (
      <div
        className={cn(
          "flex items-center gap-1.5 text-xs px-2 py-1 rounded-full font-medium",
          persona.label === "Giant Killer"
            ? "bg-purple-500/20 text-purple-700 dark:text-purple-400"
            : persona.label === "Flat Track Bully"
              ? "bg-orange-500/20 text-orange-700 dark:text-orange-400"
              : persona.label === "Gatekeeper"
                ? "bg-cyan-500/20 text-cyan-700 dark:text-cyan-400"
                : "bg-gray-500/20 text-gray-700 dark:text-gray-400"
        )}
      >
        <Swords className="h-3 w-3" />
        {persona.label}
      </div>
    );
  }

  if (insight.type === "consistency_score") {
    const consistency = insight as ConsistencyInsight;
    return (
      <div
        className={cn(
          "flex items-center gap-1.5 text-xs px-2 py-1 rounded-full font-medium",
          consistency.score >= 75
            ? "bg-green-500/20 text-green-700 dark:text-green-400"
            : consistency.score >= 55
              ? "bg-blue-500/20 text-blue-700 dark:text-blue-400"
              : consistency.score >= 35
                ? "bg-amber-500/20 text-amber-700 dark:text-amber-400"
                : "bg-red-500/20 text-red-700 dark:text-red-400"
        )}
      >
        <Target className="h-3 w-3" />
        {consistency.score}/100 {consistency.label}
      </div>
    );
  }

  // Season truth - show rank trajectory
  const seasonTruth = insight as SeasonTruthInsight;
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-xs px-2 py-1 rounded-full font-medium",
        seasonTruth.details.rankTrajectory === "rising"
          ? "bg-green-500/20 text-green-700 dark:text-green-400"
          : seasonTruth.details.rankTrajectory === "falling"
            ? "bg-red-500/20 text-red-700 dark:text-red-400"
            : "bg-muted text-muted-foreground"
      )}
    >
      {seasonTruth.details.rankTrajectory === "rising" && <TrendingUp className="h-3 w-3" />}
      {seasonTruth.details.rankTrajectory === "falling" && <TrendingDown className="h-3 w-3" />}
      {seasonTruth.details.rankTrajectory !== "rising" && seasonTruth.details.rankTrajectory !== "falling" && <Brain className="h-3 w-3" />}
      {seasonTruth.details.rankTrajectory === "rising"
        ? "Rising"
        : seasonTruth.details.rankTrajectory === "falling"
          ? "Falling"
          : "Stable"}
    </div>
  );
}

/**
 * Delta indicator component for rank/power changes
 */
export function DeltaIndicator({
  value,
  inverse = false,
  size = "sm",
}: {
  value: number | null;
  inverse?: boolean; // For ranks, lower is better so we invert the color
  size?: "sm" | "md";
}) {
  if (value === null || value === 0) {
    return (
      <span
        className={cn(
          "inline-flex items-center text-muted-foreground",
          size === "sm" ? "text-xs" : "text-sm"
        )}
      >
        <Minus className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} />
      </span>
    );
  }

  const isPositive = inverse ? value < 0 : value > 0;
  const displayValue = Math.abs(value);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 font-medium",
        isPositive
          ? "text-green-600 dark:text-green-400"
          : "text-red-600 dark:text-red-400",
        size === "sm" ? "text-xs" : "text-sm"
      )}
    >
      {isPositive ? (
        <TrendingUp className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} />
      ) : (
        <TrendingDown className={size === "sm" ? "h-3 w-3" : "h-4 w-4"} />
      )}
      {displayValue}
    </span>
  );
}
