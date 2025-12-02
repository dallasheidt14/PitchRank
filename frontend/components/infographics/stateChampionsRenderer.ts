import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface StateChampionsOptions {
  champions: Array<{ state: string; team: RankingRow }>;
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  generatedDate?: string;
}

/**
 * Renders a State Champions infographic showing #1 ranked team from each state.
 */
export async function renderStateChampionsToCanvas(options: StateChampionsOptions): Promise<HTMLCanvasElement> {
  const { champions, platform, ageGroup, gender, generatedDate } = options;
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
  gradient.addColorStop(0.6, BRAND_COLORS.darkGreen);
  gradient.addColorStop(1, '#021a15');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Hexagonal pattern overlay
  ctx.strokeStyle = 'rgba(244, 208, 63, 0.04)';
  ctx.lineWidth = 1;
  const hexSize = 40;
  for (let row = 0; row < dimensions.height / hexSize + 2; row++) {
    for (let col = 0; col < dimensions.width / hexSize + 2; col++) {
      const offsetX = row % 2 === 0 ? 0 : hexSize * 0.75;
      const x = col * hexSize * 1.5 + offsetX;
      const y = row * hexSize * 0.866;
      drawHexagon(ctx, x, y, hexSize / 2);
    }
  }

  // Scan lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.015)';
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
  const stateSize = isVertical ? 20 : isSquare ? 18 : 16;
  const teamNameSize = isVertical ? 18 : isSquare ? 16 : 14;
  const smallTextSize = isVertical ? 14 : isSquare ? 12 : 11;
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

  // Logo text
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.fillText('PITCH', logoStartX, logoY);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth, logoY);

  ctx.textAlign = 'center';

  currentY += logoSize + 25;

  // ===== TITLE =====
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('STATE CHAMPIONS', dimensions.width / 2, currentY);

  currentY += titleSize * 0.4;

  // Subtitle
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(`${ageGroup.toUpperCase()} ${genderLabel}`, dimensions.width / 2, currentY + smallTextSize);

  currentY += smallTextSize + (isVertical ? 35 : 25);

  // ===== CHAMPIONS GRID =====
  const maxChamps = isVertical ? 8 : isSquare ? 6 : 4;
  const displayChamps = champions.slice(0, maxChamps);

  const cols = isVertical ? 2 : isSquare ? 3 : 4;
  const rows = Math.ceil(displayChamps.length / cols);

  const cardWidth = (dimensions.width - padding * 2 - (cols - 1) * 15) / cols;
  const cardHeight = isVertical ? 150 : isSquare ? 130 : 110;
  const cardGap = 15;

  displayChamps.forEach((champ, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const cardX = padding + col * (cardWidth + cardGap);
    const cardY = currentY + row * (cardHeight + cardGap);

    // Card background
    ctx.fillStyle = 'rgba(255, 255, 255, 0.06)';
    roundRect(ctx, cardX, cardY, cardWidth, cardHeight, 10);
    ctx.fill();

    // Trophy/crown icon area
    const iconY = cardY + 25;
    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.font = `${isVertical ? 32 : isSquare ? 28 : 24}px Arial`;
    ctx.textAlign = 'center';
    ctx.fillText('👑', cardX + cardWidth / 2, iconY);

    // State name
    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.font = `700 ${stateSize}px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(champ.state.toUpperCase(), cardX + cardWidth / 2, iconY + 30);

    // Team name (truncated)
    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `600 ${teamNameSize}px "DM Sans", Arial, sans-serif`;
    let teamName = champ.team.team_name.toUpperCase();
    const maxNameWidth = cardWidth - 20;
    while (ctx.measureText(teamName).width > maxNameWidth && teamName.length > 8) {
      teamName = teamName.slice(0, -4) + '...';
    }
    ctx.fillText(teamName, cardX + cardWidth / 2, iconY + 55);

    // Club name
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
    let clubName = champ.team.club_name || '';
    while (ctx.measureText(clubName).width > maxNameWidth && clubName.length > 8) {
      clubName = clubName.slice(0, -4) + '...';
    }
    ctx.fillText(clubName, cardX + cardWidth / 2, iconY + 75);

    // Power score badge
    const score = champ.team.power_score_final
      ? (champ.team.power_score_final * 100).toFixed(1)
      : 'N/A';
    ctx.fillStyle = 'rgba(244, 208, 63, 0.2)';
    const badgeWidth = 60;
    const badgeHeight = 22;
    const badgeX = cardX + (cardWidth - badgeWidth) / 2;
    const badgeY = cardY + cardHeight - 32;
    roundRect(ctx, badgeX, badgeY, badgeWidth, badgeHeight, 4);
    ctx.fill();

    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.font = `700 ${smallTextSize}px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(score, cardX + cardWidth / 2, badgeY + 16);
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
  ctx.fillText(formatDate(generatedDate), padding, currentY);

  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('pitchrank.io', dimensions.width - padding, currentY);

  return canvas;
}

function drawHexagon(ctx: CanvasRenderingContext2D, x: number, y: number, size: number) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 6;
    const hx = x + size * Math.cos(angle);
    const hy = y + size * Math.sin(angle);
    if (i === 0) ctx.moveTo(hx, hy);
    else ctx.lineTo(hx, hy);
  }
  ctx.closePath();
  ctx.stroke();
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

// Generate mock state champions from rankings
export function generateStateChampions(rankings: RankingRow[]): Array<{ state: string; team: RankingRow }> {
  const stateMap = new Map<string, RankingRow>();

  // Get the #1 team from each state
  rankings.forEach((team) => {
    const state = team.state || 'Unknown';
    if (!stateMap.has(state)) {
      stateMap.set(state, team);
    }
  });

  return Array.from(stateMap.entries())
    .map(([state, team]) => ({ state, team }))
    .slice(0, 10);
}
