import { BRAND_COLORS } from './InfographicWrapper';

type CoverPlatform = 'twitter' | 'facebook' | 'linkedin';

interface CoverImageOptions {
  platform: CoverPlatform;
  ageGroup?: string;
  gender?: 'M' | 'F';
  regionName?: string;
  tagline?: string;
}

const COVER_DIMENSIONS: Record<CoverPlatform, { width: number; height: number }> = {
  twitter: { width: 1500, height: 500 },
  facebook: { width: 820, height: 312 },
  linkedin: { width: 1584, height: 396 },
};

const PLATFORM_LABELS: Record<CoverPlatform, string> = {
  twitter: 'Twitter/X Header',
  facebook: 'Facebook Cover',
  linkedin: 'LinkedIn Banner',
};

/**
 * Renders a social media cover/header image for Twitter, Facebook, or LinkedIn.
 */
export async function renderCoverImageToCanvas(options: CoverImageOptions): Promise<HTMLCanvasElement> {
  const { platform, ageGroup, gender, regionName, tagline } = options;
  const dimensions = COVER_DIMENSIONS[platform];

  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  ctx.scale(scale, scale);

  // Background gradient with diagonal sweep
  const gradient = ctx.createLinearGradient(0, 0, dimensions.width, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(0.5, BRAND_COLORS.darkGreen);
  gradient.addColorStop(1, '#021a15');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Diagonal lines pattern
  ctx.strokeStyle = 'rgba(244, 208, 63, 0.06)';
  ctx.lineWidth = 3;
  for (let i = -dimensions.height; i < dimensions.width + dimensions.height; i += 80) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i + dimensions.height, dimensions.height);
    ctx.stroke();
  }

  // Additional reverse diagonal lines for depth
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
  ctx.lineWidth = 2;
  for (let i = 0; i < dimensions.width + dimensions.height; i += 100) {
    ctx.beginPath();
    ctx.moveTo(i, dimensions.height);
    ctx.lineTo(i + dimensions.height, 0);
    ctx.stroke();
  }

  // Scan lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.01)';
  ctx.lineWidth = 1;
  for (let y = 0; y < dimensions.height; y += 3) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(dimensions.width, y);
    ctx.stroke();
  }

  // Dynamic font sizes based on platform
  const scale_factor = platform === 'facebook' ? 0.8 : platform === 'linkedin' ? 1.1 : 1;
  const logoSize = Math.round(72 * scale_factor);
  const taglineSize = Math.round(28 * scale_factor);
  const subtitleSize = Math.round(18 * scale_factor);

  const centerX = dimensions.width / 2;
  const centerY = dimensions.height / 2;

  // ===== MAIN LOGO =====
  ctx.font = `800 ${logoSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';

  const pitchWidth = ctx.measureText('PITCH').width;
  const rankWidth = ctx.measureText('RANK').width;
  const totalLogoWidth = pitchWidth + rankWidth;
  const logoStartX = centerX - totalLogoWidth / 2;
  const logoY = centerY - 10;

  // Yellow slash (larger and more prominent for cover images) - positioned right before the P
  ctx.save();
  ctx.translate(logoStartX - 14, logoY - logoSize * 0.35);
  ctx.transform(1, 0, -0.2, 1, 0, 0);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(0, 0, 12, logoSize * 0.7);
  ctx.restore();

  // Logo text
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.fillText('PITCH', logoStartX, logoY);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth, logoY);

  ctx.textAlign = 'center';

  // ===== TAGLINE =====
  const displayTagline = tagline || 'Youth Soccer Rankings That Matter';
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `400 ${taglineSize}px "DM Sans", Arial, sans-serif`;
  ctx.fillText(displayTagline, centerX, centerY + logoSize * 0.5);

  // ===== CATEGORY TAG (if provided) =====
  if (ageGroup && gender) {
    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
    let categoryText = `${ageGroup.toUpperCase()} ${genderLabel}`;
    if (regionName) {
      categoryText += ` | ${regionName.toUpperCase()}`;
    }

    // Draw category badge
    ctx.font = `600 ${subtitleSize}px Oswald, "Arial Black", sans-serif`;
    const badgeWidth = ctx.measureText(categoryText).width + 40;
    const badgeHeight = subtitleSize + 16;
    const badgeX = centerX - badgeWidth / 2;
    const badgeY = centerY + logoSize * 0.5 + taglineSize + 10;

    // Badge background
    ctx.fillStyle = 'rgba(244, 208, 63, 0.15)';
    roundRect(ctx, badgeX, badgeY, badgeWidth, badgeHeight, 6);
    ctx.fill();

    // Badge border
    ctx.strokeStyle = BRAND_COLORS.electricYellow;
    ctx.lineWidth = 2;
    roundRect(ctx, badgeX, badgeY, badgeWidth, badgeHeight, 6);
    ctx.stroke();

    // Badge text
    ctx.fillStyle = BRAND_COLORS.electricYellow;
    ctx.fillText(categoryText, centerX, badgeY + subtitleSize + 4);
  }

  // ===== DECORATIVE ELEMENTS =====
  // Left side accent
  const accentWidth = 6;
  const accentHeight = dimensions.height * 0.4;
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(40, (dimensions.height - accentHeight) / 2, accentWidth, accentHeight);

  // Right side accent
  ctx.fillRect(dimensions.width - 46, (dimensions.height - accentHeight) / 2, accentWidth, accentHeight);

  // Corner accents
  const cornerSize = 30;
  ctx.strokeStyle = BRAND_COLORS.electricYellow;
  ctx.lineWidth = 3;

  // Top-left corner
  ctx.beginPath();
  ctx.moveTo(25, 40 + cornerSize);
  ctx.lineTo(25, 40);
  ctx.lineTo(25 + cornerSize, 40);
  ctx.stroke();

  // Top-right corner
  ctx.beginPath();
  ctx.moveTo(dimensions.width - 25 - cornerSize, 40);
  ctx.lineTo(dimensions.width - 25, 40);
  ctx.lineTo(dimensions.width - 25, 40 + cornerSize);
  ctx.stroke();

  // Bottom-left corner
  ctx.beginPath();
  ctx.moveTo(25, dimensions.height - 40 - cornerSize);
  ctx.lineTo(25, dimensions.height - 40);
  ctx.lineTo(25 + cornerSize, dimensions.height - 40);
  ctx.stroke();

  // Bottom-right corner
  ctx.beginPath();
  ctx.moveTo(dimensions.width - 25 - cornerSize, dimensions.height - 40);
  ctx.lineTo(dimensions.width - 25, dimensions.height - 40);
  ctx.lineTo(dimensions.width - 25, dimensions.height - 40 - cornerSize);
  ctx.stroke();

  // ===== URL =====
  ctx.textAlign = 'right';
  ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
  ctx.font = `400 ${subtitleSize - 2}px "DM Sans", Arial, sans-serif`;
  ctx.fillText('pitchrank.com', dimensions.width - 60, dimensions.height - 25);

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

// Export cover platform options for UI
export const COVER_PLATFORMS: Array<{ value: CoverPlatform; label: string; dimensions: string }> = [
  { value: 'twitter', label: 'Twitter/X Header', dimensions: '1500x500' },
  { value: 'facebook', label: 'Facebook Cover', dimensions: '820x312' },
  { value: 'linkedin', label: 'LinkedIn Banner', dimensions: '1584x396' },
];

export { COVER_DIMENSIONS, PLATFORM_LABELS };
export type { CoverPlatform, CoverImageOptions };
