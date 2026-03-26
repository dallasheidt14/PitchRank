import { Metadata } from 'next';

export const metadata: Metadata = {
  robots: {
    index: false,
    follow: true,
  },
};

/**
 * Minimal layout for embed pages - no navigation, no footer
 * Designed to be iframe-friendly
 */
export default function EmbedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="embed-wrapper" style={{
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      fontSize: '14px',
      lineHeight: 1.5,
      color: '#1a1a1a',
      background: '#fff',
    }}>
      {children}
    </div>
  );
}
