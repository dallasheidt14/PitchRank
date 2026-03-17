'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

function PowerScoreContent() {
  const searchParams = useSearchParams();
  const variant = (searchParams.get('variant') as 'square' | 'portrait') || 'square';
  const isSquare = variant === 'square';
  
  return (
    <div 
      data-infographic="powerscore"
      className={`text-white relative overflow-hidden ${
        isSquare ? 'w-[1080px] h-[1080px] p-12' : 'w-[1080px] h-[1350px] p-14'
      }`}
      style={{ 
        fontFamily: 'DM Sans, sans-serif',
        background: 'linear-gradient(135deg, #0B5345 0%, #052E27 100%)',
      }}
    >
      {/* Subtle grid pattern overlay */}
      <div 
        className="absolute inset-0 opacity-30 pointer-events-none"
        style={{
          backgroundImage: `repeating-linear-gradient(
            0deg,
            rgba(255, 255, 255, 0.03) 0px,
            transparent 1px,
            transparent 2px,
            rgba(255, 255, 255, 0.03) 3px
          )`,
        }}
      />

      {/* Content */}
      <div className="relative z-10 h-full flex flex-col">
        {/* Logo */}
        <div className="flex items-center gap-2 mb-6">
          <div className="relative pl-5">
            <div 
              className="absolute w-1.5 h-full bg-[#F4D03F] left-0 top-0"
              style={{ transform: 'skewX(-10deg)' }}
            />
            <span 
              className="text-4xl font-extrabold tracking-wider text-white"
              style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
            >
              PITCHRANK
            </span>
          </div>
        </div>

        {/* Header */}
        <div className="mb-8">
          <h1 
            className="text-[#F4D03F] text-5xl font-extrabold tracking-wide mb-2"
            style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
          >
            HOW POWERSCORE WORKS
          </h1>
          <p className="text-white/80 text-xl">
            A two-part rating system that looks at every game from multiple angles
          </p>
        </div>

        {/* Main Content */}
        <div className="flex-1 flex flex-col justify-center gap-6">
          
          {/* Part 1: Core Rating */}
          <div className="bg-white/10 backdrop-blur rounded-2xl p-6">
            <h2 
              className="text-[#F4D03F] text-2xl font-bold mb-4 flex items-center gap-3"
              style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
            >
              <span className="text-3xl">🧠</span> CORE RATING ENGINE
            </h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>Quality of Opponents</span>
              </div>
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>Strength of Schedule</span>
              </div>
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>How Competitive You Were</span>
              </div>
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>Offensive & Defensive Patterns</span>
              </div>
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>Recency Weighting</span>
              </div>
              <div className="flex items-center gap-2 text-lg text-white">
                <span className="text-[#F4D03F]">✓</span>
                <span>Stability Over Time</span>
              </div>
            </div>
          </div>

          {/* Part 2: ML Layer */}
          <div className="bg-white/10 backdrop-blur rounded-2xl p-6">
            <h2 
              className="text-[#F4D03F] text-2xl font-bold mb-4 flex items-center gap-3"
              style={{ fontFamily: 'Oswald, sans-serif', textTransform: 'uppercase' }}
            >
              <span className="text-3xl">⚡</span> MACHINE LEARNING LAYER
            </h2>
            <p className="text-lg text-white/90 mb-3">
              Evaluates every game: <span className="text-[#F4D03F] font-semibold">"Was this result expected, or surprising?"</span>
            </p>
            <div className="flex gap-4">
              <div className="flex-1 bg-green-500/20 rounded-lg p-3 text-center">
                <span className="text-green-400 font-semibold">▲ Overperform</span>
                <p className="text-sm text-white/70">Teams climbing</p>
              </div>
              <div className="flex-1 bg-red-500/20 rounded-lg p-3 text-center">
                <span className="text-red-400 font-semibold">▼ Underperform</span>
                <p className="text-sm text-white/70">System takes notice</p>
              </div>
            </div>
          </div>

          {/* Key Insight */}
          <div className="bg-[#F4D03F] text-[#052E27] rounded-2xl p-5 text-center">
            <p className="text-xl font-bold" style={{ fontFamily: 'Oswald, sans-serif' }}>
              THE RESULT: A TRUE, DATA-DRIVEN MEASURE OF TEAM STRENGTH
            </p>
            <p className="text-lg mt-1">Not just a tally of wins and losses</p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between mt-6 pt-4 border-t border-white/20">
          <div className="text-white/60 text-lg">
            The fairest youth soccer rankings in the country
          </div>
          <div className="text-white/60 text-lg">
            pitchrank.io
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PowerScoreRenderPage() {
  return (
    <html>
      <head>
        <link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;600;700;800&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet" />
        <style>{`
          body { margin: 0; padding: 0; background: transparent; }
        `}</style>
      </head>
      <body>
        <Suspense fallback={<div>Loading...</div>}>
          <PowerScoreContent />
        </Suspense>
      </body>
    </html>
  );
}
