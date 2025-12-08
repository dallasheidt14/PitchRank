'use client';

import { useState, useMemo, useRef, useEffect, useDeferredValue, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
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
import { Search, AlertCircle, CheckCircle2, Users, Plus, ArrowLeft } from 'lucide-react';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type Fuse from 'fuse.js';
import type { RankingRow } from '@/types/RankingRow';
import type { GameWithTeams } from '@/lib/types';
import { formatGameDate } from '@/lib/dateUtils';

interface UnknownOpponentLinkProps {
  game: GameWithTeams;
  currentTeamId: string;
  opponentProviderId: string;
  onLinked?: () => void;
  /** Default age to pre-fill when creating a new team (from current team context) */
  defaultAge?: number | null;
  /** Default gender to pre-fill when creating a new team (from current team context) */
  defaultGender?: 'M' | 'F' | 'B' | 'G' | null;
}

interface CreateTeamForm {
  teamName: string;
  clubName: string;
  ageGroup: string;
  gender: 'Male' | 'Female' | '';
  stateCode: string;
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
// US States for dropdown
const US_STATES = [
  { code: 'AL', name: 'Alabama' }, { code: 'AK', name: 'Alaska' }, { code: 'AZ', name: 'Arizona' },
  { code: 'AR', name: 'Arkansas' }, { code: 'CA', name: 'California' }, { code: 'CO', name: 'Colorado' },
  { code: 'CT', name: 'Connecticut' }, { code: 'DE', name: 'Delaware' }, { code: 'FL', name: 'Florida' },
  { code: 'GA', name: 'Georgia' }, { code: 'HI', name: 'Hawaii' }, { code: 'ID', name: 'Idaho' },
  { code: 'IL', name: 'Illinois' }, { code: 'IN', name: 'Indiana' }, { code: 'IA', name: 'Iowa' },
  { code: 'KS', name: 'Kansas' }, { code: 'KY', name: 'Kentucky' }, { code: 'LA', name: 'Louisiana' },
  { code: 'ME', name: 'Maine' }, { code: 'MD', name: 'Maryland' }, { code: 'MA', name: 'Massachusetts' },
  { code: 'MI', name: 'Michigan' }, { code: 'MN', name: 'Minnesota' }, { code: 'MS', name: 'Mississippi' },
  { code: 'MO', name: 'Missouri' }, { code: 'MT', name: 'Montana' }, { code: 'NE', name: 'Nebraska' },
  { code: 'NV', name: 'Nevada' }, { code: 'NH', name: 'New Hampshire' }, { code: 'NJ', name: 'New Jersey' },
  { code: 'NM', name: 'New Mexico' }, { code: 'NY', name: 'New York' }, { code: 'NC', name: 'North Carolina' },
  { code: 'ND', name: 'North Dakota' }, { code: 'OH', name: 'Ohio' }, { code: 'OK', name: 'Oklahoma' },
  { code: 'OR', name: 'Oregon' }, { code: 'PA', name: 'Pennsylvania' }, { code: 'RI', name: 'Rhode Island' },
  { code: 'SC', name: 'South Carolina' }, { code: 'SD', name: 'South Dakota' }, { code: 'TN', name: 'Tennessee' },
  { code: 'TX', name: 'Texas' }, { code: 'UT', name: 'Utah' }, { code: 'VT', name: 'Vermont' },
  { code: 'VA', name: 'Virginia' }, { code: 'WA', name: 'Washington' }, { code: 'WV', name: 'West Virginia' },
  { code: 'WI', name: 'Wisconsin' }, { code: 'WY', name: 'Wyoming' },
];

// Age groups for dropdown
const AGE_GROUPS = ['u8', 'u9', 'u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'u19'];

export function UnknownOpponentLink({
  game,
  currentTeamId,
  opponentProviderId,
  onLinked,
  defaultAge,
  defaultGender,
}: UnknownOpponentLinkProps) {
  const queryClient = useQueryClient();
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

  // Create team mode state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createForm, setCreateForm] = useState<CreateTeamForm>(() => {
    // Convert defaultGender to full form
    const genderMap: Record<string, 'Male' | 'Female'> = {
      'M': 'Male', 'B': 'Male', 'F': 'Female', 'G': 'Female'
    };
    return {
      teamName: '',
      clubName: '',
      ageGroup: defaultAge ? `u${defaultAge}` : '',
      gender: defaultGender ? genderMap[defaultGender] || '' : '',
      stateCode: '',
    };
  });

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

  // Format game date (using timezone-safe utility)
  const gameDate = formatGameDate(game.game_date);

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

      // Invalidate the games cache to ensure fresh data is fetched
      // This is more reliable than just refetch() as it clears the cache entirely
      await queryClient.invalidateQueries({ queryKey: ['team-games', currentTeamId] });

      // Also invalidate the team search cache in case a new team was somehow involved
      await queryClient.invalidateQueries({ queryKey: ['team-search'] });

      // Close modal after short delay and call onLinked callback
      setTimeout(() => {
        setIsOpen(false);
        onLinked?.();
      }, 1000);
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLinking(false);
    }
  };

  const handleCreateTeam = async () => {
    if (!createForm.teamName || !createForm.ageGroup || !createForm.gender) {
      setLinkError('Team name, age group, and gender are required');
      return;
    }

    setIsCreating(true);
    setLinkError(null);

    try {
      const response = await fetch('/api/create-team', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gameId: game.id,
          opponentProviderId,
          teamName: createForm.teamName,
          clubName: createForm.clubName || null,
          ageGroup: createForm.ageGroup,
          gender: createForm.gender,
          stateCode: createForm.stateCode || null,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to create team');
      }

      setLinkSuccess(true);

      // Invalidate the games cache to ensure fresh data is fetched
      // This is more reliable than just refetch() as it clears the cache entirely
      await queryClient.invalidateQueries({ queryKey: ['team-games', currentTeamId] });

      // Invalidate team search cache so the new team appears in searches
      await queryClient.invalidateQueries({ queryKey: ['team-search'] });

      // Close modal after short delay and call onLinked callback
      setTimeout(() => {
        setIsOpen(false);
        onLinked?.();
      }, 1000);
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsCreating(false);
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
      setShowCreateForm(false);
      setIsCreating(false);
      // Reset create form with defaults
      const genderMap: Record<string, 'Male' | 'Female'> = {
        'M': 'Male', 'B': 'Male', 'F': 'Female', 'G': 'Female'
      };
      setCreateForm({
        teamName: '',
        clubName: '',
        ageGroup: defaultAge ? `u${defaultAge}` : '',
        gender: defaultGender ? genderMap[defaultGender] || '' : '',
        stateCode: '',
      });
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

          {/* Team Search - shown when not in create mode */}
          {!showCreateForm && (
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
                        <div className="p-4 text-center text-sm">
                          <p className="text-muted-foreground mb-3">
                            No teams found matching &quot;{searchQuery}&quot;
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setShowCreateForm(true);
                              setIsSearchOpen(false);
                              setCreateForm(prev => ({ ...prev, teamName: searchQuery }));
                            }}
                            className="gap-1"
                          >
                            <Plus className="h-3 w-3" />
                            Create &quot;{searchQuery}&quot; as new team
                          </Button>
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

              {/* Always visible link to create new team */}
              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateForm(true)}
                  className="text-sm text-muted-foreground hover:text-primary transition-colors"
                >
                  Can&apos;t find the team? <span className="underline">Create new team</span>
                </button>
              </div>
            </div>
          )}

          {/* Create Team Form - shown when in create mode */}
          {showCreateForm && (
            <div className="space-y-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowCreateForm(false)}
                className="gap-1 -ml-2"
              >
                <ArrowLeft className="h-3 w-3" />
                Back to search
              </Button>

              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="teamName">Team Name *</Label>
                  <Input
                    id="teamName"
                    value={createForm.teamName}
                    onChange={(e) => setCreateForm(prev => ({ ...prev, teamName: e.target.value }))}
                    placeholder="Enter team name"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="clubName">Club Name</Label>
                  <Input
                    id="clubName"
                    value={createForm.clubName}
                    onChange={(e) => setCreateForm(prev => ({ ...prev, clubName: e.target.value }))}
                    placeholder="Enter club name (optional)"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="ageGroup">Age Group *</Label>
                    <Select
                      value={createForm.ageGroup}
                      onValueChange={(value) => setCreateForm(prev => ({ ...prev, ageGroup: value }))}
                    >
                      <SelectTrigger id="ageGroup">
                        <SelectValue placeholder="Select age" />
                      </SelectTrigger>
                      <SelectContent>
                        {AGE_GROUPS.map((age) => (
                          <SelectItem key={age} value={age}>
                            {age.toUpperCase()}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="gender">Gender *</Label>
                    <Select
                      value={createForm.gender}
                      onValueChange={(value) => setCreateForm(prev => ({ ...prev, gender: value as 'Male' | 'Female' }))}
                    >
                      <SelectTrigger id="gender">
                        <SelectValue placeholder="Select gender" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Male">Boys</SelectItem>
                        <SelectItem value="Female">Girls</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="stateCode">State</Label>
                  <Select
                    value={createForm.stateCode}
                    onValueChange={(value) => setCreateForm(prev => ({ ...prev, stateCode: value }))}
                  >
                    <SelectTrigger id="stateCode">
                      <SelectValue placeholder="Select state (optional)" />
                    </SelectTrigger>
                    <SelectContent>
                      {US_STATES.map((state) => (
                        <SelectItem key={state.code} value={state.code}>
                          {state.name} ({state.code})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Preview info */}
              {previewData && previewData.totalGamesAffected > 0 && (
                <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg p-3 text-sm">
                  <p className="text-blue-800 dark:text-blue-200">
                    Creating this team will also link {previewData.totalGamesAffected} game{previewData.totalGamesAffected > 1 ? 's' : ''} to it.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Selected Team Display - only in search mode */}
          {!showCreateForm && selectedTeam && (
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
              disabled={isLinking || isCreating}
            >
              Cancel
            </Button>
            {showCreateForm ? (
              <Button
                onClick={handleCreateTeam}
                disabled={!createForm.teamName || !createForm.ageGroup || !createForm.gender || isCreating || linkSuccess}
              >
                {isCreating ? 'Creating...' : 'Create & Link Team'}
              </Button>
            ) : (
              <Button
                onClick={handleLink}
                disabled={!selectedTeam || isLinking || linkSuccess}
              >
                {isLinking ? 'Linking...' : 'Link Team'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
