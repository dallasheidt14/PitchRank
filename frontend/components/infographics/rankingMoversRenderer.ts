import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface RankingMoversOptions {
  climbers: Array<RankingRow & { change: number; rank?: number }>;
  fallers: Array<RankingRow & { change: number; rank?: number }>;
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
  generatedDate?: string;
}

/**
 * Renders a "Biggest Movers" graphic showing teams that climbed or dropped the most.
 */
export async function renderRankingMoversToCanvas(options: RankingMoversOptions): Promise<HTMLCanvasElement> {
  const { climbers, fallers, platform, ageGroup, gender, regionName, generatedDate } = options;
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

  // Background gradient
  const gradient = ctx.createLinearGradient(0, 0, dimensions.width, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(1, BRAND_COLORS.darkGreen);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

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
  const logoSize = isVertical ? 48 : isSquare ? 44 : 40;
  const titleSize = isVertical ? 42 : isSquare ? 36 : 32;
  const sectionTitleSize = isVertical ? 28 : isSquare ? 24 : 22;
  const teamNameSize = isVertical ? 22 : isSquare ? 20 : 18;
  const changeSize = isVertical ? 32 : isSquare ? 28 : 24;
  const smallTextSize = isVertical ? 16 : isSquare ? 14 : 12;
  const padding = isVertical ? 50 : isSquare ? 45 : 40;

  let currentY = padding;

  // ===== LOGO =====
  const logoY = currentY + logoSize * 0.8;
  ctx.font = `800 ${logoSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';

  const pitchWidth = ctx.measureText('PITCH').width;
  const rankWidth = ctx.measureText('RANK').width;
  const totalLogoWidth = pitchWidth + rankWidth;
  const logoStartX = (dimensions.width - totalLogoWidth) / 2;

  // Yellow slash - positioned right before the P
  ctx.save();
  ctx.translate(logoStartX, logoY - logoSize * 0.35);
  ctx.transform(1, 0, -0.2, 1, 0, 0);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(-12, 0, 8, logoSize * 0.7);
  ctx.restore();

  // Logo text - PITCH in white
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.fillText('PITCH', logoStartX, logoY);

  // Logo text - RANK in yellow
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth, logoY);

  // Reset alignment
  ctx.textAlign = 'center';

  currentY += logoSize + 20;

  // ===== TITLE =====
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('BIGGEST MOVERS', dimensions.width / 2, currentY);

  currentY += titleSize * 0.4;

  // Subtitle
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(`${ageGroup.toUpperCase()} ${genderLabel} • ${regionName.toUpperCase()}`, dimensions.width / 2, currentY + smallTextSize);

  currentY += smallTextSize + (isVertical ? 40 : 30);

  // ===== COLUMNS =====
  const colWidth = (dimensions.width - padding * 2 - 30) / 2;
  const leftColX = padding;
  const rightColX = padding + colWidth + 30;

  // Helper to draw a mover row
  const drawMoverRow = (
    team: RankingRow & { change: number; rank?: number },
    x: number,
    y: number,
    width: number,
    isClimber: boolean
  ) => {
    const rowHeight = isVertical ? 70 : isSquare ? 62 : 55;

    // Background
    ctx.fillStyle = isClimber ? 'rgba(76, 175, 80, 0.15)' : 'rgba(244, 67, 54, 0.15)';
    roundRect(ctx, x, y, width, rowHeight, 8);
    ctx.fill();

    // Left border
    ctx.fillStyle = isClimber ? '#4CAF50' : '#F44336';
    ctx.fillRect(x, y, 4, rowHeight);

    // Change indicator
    const changeX = x + 15;
    const changeY = y + rowHeight / 2;
    ctx.fillStyle = isClimber ? '#4CAF50' : '#F44336';
    ctx.font = `800 ${changeSize}px Oswald, "Arial Black", sans-serif`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const arrow = isClimber ? '↑' : '↓';
    const changeText = `${arrow}${Math.abs(team.change)}`;
    ctx.fillText(changeText, changeX, changeY);

    // Team name
    const textX = changeX + ctx.measureText(changeText).width + 15;
    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `600 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;

    let name = team.team_name.toUpperCase();
    const maxNameWidth = width - (textX - x) - 60;
    while (ctx.measureText(name).width > maxNameWidth && name.length > 8) {
      name = name.slice(0, -4) + '...';
    }
    ctx.fillText(name, textX, changeY - 8);

    // Current rank
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
    ctx.fillText(`Now #${team.rank || '?'}`, textX, changeY + 12);

    ctx.textBaseline = 'alphabetic';
    return rowHeight;
  };

  // ===== CLIMBERS SECTION =====
  ctx.textAlign = 'left';
  ctx.fillStyle = '#4CAF50';
  ctx.font = `700 ${sectionTitleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('🔥 RISING', leftColX, currentY);

  let climberY = currentY + sectionTitleSize + 15;
  const rowGap = isVertical ? 12 : 10;

  climbers.slice(0, 5).forEach((team) => {
    const rowHeight = drawMoverRow(team, leftColX, climberY, colWidth, true);
    climberY += rowHeight + rowGap;
  });

  // ===== FALLERS SECTION =====
  ctx.textAlign = 'left';
  ctx.fillStyle = '#F44336';
  ctx.font = `700 ${sectionTitleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('📉 FALLING', rightColX, currentY);

  let fallerY = currentY + sectionTitleSize + 15;

  fallers.slice(0, 5).forEach((team) => {
    const rowHeight = drawMoverRow(team, rightColX, fallerY, colWidth, false);
    fallerY += rowHeight + rowGap;
  });

  // ===== FOOTER =====
  currentY = dimensions.height - padding - 20;

  ctx.strokeStyle = '#1a4a3f';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padding, currentY - 16);
  ctx.lineTo(dimensions.width - padding, currentY - 16);
  ctx.stroke();

  const formatDate = (date?: string) => {
    const d = date ? new Date(date) : new Date();
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  };

  ctx.textAlign = 'left';
  ctx.fillStyle = '#999999';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(`Week of ${formatDate(generatedDate)}`, padding, currentY);

  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('pitchrank.io', dimensions.width - padding, currentY);

  return canvas;
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

// Generate mock mover data from rankings (for demo)
export function generateMoverData(rankings: RankingRow[]): {
  climbers: Array<RankingRow & { change: number }>;
  fallers: Array<RankingRow & { change: number }>;
} {
  // In real implementation, you'd compare with previous week's data
  // For now, generate random but realistic changes
  const withChanges = rankings.map((team, i) => ({
    ...team,
    rank: i + 1,
    change: Math.floor(Math.random() * 15) - 7, // -7 to +7
  }));

  const climbers = withChanges
    .filter((t) => t.change > 0)
    .sort((a, b) => b.change - a.change)
    .slice(0, 5);

  const fallers = withChanges
    .filter((t) => t.change < 0)
    .sort((a, b) => a.change - b.change)
    .slice(0, 5);

  return { climbers, fallers };
}
