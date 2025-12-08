'use client';

import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { TeamSelector } from '@/components/TeamSelector';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { AlertTriangle, ArrowRight, CheckCircle, Undo2, GitMerge } from 'lucide-react';
import type { RankingRow } from '@/types/RankingRow';

interface TeamMergeResult {
  success: boolean;
  mergeId?: string;
  deprecatedTeamName?: string;
  canonicalTeamName?: string;
  message?: string;
  error?: string;
}

interface MergedTeam {
  merge_id: string;
  deprecated_team_id: string;
  deprecated_team_name: string;
  canonical_team_id: string;
  canonical_team_name: string;
  merged_at: string;
  merged_by: string;
  merge_reason: string | null;
  games_with_deprecated_id: number;
}

/**
 * TeamMergePanel - Admin component for merging duplicate teams
 *
 * Allows selecting two teams and merging the "deprecated" team into
 * the "canonical" team. All game references are resolved at query time
 * via the resolve_team_id() function, so no game data is modified.
 */
export function TeamMergePanel() {
  // Team selection state
  const [deprecatedTeamId, setDeprecatedTeamId] = useState<string | null>(null);
  const [deprecatedTeam, setDeprecatedTeam] = useState<RankingRow | null>(null);
  const [canonicalTeamId, setCanonicalTeamId] = useState<string | null>(null);
  const [canonicalTeam, setCanonicalTeam] = useState<RankingRow | null>(null);

  // Form state
  const [mergeReason, setMergeReason] = useState('');
  const [userEmail, setUserEmail] = useState('');

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<TeamMergeResult | null>(null);

  // Recent merges for undo functionality
  const [recentMerges, setRecentMerges] = useState<MergedTeam[]>([]);
  const [loadingRecentMerges, setLoadingRecentMerges] = useState(false);

  // Handle deprecated team selection
  const handleDeprecatedChange = useCallback((teamId: string | null, team: RankingRow | null) => {
    setDeprecatedTeamId(teamId);
    setDeprecatedTeam(team);
    setResult(null);
  }, []);

  // Handle canonical team selection
  const handleCanonicalChange = useCallback((teamId: string | null, team: RankingRow | null) => {
    setCanonicalTeamId(teamId);
    setCanonicalTeam(team);
    setResult(null);
  }, []);

  // Execute the merge
  const handleMerge = async () => {
    if (!deprecatedTeamId || !canonicalTeamId || !userEmail) {
      setResult({ success: false, error: 'Please select both teams and enter your email' });
      return;
    }

    if (deprecatedTeamId === canonicalTeamId) {
      setResult({ success: false, error: 'Cannot merge a team with itself' });
      return;
    }

    setIsLoading(true);
    setResult(null);

    try {
      const response = await fetch('/api/team-merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deprecatedTeamId,
          canonicalTeamId,
          mergedBy: userEmail,
          mergeReason: mergeReason || undefined,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        setResult({
          success: true,
          mergeId: data.mergeId,
          deprecatedTeamName: data.deprecatedTeamName,
          canonicalTeamName: data.canonicalTeamName,
          message: data.message,
        });

        // Reset form on success
        setDeprecatedTeamId(null);
        setDeprecatedTeam(null);
        setCanonicalTeamId(null);
        setCanonicalTeam(null);
        setMergeReason('');

        // Refresh recent merges
        fetchRecentMerges();
      } else {
        setResult({ success: false, error: data.error || 'Merge failed' });
      }
    } catch (error) {
      setResult({ success: false, error: 'Network error. Please try again.' });
    } finally {
      setIsLoading(false);
    }
  };

  // Revert a merge
  const handleRevert = async (deprecatedTeamId: string) => {
    if (!userEmail) {
      setResult({ success: false, error: 'Please enter your email to revert merges' });
      return;
    }

    setIsLoading(true);

    try {
      const response = await fetch('/api/team-merge', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deprecatedTeamId,
          revertedBy: userEmail,
          revertReason: 'Admin revert',
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        setResult({
          success: true,
          message: data.message,
        });
        fetchRecentMerges();
      } else {
        setResult({ success: false, error: data.error || 'Revert failed' });
      }
    } catch (error) {
      setResult({ success: false, error: 'Network error. Please try again.' });
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch recent merges
  const fetchRecentMerges = async () => {
    setLoadingRecentMerges(true);
    try {
      const response = await fetch('/api/team-merge/list');
      if (response.ok) {
        const data = await response.json();
        setRecentMerges(data.merges || []);
      }
    } catch (error) {
      console.error('Failed to fetch recent merges:', error);
    } finally {
      setLoadingRecentMerges(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Merge Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitMerge className="h-5 w-5" />
            Merge Teams
          </CardTitle>
          <CardDescription>
            Merge duplicate team entries. The &quot;deprecated&quot; team will be hidden from rankings
            and all references will redirect to the &quot;canonical&quot; team.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* User Email */}
          <div className="space-y-2">
            <Label htmlFor="userEmail">Your Email (for audit)</Label>
            <Input
              id="userEmail"
              type="email"
              placeholder="admin@example.com"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
            />
          </div>

          {/* Team Selection */}
          <div className="grid md:grid-cols-2 gap-6">
            {/* Deprecated Team */}
            <div className="space-y-2">
              <Label className="text-red-600 font-medium">
                Team to Deprecate (will be hidden)
              </Label>
              <TeamSelector
                label="Select duplicate team"
                value={deprecatedTeamId}
                onChange={handleDeprecatedChange}
                excludeTeamId={canonicalTeamId || undefined}
              />
              {deprecatedTeam && (
                <div className="p-3 bg-red-50 rounded-lg text-sm">
                  <div className="font-medium text-red-800">{deprecatedTeam.team_name}</div>
                  <div className="text-red-600">
                    {deprecatedTeam.club_name && `${deprecatedTeam.club_name} • `}
                    {deprecatedTeam.state} • U{deprecatedTeam.age} {deprecatedTeam.gender === 'M' ? 'Boys' : 'Girls'}
                  </div>
                  <div className="text-red-500 text-xs mt-1">
                    {deprecatedTeam.games_played || 0} games played
                  </div>
                </div>
              )}
            </div>

            {/* Arrow */}
            <div className="hidden md:flex items-center justify-center">
              <ArrowRight className="h-8 w-8 text-gray-400" />
            </div>

            {/* Canonical Team */}
            <div className="space-y-2">
              <Label className="text-green-600 font-medium">
                Canonical Team (keep this one)
              </Label>
              <TeamSelector
                label="Select team to keep"
                value={canonicalTeamId}
                onChange={handleCanonicalChange}
                excludeTeamId={deprecatedTeamId || undefined}
              />
              {canonicalTeam && (
                <div className="p-3 bg-green-50 rounded-lg text-sm">
                  <div className="font-medium text-green-800">{canonicalTeam.team_name}</div>
                  <div className="text-green-600">
                    {canonicalTeam.club_name && `${canonicalTeam.club_name} • `}
                    {canonicalTeam.state} • U{canonicalTeam.age} {canonicalTeam.gender === 'M' ? 'Boys' : 'Girls'}
                  </div>
                  <div className="text-green-500 text-xs mt-1">
                    {canonicalTeam.games_played || 0} games played
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Merge Reason */}
          <div className="space-y-2">
            <Label htmlFor="mergeReason">Reason for Merge (optional)</Label>
            <Input
              id="mergeReason"
              placeholder="e.g., Duplicate entry from different provider"
              value={mergeReason}
              onChange={(e) => setMergeReason(e.target.value)}
            />
          </div>

          {/* Warning */}
          <div className="flex items-start gap-3 p-4 bg-yellow-50 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-yellow-600 shrink-0 mt-0.5" />
            <div className="text-sm text-yellow-800">
              <div className="font-medium">This action can be reverted</div>
              <div className="mt-1">
                Merging will hide the deprecated team from rankings. All game references will
                automatically resolve to the canonical team. No game data is modified - only
                lookup mappings are created.
              </div>
            </div>
          </div>

          {/* Result Message */}
          {result && (
            <div className={`p-4 rounded-lg ${result.success ? 'bg-green-50' : 'bg-red-50'}`}>
              {result.success ? (
                <div className="flex items-center gap-2 text-green-800">
                  <CheckCircle className="h-5 w-5" />
                  <span>{result.message}</span>
                </div>
              ) : (
                <ErrorDisplay error={result.error || 'Unknown error'} variant="inline" />
              )}
            </div>
          )}

          {/* Submit Button */}
          <Button
            onClick={handleMerge}
            disabled={!deprecatedTeamId || !canonicalTeamId || !userEmail || isLoading}
            className="w-full"
            variant="destructive"
          >
            {isLoading ? (
              <>
                <InlineLoader className="mr-2" />
                Merging...
              </>
            ) : (
              <>
                <GitMerge className="h-4 w-4 mr-2" />
                Merge Teams
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Recent Merges */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Recent Merges</span>
            <Button variant="outline" size="sm" onClick={fetchRecentMerges}>
              Refresh
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loadingRecentMerges ? (
            <div className="flex justify-center py-8">
              <InlineLoader />
            </div>
          ) : recentMerges.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No recent merges. Click &quot;Refresh&quot; to load.
            </div>
          ) : (
            <div className="space-y-3">
              {recentMerges.map((merge) => (
                <div
                  key={merge.merge_id}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                >
                  <div className="flex items-center gap-3">
                    <div className="text-sm">
                      <span className="text-red-600 line-through">{merge.deprecated_team_name}</span>
                      <ArrowRight className="h-4 w-4 inline mx-2 text-gray-400" />
                      <span className="text-green-600 font-medium">{merge.canonical_team_name}</span>
                    </div>
                    <Badge variant="secondary" className="text-xs">
                      {merge.games_with_deprecated_id} games
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">
                      {new Date(merge.merged_at).toLocaleDateString()}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRevert(merge.deprecated_team_id)}
                      disabled={isLoading}
                    >
                      <Undo2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
