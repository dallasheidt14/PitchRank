'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS, PLATFORM_DIMENSIONS } from './InfographicWrapper';
import type { RankingRow } from '@/types/RankingRow';

interface U12Top10InfographicProps {
  teams: RankingRow[];
  platform: Platform;
  scale?: number;
  generatedDate?: string;
}

/**
 * Infographic displaying the top 10 U12 Male teams nationally.
 * Optimized for social media sharing on Twitter, Instagram, and Facebook.
 */
export const U12Top10Infographic = forwardRef<HTMLDivElement, U12Top10InfographicProps>(
  ({ teams, platform, scale = 0.5, generatedDate }, ref) => {
    const top10 = teams.slice(0, 10);
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    // Scale factors based on platform
    const titleSize = isVertical ? 72 : isSquare ? 64 : 56;
    const subtitleSize = isVertical ? 32 : isSquare ? 28 : 24;
    const rankSize = isVertical ? 36 : isSquare ? 32 : 28;
    const teamNameSize = isVertical ? 28 : isSquare ? 24 : 20;
    const statsSize = isVertical ? 20 : isSquare ? 18 : 16;
    const rowGap = isVertical ? 12 : isSquare ? 8 : 6;
    const padding = isVertical ? 60 : isSquare ? 50 : 40;

    const formatDate = (date?: string) => {
      const d = date ? new Date(date) : new Date();
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    };

    return (
      <InfographicWrapper ref={ref} platform={platform} scale={scale}>
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            padding: `${padding}px`,
            color: BRAND_COLORS.brightWhite,
          }}
        >
          {/* Header Section */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              marginBottom: isVertical ? 48 : 32,
            }}
          >
            {/* Logo */}
            <div
              style={{
                fontFamily: "'Oswald', sans-serif",
                fontSize: `${titleSize}px`,
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: '3px',
                display: 'flex',
                alignItems: 'center',
                marginBottom: 16,
              }}
            >
              <span
                style={{
                  width: '8px',
                  height: `${titleSize * 1.2}px`,
                  background: BRAND_COLORS.electricYellow,
                  marginRight: '16px',
                  transform: 'skewX(-10deg)',
                }}
              />
              <span>PITCH</span>
              <span style={{ color: BRAND_COLORS.electricYellow }}>RANK</span>
            </div>

            {/* Title */}
            <div
              style={{
                fontFamily: "'Oswald', sans-serif",
                fontSize: `${subtitleSize}px`,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '2px',
                color: BRAND_COLORS.electricYellow,
                textAlign: 'center',
              }}
            >
              TOP 10 U12 BOYS - NATIONAL
            </div>

            {/* Date */}
            <div
              style={{
                fontFamily: "'DM Sans', sans-serif",
                fontSize: `${statsSize}px`,
                color: 'rgba(255, 255, 255, 0.7)',
                marginTop: 8,
              }}
            >
              Rankings as of {formatDate(generatedDate)}
            </div>
          </div>

          {/* Rankings List */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              gap: `${rowGap}px`,
            }}
          >
            {top10.map((team, index) => (
              <RankingRow
                key={team.team_id_master}
                rank={index + 1}
                team={team}
                rankSize={rankSize}
                teamNameSize={teamNameSize}
                statsSize={statsSize}
                isVertical={isVertical}
              />
            ))}
          </div>

          {/* Footer */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: isVertical ? 32 : 24,
              paddingTop: 16,
              borderTop: `2px solid rgba(255, 255, 255, 0.1)`,
            }}
          >
            <div
              style={{
                fontFamily: "'DM Sans', sans-serif",
                fontSize: `${statsSize - 2}px`,
                color: 'rgba(255, 255, 255, 0.6)',
              }}
            >
              pitchrank.io
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', sans-serif",
                fontSize: `${statsSize - 2}px`,
                color: BRAND_COLORS.electricYellow,
              }}
            >
              #YouthSoccer #U12Soccer
            </div>
          </div>
        </div>
      </InfographicWrapper>
    );
  }
);

U12Top10Infographic.displayName = 'U12Top10Infographic';

interface RankingRowProps {
  rank: number;
  team: RankingRow;
  rankSize: number;
  teamNameSize: number;
  statsSize: number;
  isVertical: boolean;
}

function RankingRow({ rank, team, rankSize, teamNameSize, statsSize, isVertical }: RankingRowProps) {
  const isTopThree = rank <= 3;
  const medalColors: Record<number, string> = {
    1: '#FFD700', // Gold
    2: '#C0C0C0', // Silver
    3: '#CD7F32', // Bronze
  };

  const getRecord = () => {
    const wins = team.total_wins ?? team.wins ?? 0;
    const losses = team.total_losses ?? team.losses ?? 0;
    const draws = team.total_draws ?? team.draws ?? 0;
    return `${wins}-${losses}-${draws}`;
  };

  const getPowerScore = () => {
    return team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: isVertical ? '16px 20px' : '12px 16px',
        background: isTopThree
          ? `linear-gradient(90deg, rgba(244, 208, 63, 0.2) 0%, rgba(244, 208, 63, 0.05) 100%)`
          : 'rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        borderLeft: isTopThree ? `4px solid ${medalColors[rank]}` : '4px solid transparent',
      }}
    >
      {/* Rank */}
      <div
        style={{
          width: isVertical ? '60px' : '50px',
          fontFamily: "'Oswald', sans-serif",
          fontSize: `${rankSize}px`,
          fontWeight: 800,
          color: isTopThree ? medalColors[rank] : BRAND_COLORS.brightWhite,
          textAlign: 'center',
        }}
      >
        {rank}
      </div>

      {/* Team Info */}
      <div
        style={{
          flex: 1,
          marginLeft: isVertical ? 16 : 12,
          minWidth: 0,
        }}
      >
        <div
          style={{
            fontFamily: "'Oswald', sans-serif",
            fontSize: `${teamNameSize}px`,
            fontWeight: 600,
            color: BRAND_COLORS.brightWhite,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {team.team_name}
        </div>
        <div
          style={{
            fontFamily: "'DM Sans', sans-serif",
            fontSize: `${statsSize - 2}px`,
            color: 'rgba(255, 255, 255, 0.6)',
            marginTop: 2,
          }}
        >
          {team.club_name ? `${team.club_name} | ` : ''}{team.state || 'N/A'}
        </div>
      </div>

      {/* Stats */}
      <div
        style={{
          display: 'flex',
          gap: isVertical ? '24px' : '16px',
          alignItems: 'center',
        }}
      >
        {/* Record */}
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: `${statsSize}px`,
              fontWeight: 600,
              color: BRAND_COLORS.brightWhite,
            }}
          >
            {getRecord()}
          </div>
          <div
            style={{
              fontFamily: "'DM Sans', sans-serif",
              fontSize: `${statsSize - 4}px`,
              color: 'rgba(255, 255, 255, 0.5)',
              textTransform: 'uppercase',
            }}
          >
            W-L-D
          </div>
        </div>

        {/* Power Score */}
        <div style={{ textAlign: 'center', minWidth: isVertical ? '70px' : '60px' }}>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: `${statsSize}px`,
              fontWeight: 700,
              color: BRAND_COLORS.electricYellow,
            }}
          >
            {getPowerScore()}
          </div>
          <div
            style={{
              fontFamily: "'DM Sans', sans-serif",
              fontSize: `${statsSize - 4}px`,
              color: 'rgba(255, 255, 255, 0.5)',
              textTransform: 'uppercase',
            }}
          >
            Score
          </div>
        </div>
      </div>
    </div>
  );
}

export default U12Top10Infographic;
