'use client';

import { useState, useEffect, useRef, useDeferredValue } from 'react';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { InlineLoader } from '@/components/ui/LoadingStates';

interface ScopedTeam {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  age_group: string;
  gender: string;
  state_code: string;
  state: string | null;
}

interface ScopedTeamSelectorProps {
  ageGroup: string | null;
  gender: string | null; // DB format: 'Male' | 'Female'
  stateCode: string | null;
  value: string | null;
  onChange: (teamId: string | null, team: ScopedTeam | null) => void;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query || query.length < 2) return text;
  try {
    const parts = text.split(new RegExp(`(${escapeRegex(query)})`, 'gi'));
    return (
      <>
        {parts.map((part, i) =>
          part.toLowerCase() === query.toLowerCase() ? (
            <mark key={i} className="bg-[#F4D03F]/40 px-0.5 rounded">
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

export function ScopedTeamSelector({ ageGroup, gender, stateCode, value, onChange }: ScopedTeamSelectorProps) {
  const allFiltersSet = Boolean(ageGroup && gender && stateCode);
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [results, setResults] = useState<ScopedTeam[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedTeam, setSelectedTeam] = useState<ScopedTeam | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const deferredQuery = useDeferredValue(searchQuery);
  const isSearchPending = searchQuery !== deferredQuery;

  // Reset selection when filters change
  useEffect(() => {
    setSearchQuery('');
    setResults([]);
    setSelectedTeam(null);
    onChange(null, null);
    // We intentionally exclude onChange from deps — it changes every render in the parent
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ageGroup, gender, stateCode]);

  // Fetch scoped results
  useEffect(() => {
    if (!allFiltersSet || deferredQuery.trim().length < 2) {
      setResults([]);
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    // state_code in the teams table is uppercase ('AZ'); our dropdown emits the
    // lowercase URL-slug form ('az'). Normalize at the fetch boundary.
    const params = new URLSearchParams({
      q: deferredQuery.trim(),
      ageGroup: ageGroup!,
      gender: gender!,
      stateCode: stateCode!.toUpperCase(),
      limit: '15',
    });

    fetch(`/api/teams/search?${params.toString()}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Search failed (${r.status})`))))
      .then((data) => {
        setResults(data.teams || []);
        setSelectedIndex(0);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        console.error('[ScopedTeamSelector] Search error:', err);
        setResults([]);
      })
      .finally(() => setIsLoading(false));

    return () => controller.abort();
  }, [deferredQuery, ageGroup, gender, stateCode, allFiltersSet]);

  const handleSelect = (team: ScopedTeam) => {
    setSelectedTeam(team);
    onChange(team.team_id_master, team);
    setSearchQuery(team.club_name ? `${team.team_name} · ${team.club_name}` : team.team_name);
    setIsOpen(false);
    setSelectedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || results.length === 0) return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((p) => (p + 1) % results.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((p) => (p - 1 + results.length) % results.length);
        break;
      case 'Enter':
        e.preventDefault();
        if (results[selectedIndex]) handleSelect(results[selectedIndex]);
        break;
      case 'Escape':
        setIsOpen(false);
        break;
    }
  };

  useEffect(() => {
    if (listRef.current && selectedIndex >= 0) {
      const el = listRef.current.children[selectedIndex] as HTMLElement;
      if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedIndex]);

  // Note: id="report-card-team-search" so the parent can focus this input when filters complete
  return (
    <div className="relative">
      <label htmlFor="report-card-team-search" className="text-sm font-medium mb-2 block">
        Search your team
      </label>
      <Input
        ref={inputRef}
        id="report-card-team-search"
        type="search"
        inputMode="search"
        autoComplete="off"
        placeholder={
          allFiltersSet
            ? 'Type at least 2 letters of your team or club name'
            : 'Pick age, gender, and state above first'
        }
        value={searchQuery}
        disabled={!allFiltersSet}
        onChange={(e) => {
          setSearchQuery(e.target.value);
          setIsOpen(true);
          if (value && selectedTeam) {
            // Typing again clears the prior selection
            setSelectedTeam(null);
            onChange(null, null);
          }
        }}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setTimeout(() => setIsOpen(false), 200)}
        onKeyDown={handleKeyDown}
        aria-autocomplete="list"
        aria-expanded={isOpen && results.length > 0}
      />
      {isOpen && allFiltersSet && searchQuery.length >= 2 && (
        <Card className="absolute z-50 w-full mt-1 max-h-60 overflow-y-auto shadow-lg">
          <CardContent className="p-2" ref={listRef}>
            {isLoading || isSearchPending ? (
              <InlineLoader text="Searching your group..." />
            ) : results.length === 0 ? (
              <div className="p-3 text-sm text-muted-foreground text-center">
                No teams matching &quot;{searchQuery}&quot; in this group. Check the spelling or widen your filters.
              </div>
            ) : (
              <div className="space-y-1">
                {results.map((team, index) => (
                  <button
                    key={team.team_id_master}
                    type="button"
                    onClick={() => handleSelect(team)}
                    className={`w-full text-left p-2 rounded-md transition-colors focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary ${
                      index === selectedIndex ? 'bg-accent font-semibold' : 'hover:bg-accent/50'
                    }`}
                  >
                    <div className="font-medium">{highlightMatch(team.team_name, deferredQuery)}</div>
                    {team.club_name && (
                      <div className="text-xs text-muted-foreground">
                        {highlightMatch(team.club_name, deferredQuery)}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {selectedTeam && (
        <p className="mt-2 text-sm text-muted-foreground">
          Selected: <span className="font-medium text-foreground">{selectedTeam.team_name}</span>
          {selectedTeam.club_name && <span> · {selectedTeam.club_name}</span>}
        </p>
      )}
    </div>
  );
}

export type { ScopedTeam };
