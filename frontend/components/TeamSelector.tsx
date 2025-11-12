'use client';

import { useState, useMemo } from 'react';
import { Input } from '@/components/ui/input';
import { useRankings } from '@/lib/hooks';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { RankingWithTeam } from '@/lib/types';

interface TeamSelectorProps {
  label: string;
  value: string | null;
  onChange: (teamId: string | null, team: RankingWithTeam | null) => void;
  excludeTeamId?: string;
}

/**
 * TeamSelector component - autocomplete team selector using rankings data
 */
export function TeamSelector({ label, value, onChange, excludeTeamId }: TeamSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  
  // Fetch all rankings for autocomplete (no filters)
  const { data: allRankings, isLoading } = useRankings();

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
         team.state_code?.toLowerCase().includes(query))
      )
      .slice(0, 10); // Limit to 10 results
  }, [allRankings, searchQuery, excludeTeamId]);

  const handleSelect = (team: RankingWithTeam) => {
    onChange(team.team_id_master, team);
    setSearchQuery(team.team_name);
    setIsOpen(false);
  };

  return (
    <div className="relative">
      <label htmlFor={`team-selector-${label}`} className="text-sm font-medium mb-2 block">
        {label}
      </label>
      <div className="relative">
        <Input
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
          className="w-full transition-colors duration-300"
          aria-label={`Search and select ${label.toLowerCase()}`}
          aria-autocomplete="list"
          aria-expanded={isOpen && filteredTeams.length > 0}
        />
        {isOpen && searchQuery && filteredTeams.length > 0 && (
          <Card className="absolute z-50 w-full mt-1 max-h-60 overflow-y-auto">
            <CardContent className="p-2">
              {isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredTeams.map((team) => (
                    <button
                      key={team.team_id_master}
                      onClick={() => handleSelect(team)}
                      className="w-full text-left p-2 rounded-md hover:bg-accent transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                      aria-label={`Select ${team.team_name}`}
                    >
                      <div className="font-medium">{team.team_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {team.club_name && <span>{team.club_name}</span>}
                        {team.state_code && (
                          <span className={team.club_name ? ' • ' : ''}>
                            {team.state_code}
                          </span>
                        )}
                        {team.national_rank && (
                          <span> • Rank #{team.national_rank}</span>
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

