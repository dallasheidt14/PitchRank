import type { ReactNode } from 'react';
import { COLORS } from './theme';
import { wordmarkUrl, WORDMARK_ASPECT } from './assets';

// Divider + pitchrank.io/rankings line that closes every infographic.
export function Footer({ isStory }: { isStory: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', marginTop: isStory ? 28 : 18 }}>
      <div style={{ display: 'flex', height: 2, background: COLORS.divider, marginBottom: 16 }} />
      <div style={{ display: 'flex', justifyContent: 'center', fontSize: isStory ? 20 : 17, color: COLORS.club }}>
        pitchrank.io/rankings
      </div>
    </div>
  );
}

// Root frame: gradient + scan-line texture overlay + (consumer-supplied) content.
export function Frame({ isStory, children }: { isStory: boolean; children: ReactNode }) {
  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        padding: isStory ? 64 : 56,
        background: `linear-gradient(135deg, ${COLORS.forestGreen} 0%, ${COLORS.darkGreen} 100%)`,
        fontFamily: 'DM Sans, sans-serif',
      }}
    >
      {/* Subtle scan-line texture for depth. If Satori ever rejects the repeating
          gradient (0-byte render), delete this overlay — the gradient alone is the fallback. */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          backgroundImage:
            'repeating-linear-gradient(0deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.02) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 3px)',
        }}
      />
      {children}
    </div>
  );
}

export function Header({
  origin,
  isStory,
  title,
  subtitle,
}: {
  origin: string;
  isStory: boolean;
  title: string;
  subtitle: string;
}) {
  const logoW = isStory ? 380 : 320;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: isStory ? 44 : 30 }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={wordmarkUrl(origin)} width={logoW} height={Math.round(logoW * WORDMARK_ASPECT)} alt="" />
      <div
        style={{
          display: 'flex',
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 60 : 50,
          color: COLORS.electricYellow,
          letterSpacing: 1,
          marginTop: 22,
          textAlign: 'center',
        }}
      >
        {title}
      </div>
      <div style={{ display: 'flex', fontSize: isStory ? 24 : 20, color: COLORS.date, marginTop: 10 }}>{subtitle}</div>
    </div>
  );
}

// One stat column on the right of a row (e.g. W-L-D, SCORE, change).
export function StatBlock({
  value,
  label,
  color,
  isStory,
  width,
}: {
  value: string;
  label: string;
  color: string;
  isStory: boolean;
  width: number;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width }}>
      <div style={{ display: 'flex', fontWeight: 700, fontSize: isStory ? 26 : 22, color }}>{value}</div>
      {label ? (
        <div
          style={{ display: 'flex', fontSize: isStory ? 13 : 11, color: COLORS.label, letterSpacing: 1, marginTop: 2 }}
        >
          {label}
        </div>
      ) : null}
    </div>
  );
}

export function RankRow({
  rank,
  accent,
  teamName,
  club,
  isStory,
  fluid = false,
  children,
}: {
  rank: number;
  accent: string | null;
  teamName: string;
  club: string;
  isStory: boolean;
  fluid?: boolean;
  children: ReactNode;
}) {
  const nameSize = isStory ? 28 : 23;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        // Fluid rows size to their own content (1 or 2 lines) and stay vertically
        // centered, so a long team name never clips or knocks the rank/stat columns
        // out of alignment. Fixed layouts keep the original equal-height fill.
        ...(fluid ? { flexShrink: 0 } : { flex: 1 }),
        background: accent ? COLORS.rowTop3 : COLORS.rowDim,
        borderLeft: `5px solid ${accent ?? COLORS.rowBorderDim}`,
        borderRadius: 10,
        padding: fluid ? (isStory ? '16px 26px' : '13px 22px') : isStory ? '0 26px' : '0 22px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          width: isStory ? 64 : 54,
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 40 : 34,
          color: accent ?? COLORS.brightWhite,
        }}
      >
        {`${rank}`}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, marginLeft: 18, overflow: 'hidden' }}>
        <div
          style={{
            display: 'flex',
            fontFamily: 'Oswald',
            fontWeight: 600,
            fontSize: nameSize,
            color: COLORS.brightWhite,
            // Cap at two lines so a pathologically long name can't grow unbounded.
            ...(fluid ? { maxHeight: Math.round(nameSize * 1.3 * 2), overflow: 'hidden' } : {}),
          }}
        >
          {teamName}
        </div>
        <div
          style={{
            display: 'flex',
            fontSize: isStory ? 17 : 14,
            color: COLORS.club,
            marginTop: 3,
            ...(fluid ? { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } : {}),
          }}
        >
          {club}
        </div>
      </div>
      {children}
    </div>
  );
}
