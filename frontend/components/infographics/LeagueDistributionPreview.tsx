'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS } from './InfographicWrapper';
import { FEMALE_LEAGUE_DATA, type LeagueDistributionData } from './leagueDistributionRenderer';

const LEAGUE_COLORS: Record<string, string> = {
  ECNL: '#3B82F6',
  GA: '#EF4444',
  'ECNL RL': '#60A5FA',
  ASPIRE: '#A855F7',
  NPL: '#F97316',
  DPL: '#14B8A6',
  EA: '#EC4899',
  NL: '#EAB308',
  Unaffiliated: '#6B7280',
};

const LEAGUE_ORDER = ['ECNL', 'GA', 'ECNL RL', 'ASPIRE', 'DPL', 'NPL', 'NL', 'EA', 'Unaffiliated'];

interface LeagueDistributionPreviewProps {
  platform: Platform;
  scale?: number;
  data?: LeagueDistributionData[];
  generatedDate?: string;
}

export const LeagueDistributionPreview = forwardRef<HTMLDivElement, LeagueDistributionPreviewProps>(
  ({ platform, scale = 0.5, data = FEMALE_LEAGUE_DATA, generatedDate }, ref) => {
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    const titleSize = isVertical ? 64 : isSquare ? 56 : 44;
    const subtitleSize = isVertical ? 30 : isSquare ? 26 : 22;
    const labelSize = isVertical ? 28 : isSquare ? 24 : 20;
    const statSize = isVertical ? 22 : isSquare ? 19 : 16;
    const barHeight = isVertical ? 48 : isSquare ? 44 : 34;
    const barGap = isVertical ? 24 : isSquare ? 18 : 14;
    const pad = isVertical ? 60 : isSquare ? 50 : 44;

    const dateStr = generatedDate
      ? new Date(generatedDate).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
      : new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

    const legendLeagues = LEAGUE_ORDER.filter((l) => data.some((d) => d.leagues.some((dl) => dl.league === l)));

    const insights = [
      'ECNL owns 39-46% of every top 100 from U13-U19',
      'GA holds steady at 9-13% across all age groups',
      'ECNL RL grows from 7% (U14) to 13% (U16+)',
    ];

    return (
      <InfographicWrapper ref={ref} platform={platform} scale={scale}>
        {/* Scan lines overlay — matches brand texture from other infographics */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `repeating-linear-gradient(
              0deg,
              rgba(255, 255, 255, 0.03) 0px,
              transparent 1px,
              transparent 2px,
              rgba(255, 255, 255, 0.03) 3px
            )`,
            pointerEvents: 'none',
          }}
        />
        {/* Top accent line */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 4,
            background: BRAND_COLORS.electricYellow,
          }}
        />

        <div
          style={{
            position: 'relative',
            zIndex: 1,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            padding: pad,
          }}
        >
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <div
              style={{
                width: 6,
                height: titleSize * 0.3,
                background: BRAND_COLORS.electricYellow,
                borderRadius: 1,
              }}
            />
            <span
              style={{
                fontFamily: 'Oswald, "Arial Black", sans-serif',
                fontWeight: 800,
                fontSize: titleSize * 0.45,
                color: '#fff',
                letterSpacing: 1,
              }}
            >
              PITCH
              <span style={{ color: BRAND_COLORS.electricYellow }}>RANK</span>
            </span>
          </div>

          {/* Title */}
          <div style={{ marginBottom: 4 }}>
            <div
              style={{
                fontFamily: 'Oswald, "Arial Black", sans-serif',
                fontWeight: 800,
                fontSize: titleSize,
                color: '#fff',
                lineHeight: 1.05,
                letterSpacing: -1,
              }}
            >
              WHO DOMINATES THE
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
              <span
                style={{
                  fontFamily: 'Oswald, "Arial Black", sans-serif',
                  fontWeight: 800,
                  fontSize: titleSize,
                  color: BRAND_COLORS.electricYellow,
                  lineHeight: 1.05,
                  letterSpacing: -1,
                }}
              >
                TOP 100?
              </span>
              <span
                style={{
                  fontFamily: 'Oswald, "Arial Black", sans-serif',
                  fontWeight: 600,
                  fontSize: titleSize * 0.5,
                  color: 'rgba(255,255,255,0.5)',
                }}
              >
                GIRLS
              </span>
            </div>
          </div>

          {/* Subtitle */}
          <div
            style={{
              fontFamily: '"DM Sans", sans-serif',
              fontWeight: 500,
              fontSize: subtitleSize,
              color: 'rgba(255,255,255,0.55)',
              marginBottom: 16,
            }}
          >
            League breakdown of the top 100 nationally ranked female teams per age group
          </div>

          {/* Accent line */}
          <div
            style={{
              width: 80,
              height: 3,
              background: BRAND_COLORS.electricYellow,
              marginBottom: 20,
            }}
          />

          {/* Chart rows */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: barGap }}>
            {data.map((row) => {
              const total = row.leagues.reduce((s, l) => s + l.count, 0);
              const sorted = [...row.leagues].sort((a, b) => {
                const ai = LEAGUE_ORDER.indexOf(a.league);
                const bi = LEAGUE_ORDER.indexOf(b.league);
                return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
              });

              return (
                <div key={row.ageGroup} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Label */}
                  <div style={{ width: isVertical ? 70 : isSquare ? 60 : 50, textAlign: 'right', flexShrink: 0 }}>
                    <div
                      style={{
                        fontFamily: 'Oswald, "Arial Black", sans-serif',
                        fontWeight: 700,
                        fontSize: labelSize,
                        color: '#fff',
                      }}
                    >
                      {row.ageGroup}
                    </div>
                    <div
                      style={{
                        fontFamily: '"DM Sans", sans-serif',
                        fontSize: statSize * 0.85,
                        color: 'rgba(255,255,255,0.35)',
                      }}
                    >
                      {row.totalActive.toLocaleString()}
                    </div>
                  </div>

                  {/* Stacked bar */}
                  <div
                    style={{
                      flex: 1,
                      height: barHeight,
                      borderRadius: 4,
                      overflow: 'hidden',
                      display: 'flex',
                      background: 'rgba(255,255,255,0.05)',
                    }}
                  >
                    {sorted.map((seg) => {
                      const pct = (seg.count / total) * 100;
                      const color = LEAGUE_COLORS[seg.league] || '#6B7280';
                      const showLabel = pct > 6;
                      const showName = pct > 12;

                      return (
                        <div
                          key={seg.league}
                          style={{
                            width: `${pct}%`,
                            height: '100%',
                            background: `linear-gradient(180deg, ${color}dd, ${color})`,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            borderRight: '1px solid rgba(0,0,0,0.3)',
                            position: 'relative',
                            overflow: 'hidden',
                          }}
                        >
                          {/* Top highlight */}
                          <div
                            style={{
                              position: 'absolute',
                              top: 0,
                              left: 0,
                              right: 0,
                              height: '40%',
                              background: 'linear-gradient(rgba(255,255,255,0.15), transparent)',
                              pointerEvents: 'none',
                            }}
                          />
                          {showLabel && (
                            <span
                              style={{
                                fontFamily: '"DM Sans", sans-serif',
                                fontWeight: 700,
                                fontSize: statSize,
                                color: '#fff',
                                textShadow: '0 1px 2px rgba(0,0,0,0.3)',
                                whiteSpace: 'nowrap',
                                position: 'relative',
                                zIndex: 1,
                              }}
                            >
                              {showName
                                ? `${seg.league === 'Unaffiliated' ? 'Other' : seg.league} ${Math.round(pct)}%`
                                : `${Math.round(pct)}%`}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', marginTop: 16 }}>
            {legendLeagues.map((l) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 2,
                    background: LEAGUE_COLORS[l],
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    fontFamily: '"DM Sans", sans-serif',
                    fontWeight: 500,
                    fontSize: statSize,
                    color: 'rgba(255,255,255,0.7)',
                  }}
                >
                  {l === 'Unaffiliated' ? 'Other / Regional' : l}
                </span>
              </div>
            ))}
          </div>

          {/* Insights */}
          <div
            style={{
              marginTop: 16,
              background: 'rgba(255,255,255,0.04)',
              borderRadius: 6,
              padding: '10px 14px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            {insights.map((text, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontFamily: '"DM Sans", sans-serif',
                  fontSize: statSize,
                }}
              >
                <span style={{ color: BRAND_COLORS.electricYellow, fontWeight: 600 }}>▸</span>
                <span style={{ color: 'rgba(255,255,255,0.65)', fontWeight: 600 }}>{text}</span>
              </div>
            ))}
          </div>

          {/* Footer */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: 'auto',
              paddingTop: 12,
            }}
          >
            <span
              style={{
                fontFamily: '"DM Sans", sans-serif',
                fontSize: statSize * 0.9,
                color: 'rgba(255,255,255,0.3)',
              }}
            >
              {dateStr}
            </span>
            <span
              style={{
                fontFamily: 'Oswald, "Arial Black", sans-serif',
                fontWeight: 600,
                fontSize: statSize,
                color: 'rgba(255,255,255,0.35)',
              }}
            >
              pitchrank.com
            </span>
          </div>
        </div>
      </InfographicWrapper>
    );
  }
);

LeagueDistributionPreview.displayName = 'LeagueDistributionPreview';
