'use client';

/**
 * Weekly Movers Infographic
 * Brand: PitchRank Creative Kit
 * Usage: Screenshot at 1080x1350 (4:5) for Instagram
 */

interface Mover {
  teamName: string;
  state: string;
  ageGroup: string;
  gender: 'Boys' | 'Girls';
  movement: number;
  newRank?: number;
}

interface WeeklyMoversProps {
  movers: Mover[];
  week?: number;
  title?: string;
  variant?: 'square' | 'portrait';
}

export function WeeklyMovers({
  movers,
  week,
  title = 'BIGGEST MOVERS THIS WEEK',
  variant = 'portrait',
}: WeeklyMoversProps) {
  const isSquare = variant === 'square';
  const displayMovers = movers.slice(0, isSquare ? 5 : 7);
  
  return (
    <div 
      className={`bg-[#052E27] text-white font-sans flex flex-col ${
        isSquare ? 'w-[1080px] h-[1080px] p-12' : 'w-[1080px] h-[1350px] p-14'
      }`}
      style={{ fontFamily: 'DM Sans, sans-serif' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-[#F4D03F] rounded-lg flex items-center justify-center">
            <span 
              className="text-[#052E27] text-xl font-bold"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              PR
            </span>
          </div>
          <span 
            className="text-white text-xl font-bold tracking-wide"
            style={{ fontFamily: 'Oswald, sans-serif' }}
          >
            PITCHRANK
          </span>
        </div>
        {week && (
          <span className="text-white/60 text-lg">Week {week}</span>
        )}
      </div>
      
      {/* Title */}
      <div className="mb-8">
        <h1 
          className="text-[#F4D03F] text-5xl font-bold tracking-wide flex items-center gap-4"
          style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
        >
          <span className="text-6xl">🔥</span> {title}
        </h1>
        <div className="w-full h-1 bg-[#F4D03F] mt-4" />
      </div>
      
      {/* Movers List */}
      <div className="flex-1 space-y-4">
        {displayMovers.map((mover, index) => (
          <div 
            key={index}
            className="flex items-center gap-4 bg-[#0B5345] rounded-xl p-5"
          >
            {/* Movement Badge */}
            <div 
              className="flex-shrink-0 w-24 h-16 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: '#22C55E' }}
            >
              <span 
                className="text-white text-3xl font-bold"
                style={{ fontFamily: 'Oswald, sans-serif' }}
              >
                ▲ +{mover.movement}
              </span>
            </div>
            
            {/* Team Info */}
            <div className="flex-1 min-w-0">
              <h3 
                className="text-white text-2xl font-bold truncate"
                style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
              >
                {mover.teamName}
              </h3>
              <p className="text-white/60 text-lg">
                {mover.state} • {mover.ageGroup} {mover.gender}
              </p>
            </div>
            
            {/* New Rank (if provided) */}
            {mover.newRank && (
              <div className="flex-shrink-0 text-right">
                <span className="text-white/60 text-sm block">Now</span>
                <span 
                  className="text-[#F4D03F] text-3xl font-bold"
                  style={{ fontFamily: 'Oswald, sans-serif' }}
                >
                  #{mover.newRank}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
      
      {/* Footer */}
      <div className="mt-auto pt-6">
        <div className="w-full h-px bg-[#0B5345] mb-4" />
        <div className="flex items-center justify-between">
          <span className="text-white/60 text-base">
            Rankings updated after every game
          </span>
          <span className="text-white/60 text-base">pitchrank.com</span>
        </div>
      </div>
    </div>
  );
}

export default WeeklyMovers;
