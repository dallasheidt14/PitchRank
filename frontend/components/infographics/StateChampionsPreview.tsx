'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS, PLATFORM_DIMENSIONS } from './InfographicWrapper';
import type { RankingRow } from '@/types/RankingRow';

interface StateChampion {
  state: string;
  team: RankingRow;
}

interface StateChampionsPreviewProps {
  champions: StateChampion[];
  platform: Platform;
  scale?: number;
  generatedDate?: string;
  ageGroup: string;
  gender: 'M' | 'F';
}

export const StateChampionsPreview = forwardRef<HTMLDivElement, StateChampionsPreviewProps>(
  ({ champions, platform, scale = 0.5, generatedDate, ageGroup, gender }, ref) => {
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    // Font sizes
    const logoSize = isVertical ? 44 : isSquare ? 40 : 36;
    const titleSize = isVertical ? 36 : isSquare ? 32 : 28;
    const stateSize = isVertical ? 18 : isSquare ? 16 : 14;
    const teamNameSize = isVertical ? 14 : isSquare ? 12 : 11;
    const smallTextSize = isVertical ? 12 : isSquare ? 11 : 10;
    const padding = isVertical ? 50 : isSquare ? 45 : 40;

    const formatDate = (date?: string) => {
      const d = date ? new Date(date) : new Date();
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    };

    const getPowerScore = (team: RankingRow) => {
      return team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
    };

    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';

    // Determine grid layout based on champion count
    const displayChampions = champions.slice(0, 12);
    const cols = isVertical ? 3 : isSquare ? 4 : 4;

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
                  left: '-18px',
                  top: '50%',
                  transform: 'translateY(-50%) skewX(-12deg)',
                  width: '7px',
                  height: '70%',
                  background: BRAND_COLORS.electricYellow,
                }}
              />
              <span style={{ color: BRAND_COLORS.brightWhite }}>PITCH</span>
              <span style={{ color: BRAND_COLORS.electricYellow }}>RANK</span>
            </div>
          </div>

          {/* Title */}
          <div style={{ textAlign: 'center', marginBottom: 8 }}>
            <div
              style={{
                fontFamily: "Oswald, 'Arial Black', sans-serif",
                fontSize: `${titleSize}px`,
                fontWeight: 700,
                color: BRAND_COLORS.electricYellow,
              }}
            >
              STATE CHAMPIONS
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize + 2}px`,
                color: '#AAAAAA',
                marginTop: 4,
              }}
            >
              {ageGroup.toUpperCase()} {genderLabel} • #1 IN EACH STATE
            </div>
          </div>

          {/* Champions Grid */}
          <div
            style={{
              flex: 1,
              display: 'grid',
              gridTemplateColumns: `repeat(${cols}, 1fr)`,
              gap: isVertical ? '10px' : '8px',
              marginTop: isVertical ? 20 : 16,
              alignContent: 'start',
            }}
          >
            {displayChampions.map((champion) => (
              <div
                key={champion.state}
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  borderRadius: '8px',
                  padding: isVertical ? '12px 8px' : '10px 6px',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                }}
              >
                {/* State Badge */}
                <div
                  style={{
                    width: isVertical ? 40 : 36,
                    height: isVertical ? 40 : 36,
                    borderRadius: '50%',
                    background: BRAND_COLORS.darkGreen,
                    border: `2px solid ${BRAND_COLORS.electricYellow}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 8,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "Oswald, 'Arial Black', sans-serif",
                      fontSize: `${stateSize}px`,
                      fontWeight: 700,
                      color: BRAND_COLORS.electricYellow,
                    }}
                  >
                    {champion.state}
                  </span>
                </div>

                {/* Team Name */}
                <div
                  style={{
                    fontFamily: "Oswald, 'Arial Black', sans-serif",
                    fontSize: `${teamNameSize}px`,
                    fontWeight: 600,
                    color: BRAND_COLORS.brightWhite,
                    textTransform: 'uppercase',
                    lineHeight: 1.2,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    maxHeight: `${teamNameSize * 2.4}px`,
                  }}
                >
                  {champion.team.team_name}
                </div>

                {/* Power Score */}
                <div
                  style={{
                    fontFamily: "Oswald, 'Arial Black', sans-serif",
                    fontSize: `${smallTextSize + 2}px`,
                    fontWeight: 700,
                    color: BRAND_COLORS.electricYellow,
                    marginTop: 4,
                  }}
                >
                  {getPowerScore(champion.team)}
                </div>
              </div>
            ))}
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
              {formatDate(generatedDate)}
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

StateChampionsPreview.displayName = 'StateChampionsPreview';

export default StateChampionsPreview;
