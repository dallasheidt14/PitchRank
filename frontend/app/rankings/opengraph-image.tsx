import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'Youth Soccer Rankings | PitchRank';
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
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Subtle soccer field lines */}
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '400px',
            height: '400px',
            borderRadius: '50%',
            border: '2px solid rgba(200, 255, 0, 0.08)',
            display: 'flex',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: '0',
            left: '50%',
            transform: 'translateX(-50%)',
            width: '2px',
            height: '100%',
            background: 'rgba(200, 255, 0, 0.06)',
            display: 'flex',
          }}
        />

        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '20px',
            zIndex: 1,
          }}
        >
          <div
            style={{
              fontSize: '80px',
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
              fontSize: '36px',
              fontWeight: 600,
              color: '#FFFFFF',
              letterSpacing: '6px',
              textTransform: 'uppercase',
            }}
          >
            Youth Soccer Rankings
          </div>
          <div
            style={{
              marginTop: '12px',
              fontSize: '24px',
              color: '#C8FF00',
              letterSpacing: '2px',
              textTransform: 'uppercase',
              fontWeight: 500,
              opacity: 0.9,
            }}
          >
            Find Your Team
          </div>
          <div
            style={{
              marginTop: '8px',
              fontSize: '18px',
              color: '#A0A0A0',
              maxWidth: '600px',
              textAlign: 'center',
              lineHeight: 1.5,
            }}
          >
            U10–U19 Boys & Girls · National & State Rankings · Updated Weekly
          </div>
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: '32px',
            fontSize: '16px',
            color: '#666',
            display: 'flex',
          }}
        >
          pitchrank.io/rankings
        </div>
      </div>
    ),
    { ...size }
  );
}
