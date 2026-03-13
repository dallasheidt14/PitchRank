'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * PitchRankAnimation — "The Rank Rise"
 *
 * A branded hero animation that tells PitchRank's story visually:
 * 1. Soccer pitch lines draw across a dark green field
 * 2. Ranking bars slide in and stack like a leaderboard
 * 3. PowerScore numbers count up
 * 4. The "PR" mark slashes in with the signature yellow accent
 *
 * Pure CSS animations + lightweight JS for the score counter.
 * Respects prefers-reduced-motion.
 */

interface RankEntry {
  rank: number;
  name: string;
  score: number;
  delay: number;
  barWidth: number;
}

const TEAMS: RankEntry[] = [
  { rank: 1, name: 'Solar SC', score: 0.97, delay: 1.2, barWidth: 97 },
  { rank: 2, name: 'FC Dallas', score: 0.94, delay: 1.4, barWidth: 94 },
  { rank: 3, name: 'Surf SC', score: 0.91, delay: 1.6, barWidth: 91 },
  { rank: 4, name: 'Lonestar SC', score: 0.87, delay: 1.8, barWidth: 87 },
  { rank: 5, name: 'Crossfire', score: 0.84, delay: 2.0, barWidth: 84 },
];

function AnimatedScore({ target, delay }: { target: number; delay: number }) {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number>(0);
  const startRef = useRef<number>(0);

  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) {
      setValue(target);
      return;
    }

    const timeout = setTimeout(() => {
      const duration = 800;
      const animate = (timestamp: number) => {
        if (!startRef.current) startRef.current = timestamp;
        const elapsed = timestamp - startRef.current;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // cubic ease-out
        setValue(parseFloat((target * eased).toFixed(2)));
        if (progress < 1) {
          rafRef.current = requestAnimationFrame(animate);
        }
      };
      rafRef.current = requestAnimationFrame(animate);
    }, delay * 1000);

    return () => {
      clearTimeout(timeout);
      cancelAnimationFrame(rafRef.current);
    };
  }, [target, delay]);

  return <span className="font-mono tabular-nums">{value.toFixed(2)}</span>;
}

export function PitchRankAnimation() {
  const [isVisible, setIsVisible] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.2 }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-xl bg-[#052E27] shadow-2xl"
      style={{ aspectRatio: '16/9', maxHeight: '560px' }}
    >
      {/* === LAYER 1: Pitch Lines === */}
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 800 450"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        {/* Center line */}
        <line
          x1="400" y1="0" x2="400" y2="450"
          stroke="#0B5345"
          strokeWidth="2"
          className={isVisible ? 'pitchrank-line-draw' : ''}
          style={{ strokeDasharray: 450, strokeDashoffset: isVisible ? 0 : 450 }}
        />
        {/* Center circle */}
        <circle
          cx="400" cy="225" r="60"
          stroke="#0B5345"
          strokeWidth="2"
          fill="none"
          className={isVisible ? 'pitchrank-circle-draw' : ''}
          style={{ strokeDasharray: 377, strokeDashoffset: isVisible ? 0 : 377 }}
        />
        {/* Left penalty box */}
        <rect
          x="0" y="125" width="120" height="200"
          stroke="#0B5345"
          strokeWidth="2"
          fill="none"
          className={isVisible ? 'pitchrank-box-draw' : ''}
          style={{ strokeDasharray: 640, strokeDashoffset: isVisible ? 0 : 640 }}
        />
        {/* Right penalty box */}
        <rect
          x="680" y="125" width="120" height="200"
          stroke="#0B5345"
          strokeWidth="2"
          fill="none"
          className={isVisible ? 'pitchrank-box-draw' : ''}
          style={{ strokeDasharray: 640, strokeDashoffset: isVisible ? 0 : 640 }}
        />
        {/* Border */}
        <rect
          x="1" y="1" width="798" height="448"
          stroke="#0B5345"
          strokeWidth="2"
          fill="none"
          className={isVisible ? 'pitchrank-border-draw' : ''}
          style={{ strokeDasharray: 2492, strokeDashoffset: isVisible ? 0 : 2492 }}
        />
      </svg>

      {/* === LAYER 2: Gradient Overlays === */}
      <div className="absolute inset-0 bg-gradient-to-r from-[#052E27] via-[#052E27]/80 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#052E27] via-transparent to-[#052E27]/40" />

      {/* === LAYER 3: Leaderboard Rankings === */}
      <div className="absolute left-6 sm:left-10 top-1/2 -translate-y-1/2 w-[55%] sm:w-[50%] space-y-2 sm:space-y-3">
        {/* Section label */}
        <div
          className={`flex items-center gap-2 mb-3 sm:mb-4 transition-all duration-700 ${
            isVisible ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-8'
          }`}
          style={{ transitionDelay: '0.8s' }}
        >
          <div className="w-1 h-5 sm:h-6 bg-[#F4D03F] -skew-x-12" />
          <span className="font-display text-[10px] sm:text-xs tracking-[0.2em] text-[#F4D03F]/80 uppercase">
            National Rankings
          </span>
        </div>

        {TEAMS.map((team) => (
          <div
            key={team.rank}
            className={`flex items-center gap-2 sm:gap-3 transition-all duration-700 ease-out ${
              isVisible ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-12'
            }`}
            style={{ transitionDelay: `${team.delay}s` }}
          >
            {/* Rank number */}
            <span
              className={`font-display text-lg sm:text-2xl font-bold min-w-[1.5rem] sm:min-w-[2rem] text-right ${
                team.rank === 1
                  ? 'text-[#F4D03F]'
                  : team.rank === 2
                    ? 'text-[#C0C0C0]'
                    : team.rank === 3
                      ? 'text-[#CD7F32]'
                      : 'text-white/50'
              }`}
            >
              {team.rank}
            </span>

            {/* Bar + info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between mb-0.5 sm:mb-1">
                <span className="font-sans text-[11px] sm:text-sm font-medium text-white/90 truncate">
                  {team.name}
                </span>
                <span className="text-[10px] sm:text-xs text-[#F4D03F] ml-2 shrink-0">
                  {isVisible && <AnimatedScore target={team.score} delay={team.delay} />}
                </span>
              </div>
              {/* PowerScore bar */}
              <div className="h-1.5 sm:h-2 rounded-full bg-white/10 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all ease-out"
                  style={{
                    width: isVisible ? `${team.barWidth}%` : '0%',
                    transitionDuration: '1s',
                    transitionDelay: `${team.delay + 0.3}s`,
                    background:
                      team.rank === 1
                        ? 'linear-gradient(90deg, #0B5345, #F4D03F)'
                        : team.rank <= 3
                          ? 'linear-gradient(90deg, #0B5345, #0B5345cc)'
                          : 'linear-gradient(90deg, #0B534580, #0B534540)',
                  }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* === LAYER 4: PR Logo Mark === */}
      <div
        className={`absolute right-6 sm:right-12 top-1/2 -translate-y-1/2 transition-all duration-1000 ease-out ${
          isVisible ? 'opacity-100 scale-100 translate-x-0' : 'opacity-0 scale-75 translate-x-8'
        }`}
        style={{ transitionDelay: '0.5s' }}
      >
        <div className="relative">
          {/* Glow backdrop */}
          <div
            className={`absolute inset-0 rounded-2xl transition-opacity duration-1000 ${
              isVisible ? 'opacity-100' : 'opacity-0'
            }`}
            style={{
              transitionDelay: '1.5s',
              background: 'radial-gradient(circle, #F4D03F15 0%, transparent 70%)',
              transform: 'scale(2)',
            }}
          />

          {/* Logo container */}
          <div className="relative w-24 h-24 sm:w-36 sm:h-36 md:w-44 md:h-44 flex items-center justify-center">
            <svg
              viewBox="0 0 200 200"
              className="w-full h-full"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Background rounded square */}
              <rect
                x="10" y="10" width="180" height="180" rx="32"
                fill="#052E27"
                stroke="#0B5345"
                strokeWidth="2"
                className={isVisible ? 'pitchrank-logo-bg' : ''}
                style={{ opacity: isVisible ? 1 : 0 }}
              />

              {/* PR Text */}
              <text
                x="100" y="128"
                fontFamily="Oswald, sans-serif"
                fontWeight="700"
                fontSize="88"
                fill="#F4D03F"
                textAnchor="middle"
                letterSpacing="-4"
                className={`transition-opacity duration-700 ${isVisible ? 'opacity-100' : 'opacity-0'}`}
                style={{ transitionDelay: '0.8s' }}
              >
                PR
              </text>

              {/* Signature diagonal slash */}
              <rect
                x="38" y="155" width="124" height="8" rx="4"
                fill="#F4D03F"
                transform="skewX(-10)"
                className={isVisible ? 'pitchrank-slash-reveal' : ''}
                style={{
                  transformOrigin: 'left center',
                  transform: `skewX(-10) scaleX(${isVisible ? 1 : 0})`,
                }}
              />
            </svg>
          </div>

          {/* Tagline under logo */}
          <p
            className={`text-center font-display text-[9px] sm:text-xs tracking-[0.25em] text-white/60 uppercase mt-2 transition-all duration-700 ${
              isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
            }`}
            style={{ transitionDelay: '2.5s' }}
          >
            Data-Driven Rankings
          </p>
        </div>
      </div>

      {/* === LAYER 5: Floating Accent Particles === */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
        {[...Array(6)].map((_, i) => (
          <div
            key={i}
            className={`absolute rounded-full bg-[#F4D03F] pitchrank-particle ${
              isVisible ? 'opacity-100' : 'opacity-0'
            }`}
            style={{
              width: `${2 + (i % 3)}px`,
              height: `${2 + (i % 3)}px`,
              left: `${15 + i * 14}%`,
              top: `${20 + (i % 4) * 15}%`,
              animationDelay: `${2 + i * 0.5}s`,
              animationDuration: `${3 + (i % 3)}s`,
            }}
          />
        ))}
      </div>

      {/* === LAYER 6: Bottom Stats Bar === */}
      <div
        className={`absolute bottom-0 left-0 right-0 flex items-center justify-center gap-4 sm:gap-8 py-2.5 sm:py-3 bg-[#0B5345]/80 backdrop-blur-sm border-t border-[#0B5345] transition-all duration-700 ${
          isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'
        }`}
        style={{ transitionDelay: '2.8s' }}
      >
        {[
          { label: 'Games Analyzed', value: '250K+' },
          { label: 'Teams Ranked', value: '25K+' },
          { label: 'States', value: '50' },
        ].map((stat, i) => (
          <div key={stat.label} className="text-center">
            <div
              className={`font-display text-sm sm:text-lg font-bold text-[#F4D03F] transition-all duration-500 ${
                isVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-50'
              }`}
              style={{ transitionDelay: `${3 + i * 0.2}s` }}
            >
              {stat.value}
            </div>
            <div className="text-[8px] sm:text-[10px] text-white/50 uppercase tracking-wider font-sans">
              {stat.label}
            </div>
          </div>
        ))}
      </div>

      {/* === Inline Keyframe Styles === */}
      <style jsx>{`
        .pitchrank-line-draw,
        .pitchrank-circle-draw,
        .pitchrank-box-draw,
        .pitchrank-border-draw {
          transition: stroke-dashoffset 2s ease-out;
        }
        .pitchrank-circle-draw {
          transition-delay: 0.5s;
        }
        .pitchrank-box-draw {
          transition-delay: 0.3s;
        }
        .pitchrank-border-draw {
          transition-delay: 0s;
        }
        .pitchrank-logo-bg {
          transition: opacity 0.5s ease-out 0.5s;
        }
        .pitchrank-slash-reveal {
          transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 1.2s;
        }
        @keyframes pitchrank-float {
          0%, 100% {
            transform: translateY(0) scale(1);
            opacity: 0.3;
          }
          50% {
            transform: translateY(-20px) scale(1.5);
            opacity: 0.6;
          }
        }
        .pitchrank-particle {
          animation: pitchrank-float 3s ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          .pitchrank-line-draw,
          .pitchrank-circle-draw,
          .pitchrank-box-draw,
          .pitchrank-border-draw,
          .pitchrank-logo-bg,
          .pitchrank-slash-reveal {
            transition-duration: 0.01ms !important;
            transition-delay: 0ms !important;
          }
          .pitchrank-particle {
            animation: none !important;
            opacity: 0.3 !important;
          }
        }
      `}</style>
    </div>
  );
}
