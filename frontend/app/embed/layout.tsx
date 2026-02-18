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
    <html lang="en">
      <head>
        <style dangerouslySetInnerHTML={{ __html: `
          * { box-sizing: border-box; margin: 0; padding: 0; }
          body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            color: #1a1a1a;
            background: #fff;
          }
        `}} />
      </head>
      <body>
        {children}
      </body>
    </html>
  );
}
