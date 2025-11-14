'use client';

import { useState, useMemo, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Fuse from 'fuse.js';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { InlineLoader } from '@/components/ui/LoadingStates';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Search, X } from 'lucide-react';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Highlight matching text in a string
 */
function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query) return text;
  
  const parts = text.split(new RegExp(`(${query})`, 'gi'));
  return (
    <>
      {parts.map((part, index) => 
        part.toLowerCase() === query.toLowerCase() ? (
          <mark key={index} className="bg-yellow-200 dark:bg-yellow-900 px-1 rounded">
            {part}
          </mark>
        ) : (
          part
        )
      )}
    </>
  );
}

/**
 * GlobalSearch component - fuzzy search for teams across the entire site
 */
export function GlobalSearch() {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  
  const { data: allTeams, isLoading, isError, error, refetch } = useTeamSearch();

  // Configure Fuse.js for fuzzy search
  const fuse = useMemo(() => {
    if (!allTeams) return null;
    
    return new Fuse(allTeams, {
      keys: [
        { name: 'team_name', weight: 0.7 },
        { name: 'club_name', weight: 0.2 },
        { name: 'state_code', weight: 0.1 },
      ],
      threshold: 0.3, // Lower = stricter matching
      includeScore: true,
      minMatchCharLength: 2,
    });
  }, [allTeams]);

  // Perform fuzzy search
  const searchResults = useMemo(() => {
    if (!searchQuery || !fuse || searchQuery.length < 2) return [];
    
    const results = fuse.search(searchQuery);
    return results.slice(0, 8).map(result => result.item); // Limit to 8 results
  }, [searchQuery, fuse]);

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
      if (inputRef.current && !inputRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative w-full max-w-md hidden md:block">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          ref={inputRef}
          type="text"
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
          className="pl-10 pr-10 w-full"
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
            className="absolute right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      
      {isOpen && searchQuery.length >= 2 && (
        <Card className="absolute z-50 w-full mt-1 max-h-80 overflow-y-auto shadow-lg">
          <CardContent className="p-2">
            {isLoading ? (
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
                    className={`w-full text-left p-3 rounded-md transition-colors duration-200 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary ${
                      index === selectedIndex
                        ? 'bg-accent font-semibold'
                        : 'hover:bg-accent/50'
                    }`}
                    aria-label={`Select ${team.team_name}`}
                  >
                    <div className="font-medium">
                      {highlightMatch(team.team_name, searchQuery)}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {team.club_name && (
                        <span>{highlightMatch(team.club_name, searchQuery)}</span>
                      )}
                      {team.state_code && (
                        <span className={team.club_name ? ' • ' : ''}>
                          {team.state_code.toUpperCase()}
                        </span>
                      )}
                      {team.rank_in_cohort_final && (
                        <span> • Rank #{team.rank_in_cohort_final}</span>
                      )}
                      {team.age_group && team.gender && (
                        <span className={team.club_name || team.state_code || team.rank_in_cohort_final ? ' • ' : ''}>
                          {team.age_group.toUpperCase()} {team.gender}
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

