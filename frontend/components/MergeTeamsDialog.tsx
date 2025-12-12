'use client';

import { useState, useEffect, useCallback } from 'react';
import { Search, Merge, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useUser } from '@/hooks/useUser';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';

interface Team {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  age_group: string | null;
  gender: string | null;
  state_code: string | null;
  state: string | null;
}

interface MergeTeamsDialogProps {
  currentTeamId: string;
  currentTeamName: string;
  currentTeamAgeGroup?: string | null;
  currentTeamGender?: string | null;
  currentTeamStateCode?: string | null;
}

export function MergeTeamsDialog({
  currentTeamId,
  currentTeamName,
  currentTeamAgeGroup,
  currentTeamGender,
  currentTeamStateCode,
}: MergeTeamsDialogProps) {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Team[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [isMerging, setIsMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const { user } = useUser();
  const queryClient = useQueryClient();
  const router = useRouter();

  const performSearch = useCallback(async (query: string) => {
    setIsSearching(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        q: query,
        limit: '20',
      });

      // Add filters to narrow results
      if (currentTeamAgeGroup) {
        params.append('ageGroup', currentTeamAgeGroup);
      }
      if (currentTeamGender) {
        params.append('gender', currentTeamGender);
      }
      if (currentTeamStateCode) {
        params.append('stateCode', currentTeamStateCode);
      }

      const response = await fetch(`/api/teams/search?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Search failed');
      }

      // Filter out the current team from results
      const filtered = (data.teams || []).filter(
        (team: Team) => team.team_id_master !== currentTeamId
      );
      setSearchResults(filtered);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, [currentTeamAgeGroup, currentTeamGender, currentTeamStateCode]);

  // Debounced search
  useEffect(() => {
    if (!searchQuery || searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }

    const timeoutId = setTimeout(() => {
      performSearch(searchQuery);
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [searchQuery, performSearch]);

  const handleMerge = async () => {
    if (!selectedTeam || !user?.email) {
      setError('Please select a team and ensure you are logged in');
      return;
    }

    setIsMerging(true);
    setError(null);
    setSuccess(false);

    try {
      const response = await fetch('/api/team-merge', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          deprecatedTeamId: currentTeamId,
          canonicalTeamId: selectedTeam.team_id_master,
          mergedBy: user.email,
          mergeReason: `Merged via team detail page - user requested merge`,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Merge failed');
      }

      setSuccess(true);
      
      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: ['team', currentTeamId] });
      queryClient.invalidateQueries({ queryKey: ['team-games', currentTeamId] });
      queryClient.invalidateQueries({ queryKey: ['team', selectedTeam.team_id_master] });
      queryClient.invalidateQueries({ queryKey: ['team-games', selectedTeam.team_id_master] });

      // Redirect to canonical team after 2 seconds
      setTimeout(() => {
        router.push(`/teams/${selectedTeam.team_id_master}`);
        router.refresh();
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Merge failed');
    } finally {
      setIsMerging(false);
    }
  };

  const resetDialog = () => {
    setSearchQuery('');
    setSearchResults([]);
    setSelectedTeam(null);
    setError(null);
    setSuccess(false);
  };

  useEffect(() => {
    if (open) {
      resetDialog();
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="flex items-center gap-2">
          <Merge className="h-4 w-4" />
          Merge Dupe Teams
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Merge Duplicate Teams</DialogTitle>
          <DialogDescription>
            Merge <strong>{currentTeamName}</strong> into another team. All games and data will be combined.
          </DialogDescription>
        </DialogHeader>

        {success ? (
          <div className="space-y-4 py-4">
            <div className="flex items-center gap-3 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
              <div>
                <p className="font-medium text-green-900 dark:text-green-100">
                  Successfully merged!
                </p>
                <p className="text-sm text-green-700 dark:text-green-300 mt-1">
                  Redirecting to {selectedTeam?.team_name}...
                </p>
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="team-search">Search for team to merge into</Label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="team-search"
                    placeholder="Type team name or club name..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-10"
                    disabled={isMerging}
                  />
                  {isSearching && (
                    <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
                  )}
                </div>
                {currentTeamAgeGroup || currentTeamGender || currentTeamStateCode ? (
                  <p className="text-xs text-muted-foreground">
                    Filtering by: {[
                      currentTeamAgeGroup && `Age: ${currentTeamAgeGroup}`,
                      currentTeamGender && `Gender: ${currentTeamGender}`,
                      currentTeamStateCode && `State: ${currentTeamStateCode}`,
                    ].filter(Boolean).join(', ')}
                  </p>
                ) : null}
              </div>

              {error && (
                <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-md text-sm">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </div>
              )}

              {searchResults.length > 0 && (
                <div className="space-y-2">
                  <Label>Select a team:</Label>
                  <div className="border rounded-md max-h-60 overflow-y-auto">
                    {searchResults.map((team) => (
                      <button
                        key={team.team_id_master}
                        type="button"
                        onClick={() => setSelectedTeam(team)}
                        className={`w-full text-left p-3 hover:bg-accent transition-colors border-b last:border-b-0 ${
                          selectedTeam?.team_id_master === team.team_id_master
                            ? 'bg-accent border-l-4 border-l-primary'
                            : ''
                        }`}
                        disabled={isMerging}
                      >
                        <div className="font-medium">{team.team_name}</div>
                        <div className="text-sm text-muted-foreground mt-1">
                          {team.club_name && <span>{team.club_name}</span>}
                          {team.club_name && (team.age_group || team.gender || team.state_code) && ' • '}
                          {[
                            team.age_group,
                            team.gender,
                            team.state_code,
                          ].filter(Boolean).join(' • ')}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {searchQuery.length >= 2 && !isSearching && searchResults.length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No teams found. Try a different search term.
                </div>
              )}

              {selectedTeam && (
                <div className="p-4 bg-muted rounded-md">
                  <p className="text-sm font-medium mb-2">Merge Preview:</p>
                  <div className="space-y-1 text-sm">
                    <div>
                      <span className="text-muted-foreground">From:</span>{' '}
                      <strong>{currentTeamName}</strong>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Into:</span>{' '}
                      <strong>{selectedTeam.team_name}</strong>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      All games from {currentTeamName} will be combined with {selectedTeam.team_name}.
                    </p>
                  </div>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={isMerging}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleMerge}
                disabled={!selectedTeam || isMerging || !user?.email}
              >
                {isMerging ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Merging...
                  </>
                ) : (
                  <>
                    <Merge className="mr-2 h-4 w-4" />
                    Merge Teams
                  </>
                )}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

