interface HomeStatsProps {
  totalGames?: number;
  totalTeams?: number;
  fallbackGames?: number;
  fallbackTeams?: number;
}

export function HomeStats({ totalGames, totalTeams, fallbackGames = 16000, fallbackTeams = 2800 }: HomeStatsProps) {
  const games = totalGames ?? fallbackGames;
  const teams = totalTeams ?? fallbackTeams;
  const formatNumber = (num: number) => num.toLocaleString('en-US');

  return (
    <div className="grid grid-cols-3 gap-4 sm:gap-8 mb-8 max-w-4xl">
      <div className="text-center">
        <div className="font-mono text-xl sm:text-3xl md:text-4xl lg:text-5xl font-bold text-accent">
          {formatNumber(games)}
        </div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">Games Analyzed</div>
      </div>
      <div className="text-center">
        <div className="font-mono text-xl sm:text-3xl md:text-4xl lg:text-5xl font-bold text-accent">
          {formatNumber(teams)}
        </div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">Teams Ranked</div>
      </div>
      <div className="text-center">
        <div className="font-mono text-xl sm:text-3xl md:text-4xl lg:text-5xl font-bold text-accent">50</div>
        <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">States Covered</div>
      </div>
    </div>
  );
}
