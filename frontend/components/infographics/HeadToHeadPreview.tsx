'use client';

import React, { forwardRef } from 'react';
import { InfographicWrapper, Platform, BRAND_COLORS, PLATFORM_DIMENSIONS } from './InfographicWrapper';
import type { RankingRow } from '@/types/RankingRow';
import { predictMatch, type MatchPrediction } from '@/lib/matchPredictor';
import type { Game } from '@/lib/types';

interface HeadToHeadPreviewProps {
  team1: RankingRow & { rank?: number };
  team2: RankingRow & { rank?: number };
  platform: Platform;
  scale?: number;
  generatedDate?: string;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
  allGames?: Game[];
}

export const HeadToHeadPreview = forwardRef<HTMLDivElement, HeadToHeadPreviewProps>(
  ({ team1, team2, platform, scale = 0.5, generatedDate, ageGroup, gender, regionName, allGames = [] }, ref) => {
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const isVertical = platform === 'instagramStory';
    const isSquare = platform === 'instagram';

    // Font sizes
    const logoSize = isVertical ? 44 : isSquare ? 40 : 36;
    const teamNameSize = isVertical ? 28 : isSquare ? 24 : 20;
    const rankSize = isVertical ? 48 : isSquare ? 42 : 36;
    const statValueSize = isVertical ? 24 : isSquare ? 20 : 18;
    const statLabelSize = isVertical ? 12 : isSquare ? 11 : 10;
    const smallTextSize = isVertical ? 14 : isSquare ? 12 : 11;
    const vsSize = isVertical ? 36 : isSquare ? 32 : 28;
    const padding = isVertical ? 50 : isSquare ? 45 : 40;

    const formatDate = (date?: string) => {
      const d = date ? new Date(date) : new Date();
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    };

    const getRecord = (team: RankingRow) => {
      const wins = team.total_wins ?? team.wins ?? 0;
      const losses = team.total_losses ?? team.losses ?? 0;
      const draws = team.total_draws ?? team.draws ?? 0;
      return `${wins}-${losses}-${draws}`;
    };

    const getWinPct = (team: RankingRow) => {
      const wins = team.total_wins ?? team.wins ?? 0;
      const losses = team.total_losses ?? team.losses ?? 0;
      const draws = team.total_draws ?? team.draws ?? 0;
      const total = wins + losses + draws;
      if (total === 0) return '0%';
      return `${Math.round((wins / total) * 100)}%`;
    };

    const getPowerScore = (team: RankingRow) => {
      return team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
    };

    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';

    // Get prediction using the same logic as compare tab
    const matchPrediction = predictMatch(
      { ...team1, team_id_master: team1.team_id_master || '' } as any,
      { ...team2, team_id_master: team2.team_id_master || '' } as any,
      allGames
    );
    const prediction = {
      winProbability1: matchPrediction.winProbabilityA,
      winProbability2: matchPrediction.winProbabilityB,
      expectedScore1: Math.round(matchPrediction.expectedScore.teamA),
      expectedScore2: Math.round(matchPrediction.expectedScore.teamB),
    };

    const stats = [
      { label: 'RECORD', team1: getRecord(team1), team2: getRecord(team2) },
      { label: 'POWER SCORE', team1: getPowerScore(team1), team2: getPowerScore(team2), highlight: true },
      { label: 'WIN %', team1: getWinPct(team1), team2: getWinPct(team2) },
    ];

    const TeamCard = ({ team, rank, side }: { team: RankingRow; rank: number; side: 'left' | 'right' }) => (
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: side === 'left' ? 'flex-start' : 'flex-end',
          textAlign: side === 'left' ? 'left' : 'right',
        }}
      >
        <div
          style={{
            fontFamily: "Oswald, 'Arial Black', sans-serif",
            fontSize: `${rankSize}px`,
            fontWeight: 800,
            color: BRAND_COLORS.electricYellow,
            lineHeight: 1,
          }}
        >
          #{rank} {team.state || ''}
        </div>
        <div
          style={{
            fontFamily: "Oswald, 'Arial Black', sans-serif",
            fontSize: `${teamNameSize}px`,
            fontWeight: 700,
            color: BRAND_COLORS.brightWhite,
            textTransform: 'uppercase',
            marginTop: 8,
            maxWidth: (dimensions.width - padding * 2) / 2 - 40,
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
            marginTop: 4,
          }}
        >
          {team.club_name || team.state || 'N/A'}
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
              marginBottom: 12,
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
          <div
            style={{
              textAlign: 'center',
              fontFamily: "Oswald, 'Arial Black', sans-serif",
              fontSize: `${smallTextSize + 4}px`,
              fontWeight: 700,
              color: BRAND_COLORS.electricYellow,
              marginBottom: isVertical ? 40 : 30,
            }}
          >
            HEAD TO HEAD • {ageGroup.toUpperCase()} {genderLabel}
          </div>

          {/* Teams Section */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: isVertical ? 50 : 40,
            }}
          >
            <TeamCard team={team1} rank={team1.rank || 1} side="left" />

            {/* VS Badge */}
            <div
              style={{
                width: isVertical ? 70 : 60,
                height: isVertical ? 70 : 60,
                borderRadius: '50%',
                background: BRAND_COLORS.electricYellow,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 16px',
                flexShrink: 0,
              }}
            >
              <span
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${vsSize}px`,
                  fontWeight: 800,
                  color: BRAND_COLORS.darkGreen,
                }}
              >
                VS
              </span>
            </div>

            <TeamCard team={team2} rank={team2.rank || 2} side="right" />
          </div>

          {/* Stats Comparison */}
          <div>
            {stats.map((stat) => (
              <div
                key={stat.label}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  background: 'rgba(255, 255, 255, 0.05)',
                  borderRadius: '6px',
                  padding: isVertical ? '14px 16px' : '12px 14px',
                  marginBottom: isVertical ? 12 : 10,
                }}
              >
                <div
                  style={{
                    flex: 1,
                    fontFamily: "Oswald, 'Arial Black', sans-serif",
                    fontSize: `${statValueSize}px`,
                    fontWeight: 700,
                    color: stat.highlight ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite,
                    textAlign: 'left',
                  }}
                >
                  {stat.team1}
                </div>
                <div
                  style={{
                    fontFamily: "'DM Sans', Arial, sans-serif",
                    fontSize: `${statLabelSize}px`,
                    color: '#888888',
                    textTransform: 'uppercase',
                    padding: '0 16px',
                  }}
                >
                  {stat.label}
                </div>
                <div
                  style={{
                    flex: 1,
                    fontFamily: "Oswald, 'Arial Black', sans-serif",
                    fontSize: `${statValueSize}px`,
                    fontWeight: 700,
                    color: stat.highlight ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite,
                    textAlign: 'right',
                  }}
                >
                  {stat.team2}
                </div>
              </div>
            ))}
          </div>

          {/* Predicted Score */}
          <div
            style={{
              marginTop: isVertical ? 24 : 20,
              textAlign: 'center',
            }}
          >
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${statLabelSize}px`,
                color: '#888888',
                textTransform: 'uppercase',
                marginBottom: 8,
              }}
            >
              PROJECTED SCORE
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: isVertical ? 24 : 20,
              }}
            >
              <div
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${isVertical ? 56 : isSquare ? 48 : 40}px`,
                  fontWeight: 800,
                  color: prediction.winProbability1 > 0.5 ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite,
                }}
              >
                {prediction.expectedScore1}
              </div>
              <div
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${isVertical ? 28 : isSquare ? 24 : 20}px`,
                  fontWeight: 700,
                  color: '#888888',
                }}
              >
                -
              </div>
              <div
                style={{
                  fontFamily: "Oswald, 'Arial Black', sans-serif",
                  fontSize: `${isVertical ? 56 : isSquare ? 48 : 40}px`,
                  fontWeight: 800,
                  color: prediction.winProbability2 > 0.5 ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite,
                }}
              >
                {prediction.expectedScore2}
              </div>
            </div>
            <div
              style={{
                fontFamily: "'DM Sans', Arial, sans-serif",
                fontSize: `${smallTextSize - 2}px`,
                color: '#666666',
                marginTop: 4,
              }}
            >
              Win Probability: {Math.round(prediction.winProbability1 * 100)}% - {Math.round(prediction.winProbability2 * 100)}%
            </div>
          </div>

          {/* Spacer */}
          <div style={{ flex: 1 }} />

          {/* Footer */}
          <div
            style={{
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

HeadToHeadPreview.displayName = 'HeadToHeadPreview';

export default HeadToHeadPreview;
