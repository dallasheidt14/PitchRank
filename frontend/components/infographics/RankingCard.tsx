'use client';

/**
 * Team Ranking Card Infographic
 * Brand: PitchRank Creative Kit
 * Usage: Screenshot at 1080x1080 (1:1) for Instagram/social
 */

interface RankingCardProps {
  rank: number;
  teamName: string;
  clubName?: string;
  state: string;
  ageGroup: string;
  gender: 'Boys' | 'Girls';
  powerScore: number;
  record: string; // "12-1-0" format
  movement?: number; // positive = up, negative = down, 0 = no change
  variant?: 'square' | 'story';
}

export function RankingCard({
  rank,
  teamName,
  clubName,
  state,
  ageGroup,
  gender,
  powerScore,
  record,
  movement = 0,
  variant = 'square',
}: RankingCardProps) {
  const isStory = variant === 'story';
  
  const getMovementDisplay = () => {
    if (movement > 0) return { icon: '▲', color: '#22C55E', text: `+${movement}` };
    if (movement < 0) return { icon: '▼', color: '#EF4444', text: `${movement}` };
    return { icon: '━', color: '#9CA3AF', text: '0' };
  };
  
  const movementInfo = getMovementDisplay();
  
  const getMedalEmoji = (rank: number) => {
    if (rank === 1) return '🥇';
    if (rank === 2) return '🥈';
    if (rank === 3) return '🥉';
    return null;
  };
  
  const medal = getMedalEmoji(rank);
  
  return (
    <div 
      className={`bg-[#052E27] text-white font-sans flex flex-col ${
        isStory ? 'w-[1080px] h-[1920px] p-16' : 'w-[1080px] h-[1080px] p-12'
      }`}
      style={{ fontFamily: 'DM Sans, sans-serif' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 bg-[#F4D03F] rounded-lg flex items-center justify-center">
            <span 
              className="text-[#052E27] text-2xl font-bold"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              PR
            </span>
          </div>
          <span 
            className="text-white text-2xl font-bold tracking-wide"
            style={{ fontFamily: 'Oswald, sans-serif' }}
          >
            PITCHRANK
          </span>
        </div>
        <div className="text-right">
          <span className="text-white/60 text-lg">{state} • {ageGroup} {gender}</span>
        </div>
      </div>
      
      <div className="w-full h-px bg-[#0B5345] mb-8" />
      
      {/* Main Content */}
      <div className={`flex-1 flex flex-col ${isStory ? 'justify-center' : 'justify-center'}`}>
        {/* Rank */}
        <div className="text-center mb-6">
          <div className="flex items-center justify-center gap-4">
            {medal && <span className="text-7xl">{medal}</span>}
            <span 
              className="text-[#F4D03F] font-bold leading-none"
              style={{ 
                fontFamily: 'Oswald, sans-serif',
                fontSize: isStory ? '220px' : '180px',
              }}
            >
              #{rank}
            </span>
          </div>
        </div>
        
        {/* Team Name */}
        <div className="text-center mb-8">
          <h1 
            className="text-white font-bold leading-tight mb-2"
            style={{ 
              fontFamily: 'Oswald, sans-serif',
              fontSize: teamName.length > 20 ? '48px' : '56px',
              textTransform: 'uppercase',
              letterSpacing: '0.02em',
            }}
          >
            {teamName}
          </h1>
          {clubName && (
            <p className="text-white/70 text-2xl">{clubName}</p>
          )}
        </div>
        
        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-6 max-w-3xl mx-auto w-full">
          {/* PowerScore */}
          <div className="bg-[#0B5345] rounded-2xl p-6 text-center">
            <span className="text-white/60 text-sm uppercase tracking-wide block mb-2">
              PowerScore
            </span>
            <span 
              className="text-[#F4D03F] text-5xl font-bold"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              {powerScore.toLocaleString()}
            </span>
          </div>
          
          {/* Record */}
          <div className="bg-[#0B5345] rounded-2xl p-6 text-center">
            <span className="text-white/60 text-sm uppercase tracking-wide block mb-2">
              Record
            </span>
            <span 
              className="text-white text-5xl font-bold"
              style={{ fontFamily: 'Oswald, sans-serif' }}
            >
              {record}
            </span>
          </div>
          
          {/* Movement */}
          <div className="bg-[#0B5345] rounded-2xl p-6 text-center">
            <span className="text-white/60 text-sm uppercase tracking-wide block mb-2">
              This Week
            </span>
            <span 
              className="text-5xl font-bold flex items-center justify-center gap-2"
              style={{ 
                fontFamily: 'Oswald, sans-serif',
                color: movementInfo.color,
              }}
            >
              {movementInfo.icon} {movementInfo.text}
            </span>
          </div>
        </div>
      </div>
      
      {/* Footer */}
      <div className="mt-auto pt-8">
        <div className="w-full h-px bg-[#0B5345] mb-6" />
        <div className="flex items-center justify-between">
          <span className="text-white/60 text-lg">
            Based on {new Date().toLocaleDateString('en-US', { month: 'short', year: 'numeric' })} data
          </span>
          <span className="text-white/60 text-lg">pitchrank.com</span>
        </div>
      </div>
    </div>
  );
}

export default RankingCard;
