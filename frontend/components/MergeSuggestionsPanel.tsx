'use client';

import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import {
  Lightbulb,
  Users,
  Calendar,
  Type,
  MapPin,
  TrendingUp,
  ArrowRight,
  CheckCircle,
  XCircle,
} from 'lucide-react';

interface MergeSuggestion {
  teamAId: string;
  teamAName: string;
  teamBId: string;
  teamBName: string;
  confidenceScore: number;
  recommendation: 'high' | 'medium' | 'low';
  signals: {
    opponentOverlap: number;
    scheduleAlignment: number;
    nameSimilarity: number;
    geography: number;
    performance: number;
  };
  details: {
    opponentOverlap: string;
    scheduleAlignment: string;
    nameSimilarity: string;
    geography: string;
    performance: string;
  };
}

interface MergeSuggestionsPanelProps {
  onMergeClick?: (deprecatedId: string, canonicalId: string) => void;
}

const AGE_GROUPS = [
  { value: '8', label: 'U8' },
  { value: '9', label: 'U9' },
  { value: '10', label: 'U10' },
  { value: '11', label: 'U11' },
  { value: '12', label: 'U12' },
  { value: '13', label: 'U13' },
  { value: '14', label: 'U14' },
  { value: '15', label: 'U15' },
  { value: '16', label: 'U16' },
  { value: '17', label: 'U17' },
  { value: '18', label: 'U18' },
  { value: '19', label: 'U19' },
];

const GENDERS = [
  { value: 'Male', label: 'Boys' },
  { value: 'Female', label: 'Girls' },
];

/**
 * MergeSuggestionsPanel - AI-powered merge suggestion component
 *
 * Analyzes teams to suggest potential duplicates based on:
 * - Opponent overlap (40%) - shared opponents
 * - Schedule alignment (25%) - similar game dates
 * - Name similarity (20%) - fuzzy name matching
 * - Geography (10%) - same state/club
 * - Performance (5%) - similar win rates
 */
export function MergeSuggestionsPanel({ onMergeClick }: MergeSuggestionsPanelProps) {
  // Filter state
  const [ageGroup, setAgeGroup] = useState<string>('');
  const [gender, setGender] = useState<string>('');

  // Results state
  const [suggestions, setSuggestions] = useState<MergeSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [teamsAnalyzed, setTeamsAnalyzed] = useState(0);

  // Dismissed suggestions
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Fetch suggestions
  const fetchSuggestions = useCallback(async () => {
    if (!ageGroup || !gender) {
      setError('Please select both age group and gender');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Note: minConfidence is enforced server-side at 90%
      const params = new URLSearchParams({
        ageGroup,
        gender,
        limit: '50',
      });

      const response = await fetch(`/api/team-merge/suggestions?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to fetch suggestions');
      }

      setSuggestions(data.suggestions || []);
      setTeamsAnalyzed(data.teamsAnalyzed || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [ageGroup, gender]);

  // Dismiss a suggestion
  const handleDismiss = (suggestionKey: string) => {
    setDismissed(prev => new Set([...prev, suggestionKey]));
  };

  // Get badge color for recommendation level
  const getRecommendationColor = (rec: string) => {
    switch (rec) {
      case 'high': return 'bg-green-100 text-green-800 border-green-200';
      case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  // Get signal icon
  const getSignalIcon = (signal: string) => {
    switch (signal) {
      case 'opponentOverlap': return <Users className="h-4 w-4" />;
      case 'scheduleAlignment': return <Calendar className="h-4 w-4" />;
      case 'nameSimilarity': return <Type className="h-4 w-4" />;
      case 'geography': return <MapPin className="h-4 w-4" />;
      case 'performance': return <TrendingUp className="h-4 w-4" />;
      default: return null;
    }
  };

  // Filter out dismissed suggestions
  const activeSuggestions = suggestions.filter(
    s => !dismissed.has(`${s.teamAId}-${s.teamBId}`)
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lightbulb className="h-5 w-5 text-yellow-500" />
          Intelligent Merge Suggestions
        </CardTitle>
        <CardDescription>
          AI-powered analysis to find potential duplicate teams based on opponent overlap,
          schedules, names, geography, and performance.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Filters */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Age Group</Label>
            <Select value={ageGroup} onValueChange={setAgeGroup}>
              <SelectTrigger>
                <SelectValue placeholder="Select age" />
              </SelectTrigger>
              <SelectContent>
                {AGE_GROUPS.map(ag => (
                  <SelectItem key={ag.value} value={ag.value}>
                    {ag.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Gender</Label>
            <Select value={gender} onValueChange={setGender}>
              <SelectTrigger>
                <SelectValue placeholder="Select gender" />
              </SelectTrigger>
              <SelectContent>
                {GENDERS.map(g => (
                  <SelectItem key={g.value} value={g.value}>
                    {g.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Info about threshold */}
        <p className="text-sm text-muted-foreground">
          Only high-confidence matches (90%+) are shown. Teams with different location codes,
          team numbers, or division markers are automatically excluded.
        </p>

        {/* Search Button */}
        <Button
          onClick={fetchSuggestions}
          disabled={isLoading || !ageGroup || !gender}
          className="w-full"
        >
          {isLoading ? (
            <>
              <InlineLoader className="mr-2" />
              Analyzing teams...
            </>
          ) : (
            <>
              <Lightbulb className="h-4 w-4 mr-2" />
              Find Duplicate Teams
            </>
          )}
        </Button>

        {/* Error */}
        {error && (
          <ErrorDisplay error={error} compact />
        )}

        {/* Results Summary */}
        {!isLoading && suggestions.length > 0 && (
          <div className="text-sm text-gray-500">
            Found {activeSuggestions.length} potential duplicates from {teamsAnalyzed} teams analyzed
          </div>
        )}

        {/* Suggestions List */}
        {!isLoading && activeSuggestions.length > 0 && (
          <div className="space-y-4">
            {activeSuggestions.map((suggestion, index) => (
              <Card key={`${suggestion.teamAId}-${suggestion.teamBId}`} className="border-l-4 border-l-yellow-400">
                <CardContent className="p-4">
                  {/* Header */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Badge className={getRecommendationColor(suggestion.recommendation)}>
                        {suggestion.recommendation.toUpperCase()} CONFIDENCE
                      </Badge>
                      <span className="text-sm text-gray-500">
                        {Math.round(suggestion.confidenceScore * 100)}% match
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDismiss(`${suggestion.teamAId}-${suggestion.teamBId}`)}
                    >
                      <XCircle className="h-4 w-4" />
                    </Button>
                  </div>

                  {/* Teams */}
                  <div className="flex items-center gap-4 mb-4">
                    <div className="flex-1 p-3 bg-gray-50 rounded-lg">
                      <div className="font-medium">{suggestion.teamAName}</div>
                      <div className="text-xs text-gray-500">ID: {suggestion.teamAId.slice(0, 8)}...</div>
                    </div>
                    <ArrowRight className="h-5 w-5 text-gray-400 shrink-0" />
                    <div className="flex-1 p-3 bg-gray-50 rounded-lg">
                      <div className="font-medium">{suggestion.teamBName}</div>
                      <div className="text-xs text-gray-500">ID: {suggestion.teamBId.slice(0, 8)}...</div>
                    </div>
                  </div>

                  {/* Signal Breakdown */}
                  <div className="grid grid-cols-5 gap-2 mb-4">
                    {Object.entries(suggestion.signals).map(([signal, score]) => (
                      <div
                        key={signal}
                        className="text-center p-2 bg-gray-50 rounded"
                        title={suggestion.details[signal as keyof typeof suggestion.details]}
                      >
                        <div className="flex justify-center mb-1">
                          {getSignalIcon(signal)}
                        </div>
                        <div className="text-xs font-medium">
                          {Math.round(score * 100)}%
                        </div>
                        <div className="text-[10px] text-gray-500 capitalize">
                          {signal.replace(/([A-Z])/g, ' $1').trim()}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1"
                      onClick={() => onMergeClick?.(suggestion.teamAId, suggestion.teamBId)}
                    >
                      <CheckCircle className="h-4 w-4 mr-2" />
                      Merge A → B
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1"
                      onClick={() => onMergeClick?.(suggestion.teamBId, suggestion.teamAId)}
                    >
                      <CheckCircle className="h-4 w-4 mr-2" />
                      Merge B → A
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && suggestions.length === 0 && teamsAnalyzed > 0 && (
          <div className="text-center py-8 text-gray-500">
            No potential duplicate teams found above 90% confidence.
            This is good - it means your team data is clean!
          </div>
        )}
      </CardContent>
    </Card>
  );
}
