import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'PitchRank — Youth Soccer Rankings';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: 'linear-gradient(135deg, #052E27 0%, #0A4A3F 50%, #0D5C4E 100%)',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '24px',
          }}
        >
          <div
            style={{
              fontSize: '72px',
              fontWeight: 800,
              color: '#C8FF00',
              letterSpacing: '-2px',
              textTransform: 'uppercase',
            }}
          >
            PitchRank
          </div>
          <div
            style={{
              fontSize: '32px',
              fontWeight: 400,
              color: '#E0E0E0',
              letterSpacing: '4px',
              textTransform: 'uppercase',
            }}
          >
            Youth Soccer Rankings
          </div>
          <div
            style={{
              marginTop: '16px',
              fontSize: '20px',
              color: '#A0A0A0',
              maxWidth: '700px',
              textAlign: 'center',
              lineHeight: 1.5,
            }}
          >
            Data-powered team rankings and performance analytics.
            U10–U18 Boys & Girls across all 50 states.
          </div>
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: '32px',
            fontSize: '16px',
            color: '#666',
          }}
        >
          pitchrank.io
        </div>
      </div>
    ),
    { ...size }
  );
}
