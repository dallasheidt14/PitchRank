import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface RenderOptions {
  teams: RankingRow[];
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  region: string | null;
  regionName: string;
  generatedDate: string;
}

/**
 * Renders a Top 10 infographic directly to canvas using Canvas 2D API.
 * This bypasses html2canvas issues with modern CSS color functions.
 */
export async function renderInfographicToCanvas(options: RenderOptions): Promise<HTMLCanvasElement> {
  const { teams, platform, ageGroup, gender, regionName, generatedDate } = options;
  const dimensions = PLATFORM_DIMENSIONS[platform];
  const isVertical = platform === 'instagramStory';
  const isSquare = platform === 'instagram';

  // Create canvas with 2x scale for retina
  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  // Scale for retina
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
  const titleSize = isVertical ? 28 : isSquare ? 24 : 22;
  const subtitleSize = isVertical ? 18 : isSquare ? 16 : 14;
  const teamNameSize = isVertical ? 22 : isSquare ? 20 : 18;
  const rankSize = isVertical ? 32 : isSquare ? 28 : 24;
  const scoreSize = isVertical ? 16 : isSquare ? 14 : 12;
  const footerSize = isVertical ? 14 : isSquare ? 12 : 11;
  const padding = isVertical ? 50 : isSquare ? 45 : 40;

  let currentY = padding;

  // ===== HEADER SECTION =====

  // Draw logo - "PITCHRANK" with yellow slash
  ctx.textAlign = 'center';
  ctx.font = `800 ${logoSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textBaseline = 'middle';

  const logoY = currentY + logoSize / 2;
  const logoText = 'PITCHRANK';
  const logoWidth = ctx.measureText(logoText).width;
  const logoStartX = (dimensions.width - logoWidth) / 2;

  // Yellow slash before P
  ctx.save();
  ctx.translate(logoStartX - 16, logoY);
  ctx.transform(1, 0, -0.2, 1, 0, 0);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(-5, -logoSize * 0.35, 8, logoSize * 0.7);
  ctx.restore();

  // "PITCH" in white
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  const pitchWidth = ctx.measureText('PITCH').width;
  ctx.fillText('PITCH', logoStartX + pitchWidth / 2, logoY);

  // "RANK" in yellow
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  const rankWidth = ctx.measureText('RANK').width;
  ctx.fillText('RANK', logoStartX + pitchWidth + rankWidth / 2, logoY);

  currentY += logoSize + (isVertical ? 30 : 25);

  // Title - "TOP 10 RANKINGS"
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('TOP 10 RANKINGS', dimensions.width / 2, currentY);

  currentY += titleSize + 8;

  // Subtitle - Age group and region
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${subtitleSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(`${ageGroup.toUpperCase()} ${genderLabel} • ${regionName.toUpperCase()}`, dimensions.width / 2, currentY);

  currentY += subtitleSize + (isVertical ? 30 : 20);

  // ===== TEAMS LIST =====
  const teamsToShow = teams.slice(0, 10);
  const availableHeight = dimensions.height - currentY - (isVertical ? 100 : 80);
  const rowHeight = Math.min(availableHeight / 10, isVertical ? 70 : isSquare ? 60 : 55);
  const rowGap = (availableHeight - rowHeight * 10) / 9;

  teamsToShow.forEach((team, index) => {
    const rowY = currentY + index * (rowHeight + rowGap);
    const rowCenterY = rowY + rowHeight / 2;

    // Row background
    ctx.fillStyle = index % 2 === 0 ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.02)';
    roundRect(ctx, padding, rowY, dimensions.width - padding * 2, rowHeight, 8);
    ctx.fill();

    // Top 3 gold accent
    if (index < 3) {
      ctx.fillStyle = 'rgba(244, 208, 63, 0.15)';
      ctx.fillRect(padding, rowY, 4, rowHeight);
    }

    // Rank number
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = index < 3 ? BRAND_COLORS.electricYellow : BRAND_COLORS.brightWhite;
    ctx.font = `700 ${rankSize}px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(String(index + 1), padding + 40, rowCenterY);

    // Team name
    ctx.textAlign = 'left';
    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `600 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;

    let teamName = team.team_name.toUpperCase();
    const maxNameWidth = dimensions.width - padding * 2 - 200;
    while (ctx.measureText(teamName).width > maxNameWidth && teamName.length > 10) {
      teamName = teamName.slice(0, -4) + '...';
    }

    ctx.fillText(teamName, padding + 80, rowCenterY - (scoreSize / 2 + 2));

    // Club name and state
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${scoreSize}px "DM Sans", Arial, sans-serif`;
    const clubText = team.club_name ? `${team.club_name} | ${team.state || 'N/A'}` : team.state || 'N/A';
    ctx.fillText(clubText, padding + 80, rowCenterY + (scoreSize / 2 + 4));

    // Record
    ctx.textAlign = 'right';
    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `500 ${scoreSize + 2}px "JetBrains Mono", monospace`;
    const wins = team.total_wins ?? team.wins ?? 0;
    const losses = team.total_losses ?? team.losses ?? 0;
    const draws = team.total_draws ?? team.draws ?? 0;
    ctx.fillText(`${wins}-${losses}-${draws}`, dimensions.width - padding - 15, rowCenterY - 6);

    // Power score
    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.font = `600 ${scoreSize}px "JetBrains Mono", monospace`;
    const score = team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
    ctx.fillText(score, dimensions.width - padding - 15, rowCenterY + 10);
  });

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
  ctx.textAlign = 'left';
  ctx.fillStyle = '#999999';
  ctx.font = `400 ${footerSize}px "DM Sans", Arial, sans-serif`;
  const date = new Date(generatedDate);
  const formattedDate = date.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  ctx.fillText(formattedDate, padding, currentY);

  // Website URL
  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('pitchrank.com', dimensions.width - padding, currentY);

  return canvas;
}

/**
 * Converts a canvas to a PNG Blob.
 */
export function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error('Failed to convert canvas to blob'));
      }
    }, 'image/png', 1.0);
  });
}

// Helper function to draw rounded rectangles
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
