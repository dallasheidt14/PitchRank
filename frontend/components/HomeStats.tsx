'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface HomeStatsProps {
  fallbackGames?: number;
  fallbackTeams?: number;
}

export function HomeStats({ fallbackGames = 16000, fallbackTeams = 2800 }: HomeStatsProps) {
  const [totalGames, setTotalGames] = useState(fallbackGames);
  const [totalTeams, setTotalTeams] = useState(fallbackTeams);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    async function fetchStats() {
      try {
        // Try RPC function first
        const { data, error } = await supabase.rpc('get_db_stats');

        if (!error && data && data.length > 0) {
          setTotalGames(Number(data[0].total_games) || fallbackGames);
          setTotalTeams(Number(data[0].total_teams) || fallbackTeams);
        } else {
          // Fallback to direct queries
          const [gamesRes, teamsRes] = await Promise.all([
            supabase.from('games').select('*', { count: 'exact', head: true })
              .not('home_score', 'is', null),
            supabase.from('rankings_full').select('*', { count: 'exact', head: true })
              .not('power_score_final', 'is', null)
          ]);

          if (!gamesRes.error && gamesRes.count) setTotalGames(gamesRes.count);
          if (!teamsRes.error && teamsRes.count) setTotalTeams(teamsRes.count);
        }
      } catch (err) {
        console.error('Error fetching stats:', err);
      } finally {
        setLoaded(true);
      }
    }

    fetchStats();
  }, [fallbackGames, fallbackTeams]);

  const formatNumber = (num: number) => num.toLocaleString('en-US');

  return (
    <div className="grid grid-cols-3 gap-4 sm:gap-8 mb-8 max-w-2xl">
      <div className="text-center">
        <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">
          {formatNumber(totalGames)}
        </div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">
          Games Analyzed
        </div>
      </div>
      <div className="text-center">
        <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">
          {formatNumber(totalTeams)}
        </div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">
          Teams Ranked
        </div>
      </div>
      <div className="text-center">
        <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">
          50
        </div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">
          States Covered
        </div>
      </div>
    </div>
  );
}
