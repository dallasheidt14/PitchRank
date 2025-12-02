'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS, PLATFORM_DIMENSIONS } from './InfographicWrapper';
import type { RankingRow } from '@/types/RankingRow';

interface MoverTeam extends RankingRow {
  change: number;
  rank?: number;
}

interface BiggestMoversPreviewProps {
  climbers: MoverTeam[];
  fallers: MoverTeam[];
  platform: Platform;
  scale?: number;
  generatedDate?: string;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
}

export const BiggestMoversPreview = forwardRef<HTMLDivElement, BiggestMoversPreviewProps>(
  ({ climbers, fallers, platform, scale = 0.5, generatedDate, ageGroup, gender, regionName }, ref) => {
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    // Font sizes
    const logoSize = isVertical ? 48 : isSquare ? 44 : 40;
    const titleSize = isVertical ? 42 : isSquare ? 36 : 32;
    const sectionTitleSize = isVertical ? 24 : isSquare ? 20 : 18;
    const teamNameSize = isVertical ? 18 : isSquare ? 16 : 14;
    const changeSize = isVertical ? 28 : isSquare ? 24 : 20;
    const smallTextSize = isVertical ? 14 : isSquare ? 12 : 11;
    const padding = isVertical ? 50 : isSquare ? 45 : 40;

    const formatDate = (date?: string) => {
      const d = date ? new Date(date) : new Date();
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    };

    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';

    const MoverRow = ({ team, isClimber }: { team: MoverTeam; isClimber: boolean }) => (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: isVertical ? '12px 14px' : '10px 12px',
          background: isClimber ? 'rgba(76, 175, 80, 0.15)' : 'rgba(244, 67, 54, 0.15)',
          borderRadius: '8px',
          borderLeft: `4px solid ${isClimber ? '#4CAF50' : '#F44336'}`,
          marginBottom: isVertical ? '10px' : '8px',
        }}
      >
        <div
          style={{
            fontFamily: "Oswald, 'Arial Black', sans-serif",
            fontSize: `${changeSize}px`,
            fontWeight: 800,
            color: isClimber ? '#4CAF50' : '#F44336',
            marginRight: '12px',
            minWidth: isVertical ? '50px' : '40px',
          }}
        >
          {isClimber ? '↑' : '↓'}{Math.abs(team.change)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${teamNameSize}px`,
              fontWeight: 600,
              color: BRAND_COLORS.brightWhite,
              textTransform: 'uppercase',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {team.team_name}
          </div>
          <div
            style={{
              fontFamily: "'DM Sans', Arial, sans-serif",
              fontSize: `${smallTextSize}px`,
              color: '#888888',
            }}
          >
            Now #{team.rank || '?'}
          </div>
        </div>
      </div>
    );

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
          {/* Logo */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginBottom: 16,
            }}
          >
            <div
              style={{
                position: 'relative',
                fontFamily: "Oswald, 'Arial Black', sans-serif",
                fontSize: `${logoSize}px`,
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: '3px',
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
          </div>

          {/* Title */}
          <div
            style={{
              textAlign: 'center',
              marginBottom: 8,
            }}
          >
            <div
              style={{
                fontFamily: "Oswald, 'Arial Black', sans-serif",
                fontSize: `${titleSize}px`,
                fontWeight: 700,
                color: BRAND_COLORS.electricYellow,
              }}
            >
              BIGGEST MOVERS
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize}px`,
                color: '#AAAAAA',
                marginTop: 4,
              }}
            >
              {ageGroup.toUpperCase()} {genderLabel} • {regionName.toUpperCase()}
            </div>
          </div>

          {/* Two Columns */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              gap: isVertical ? '20px' : '16px',
              marginTop: isVertical ? 24 : 16,
            }}
          >
            {/* Climbers Column */}
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${sectionTitleSize}px`,
                  fontWeight: 700,
                  color: '#4CAF50',
                  marginBottom: isVertical ? 12 : 10,
                }}
              >
                🔥 RISING
              </div>
              {climbers.slice(0, 5).map((team, i) => (
                <MoverRow key={team.team_id_master || i} team={team} isClimber={true} />
              ))}
            </div>

            {/* Fallers Column */}
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${sectionTitleSize}px`,
                  fontWeight: 700,
                  color: '#F44336',
                  marginBottom: isVertical ? 12 : 10,
                }}
              >
                📉 FALLING
              </div>
              {fallers.slice(0, 5).map((team, i) => (
                <MoverRow key={team.team_id_master || i} team={team} isClimber={false} />
              ))}
            </div>
          </div>

          {/* Footer */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: 16,
              borderTop: '2px solid #1a4a3f',
              marginTop: 16,
            }}
          >
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize}px`,
                color: '#999999',
              }}
            >
              Week of {formatDate(generatedDate)}
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize}px`,
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

BiggestMoversPreview.displayName = 'BiggestMoversPreview';

export default BiggestMoversPreview;
