'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS, PLATFORM_DIMENSIONS } from './InfographicWrapper';
import type { RankingRow } from '@/types/RankingRow';

interface TeamSpotlightPreviewProps {
  team: RankingRow & { rank?: number };
  platform: Platform;
  scale?: number;
  generatedDate?: string;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
  headline?: string;
}

export const TeamSpotlightPreview = forwardRef<HTMLDivElement, TeamSpotlightPreviewProps>(
  ({ team, platform, scale = 0.5, generatedDate, ageGroup, gender, regionName, headline = 'TEAM SPOTLIGHT' }, ref) => {
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    // Font sizes based on platform
    const logoSize = isVertical ? 48 : isSquare ? 44 : 40;
    const headlineSize = isVertical ? 36 : isSquare ? 32 : 28;
    const teamNameSize = isVertical ? 48 : isSquare ? 42 : 36;
    const statLabelSize = isVertical ? 16 : isSquare ? 14 : 12;
    const statValueSize = isVertical ? 42 : isSquare ? 36 : 32;
    const smallTextSize = isVertical ? 18 : isSquare ? 16 : 14;
    const badgeSize = isVertical ? 100 : isSquare ? 90 : 80;
    const padding = isVertical ? 60 : isSquare ? 50 : 40;

    const formatDate = (date?: string) => {
      const d = date ? new Date(date) : new Date();
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    };

    const getRecord = () => {
      const wins = team.total_wins ?? team.wins ?? 0;
      const losses = team.total_losses ?? team.losses ?? 0;
      const draws = team.total_draws ?? team.draws ?? 0;
      return `${wins}-${losses}-${draws}`;
    };

    const getWinPct = () => {
      const wins = team.total_wins ?? team.wins ?? 0;
      const losses = team.total_losses ?? team.losses ?? 0;
      const draws = team.total_draws ?? team.draws ?? 0;
      const total = wins + losses + draws;
      if (total === 0) return '0%';
      return `${Math.round((wins / total) * 100)}%`;
    };

    const getTotalGames = () => {
      const wins = team.total_wins ?? team.wins ?? 0;
      const losses = team.total_losses ?? team.losses ?? 0;
      const draws = team.total_draws ?? team.draws ?? 0;
      return wins + losses + draws;
    };

    const getPowerScore = () => {
      return team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
    };

    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
    const categoryText = `${ageGroup.toUpperCase()} ${genderLabel} • ${regionName.toUpperCase()}`;

    const stats = [
      { label: 'RECORD', value: getRecord(), highlight: false },
      { label: 'POWER SCORE', value: getPowerScore(), highlight: true },
      { label: 'WIN %', value: getWinPct(), highlight: false },
      { label: 'GAMES', value: String(getTotalGames()), highlight: false },
    ];

    return (
      <InfographicWrapper ref={ref} platform={platform} scale={scale}>
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: `${padding}px`,
            color: BRAND_COLORS.brightWhite,
          }}
        >
          {/* Logo */}
          <div
            style={{
              position: 'relative',
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${logoSize}px`,
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '3px',
              marginBottom: 8,
            }}
          >
            <span
              style={{
                position: 'absolute',
                left: '-20px',
                top: '50%',
                transform: 'translateY(-50%) skewX(-12deg)',
                width: '8px',
                height: '70%',
                background: BRAND_COLORS.electricYellow,
              }}
            />
            <span style={{ color: BRAND_COLORS.brightWhite }}>PITCH</span>
            <span style={{ color: BRAND_COLORS.electricYellow }}>RANK</span>
          </div>

          {/* Headline */}
          <div
            style={{
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${headlineSize}px`,
              fontWeight: 700,
              color: BRAND_COLORS.electricYellow,
              marginBottom: isVertical ? 40 : 30,
            }}
          >
            {headline}
          </div>

          {/* Rank Badge */}
          <div
            style={{
              width: `${badgeSize}px`,
              height: `${badgeSize}px`,
              borderRadius: '50%',
              background: BRAND_COLORS.electricYellow,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: isVertical ? 30 : 25,
            }}
          >
            <span
              style={{
                fontFamily: "Oswald, 'Arial Black', sans-serif",
                fontSize: `${badgeSize * 0.45}px`,
                fontWeight: 800,
                color: BRAND_COLORS.darkGreen,
              }}
            >
              #{team.rank || 1}
            </span>
          </div>

          {/* Team Name */}
          <div
            style={{
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${teamNameSize}px`,
              fontWeight: 800,
              textTransform: 'uppercase',
              textAlign: 'center',
              lineHeight: 1.1,
              marginBottom: 8,
              maxWidth: dimensions.width - padding * 2,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {team.team_name}
          </div>

          {/* Club & Location */}
          <div
            style={{
              fontFamily: "'DM Sans', Arial, sans-serif",
              fontSize: `${smallTextSize}px`,
              color: '#AAAAAA',
              marginBottom: isVertical ? 50 : 40,
            }}
          >
            {team.club_name || ''} | {team.state || 'N/A'}
          </div>

          {/* Stats Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: isVertical ? '16px' : '12px',
              marginBottom: isVertical ? 40 : 30,
            }}
          >
            {stats.map((stat) => (
              <div
                key={stat.label}
                style={{
                  background: 'rgba(255, 255, 255, 0.08)',
                  borderRadius: '8px',
                  padding: isVertical ? '20px 30px' : '16px 24px',
                  textAlign: 'center',
                  minWidth: isVertical ? '160px' : '140px',
                }}
              >
                <div
                  style={{
                    fontFamily: "Oswald, 'Arial Black', sans-serif",
                    fontSize: `${statValueSize}px`,
                    fontWeight: 700,
                    color: stat.highlight ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite,
                    lineHeight: 1,
                  }}
                >
                  {stat.value}
                </div>
                <div
                  style={{
                    fontFamily: "'DM Sans', Arial, sans-serif",
                    fontSize: `${statLabelSize}px`,
                    color: '#888888',
                    marginTop: 4,
                  }}
                >
                  {stat.label}
                </div>
              </div>
            ))}
          </div>

          {/* Category Tag */}
          <div
            style={{
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${smallTextSize}px`,
              fontWeight: 600,
              color: BRAND_COLORS.electricYellow,
            }}
          >
            {categoryText}
          </div>

          {/* Spacer */}
          <div style={{ flex: 1 }} />

          {/* Footer */}
          <div
            style={{
              width: '100%',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: 16,
              borderTop: '2px solid #1a4a3f',
            }}
          >
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize - 2}px`,
                color: '#999999',
              }}
            >
              {formatDate(generatedDate)}
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize - 2}px`,
                color: BRAND_COLORS.electricYellow,
              }}
            >
              pitchrank.io
            </div>
          </div>
        </div>
      </InfographicWrapper>
    );
  }
);

TeamSpotlightPreview.displayName = 'TeamSpotlightPreview';

export default TeamSpotlightPreview;
