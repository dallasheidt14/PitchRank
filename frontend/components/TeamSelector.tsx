'use client';

import { useState, useMemo, useRef, useEffect, useDeferredValue } from 'react';
import { Input } from '@/components/ui/input';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import { Card, CardContent } from '@/components/ui/card';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { InlineLoader } from '@/components/ui/LoadingStates';
import type Fuse from 'fuse.js';
import type { RankingRow } from '@/types/RankingRow';

interface TeamSelectorProps {
  label: string;
  value: string | null;
  onChange: (teamId: string | null, team: RankingRow | null) => void;
  excludeTeamId?: string;
}

/**
 * Escape special regex characters in a string
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Highlight matching text in a string (with safe regex escaping)
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
            <mark key={index} className="bg-yellow-200 px-1 rounded">
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
 * TeamSelector component - enhanced autocomplete team selector with keyboard navigation
 */
export function TeamSelector({ label, value, onChange, excludeTeamId }: TeamSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [FuseClass, setFuseClass] = useState<typeof Fuse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Defer the search query to prevent UI jank during typing
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const isSearchPending = searchQuery !== deferredSearchQuery;

  // Fetch all teams for autocomplete (not just ranked teams)
  const { data: allTeams, isLoading, isError, error, refetch } = useTeamSearch();

  // Dynamically load Fuse.js only when needed
  useEffect(() => {
    if (!FuseClass) {
      import('fuse.js').then((module) => {
        setFuseClass(() => module.default);
      });
    }
  }, [FuseClass]);

  const selectedTeam = useMemo(() => {
    if (!value || !allTeams) return null;
    return allTeams.find(r => r.team_id_master === value) || null;
  }, [value, allTeams]);

  // Configure Fuse.js for fuzzy search with optimized settings
  const fuse = useMemo(() => {
    if (!allTeams || !FuseClass) return null;

    // Filter out excluded team before creating Fuse instance
    const teamsToSearch = excludeTeamId
      ? allTeams.filter(team => team.team_id_master !== excludeTeamId)
      : allTeams;

    return new FuseClass(teamsToSearch, {
      keys: [
        { name: 'searchable_name', weight: 0.5 },
        { name: 'club_name', weight: 0.4 },
        { name: 'state', weight: 0.1 },
      ],
      threshold: 0.4, // Tighter threshold for faster, more accurate results
      ignoreLocation: true,
      findAllMatches: false, // Stop at first match for better performance
      includeScore: true,
      minMatchCharLength: 2,
      shouldSort: true,
      useExtendedSearch: false,
      isCaseSensitive: false,
    });
  }, [allTeams, FuseClass, excludeTeamId]);

  // Perform search using word-based matching for better multi-word queries
  const filteredTeams = useMemo(() => {
    if (!deferredSearchQuery || !allTeams || deferredSearchQuery.length < 2) return [];

    const queryWords = deferredSearchQuery.toLowerCase().split(/\s+/).filter(w => w.length > 0);

    // Get teams to search (excluding the excluded team)
    const teamsToSearch = excludeTeamId
      ? allTeams.filter(team => team.team_id_master !== excludeTeamId)
      : allTeams;

    // Filter teams where ALL query words appear in searchable_name or club_name
    const matchingTeams = teamsToSearch.filter(team => {
      const searchText = ((team.searchable_name || team.team_name) + ' ' + (team.club_name || '')).toLowerCase();
      return queryWords.every(word => searchText.includes(word));
    });

    // Sort by how early the first match appears (better relevance)
    matchingTeams.sort((a, b) => {
      const aText = ((a.searchable_name || a.team_name) + ' ' + (a.club_name || '')).toLowerCase();
      const bText = ((b.searchable_name || b.team_name) + ' ' + (b.club_name || '')).toLowerCase();
      const aIndex = Math.min(...queryWords.map(w => aText.indexOf(w)));
      const bIndex = Math.min(...queryWords.map(w => bText.indexOf(w)));
      return aIndex - bIndex;
    });

    return matchingTeams.slice(0, 10);
  }, [deferredSearchQuery, allTeams, excludeTeamId]);

  // Reset selected index when filtered teams change
  useEffect(() => {
    setSelectedIndex(0);
  }, [filteredTeams.length]);

  const handleSelect = (team: RankingRow) => {
    onChange(team.team_id_master, team);
    setSearchQuery(team.team_name);
    setIsOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || filteredTeams.length === 0) {
      // Allow Enter to search even if dropdown isn't open
      if (e.key === 'Enter' && searchQuery.length >= 2 && fuse) {
        const results = fuse.search(searchQuery);
        if (results && results.length > 0) {
          handleSelect(results[0].item);
        }
      }
      return;
    }

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
          handleSelect(filteredTeams[selectedIndex]);
        }
        break;
      case 'Escape':
        setIsOpen(false);
        break;
    }
  };

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && selectedIndex >= 0) {
      const selectedElement = listRef.current.children[selectedIndex] as HTMLElement;
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [selectedIndex]);

  return (
    <div className="relative">
      <label htmlFor={`team-selector-${label}`} className="text-sm font-medium mb-2 block">
        {label}
      </label>
      <div className="relative">
        <Input
          ref={inputRef}
          id={`team-selector-${label}`}
          type="search"
          inputMode="search"
          autoComplete="off"
          placeholder="Search for a team..."
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onBlur={() => setTimeout(() => setIsOpen(false), 200)}
          onKeyDown={handleKeyDown}
          className="w-full transition-colors duration-300"
          aria-label={`Search and select ${label.toLowerCase()}`}
          aria-autocomplete="list"
          aria-expanded={isOpen && filteredTeams.length > 0}
        />
        {isOpen && searchQuery && (
          <Card className="absolute z-50 w-full mt-1 max-h-60 overflow-y-auto shadow-lg">
            <CardContent className="p-2" ref={listRef}>
              {isLoading || isSearchPending ? (
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
                      onClick={() => handleSelect(team)}
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
                        {team.rank_in_cohort_final && (
                          <span> • Rank #{team.rank_in_cohort_final}</span>
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
      {selectedTeam && (
        <div className="mt-2 text-sm text-muted-foreground">
          Selected: <span className="font-medium">{selectedTeam.team_name}</span>
        </div>
      )}
    </div>
  );
}
