import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

type StoryType = 'newRankings' | 'comingSoon' | 'teamAnnouncement' | 'weeklyUpdate';

interface StoryTemplateOptions {
  type: StoryType;
  platform: Platform;
  ageGroup?: string;
  gender?: 'M' | 'F';
  regionName?: string;
  customHeadline?: string;
  customSubtext?: string;
}

const STORY_CONTENT: Record<StoryType, { headline: string; subtext: string; emoji: string }> = {
  newRankings: {
    headline: 'NEW RANKINGS\nLIVE!',
    subtext: 'Swipe up to see where your team ranks',
    emoji: '🏆',
  },
  comingSoon: {
    headline: 'RANKINGS\nUPDATE',
    subtext: 'New rankings drop tomorrow!',
    emoji: '⏰',
  },
  teamAnnouncement: {
    headline: 'BIG\nMOVES!',
    subtext: 'See which teams are climbing the ranks',
    emoji: '🚀',
  },
  weeklyUpdate: {
    headline: 'THIS WEEK\nIN SOCCER',
    subtext: 'Weekly rankings recap is here',
    emoji: '📊',
  },
};

/**
 * Renders Instagram Story style announcement templates.
 */
export async function renderStoryTemplateToCanvas(options: StoryTemplateOptions): Promise<HTMLCanvasElement> {
  const { type, platform, ageGroup, gender, regionName, customHeadline, customSubtext } = options;

  // Force story dimensions for this template
  const dimensions = platform === 'instagramStory'
    ? PLATFORM_DIMENSIONS.instagramStory
    : PLATFORM_DIMENSIONS.instagramStory; // Always use story dimensions

  const content = STORY_CONTENT[type];

  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');

  ctx.scale(scale, scale);

  // Background gradient (more dramatic for stories)
  const gradient = ctx.createLinearGradient(0, 0, 0, dimensions.height);
  gradient.addColorStop(0, BRAND_COLORS.forestGreen);
  gradient.addColorStop(0.5, BRAND_COLORS.darkGreen);
  gradient.addColorStop(1, '#021a15');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, dimensions.width, dimensions.height);

  // Animated-style diagonal lines
  ctx.strokeStyle = 'rgba(244, 208, 63, 0.1)';
  ctx.lineWidth = 3;
  for (let i = -dimensions.height; i < dimensions.width + dimensions.height; i += 60) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i + dimensions.height, dimensions.height);
    ctx.stroke();
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

  const padding = 60;
  const centerX = dimensions.width / 2;

  // ===== TOP LOGO =====
  let currentY = padding + 40;
  const logoSize = 52;

  ctx.textAlign = 'center';
  ctx.font = `800 ${logoSize}px Oswald, "Arial Black", sans-serif`;
  const logoWidth = ctx.measureText('PITCHRANK').width;
  const logoStartX = centerX - logoWidth / 2;

  // Yellow slash
  ctx.save();
  ctx.translate(logoStartX - 18, currentY);
  ctx.transform(1, 0, -0.2, 1, 0, 0);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(-5, -logoSize * 0.35, 9, logoSize * 0.7);
  ctx.restore();

  ctx.fillStyle = BRAND_COLORS.brightWhite;
  const pitchWidth = ctx.measureText('PITCH').width;
  ctx.fillText('PITCH', logoStartX + pitchWidth / 2, currentY);
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', logoStartX + pitchWidth + ctx.measureText('RANK').width / 2, currentY);

  // ===== MAIN CONTENT (CENTER) =====
  const centerY = dimensions.height / 2;

  // Emoji
  ctx.font = `100px Arial`;
  ctx.fillText(content.emoji, centerX, centerY - 150);

  // Main headline
  const headlineText = customHeadline || content.headline;
  const headlineLines = headlineText.split('\n');
  const headlineSize = 90;

  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `800 ${headlineSize}px Oswald, "Arial Black", sans-serif`;

  headlineLines.forEach((line, i) => {
    const lineY = centerY - 20 + (i * headlineSize);
    ctx.fillText(line, centerX, lineY);
  });

  // Subtext
  const subtextY = centerY + headlineLines.length * headlineSize - 30;
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.font = `600 28px "DM Sans", Arial, sans-serif`;
  ctx.fillText(customSubtext || content.subtext, centerX, subtextY);

  // Category tag (if provided)
  if (ageGroup && gender) {
    const genderLabel = gender === 'M' ? 'BOYS' : 'GIRLS';
    const categoryText = `${ageGroup.toUpperCase()} ${genderLabel}${regionName ? ` • ${regionName.toUpperCase()}` : ''}`;

    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.font = `500 22px Oswald, "Arial Black", sans-serif`;
    ctx.fillText(categoryText, centerX, subtextY + 50);
  }

  // ===== CTA AT BOTTOM =====
  const ctaY = dimensions.height - padding - 100;

  // Swipe up arrow
  ctx.strokeStyle = BRAND_COLORS.electricYellow;
  ctx.lineWidth = 4;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(centerX - 20, ctaY + 15);
  ctx.lineTo(centerX, ctaY);
  ctx.lineTo(centerX + 20, ctaY + 15);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(centerX, ctaY);
  ctx.lineTo(centerX, ctaY + 40);
  ctx.stroke();

  // CTA text
  ctx.fillStyle = BRAND_COLORS.brightWhite;
  ctx.font = `600 20px "DM Sans", Arial, sans-serif`;
  ctx.fillText('SWIPE UP', centerX, ctaY + 70);

  // ===== BOTTOM URL =====
  ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
  ctx.font = `400 18px "DM Sans", Arial, sans-serif`;
  ctx.fillText('pitchrank.com', centerX, dimensions.height - padding);

  return canvas;
}

// Export story types for UI
export const STORY_TYPES: Array<{ value: StoryType; label: string; description: string }> = [
  { value: 'newRankings', label: 'New Rankings Live', description: 'Announce new rankings are available' },
  { value: 'comingSoon', label: 'Coming Soon', description: 'Tease upcoming rankings update' },
  { value: 'teamAnnouncement', label: 'Big Moves', description: 'Highlight major rank changes' },
  { value: 'weeklyUpdate', label: 'Weekly Update', description: 'Weekly recap announcement' },
];
