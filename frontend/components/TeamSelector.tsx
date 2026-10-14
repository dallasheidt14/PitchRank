'use client';

import { useState, useRef, useEffect, useDeferredValue } from 'react';
import { Input } from '@/components/ui/input';
import { useTeamSearch } from '@/hooks/useTeamSearch';
import { Card, CardContent } from '@/components/ui/card';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { InlineLoader } from '@/components/ui/LoadingStates';
import type { RankingRow } from '@/types/RankingRow';
import { teamDisplayName, spokenTeamMeta, scrollBehavior } from '@/lib/utils';
import { TeamRowSubtitle } from '@/components/TeamRowSubtitle';

interface TeamSelectorProps {
  label: string;
  value: string | null;
  onChange: (teamId: string | null, team: RankingRow | null) => void;
  /** The row for `value`, owned by the parent so a swap moves it with the id. */
  selectedTeam?: RankingRow | null;
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
export function TeamSelector({ label, value, onChange, selectedTeam = null, excludeTeamId }: TeamSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Defer the search query to prevent UI jank during typing
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const isSearchPending = searchQuery !== deferredSearchQuery;

  const {
    results: filteredTeams,
    match,
    isLoading,
    isError,
    error,
    refetch,
  } = useTeamSearch(deferredSearchQuery, { limit: 10, excludeId: excludeTeamId });

  const shownTeam = value && selectedTeam?.team_id_master === value ? selectedTeam : null;

  // Registered names carry no cohort and repeat across age groups, and nothing else on
  // /compare shows one, so the confirmation must.
  const selectedTeamMeta = shownTeam ? spokenTeamMeta(shownTeam) : '';

  const handleSelect = (team: RankingRow) => {
    onChange(team.team_id_master, team);
    setSearchQuery(teamDisplayName(team));
    setIsOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || filteredTeams.length === 0) {
      // Enter with the dropdown closed picks the top match
      if (e.key === 'Enter' && searchQuery.length >= 2 && filteredTeams.length > 0) {
        handleSelect(filteredTeams[0]);
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
        selectedElement.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() });
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
            setSelectedIndex(0);
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
        {isOpen && searchQuery.trim().length >= 2 && (
          <Card className="absolute z-50 w-full mt-1 max-h-60 overflow-y-auto shadow-lg">
            <CardContent className="p-2">
              {isLoading || isSearchPending ? (
                <InlineLoader text="Searching teams..." />
              ) : isError ? (
                <ErrorDisplay error={error} retry={refetch} compact />
              ) : filteredTeams.length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  No teams found matching &quot;{searchQuery}&quot;
                </div>
              ) : (
                <>
                  {match !== 'exact' && (
                    <div className="px-3 pb-1 text-xs text-muted-foreground">Showing close matches</div>
                  )}
                  <div className="space-y-1" ref={listRef}>
                    {filteredTeams.map((team, index) => {
                      const displayName = teamDisplayName(team);
                      const spokenMeta = spokenTeamMeta(team);
                      return (
                        <button
                          key={team.team_id_master}
                          onClick={() => handleSelect(team)}
                          className={`w-full text-left p-2 rounded-md transition-colors duration-200 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary ${
                            index === selectedIndex ? 'bg-accent font-semibold' : 'hover:bg-accent/50'
                          }`}
                          aria-label={`Select ${displayName}${spokenMeta ? ` ${spokenMeta}` : ''}`}
                        >
                          <div className="font-medium">{highlightMatch(displayName, deferredSearchQuery)}</div>
                          <TeamRowSubtitle
                            team={team}
                            highlight={(text) => highlightMatch(text, deferredSearchQuery)}
                            className="text-xs text-muted-foreground truncate"
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
      {shownTeam && (
        <div className="mt-2 text-sm text-muted-foreground">
          Selected: <span className="font-medium">{teamDisplayName(shownTeam)}</span>
          {selectedTeamMeta && <span> — {selectedTeamMeta}</span>}
        </div>
      )}
    </div>
  );
}
