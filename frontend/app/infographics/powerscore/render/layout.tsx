import '@/app/globals.css';

/**
 * Minimal layout for infographic rendering - no nav, no footer, no chrome
 */
export default function RenderLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link 
          href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;600;700;800&family=DM+Sans:wght@400;500;600;700&display=swap" 
          rel="stylesheet" 
        />
        <style>{`
          body { 
            margin: 0 !important; 
            padding: 0 !important; 
            background: transparent !important;
            overflow: hidden !important;
          }
          /* Hide Next.js dev indicators */
          [data-nextjs-dialog-overlay],
          [data-nextjs-dialog],
          nextjs-portal,
          #__next-build-indicator,
          .nextjs-toast-errors-parent {
            display: none !important;
          }
        `}</style>
      </head>
      <body style={{ margin: 0, padding: 0 }}>
        {children}
      </body>
    </html>
  );
}
