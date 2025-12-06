'use client';

import { useState, useMemo, useRef, useEffect, useDeferredValue, useCallback } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Search, AlertCircle, CheckCircle2, Users } from 'lucide-react';
import type Fuse from 'fuse.js';
import type { RankingRow } from '@/types/RankingRow';
import type { GameWithTeams } from '@/lib/types';

interface UnknownOpponentLinkProps {
  game: GameWithTeams;
  currentTeamId: string;
  opponentProviderId: string;
  onLinked?: () => void;
}

interface PreviewData {
  totalGamesAffected: number;
  asHomeTeam: number;
  asAwayTeam: number;
  providerName?: string;
  previewGames: Array<{
    id: string;
    gameDate: string;
    score: string;
    competition: string;
    otherTeam: string;
  }>;
}

/**
 * Escape special regex characters in a string
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Highlight matching text in a string
 */
function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query || query.length < 2) return text;

  try {
    const escapedQuery = escapeRegex(query);
    const parts = text.split(new RegExp(`(${escapedQuery})`, 'gi'));
    return (
      <>
        {parts.map((part, index) =>
          part.toLowerCase() === query.toLowerCase() ? (
            <mark key={index} className="bg-yellow-200 dark:bg-yellow-800 px-0.5 rounded">
              {part}
            </mark>
          ) : (
            part
          )
        )}
      </>
    );
  } catch {
    return text;
  }
}

/**
 * UnknownOpponentLink - Clickable component to link unknown opponents to teams
 */
export function UnknownOpponentLink({
  game,
  currentTeamId,
  opponentProviderId,
  onLinked,
}: UnknownOpponentLinkProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTeam, setSelectedTeam] = useState<RankingRow | null>(null);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [FuseClass, setFuseClass] = useState<typeof Fuse | null>(null);
  const [isLinking, setIsLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkSuccess, setLinkSuccess] = useState(false);
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const deferredSearchQuery = useDeferredValue(searchQuery);
  const isSearchPending = searchQuery !== deferredSearchQuery;

  const { data: allTeams, isLoading: isLoadingTeams, isError, error, refetch } = useTeamSearch();

  // Load Fuse.js dynamically
  useEffect(() => {
    if (!FuseClass) {
      import('fuse.js').then((module) => {
        setFuseClass(() => module.default);
      });
    }
  }, [FuseClass]);

  // Format game date
  const gameDate = new Date(game.game_date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  // Get score
  const isHome = game.home_team_master_id === currentTeamId;
  const teamScore = isHome ? game.home_score : game.away_score;
  const opponentScore = isHome ? game.away_score : game.home_score;
  const scoreText = teamScore !== null && opponentScore !== null
    ? `${teamScore} - ${opponentScore}`
    : 'No score';

  // Fetch preview when modal opens
  const fetchPreview = useCallback(async () => {
    if (!isOpen || previewData) return;

    setIsLoadingPreview(true);
    try {
      const response = await fetch('/api/link-opponent/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gameId: game.id,
          opponentProviderId,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setPreviewData(data);
      }
    } catch (err) {
      console.error('Failed to fetch preview:', err);
    } finally {
      setIsLoadingPreview(false);
    }
  }, [isOpen, game.id, opponentProviderId, previewData]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  // Search teams using word-based matching
  const filteredTeams = useMemo(() => {
    if (!deferredSearchQuery || !allTeams || deferredSearchQuery.length < 2) return [];

    const queryWords = deferredSearchQuery.toLowerCase().split(/\s+/).filter(w => w.length > 0);

    // Exclude the current team
    const teamsToSearch = allTeams.filter(team => team.team_id_master !== currentTeamId);

    // Filter teams where ALL query words appear
    const matchingTeams = teamsToSearch.filter(team => {
      const searchText = ((team.searchable_name || team.team_name) + ' ' + (team.club_name || '')).toLowerCase();
      return queryWords.every(word => searchText.includes(word));
    });

    // Sort by relevance
    matchingTeams.sort((a, b) => {
      const aText = ((a.searchable_name || a.team_name) + ' ' + (a.club_name || '')).toLowerCase();
      const bText = ((b.searchable_name || b.team_name) + ' ' + (b.club_name || '')).toLowerCase();
      const aIndex = Math.min(...queryWords.map(w => aText.indexOf(w)));
      const bIndex = Math.min(...queryWords.map(w => bText.indexOf(w)));
      return aIndex - bIndex;
    });

    return matchingTeams.slice(0, 10);
  }, [deferredSearchQuery, allTeams, currentTeamId]);

  // Reset selected index when results change
  useEffect(() => {
    setSelectedIndex(0);
  }, [filteredTeams.length]);

  const handleSelectTeam = (team: RankingRow) => {
    setSelectedTeam(team);
    setSearchQuery(team.team_name);
    setIsSearchOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isSearchOpen || filteredTeams.length === 0) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredTeams.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredTeams.length) % filteredTeams.length);
        break;
      case 'Enter':
        e.preventDefault();
        if (filteredTeams[selectedIndex]) {
          handleSelectTeam(filteredTeams[selectedIndex]);
        }
        break;
      case 'Escape':
        setIsSearchOpen(false);
        break;
    }
  };

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && selectedIndex >= 0 && filteredTeams.length > 0) {
      const selectedElement = listRef.current.children[selectedIndex] as HTMLElement;
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [selectedIndex, filteredTeams.length]);

  const handleLink = async () => {
    if (!selectedTeam) return;

    setIsLinking(true);
    setLinkError(null);

    try {
      const response = await fetch('/api/link-opponent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gameId: game.id,
          opponentProviderId,
          teamIdMaster: selectedTeam.team_id_master,
          applyToAllGames: true,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to link team');
      }

      setLinkSuccess(true);

      // Close modal after short delay and refresh
      setTimeout(() => {
        setIsOpen(false);
        onLinked?.();
      }, 1500);
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLinking(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open);
    if (!open) {
      // Reset state when closing
      setSearchQuery('');
      setSelectedTeam(null);
      setIsSearchOpen(false);
      setLinkError(null);
      setLinkSuccess(false);
      setPreviewData(null);
    }
  };

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="text-muted-foreground hover:text-primary hover:underline transition-colors cursor-pointer focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded px-1"
        aria-label="Link unknown opponent to a team"
      >
        Unknown
      </button>

      <Dialog open={isOpen} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              Link Unknown Opponent
            </DialogTitle>
            <DialogDescription>
              Search for the opponent team or create a new one
            </DialogDescription>
          </DialogHeader>

          {/* Game Context */}
          <div className="bg-muted/50 rounded-lg p-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-muted-foreground">Date:</span>{' '}
                <span className="font-medium">{gameDate}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Score:</span>{' '}
                <span className="font-medium">{scoreText}</span>
              </div>
              <div className="col-span-2">
                <span className="text-muted-foreground">Competition:</span>{' '}
                <span className="font-medium">{game.competition || game.division_name || 'Unknown'}</span>
              </div>
              <div className="col-span-2">
                <span className="text-muted-foreground">Provider ID:</span>{' '}
                <code className="text-xs bg-muted px-1 py-0.5 rounded">{opponentProviderId}</code>
                {previewData?.providerName && (
                  <span className="text-xs text-muted-foreground ml-1">({previewData.providerName})</span>
                )}
              </div>
            </div>
          </div>

          {/* Preview of affected games */}
          {isLoadingPreview && (
            <InlineLoader text="Checking affected games..." />
          )}
          {previewData && previewData.totalGamesAffected > 1 && (
            <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg p-3 text-sm">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-blue-600 dark:text-blue-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-medium text-blue-800 dark:text-blue-200">
                    This will update {previewData.totalGamesAffected} games
                  </p>
                  <p className="text-blue-600 dark:text-blue-300 text-xs mt-1">
                    All games with the same provider ID will be linked to the selected team.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Team Search */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Search for team</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                ref={inputRef}
                type="search"
                inputMode="search"
                autoComplete="off"
                placeholder="Type team name..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsSearchOpen(true);
                  setSelectedTeam(null);
                }}
                onFocus={() => setIsSearchOpen(true)}
                onKeyDown={handleKeyDown}
                className="pl-10"
                aria-label="Search for opponent team"
                aria-autocomplete="list"
                aria-expanded={isSearchOpen && filteredTeams.length > 0}
              />

              {/* Search Results Dropdown */}
              {isSearchOpen && searchQuery.length >= 2 && (
                <Card className="absolute z-50 w-full mt-1 max-h-60 overflow-y-auto shadow-lg">
                  <CardContent className="p-2" ref={listRef}>
                    {isLoadingTeams || isSearchPending ? (
                      <InlineLoader text="Searching teams..." />
                    ) : isError ? (
                      <ErrorDisplay error={error} retry={refetch} compact />
                    ) : filteredTeams.length === 0 ? (
                      <div className="p-4 text-center text-sm text-muted-foreground">
                        No teams found matching &quot;{searchQuery}&quot;
                      </div>
                    ) : (
                      <div className="space-y-1">
                        {filteredTeams.map((team, index) => (
                          <button
                            key={team.team_id_master}
                            onClick={() => handleSelectTeam(team)}
                            className={`w-full text-left p-2 rounded-md transition-colors duration-200 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary ${
                              index === selectedIndex
                                ? 'bg-accent font-semibold'
                                : 'hover:bg-accent/50'
                            }`}
                            aria-label={`Select ${team.team_name}`}
                          >
                            <div className="font-medium">
                              {highlightMatch(team.team_name, deferredSearchQuery)}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {team.club_name && (
                                <span>{highlightMatch(team.club_name, deferredSearchQuery)}</span>
                              )}
                              {team.state && (
                                <span className={team.club_name ? ' • ' : ''}>
                                  {team.state.toUpperCase()}
                                </span>
                              )}
                              {team.age != null && team.gender && (
                                <span className={team.club_name || team.state ? ' • ' : ''}>
                                  U{team.age} {team.gender === 'M' ? 'Boys' : team.gender === 'F' ? 'Girls' : team.gender}
                                </span>
                              )}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </div>

          {/* Selected Team Display */}
          {selectedTeam && (
            <div className="bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800 rounded-lg p-3">
              <div className="flex items-start gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-medium text-green-800 dark:text-green-200">
                    {selectedTeam.team_name}
                  </p>
                  <p className="text-green-600 dark:text-green-300 text-xs">
                    {selectedTeam.club_name && `${selectedTeam.club_name} • `}
                    {selectedTeam.state?.toUpperCase()}
                    {selectedTeam.age != null && ` • U${selectedTeam.age}`}
                    {selectedTeam.gender && ` ${selectedTeam.gender === 'M' ? 'Boys' : 'Girls'}`}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Error Display */}
          {linkError && (
            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                <p className="text-red-800 dark:text-red-200 text-sm">{linkError}</p>
              </div>
            </div>
          )}

          {/* Success Display */}
          {linkSuccess && (
            <div className="bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800 rounded-lg p-3">
              <div className="flex items-start gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400 mt-0.5 flex-shrink-0" />
                <p className="text-green-800 dark:text-green-200 text-sm">
                  Successfully linked! Refreshing...
                </p>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isLinking}
            >
              Cancel
            </Button>
            <Button
              onClick={handleLink}
              disabled={!selectedTeam || isLinking || linkSuccess}
            >
              {isLinking ? 'Linking...' : 'Link Team'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
