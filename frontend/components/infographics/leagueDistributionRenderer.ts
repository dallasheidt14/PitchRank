import { PLATFORM_DIMENSIONS, BRAND_COLORS, Platform } from './InfographicWrapper';

// League distribution data for each age group
export interface LeagueDistributionData {
  ageGroup: string;
  totalActive: number;
  leagues: { league: string; count: number }[];
}

// Color palette for leagues
const LEAGUE_COLORS: Record<string, string> = {
  ECNL: '#3B82F6', // bright blue
  GA: '#EF4444', // red
  'ECNL RL': '#60A5FA', // lighter blue
  ASPIRE: '#A855F7', // purple
  NPL: '#F97316', // orange
  DPL: '#14B8A6', // teal
  EA: '#EC4899', // pink
  NL: '#EAB308', // amber
  Unaffiliated: '#6B7280', // gray
};

const LEAGUE_ORDER = ['ECNL', 'GA', 'ECNL RL', 'ASPIRE', 'DPL', 'NPL', 'NL', 'EA', 'Unaffiliated'];

export const FEMALE_LEAGUE_DATA: LeagueDistributionData[] = [
  {
    ageGroup: 'U13',
    totalActive: 2768,
    leagues: [
      { league: 'ECNL', count: 45 },
      { league: 'Unaffiliated', count: 30 },
      { league: 'GA', count: 11 },
      { league: 'ECNL RL', count: 9 },
      { league: 'ASPIRE', count: 2 },
      { league: 'NPL', count: 1 },
      { league: 'EA', count: 1 },
      { league: 'DPL', count: 1 },
    ],
  },
  {
    ageGroup: 'U14',
    totalActive: 2759,
    leagues: [
      { league: 'ECNL', count: 46 },
      { league: 'Unaffiliated', count: 32 },
      { league: 'GA', count: 13 },
      { league: 'ECNL RL', count: 7 },
      { league: 'NL', count: 1 },
      { league: 'NPL', count: 1 },
    ],
  },
  {
    ageGroup: 'U15',
    totalActive: 2072,
    leagues: [
      { league: 'ECNL', count: 40 },
      { league: 'Unaffiliated', count: 34 },
      { league: 'GA', count: 13 },
      { league: 'ECNL RL', count: 8 },
      { league: 'NPL', count: 2 },
      { league: 'ASPIRE', count: 1 },
      { league: 'DPL', count: 1 },
      { league: 'NL', count: 1 },
    ],
  },
  {
    ageGroup: 'U16',
    totalActive: 950,
    leagues: [
      { league: 'ECNL', count: 39 },
      { league: 'Unaffiliated', count: 30 },
      { league: 'ECNL RL', count: 13 },
      { league: 'GA', count: 9 },
      { league: 'ASPIRE', count: 3 },
      { league: 'DPL', count: 2 },
      { league: 'NL', count: 2 },
      { league: 'NPL', count: 2 },
    ],
  },
  {
    ageGroup: 'U17',
    totalActive: 734,
    leagues: [
      { league: 'ECNL', count: 44 },
      { league: 'Unaffiliated', count: 20 },
      { league: 'ECNL RL', count: 13 },
      { league: 'GA', count: 10 },
      { league: 'DPL', count: 6 },
      { league: 'ASPIRE', count: 4 },
      { league: 'NPL', count: 2 },
      { league: 'NL', count: 1 },
    ],
  },
  {
    ageGroup: 'U19',
    totalActive: 711,
    leagues: [
      { league: 'ECNL', count: 41 },
      { league: 'Unaffiliated', count: 28 },
      { league: 'GA', count: 12 },
      { league: 'ECNL RL', count: 11 },
      { league: 'NPL', count: 3 },
      { league: 'ASPIRE', count: 2 },
      { league: 'DPL', count: 2 },
      { league: 'NL', count: 1 },
    ],
  },
];

interface RenderOptions {
  platform: Platform;
  data?: LeagueDistributionData[];
  generatedDate?: string;
}

function drawRoundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  if (w < 2 * r) r = w / 2;
  if (h < 2 * r) r = h / 2;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/**
 * Renders the league distribution infographic directly to canvas.
 * Shows stacked horizontal bars per age group with league color coding.
 */
export async function renderLeagueDistributionToCanvas(options: RenderOptions): Promise<HTMLCanvasElement> {
  const { platform, data = FEMALE_LEAGUE_DATA, generatedDate } = options;
  const dimensions = PLATFORM_DIMENSIONS[platform];
  const isSquare = platform === 'instagram';
  const isVertical = platform === 'instagramStory';

  const canvas = document.createElement('canvas');
  const scale = 2;
  canvas.width = dimensions.width * scale;
  canvas.height = dimensions.height * scale;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not get canvas context');
  ctx.scale(scale, scale);

  const W = dimensions.width;
  const H = dimensions.height;

  // === BACKGROUND — brand forest green / dark green ===
  const bgGrad = ctx.createLinearGradient(0, 0, W, H);
  bgGrad.addColorStop(0, BRAND_COLORS.forestGreen);
  bgGrad.addColorStop(1, BRAND_COLORS.darkGreen);
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // Scan lines (matches existing infographics)
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
  ctx.lineWidth = 1;
  for (let y = 0; y < H; y += 3) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }

  // Sizing
  const pad = isVertical ? 60 : isSquare ? 50 : 44;
  const titleSize = isVertical ? 64 : isSquare ? 56 : 44;
  const subtitleSize = isVertical ? 30 : isSquare ? 26 : 22;
  const labelSize = isVertical ? 28 : isSquare ? 24 : 20;
  const statSize = isVertical ? 22 : isSquare ? 19 : 16;
  const barHeight = isVertical ? 48 : isSquare ? 44 : 34;
  const barGap = isVertical ? 24 : isSquare ? 18 : 14;
  const legendDotSize = isVertical ? 14 : isSquare ? 12 : 10;

  let curY = pad;

  // === PITCHRANK LOGO ===
  ctx.font = `800 ${titleSize * 0.45}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  const logoSmallSize = titleSize * 0.45;
  const logoY = curY + logoSmallSize;

  // Slash bar
  const slashW = 6;
  const slashH = logoSmallSize * 0.65;
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(pad, logoY - slashH + 2, slashW, slashH);

  // PITCH
  ctx.fillStyle = '#ffffff';
  ctx.font = `800 ${logoSmallSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillText('PITCH', pad + slashW + 8, logoY);
  const pitchW = ctx.measureText('PITCH').width;

  // RANK
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('RANK', pad + slashW + 8 + pitchW, logoY);

  curY = logoY + 20;

  // === TITLE ===
  ctx.font = `800 ${titleSize}px Oswald, "Arial Black", sans-serif`;
  ctx.textAlign = 'left';
  ctx.fillStyle = '#ffffff';
  ctx.fillText('WHO DOMINATES THE', pad, curY + titleSize);
  curY += titleSize + 8;
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillText('TOP 100?', pad, curY + titleSize);

  // "GIRLS" tag next to TOP 100
  const top100W = ctx.measureText('TOP 100?').width;
  ctx.font = `600 ${titleSize * 0.5}px Oswald, "Arial Black", sans-serif`;
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.fillText('GIRLS', pad + top100W + 16, curY + titleSize);

  curY += titleSize + 6;

  // Subtitle
  ctx.font = `500 ${subtitleSize}px "DM Sans", sans-serif`;
  ctx.fillStyle = 'rgba(255,255,255,0.55)';
  ctx.fillText(
    'League breakdown of the top 100 nationally ranked female teams per age group',
    pad,
    curY + subtitleSize
  );
  curY += subtitleSize + 28;

  // Accent line
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(pad, curY, 80, 3);
  curY += 20;

  // === CHART AREA ===
  const chartLeft = pad + (isVertical ? 80 : isSquare ? 70 : 60);
  const chartRight = W - pad;
  const chartW = chartRight - chartLeft;

  // Column headers: age group label + bar + percentage annotations
  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const rowY = curY + i * (barHeight + barGap);

    // Age group label
    ctx.font = `700 ${labelSize}px Oswald, "Arial Black", sans-serif`;
    ctx.textAlign = 'right';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(row.ageGroup, chartLeft - 14, rowY + barHeight * 0.68);

    // Total teams count (small, below label)
    ctx.font = `400 ${statSize * 0.85}px "DM Sans", sans-serif`;
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.textAlign = 'right';
    ctx.fillText(`${row.totalActive.toLocaleString()}`, chartLeft - 14, rowY + barHeight * 0.68 + statSize);

    // Stacked bar background
    drawRoundedRect(ctx, chartLeft, rowY, chartW, barHeight, 4);
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.fill();

    // Sort leagues in canonical order for the bar
    const sortedLeagues = [...row.leagues].sort((a, b) => {
      const ai = LEAGUE_ORDER.indexOf(a.league);
      const bi = LEAGUE_ORDER.indexOf(b.league);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

    // Draw stacked segments
    let barX = chartLeft;
    const total = row.leagues.reduce((s, l) => s + l.count, 0);

    for (const seg of sortedLeagues) {
      const segW = (seg.count / total) * chartW;
      if (segW < 1) continue;

      const color = LEAGUE_COLORS[seg.league] || '#6B7280';

      // Segment fill
      ctx.save();
      drawRoundedRect(ctx, chartLeft, rowY, chartW, barHeight, 4);
      ctx.clip();
      ctx.fillStyle = color;
      ctx.fillRect(barX, rowY, segW, barHeight);

      // Subtle inner highlight
      const segGrad = ctx.createLinearGradient(barX, rowY, barX, rowY + barHeight);
      segGrad.addColorStop(0, 'rgba(255,255,255,0.15)');
      segGrad.addColorStop(0.5, 'transparent');
      segGrad.addColorStop(1, 'rgba(0,0,0,0.1)');
      ctx.fillStyle = segGrad;
      ctx.fillRect(barX, rowY, segW, barHeight);
      ctx.restore();

      // Label inside segment if wide enough
      const pct = Math.round((seg.count / total) * 100);
      if (segW > 44) {
        ctx.font = `700 ${statSize}px "DM Sans", sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillStyle = '#ffffff';
        ctx.textBaseline = 'middle';
        const labelText = segW > 80 ? `${seg.league === 'Unaffiliated' ? 'Other' : seg.league} ${pct}%` : `${pct}%`;
        ctx.fillText(labelText, barX + segW / 2, rowY + barHeight / 2);
        ctx.textBaseline = 'alphabetic';
      }

      barX += segW;
    }

    // Thin segment dividers
    barX = chartLeft;
    for (const seg of sortedLeagues) {
      const segW = (seg.count / total) * chartW;
      barX += segW;
      if (barX < chartRight - 1) {
        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(barX, rowY);
        ctx.lineTo(barX, rowY + barHeight);
        ctx.stroke();
      }
    }
  }

  curY += data.length * (barHeight + barGap) + 16;

  // === LEGEND ===
  const legendLeagues = LEAGUE_ORDER.filter((l) => data.some((d) => d.leagues.some((dl) => dl.league === l)));

  ctx.font = `600 ${statSize}px "DM Sans", sans-serif`;
  const legendItemWidths = legendLeagues.map((l) => {
    const label = l === 'Unaffiliated' ? 'Other / Regional' : l;
    return legendDotSize + 6 + ctx.measureText(label).width + 20;
  });

  // Wrap legend into rows
  const legendRows: { league: string; x: number }[][] = [];
  let currentRow: { league: string; x: number }[] = [];
  let rowX = pad;
  const maxLegendW = W - pad * 2;

  for (let i = 0; i < legendLeagues.length; i++) {
    if (rowX + legendItemWidths[i] > pad + maxLegendW && currentRow.length > 0) {
      legendRows.push(currentRow);
      currentRow = [];
      rowX = pad;
    }
    currentRow.push({ league: legendLeagues[i], x: rowX });
    rowX += legendItemWidths[i];
  }
  if (currentRow.length > 0) legendRows.push(currentRow);

  const legendRowH = legendDotSize + 14;
  for (let ri = 0; ri < legendRows.length; ri++) {
    const ly = curY + ri * legendRowH;
    for (const item of legendRows[ri]) {
      const color = LEAGUE_COLORS[item.league] || '#6B7280';

      // Dot
      drawRoundedRect(ctx, item.x, ly, legendDotSize, legendDotSize, 2);
      ctx.fillStyle = color;
      ctx.fill();

      // Label
      ctx.font = `500 ${statSize}px "DM Sans", sans-serif`;
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      const label = item.league === 'Unaffiliated' ? 'Other / Regional' : item.league;
      ctx.fillText(label, item.x + legendDotSize + 6, ly + legendDotSize - 1);
    }
  }

  curY += legendRows.length * legendRowH + 20;

  // === INSIGHT CALLOUTS ===
  const insights = [
    { icon: '▸', text: 'ECNL owns 39-46% of every top 100 from U13-U19' },
    { icon: '▸', text: 'GA holds steady at 9-13% across all age groups' },
    { icon: '▸', text: 'ECNL RL grows from 7% (U14) to 13% (U16+)' },
  ];

  // Only show insights if there's room
  const insightH = statSize + 10;
  const insightsNeeded = insights.length * insightH + 10;
  const footerNeeded = 50;

  if (curY + insightsNeeded + footerNeeded < H - pad) {
    ctx.fillStyle = 'rgba(255,255,255,0.04)';
    drawRoundedRect(ctx, pad, curY, W - pad * 2, insightsNeeded + 12, 6);
    ctx.fill();

    for (let i = 0; i < insights.length; i++) {
      const iy = curY + 12 + i * insightH;
      ctx.font = `600 ${statSize}px "DM Sans", sans-serif`;
      ctx.textAlign = 'left';
      ctx.fillStyle = BRAND_COLORS.electricYellow;
      ctx.fillText(insights[i].icon, pad + 12, iy + statSize);
      ctx.fillStyle = 'rgba(255,255,255,0.65)';
      ctx.fillText(insights[i].text, pad + 28, iy + statSize);
    }
    curY += insightsNeeded + 20;
  }

  // === FOOTER ===
  const footerY = H - pad;

  // Date
  const dateStr = generatedDate
    ? new Date(generatedDate).toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      })
    : new Date().toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      });

  ctx.font = `400 ${statSize * 0.9}px "DM Sans", sans-serif`;
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.fillText(dateStr, pad, footerY);

  // pitchrank.com
  ctx.textAlign = 'right';
  ctx.font = `600 ${statSize}px Oswald, "Arial Black", sans-serif`;
  ctx.fillStyle = 'rgba(255,255,255,0.35)';
  ctx.fillText('pitchrank.com', W - pad, footerY);

  // Top border accent line
  ctx.fillStyle = BRAND_COLORS.electricYellow;
  ctx.fillRect(0, 0, W, 4);

  return canvas;
}

export function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Canvas toBlob failed'));
      },
      'image/png',
      1.0
    );
  });
}
