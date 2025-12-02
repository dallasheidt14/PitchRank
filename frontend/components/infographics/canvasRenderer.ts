import type { RankingRow } from '@/types/RankingRow';
import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

interface RenderOptions {
  teams: RankingRow[];
  platform: Platform;
  ageGroup: string;
  gender: 'M' | 'F';
  region: string | null;
  regionName: string;
  generatedDate?: string;
}

/**
 * Renders the infographic directly to a canvas element.
 * This bypasses html2canvas issues with modern CSS.
 */
export async function renderInfographicToCanvas(options: RenderOptions): Promise<HTMLCanvasElement> {
  const { teams, platform, ageGroup, gender, region, regionName, generatedDate } = options;
  const dimensions = PLATFORM_DIMENSIONS[platform];
  const isVertical = platform === 'instagramStory';
  const isSquare = platform === 'instagram';

  // Create canvas
  const canvas = document.createElement('canvas');
  const scale = 2; // For high DPI
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  // Scale for high DPI
  ctx.scale(scale, scale);

  // Draw background gradient
  const gradient = ctx.createLinearGradient(0, 0, dimensions.width, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(1, BRAND_COLORS.darkGreen);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Draw subtle scan lines for texture
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
  ctx.lineWidth = 1;
  for (let y = 0; y < dimensions.height; y += 3) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(dimensions.width, y);
    ctx.stroke();
  }

  // Font sizes based on platform
  const titleSize = isVertical ? 72 : isSquare ? 64 : 56;
  const subtitleSize = isVertical ? 32 : isSquare ? 28 : 24;
  const rankSize = isVertical ? 36 : isSquare ? 32 : 28;
  const teamNameSize = isVertical ? 26 : isSquare ? 22 : 18;
  const statsSize = isVertical ? 20 : isSquare ? 18 : 16;
  const padding = isVertical ? 60 : isSquare ? 50 : 40;

  let currentY = padding;

  // ===== HEADER SECTION =====

  // Draw logo: /PITCHRANK
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  // Draw the slash
  const logoY = currentY + titleSize / 2;
  const logoText = 'PITCHRANK';
  ctx.font = `800 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  const logoWidth = ctx.measureText(logoText).width;
  const logoStartX = (dimensions.width - logoWidth) / 2;

  // Yellow slash bar
  ctx.save();
  ctx.translate(logoStartX - 20, logoY);
  ctx.transform(1, 0, -0.2, 1, 0, 0); // Skew
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(-6, -titleSize * 0.4, 10, titleSize * 0.8);
  ctx.restore();

  // Draw PITCH in white
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `800 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  const pitchWidth = ctx.measureText('PITCH').width;
  ctx.fillText('PITCH', logoStartX + pitchWidth / 2, logoY);

  // Draw RANK in yellow
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth + ctx.measureText('RANK').width / 2, logoY);

  currentY += titleSize + 16;

  // Draw title (TOP 10 U12 BOYS - NATIONAL)
  const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
  const regionLabel = region ? regionName.toUpperCase() : 'NATIONAL';
  const title = `TOP 10 ${ageGroup.toUpperCase()} ${genderLabel} - ${regionLabel}`;

  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `700 ${subtitleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'center';
  ctx.fillText(title, dimensions.width / 2, currentY + subtitleSize / 2);

  currentY += subtitleSize + 8;

  // Draw date
  const formatDate = (date?: string) => {
    const d = date ? new Date(date) : new Date();
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  };

  ctx.fillStyle = '#AAAAAA';
  ctx.font = `400 ${statsSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(`Rankings as of ${formatDate(generatedDate)}`, dimensions.width / 2, currentY + statsSize / 2);

  currentY += statsSize + (isVertical ? 48 : 32);

  // ===== RANKINGS LIST =====
  const top10 = teams.slice(0, 10);
  const rowHeight = isVertical ? 70 : isSquare ? 62 : 52;
  const rowGap = isVertical ? 12 : isSquare ? 8 : 6;
  const rowPaddingX = isVertical ? 20 : 16;

  const medalColors: Record<number, string> = {
    1: '#FFD700', // Gold
    2: '#C0C0C0', // Silver
    3: '#CD7F32', // Bronze
  };

  top10.forEach((team, index) => {
    const rank = index + 1;
    const isTopThree = rank <= 3;
    const rowY = currentY;

    // Row background
    if (isTopThree) {
      const rowGradient = ctx.createLinearGradient(padding, rowY, dimensions.width - padding, rowY);
      rowGradient.addColorStop(0, 'rgba(244, 208, 63, 0.25)');
      rowGradient.addColorStop(1, 'rgba(244, 208, 63, 0.05)');
      ctx.fillStyle = rowGradient;
    } else {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
    }

    // Draw rounded rect
    const rowX = padding;
    const rowWidth = dimensions.width - padding * 2;
    const radius = 8;

    ctx.beginPath();
    ctx.moveTo(rowX + radius, rowY);
    ctx.lineTo(rowX + rowWidth - radius, rowY);
    ctx.quadraticCurveTo(rowX + rowWidth, rowY, rowX + rowWidth, rowY + radius);
    ctx.lineTo(rowX + rowWidth, rowY + rowHeight - radius);
    ctx.quadraticCurveTo(rowX + rowWidth, rowY + rowHeight, rowX + rowWidth - radius, rowY + rowHeight);
    ctx.lineTo(rowX + radius, rowY + rowHeight);
    ctx.quadraticCurveTo(rowX, rowY + rowHeight, rowX, rowY + rowHeight - radius);
    ctx.lineTo(rowX, rowY + radius);
    ctx.quadraticCurveTo(rowX, rowY, rowX + radius, rowY);
    ctx.fill();

    // Left border for top 3
    if (isTopThree) {
      ctx.fillStyle = medalColors[rank];
      ctx.fillRect(rowX, rowY, 4, rowHeight);
    }

    // Draw rank number
    const rankX = rowX + rowPaddingX + 25;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = isTopThree ? medalColors[rank] : BRAND_COLORS.brightWhite;
    ctx.font = `800 ${rankSize}px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(String(rank), rankX, rowY + rowHeight / 2);

    // Draw team name
    const teamInfoX = rankX + 50;
    ctx.textAlign = 'left';
    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `600 ${teamNameSize}px Oswald, "Arial Black", sans-serif`;

    // Truncate team name if too long
    let teamName = team.team_name.toUpperCase();
    const maxTeamWidth = dimensions.width - teamInfoX - 180;
    while (ctx.measureText(teamName).width > maxTeamWidth && teamName.length > 10) {
      teamName = teamName.slice(0, -4) + '...';
    }
    ctx.fillText(teamName, teamInfoX, rowY + rowHeight / 2 - 8);

    // Draw club name & state
    const clubText = `${team.club_name || ''} | ${team.state || 'N/A'}`;
    ctx.fillStyle = '#999999';
    ctx.font = `400 ${statsSize - 2}px "DM Sans", Arial, sans-serif`;

    let displayClubText = clubText;
    while (ctx.measureText(displayClubText).width > maxTeamWidth && displayClubText.length > 10) {
      displayClubText = displayClubText.slice(0, -4) + '...';
    }
    ctx.fillText(displayClubText, teamInfoX, rowY + rowHeight / 2 + 12);

    // Draw stats (right side)
    const statsRightX = dimensions.width - padding - rowPaddingX;

    // Power Score
    const score = team.power_score_final ? (team.power_score_final * 100).toFixed(1) : 'N/A';
    ctx.textAlign = 'center';
    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.font = `700 ${statsSize}px "DM Sans", Arial, sans-serif`;
    ctx.fillText(score, statsRightX - 30, rowY + rowHeight / 2 - 6);
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${statsSize - 4}px "DM Sans", Arial, sans-serif`;
    ctx.fillText('SCORE', statsRightX - 30, rowY + rowHeight / 2 + 10);

    // Record (W-L-D)
    const wins = team.total_wins ?? team.wins ?? 0;
    const losses = team.total_losses ?? team.losses ?? 0;
    const draws = team.total_draws ?? team.draws ?? 0;
    const record = `${wins}-${losses}-${draws}`;

    ctx.fillStyle = BRAND_COLORS.brightWhite;
    ctx.font = `700 ${statsSize}px "DM Sans", Arial, sans-serif`;
    ctx.fillText(record, statsRightX - 100, rowY + rowHeight / 2 - 6);
    ctx.fillStyle = '#888888';
    ctx.font = `400 ${statsSize - 4}px "DM Sans", Arial, sans-serif`;
    ctx.fillText('W-L-D', statsRightX - 100, rowY + rowHeight / 2 + 10);

    currentY += rowHeight + rowGap;
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

  // pitchrank.com
  ctx.textAlign = 'left';
  ctx.fillStyle = '#999999';
  ctx.font = `400 ${statsSize - 2}px "DM Sans", Arial, sans-serif`;
  ctx.fillText('pitchrank.com', padding, currentY);

  // Hashtags
  const hashtags = `#YouthSoccer #${ageGroup}Soccer${region ? ` #${regionName}Soccer` : ''}`;
  ctx.textAlign = 'right';
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText(hashtags, dimensions.width - padding, currentY);

  return canvas;
}

/**
 * Converts a canvas to a Blob
 */
export function canvasToBlob(canvas: HTMLCanvasElement, type = 'image/png', quality = 1.0): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('Failed to create blob from canvas'));
        }
      },
      type,
      quality
    );
  });
}
