import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface HeadToHeadOptions {
  team1: RankingRow & { rank?: number };
  team2: RankingRow & { rank?: number };
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
  generatedDate?: string;
}

/**
 * Renders a Head-to-Head comparison graphic between two teams.
 */
export async function renderHeadToHeadToCanvas(options: HeadToHeadOptions): Promise<HTMLCanvasElement> {
  const { team1, team2, platform, ageGroup, gender, regionName, generatedDate } = options;
  const dimensions = PLATFORM_DIMENSIONS[platform];
  const isVertical = platform === 'instagramStory';
  const isSquare = platform === 'instagram';

  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  ctx.scale(scale, scale);

  // Background
  const gradient = ctx.createLinearGradient(0, 0, dimensions.width, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(1, BRAND_COLORS.darkGreen);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Diagonal split
  ctx.fillStyle = 'rgba(0, 0, 0, 0.15)';
  ctx.beginPath();
  ctx.moveTo(dimensions.width / 2 - 50, 0);
  ctx.lineTo(dimensions.width / 2 + 50, dimensions.height);
  ctx.lineTo(dimensions.width, dimensions.height);
  ctx.lineTo(dimensions.width, 0);
  ctx.closePath();
  ctx.fill();

  // Scan lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
  ctx.lineWidth = 1;
  for (let y = 0; y < dimensions.height; y += 3) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(dimensions.width, y);
    ctx.stroke();
  }

  // Font sizes
  const logoSize = isVertical ? 44 : isSquare ? 40 : 36;
  const vsSize = isVertical ? 64 : isSquare ? 56 : 48;
  const teamNameSize = isVertical ? 36 : isSquare ? 32 : 28;
  const statValueSize = isVertical ? 42 : isSquare ? 36 : 32;
  const statLabelSize = isVertical ? 14 : isSquare ? 12 : 11;
  const smallTextSize = isVertical ? 16 : isSquare ? 14 : 12;
  const padding = isVertical ? 50 : isSquare ? 45 : 40;

  let currentY = padding;
  const centerX = dimensions.width / 2;

  // ===== LOGO =====
  const logoY = currentY + logoSize * 0.8;
  ctx.font = `800 ${logoSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';

  const pitchWidth = ctx.measureText('PITCH').width;
  const rankWidth = ctx.measureText('RANK').width;
  const totalLogoWidth = pitchWidth + rankWidth;
  const logoStartX = centerX - totalLogoWidth / 2;

  // Yellow slash - positioned right before the P
  ctx.save();
  ctx.translate(logoStartX - 4, logoY - logoSize * 0.35);
  ctx.transform(1, 0, -0.2, 1, 0, 0);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(-7, 0, 7, logoSize * 0.7);
  ctx.restore();

  // Logo text
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.fillText('PITCH', logoStartX, logoY);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth, logoY);

  ctx.textAlign = 'center';

  currentY += logoSize + 15;

  // ===== TITLE =====
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${smallTextSize + 4}px Oswald, "Arial Black", sans-serif`;
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  ctx.fillText(`HEAD TO HEAD • ${ageGroup.toUpperCase()} ${genderLabel}`, centerX, currentY);

  currentY += (isVertical ? 60 : isSquare ? 50 : 45);

  // ===== VS BADGE =====
  const vsY = isVertical ? dimensions.height * 0.42 : dimensions.height * 0.5;

  // VS circle background
  ctx.beginPath();
  ctx.arc(centerX, vsY, vsSize * 0.7, 0, Math.PI * 2);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fill();

  ctx.fillStyle = BRAND_COLORS.darkGreen;
  ctx.font = `800 ${vsSize * 0.5}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText('VS', centerX, vsY);
  ctx.textBaseline = 'alphabetic';

  // ===== TEAM 1 (LEFT) =====
  const team1X = padding + (centerX - padding - 60) / 2;
  const team2X = centerX + 60 + (centerX - padding - 60) / 2;

  // Team 1 Rank Badge
  const badgeSize = isVertical ? 60 : isSquare ? 55 : 50;
  const badge1Y = currentY + badgeSize / 2;

  ctx.beginPath();
  ctx.arc(team1X, badge1Y, badgeSize / 2, 0, Math.PI * 2);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fill();

  ctx.fillStyle = BRAND_COLORS.darkGreen;
  ctx.font = `800 ${badgeSize * 0.45}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(`#${team1.rank || '?'}`, team1X, badge1Y);
  ctx.textBaseline = 'alphabetic';

  // Team 1 Name
  currentY += badgeSize + 20;
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `700 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;

  let team1Name = team1.team_name.toUpperCase();
  const maxNameWidth = centerX - padding - 80;
  while (ctx.measureText(team1Name).width > maxNameWidth && team1Name.length > 8) {
    team1Name = team1Name.slice(0, -4) + '...';
  }
  ctx.fillText(team1Name, team1X, currentY);

  // Team 1 Club
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(team1.state || 'N/A', team1X, currentY + teamNameSize * 0.4 + 5);

  // ===== TEAM 2 (RIGHT) =====
  // Team 2 Rank Badge
  ctx.beginPath();
  ctx.arc(team2X, badge1Y, badgeSize / 2, 0, Math.PI * 2);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fill();

  ctx.fillStyle = BRAND_COLORS.darkGreen;
  ctx.font = `800 ${badgeSize * 0.45}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(`#${team2.rank || '?'}`, team2X, badge1Y);
  ctx.textBaseline = 'alphabetic';

  // Team 2 Name
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `700 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;

  let team2Name = team2.team_name.toUpperCase();
  while (ctx.measureText(team2Name).width > maxNameWidth && team2Name.length > 8) {
    team2Name = team2Name.slice(0, -4) + '...';
  }
  ctx.fillText(team2Name, team2X, currentY);

  // Team 2 Club
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(team2.state || 'N/A', team2X, currentY + teamNameSize * 0.4 + 5);

  // ===== STATS COMPARISON =====
  currentY = vsY + vsSize * 0.7 + 30;

  const stats = [
    {
      label: 'RECORD',
      team1: getRecord(team1),
      team2: getRecord(team2),
    },
    {
      label: 'POWER SCORE',
      team1: team1.power_score_final ? (team1.power_score_final * 100).toFixed(1) : 'N/A',
      team2: team2.power_score_final ? (team2.power_score_final * 100).toFixed(1) : 'N/A',
      highlight: true,
    },
    {
      label: 'WIN %',
      team1: getWinPct(team1),
      team2: getWinPct(team2),
    },
    {
      label: 'TOTAL GAMES',
      team1: String(getTotalGames(team1)),
      team2: String(getTotalGames(team2)),
    },
  ];

  const statRowHeight = isVertical ? 55 : isSquare ? 50 : 45;
  const statGap = isVertical ? 12 : 10;

  stats.forEach((stat, i) => {
    const rowY = currentY + i * (statRowHeight + statGap);

    // Background bar
    ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
    roundRect(ctx, padding, rowY, dimensions.width - padding * 2, statRowHeight, 6);
    ctx.fill();

    // Label (center)
    ctx.fillStyle = '#888888';
    ctx.font = `500 ${statLabelSize}px "DM Sans", Arial, sans-serif`;
    ctx.fillText(stat.label, centerX, rowY + statRowHeight / 2 + 4);

    // Team 1 value (left)
    ctx.textAlign = 'left';
    ctx.fillStyle = stat.highlight ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite;
    ctx.font = `700 ${statValueSize}px Oswald, "Arial Black", sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(stat.team1, padding + 20, rowY + statRowHeight / 2);

    // Team 2 value (right)
    ctx.textAlign = 'right';
    ctx.fillText(stat.team2, dimensions.width - padding - 20, rowY + statRowHeight / 2);

    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
  });

  // ===== FOOTER =====
  currentY = dimensions.height - padding - 20;

  ctx.strokeStyle = '#1a4a3f';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padding, currentY - 16);
  ctx.lineTo(dimensions.width - padding, currentY - 16);
  ctx.stroke();

  ctx.textAlign = 'left';
  ctx.fillStyle = '#999999';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  const formatDate = (date?: string) => {
    const d = date ? new Date(date) : new Date();
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  };
  ctx.fillText(formatDate(generatedDate), padding, currentY);

  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('pitchrank.io', dimensions.width - padding, currentY);

  return canvas;
}

function getRecord(team: RankingRow): string {
  const w = team.total_wins ?? team.wins ?? 0;
  const l = team.total_losses ?? team.losses ?? 0;
  const d = team.total_draws ?? team.draws ?? 0;
  return `${w}-${l}-${d}`;
}

function getWinPct(team: RankingRow): string {
  const w = team.total_wins ?? team.wins ?? 0;
  const l = team.total_losses ?? team.losses ?? 0;
  const d = team.total_draws ?? team.draws ?? 0;
  const total = w + l + d;
  if (total === 0) return '0%';
  return `${Math.round((w / total) * 100)}%`;
}

function getTotalGames(team: RankingRow): number {
  const w = team.total_wins ?? team.wins ?? 0;
  const l = team.total_losses ?? team.losses ?? 0;
  const d = team.total_draws ?? team.draws ?? 0;
  return w + l + d;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}
