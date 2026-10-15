'use client';

import { useState, useRef, useEffect, useDeferredValue } from 'react';
import { useRouter } from 'next/navigation';

import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Search, X } from 'lucide-react';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import type { RankingRow } from '@/types/RankingRow';
import { trackSearchUsed, trackSearchResultClicked } from '@/lib/events';
import { teamDisplayName, spokenTeamMeta, scrollBehavior } from '@/lib/utils';
import { TeamRowSubtitle } from '@/components/TeamRowSubtitle';

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

/** The header renders one GlobalSearch below lg and another from lg up; each input gets its own id. */
export const GLOBAL_SEARCH_INPUT_IDS = { mobile: 'global-search-mobile', desktop: 'global-search-desktop' } as const;

/**
 * GlobalSearch component - search for teams across the entire site
 */
export function GlobalSearch({ inputId }: { inputId?: string }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Defer the search query to prevent UI jank during typing
  const deferredSearchQuery = useDeferredValue(searchQuery);
  // Track if search is pending (deferred value hasn't caught up)
  const isSearchPending = searchQuery !== deferredSearchQuery;

  const {
    results: searchResults,
    match,
    isLoading,
    isError,
    error,
    refetch,
  } = useTeamSearch(deferredSearchQuery, { limit: 8 });

  // selectedIndex is reset to 0 when search query changes (in handleSearchChange below)

  // Track a query once its own results have arrived (the hook loads until they do), so the
  // count belongs to it
  const lastTrackedQuery = useRef<string>('');
  const currentQuery = deferredSearchQuery.trim();
  useEffect(() => {
    if (currentQuery.length >= 2 && !isLoading && !isError && currentQuery !== lastTrackedQuery.current) {
      lastTrackedQuery.current = currentQuery;
      trackSearchUsed({
        query: currentQuery,
        results_count: searchResults.length,
      });
    }
  }, [currentQuery, isLoading, isError, searchResults.length]);

  const handleSelect = (team: RankingRow) => {
    // Track search result click
    trackSearchResultClicked({
      team_id_master: team.team_id_master,
      team_name: team.team_name,
      rank_in_cohort_final: team.rank_in_cohort_final,
    });
    router.push(`/teams/${team.team_id_master}`);
    setSearchQuery('');
    setIsOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || searchResults.length === 0) {
      if (e.key === 'Enter' && searchQuery.length >= 2) {
        // If Enter pressed with query but no results open, navigate to first result
        if (searchResults.length > 0) {
          handleSelect(searchResults[0]);
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
        selectedElement.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() });
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
          id={inputId}
          type="search"
          inputMode="search"
          autoComplete="off"
          placeholder="Find your team"
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setSelectedIndex(0);
            setIsOpen(true);
          }}
          onFocus={() => {
            if (searchQuery.length >= 2) {
              setIsOpen(true);
            }
          }}
          onKeyDown={handleKeyDown}
          className="pl-8 sm:pl-10 pr-8 sm:pr-10 w-full text-sm h-10 sm:h-11 [&::-webkit-search-cancel-button]:hidden"
          role="combobox"
          aria-label="Find your team"
          aria-autocomplete="list"
          aria-expanded={isOpen && searchResults.length > 0}
          aria-controls="global-search-results"
        />
        {searchQuery && (
          <button
            onClick={() => {
              setSearchQuery('');
              setIsOpen(false);
              inputRef.current?.focus();
            }}
            className="absolute right-2 sm:right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center -mr-2"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {isOpen && searchQuery.trim().length >= 2 && (
        // The box is too narrow to show team names: below lg it shares the header row with the
        // logo and menu, and from lg the nav links squeeze it. So the results get their own width:
        // a centred panel under the header below lg, and at least 24rem under the box from lg.
        <Card className="absolute z-50 w-full mt-1 max-h-80 overflow-y-auto shadow-lg max-lg:fixed max-lg:inset-x-2 max-lg:top-[var(--site-header-height)] max-lg:mx-auto max-lg:w-auto max-lg:max-w-xl lg:left-1/2 lg:w-[max(100%,24rem)] lg:-translate-x-1/2">
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
              <>
                {match !== 'exact' && (
                  <div className="px-3 pb-1 text-xs text-muted-foreground">Showing close matches</div>
                )}
                <div id="global-search-results" role="listbox" className="space-y-1" ref={listRef}>
                  {searchResults.map((team, index) => {
                    const displayName = teamDisplayName(team);
                    const spokenMeta = spokenTeamMeta(team);
                    return (
                      <button
                        key={team.team_id_master}
                        role="option"
                        aria-selected={index === selectedIndex}
                        onClick={() => handleSelect(team)}
                        className={`w-full text-left p-3 rounded-md transition-colors duration-200 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary min-h-[44px] ${
                          index === selectedIndex ? 'bg-accent font-semibold' : 'hover:bg-accent/50'
                        }`}
                        aria-label={`Select ${displayName}${spokenMeta ? ` ${spokenMeta}` : ''}`}
                      >
                        <div className="font-medium line-clamp-2 break-words">
                          {highlightMatch(displayName, deferredSearchQuery)}
                        </div>
                        <TeamRowSubtitle
                          team={team}
                          highlight={(text) => highlightMatch(text, deferredSearchQuery)}
                          className="text-xs text-muted-foreground mt-1 truncate"
                        />
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
