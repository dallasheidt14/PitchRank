import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface TeamSpotlightOptions {
  team: RankingRow & { rank?: number };
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  region: string | null;
  regionName: string;
  generatedDate?: string;
  headline?: string; // e.g., "TEAM OF THE WEEK", "RISING STAR"
}

/**
 * Renders a Team Spotlight Card directly to canvas.
 * Features a single team with detailed stats.
 */
export async function renderTeamSpotlightToCanvas(options: TeamSpotlightOptions): Promise<HTMLCanvasElement> {
  const { team, platform, ageGroup, gender, regionName, generatedDate, headline = 'TEAM SPOTLIGHT' } = options;
  const dimensions = PLATFORM_DIMENSIONS[platform];
  const isVertical = platform === 'instagramStory';
  const isSquare = platform === 'instagram';

  // Create canvas
  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  ctx.scale(scale, scale);

  // Draw background gradient
  const gradient = ctx.createLinearGradient(0, 0, dimensions.width, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(1, BRAND_COLORS.darkGreen);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Draw scan lines texture
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
  ctx.lineWidth = 1;
  for (let y = 0; y < dimensions.height; y += 3) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(dimensions.width, y);
    ctx.stroke();
  }

  // Font sizes based on platform
  const logoSize = isVertical ? 48 : isSquare ? 44 : 40;
  const headlineSize = isVertical ? 36 : isSquare ? 32 : 28;
  const teamNameSize = isVertical ? 56 : isSquare ? 48 : 42;
  const statLabelSize = isVertical ? 18 : isSquare ? 16 : 14;
  const statValueSize = isVertical ? 48 : isSquare ? 42 : 36;
  const smallTextSize = isVertical ? 20 : isSquare ? 18 : 16;
  const padding = isVertical ? 60 : isSquare ? 50 : 40;

  let currentY = padding;

  // ===== HEADER: Logo =====
  // Draw logo - using left alignment for precise positioning
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

  // Reset to center alignment for remaining elements
  ctx.textAlign = 'center';

  currentY += logoSize + (isVertical ? 40 : 30);

  // ===== HEADLINE (e.g., "TEAM OF THE WEEK") =====
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${headlineSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText(headline, dimensions.width / 2, currentY);

  currentY += headlineSize + (isVertical ? 50 : 40);

  // ===== RANK BADGE =====
  const badgeSize = isVertical ? 100 : isSquare ? 90 : 80;
  const badgeY = currentY + badgeSize / 2;

  // Badge background
  ctx.beginPath();
  ctx.arc(dimensions.width / 2, badgeY, badgeSize / 2, 0, Math.PI * 2);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fill();

  // Rank number
  ctx.fillStyle = BRAND_COLORS.darkGreen;
  ctx.font = `800 ${badgeSize * 0.5}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(`#${team.rank || 1}`, dimensions.width / 2, badgeY);
  ctx.textBaseline = 'alphabetic';

  currentY += badgeSize + (isVertical ? 50 : 45);

  // ===== TEAM NAME =====
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `800 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'top';

  // Truncate if needed
  let teamName = team.team_name.toUpperCase();
  const maxWidth = dimensions.width - padding * 2;
  while (ctx.measureText(teamName).width > maxWidth && teamName.length > 10) {
    teamName = teamName.slice(0, -4) + '...';
  }
  ctx.fillText(teamName, dimensions.width / 2, currentY);
  ctx.textBaseline = 'alphabetic';

  currentY += teamNameSize + 10;

  // ===== CLUB & LOCATION =====
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${smallTextSize}px "DM Sans", Arial, sans-serif`;
  const clubText = `${team.club_name || ''} | ${team.state || 'N/A'}`;
  ctx.fillText(clubText, dimensions.width / 2, currentY);

  currentY += smallTextSize + (isVertical ? 60 : 50);

  // ===== STATS GRID =====
  const stats = [
    { label: 'RECORD', value: `${team.total_wins ?? team.wins ?? 0}-${team.total_losses ?? team.losses ?? 0}-${team.total_draws ?? team.draws ?? 0}` },
    { label: 'POWER SCORE', value: team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A' },
    { label: 'WIN %', value: calculateWinPct(team) },
    { label: 'GAMES', value: String(calculateTotalGames(team)) },
  ];

  const statBoxWidth = isVertical ? 200 : isSquare ? 180 : 160;
  const statBoxHeight = isVertical ? 100 : isSquare ? 90 : 80;
  const statGap = isVertical ? 20 : isSquare ? 16 : 14;
  const gridWidth = statBoxWidth * 2 + statGap;
  const gridStartX = (dimensions.width - gridWidth) / 2;

  stats.forEach((stat, index) => {
    const col = index % 2;
    const row = Math.floor(index / 2);
    const boxX = gridStartX + col * (statBoxWidth + statGap);
    const boxY = currentY + row * (statBoxHeight + statGap);

    // Stat box background
    ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
    roundRect(ctx, boxX, boxY, statBoxWidth, statBoxHeight, 8);
    ctx.fill();

    // Stat value
    ctx.fillStyle = index === 1 ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite;
    ctx.font = `700 ${statValueSize}px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(stat.value, boxX + statBoxWidth / 2, boxY + statBoxHeight / 2 - 5);

    // Stat label
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${statLabelSize}px "DM Sans", Arial, sans-serif`;
    ctx.fillText(stat.label, boxX + statBoxWidth / 2, boxY + statBoxHeight / 2 + statValueSize / 2 + 5);
  });

  currentY += (statBoxHeight + statGap) * 2 + (isVertical ? 50 : 40);

  // ===== CATEGORY TAG =====
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  const categoryText = `${ageGroup.toUpperCase()} ${genderLabel} • ${regionName.toUpperCase()}`;

  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `600 ${smallTextSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText(categoryText, dimensions.width / 2, currentY);

  // ===== FOOTER =====
  currentY = dimensions.height - padding - 20;

  // Footer line
  ctx.strokeStyle = '#1a4a3f';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(padding, currentY - 16);
  ctx.lineTo(dimensions.width - padding, currentY - 16);
  ctx.stroke();

  // Date
  const formatDate = (date?: string) => {
    const d = date ? new Date(date) : new Date();
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  };

  ctx.textAlign = 'left';
  ctx.fillStyle = '#999999';
  ctx.font = `400 ${smallTextSize - 2}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(formatDate(generatedDate), padding, currentY);

  // URL
  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('pitchrank.io', dimensions.width - padding, currentY);

  return canvas;
}

// Helper functions
function calculateWinPct(team: RankingRow): string {
  const wins = team.total_wins ?? team.wins ?? 0;
  const losses = team.total_losses ?? team.losses ?? 0;
  const draws = team.total_draws ?? team.draws ?? 0;
  const total = wins + losses + draws;
  if (total === 0) return '0%';
  return `${Math.round((wins / total) * 100)}%`;
}

function calculateTotalGames(team: RankingRow): number {
  const wins = team.total_wins ?? team.wins ?? 0;
  const losses = team.total_losses ?? team.losses ?? 0;
  const draws = team.total_draws ?? team.draws ?? 0;
  return wins + losses + draws;
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
