'use client';

import { useState, useMemo, useRef, useEffect } from 'react';
import { Input } from '@/components/ui/input';
import { useRankings } from '@/lib/hooks';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { InlineLoader } from '@/components/ui/LoadingStates';
import type { RankingRow } from '@/types/RankingRow';

interface TeamSelectorProps {
  label: string;
  value: string | null;
  onChange: (teamId: string | null, team: RankingRow | null) => void;
  excludeTeamId?: string;
}

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
 * TeamSelector component - enhanced autocomplete team selector with keyboard navigation
 */
export function TeamSelector({ label, value, onChange, excludeTeamId }: TeamSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  
  // Fetch all rankings for autocomplete (no filters)
  const { data: allRankings, isLoading, isError, error, refetch } = useRankings();

  const selectedTeam = useMemo(() => {
    if (!value || !allRankings) return null;
    return allRankings.find(r => r.team_id_master === value) || null;
  }, [value, allRankings]);

  const filteredTeams = useMemo(() => {
    if (!allRankings || !searchQuery) return [];
    
    const query = searchQuery.toLowerCase();
    return allRankings
      .filter(team => 
        team.team_id_master !== excludeTeamId &&
        (team.team_name.toLowerCase().includes(query) ||
         team.club_name?.toLowerCase().includes(query) ||
         team.state?.toLowerCase().includes(query))
      )
      .slice(0, 10); // Limit to 10 results
  }, [allRankings, searchQuery, excludeTeamId]);

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
    if (!isOpen || filteredTeams.length === 0) return;

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
          type="text"
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
              {isLoading ? (
                <InlineLoader text="Loading teams..." />
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
                        {highlightMatch(team.team_name, searchQuery)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {team.club_name && (
                          <span>{highlightMatch(team.club_name, searchQuery)}</span>
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
