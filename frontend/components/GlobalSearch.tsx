'use client';

import { useState, useMemo, useRef, useEffect, useDeferredValue, useTransition, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import type Fuse from 'fuse.js';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Search, X } from 'lucide-react';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import type { RankingRow } from '@/types/RankingRow';

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
    // Fallback if regex still fails
    return text;
  }
}

/**
 * GlobalSearch component - fuzzy search for teams across the entire site
 * Lazy loads Fuse.js library for better initial bundle size
 */
export function GlobalSearch() {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [FuseClass, setFuseClass] = useState<typeof Fuse | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Defer the search query to prevent UI jank during typing
  const deferredSearchQuery = useDeferredValue(searchQuery);
  // Track if search is pending (deferred value hasn't caught up)
  const isSearchPending = searchQuery !== deferredSearchQuery;

  const { data: allTeams, isLoading, isError, error, refetch } = useTeamSearch();

  // Dynamically load Fuse.js only when needed
  useEffect(() => {
    if (!FuseClass) {
      import('fuse.js').then((module) => {
        setFuseClass(() => module.default);
      });
    }
  }, [FuseClass]);

  // Configure Fuse.js for fuzzy search with optimized settings
  const fuse = useMemo(() => {
    if (!allTeams || !FuseClass) return null;

    return new FuseClass(allTeams, {
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
      // Performance optimizations
      useExtendedSearch: false,
      isCaseSensitive: false,
    });
  }, [allTeams, FuseClass]);

  // Perform search using word-based matching for better multi-word queries
  // "rebels san diego romero" will match if ALL words appear in searchable_name or club_name
  const searchResults = useMemo(() => {
    if (!deferredSearchQuery || !allTeams || deferredSearchQuery.length < 2) return [];

    const queryWords = deferredSearchQuery.toLowerCase().split(/\s+/).filter(w => w.length > 0);

    // Filter teams where ALL query words appear in searchable_name or club_name
    const matchingTeams = allTeams.filter(team => {
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

    return matchingTeams.slice(0, 8);
  }, [deferredSearchQuery, allTeams]);

  // Reset selected index when results change
  useEffect(() => {
    setSelectedIndex(0);
  }, [searchResults.length]);

  const handleSelect = (team: RankingRow) => {
    router.push(`/teams/${team.team_id_master}`);
    setSearchQuery('');
    setIsOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || searchResults.length === 0) {
      if (e.key === 'Enter' && searchQuery.length >= 2) {
        // If Enter pressed with query but no results open, try to navigate to first result
        const results = fuse?.search(searchQuery);
        if (results && results.length > 0) {
          handleSelect(results[0].item);
        }
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % searchResults.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + searchResults.length) % searchResults.length);
        break;
      case 'Enter':
        e.preventDefault();
        if (searchResults[selectedIndex]) {
          handleSelect(searchResults[selectedIndex]);
        }
        break;
      case 'Escape':
        setIsOpen(false);
        setSearchQuery('');
        break;
    }
  };

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current && selectedIndex >= 0 && searchResults.length > 0) {
      const selectedElement = listRef.current.children[selectedIndex] as HTMLElement;
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [selectedIndex, searchResults.length]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search className="absolute left-2 sm:left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
        <Input
          ref={inputRef}
          type="search"
          inputMode="search"
          autoComplete="off"
          placeholder="Search teams..."
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => {
            if (searchQuery.length >= 2) {
              setIsOpen(true);
            }
          }}
          onKeyDown={handleKeyDown}
          className="pl-8 sm:pl-10 pr-8 sm:pr-10 w-full text-sm h-10 sm:h-11"
          aria-label="Search for teams"
          aria-autocomplete="list"
          aria-expanded={isOpen && searchResults.length > 0}
        />
        {searchQuery && (
          <button
            onClick={() => {
              setSearchQuery('');
              setIsOpen(false);
            }}
            className="absolute right-2 sm:right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center -mr-2"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      
      {isOpen && searchQuery.length >= 2 && (
        <Card className="absolute z-50 w-full mt-1 max-h-80 overflow-y-auto shadow-lg">
          <CardContent className="p-2">
            {isLoading || isSearchPending ? (
              <InlineLoader text="Searching teams..." />
            ) : isError ? (
              <ErrorDisplay error={error} retry={refetch} compact />
            ) : searchResults.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground">
                No teams found matching &quot;{searchQuery}&quot;
              </div>
            ) : (
              <div className="space-y-1" ref={listRef}>
                {searchResults.map((team, index) => (
                  <button
                    key={team.team_id_master}
                    onClick={() => handleSelect(team)}
                    className={`w-full text-left p-3 rounded-md transition-colors duration-200 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary min-h-[44px] ${
                      index === selectedIndex
                        ? 'bg-accent font-semibold'
                        : 'hover:bg-accent/50'
                    }`}
                    aria-label={`Select ${team.team_name}`}
                  >
                    <div className="font-medium truncate">
                      {highlightMatch(team.team_name, deferredSearchQuery)}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
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
                      {team.age != null && team.gender && (
                        <span className={team.club_name || team.state || team.rank_in_cohort_final ? ' • ' : ''}>
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
  );
}

