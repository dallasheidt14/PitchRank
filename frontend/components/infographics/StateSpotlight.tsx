'use client';

/**
 * State Spotlight Infographic
 * Brand: PitchRank Creative Kit
 * Usage: Screenshot at 1080x1350 (4:5) for Instagram
 */

interface RankedTeam {
  rank: number;
  teamName: string;
  powerScore: number;
  movement?: number;
}

interface StateSpotlightProps {
  state: string;
  stateCode: string;
  ageGroup: string;
  gender: 'Boys' | 'Girls';
  teams: RankedTeam[];
  totalTeams?: number;
  variant?: 'square' | 'portrait';
}

export function StateSpotlight({
  state,
  stateCode,
  ageGroup,
  gender,
  teams,
  totalTeams,
  variant = 'portrait',
}: StateSpotlightProps) {
  const isSquare = variant === 'square';
  const displayTeams = teams.slice(0, isSquare ? 5 : 7);
  
  const getMovementDisplay = (movement?: number) => {
    if (!movement || movement === 0) return { icon: '━', color: '#9CA3AF' };
    if (movement > 0) return { icon: `▲+${movement}`, color: '#22C55E' };
    return { icon: `▼${movement}`, color: '#EF4444' };
  };
  
  return (
    <div 
      className={`bg-[#052E27] text-white font-sans flex flex-col ${
        isSquare ? 'w-[1080px] h-[1080px] p-12' : 'w-[1080px] h-[1350px] p-14'
      }`}
      style={{ fontFamily: 'DM Sans, sans-serif' }}
    >
      {/* Header Bar - Yellow accent */}
      <div className="bg-[#F4D03F] -mx-14 -mt-14 px-14 py-6 mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 
              className="text-[#052E27] text-5xl font-bold tracking-wide"
              style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
            >
              {state} {ageGroup} {gender}
            </h1>
            <p className="text-[#052E27]/70 text-xl mt-1">TOP {displayTeams.length} THIS WEEK</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-14 h-14 bg-[#052E27] rounded-lg flex items-center justify-center">
              <span 
                className="text-[#F4D03F] text-2xl font-bold"
                style={{ fontFamily: 'Oswald, sans-serif' }}
              >
                PR
              </span>
            </div>
          </div>
        </div>
      </div>
      
      {/* Rankings Table */}
      <div className="flex-1">
        {/* Table Header */}
        <div className="flex items-center gap-4 px-4 py-3 text-white/50 text-sm uppercase tracking-wide border-b border-[#0B5345]">
          <span className="w-16 text-center">Rank</span>
          <span className="flex-1">Team</span>
          <span className="w-28 text-center">PowerScore</span>
          <span className="w-20 text-right">Change</span>
        </div>
        
        {/* Teams */}
        <div className="divide-y divide-[#0B5345]">
          {displayTeams.map((team, index) => {
            const movement = getMovementDisplay(team.movement);
            const isTop3 = team.rank <= 3;
            
            return (
              <div 
                key={index}
                className={`flex items-center gap-4 px-4 py-5 ${
                  isTop3 ? 'bg-[#0B5345]/50' : ''
                }`}
              >
                {/* Rank */}
                <div className="w-16 text-center">
                  <span 
                    className={`text-4xl font-bold ${
                      team.rank === 1 ? 'text-[#F4D03F]' : 'text-white'
                    }`}
                    style={{ fontFamily: 'Oswald, sans-serif' }}
                  >
                    {team.rank}
                  </span>
                </div>
                
                {/* Team Name */}
                <div className="flex-1 min-w-0">
                  <h3 
                    className="text-white text-2xl font-bold truncate"
                    style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
                  >
                    {team.teamName}
                  </h3>
                </div>
                
                {/* PowerScore */}
                <div className="w-28 text-center">
                  <span 
                    className="text-[#F4D03F] text-3xl font-bold"
                    style={{ fontFamily: 'Oswald, sans-serif' }}
                  >
                    {team.powerScore.toLocaleString()}
                  </span>
                </div>
                
                {/* Movement */}
                <div className="w-20 text-right">
                  <span 
                    className="text-xl font-semibold"
                    style={{ color: movement.color }}
                  >
                    {movement.icon}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      
      {/* Footer */}
      <div className="mt-auto pt-6">
        <div className="w-full h-px bg-[#0B5345] mb-4" />
        <div className="flex items-center justify-between">
          <span className="text-white/60 text-base">
            {totalTeams ? `${totalTeams.toLocaleString()} teams in ${stateCode}` : `${stateCode} rankings`}
          </span>
          <span className="text-white/60 text-base">pitchrank.com</span>
        </div>
      </div>
    </div>
  );
}

export default StateSpotlight;
