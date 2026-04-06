'use client';

import React, { useState, useCallback } from 'react';
import { LeagueDistributionPreview, PLATFORM_DIMENSIONS, Platform } from '@/components/infographics';
import { renderLeagueDistributionToCanvas, canvasToBlob } from '@/components/infographics/leagueDistributionRenderer';
import { Download, ChevronDown } from 'lucide-react';
import { Instagram, Facebook } from '@/components/ui/brand-icons';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/PageHeader';

const XIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

const platforms: { id: Platform; label: string; icon: React.ReactNode }[] = [
  { id: 'instagram', label: 'Instagram Post', icon: <Instagram size={18} /> },
  { id: 'instagramStory', label: 'Instagram Story', icon: <Instagram size={18} /> },
  { id: 'twitter', label: 'Twitter/X Post', icon: <XIcon /> },
  { id: 'facebook', label: 'Facebook Post', icon: <Facebook size={18} /> },
];

export default function LeagueDistributionPage() {
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>('instagram');
  const [isDownloading, setIsDownloading] = useState(false);
  const [showPlatformDropdown, setShowPlatformDropdown] = useState(false);

  const dimensions = PLATFORM_DIMENSIONS[selectedPlatform];

  const handleDownload = useCallback(async () => {
    setIsDownloading(true);
    try {
      const canvas = await renderLeagueDistributionToCanvas({
        platform: selectedPlatform,
      });
      const blob = await canvasToBlob(canvas);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `pitchrank-league-distribution-girls-${selectedPlatform}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download failed:', err);
    } finally {
      setIsDownloading(false);
    }
  }, [selectedPlatform]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <PageHeader
          title="League Distribution"
          description="Who dominates the top 100 girls nationally? League breakdown by age group."
        />

        <div className="mt-8 flex flex-col lg:flex-row gap-8">
          {/* Controls */}
          <div className="lg:w-72 space-y-4 flex-shrink-0">
            {/* Platform selector */}
            <div>
              <label className="text-sm font-medium text-muted-foreground mb-2 block">Platform</label>
              <div className="relative">
                <button
                  onClick={() => setShowPlatformDropdown(!showPlatformDropdown)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-border bg-card text-sm hover:bg-accent/10 transition-colors"
                >
                  <span className="flex items-center gap-2">
                    {platforms.find((p) => p.id === selectedPlatform)?.icon}
                    {platforms.find((p) => p.id === selectedPlatform)?.label}
                  </span>
                  <ChevronDown size={16} />
                </button>
                {showPlatformDropdown && (
                  <div className="absolute z-10 mt-1 w-full rounded-lg border border-border bg-card shadow-lg">
                    {platforms.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => {
                          setSelectedPlatform(p.id);
                          setShowPlatformDropdown(false);
                        }}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent/10 transition-colors first:rounded-t-lg last:rounded-b-lg ${
                          selectedPlatform === p.id ? 'bg-accent/10 font-medium' : ''
                        }`}
                      >
                        {p.icon}
                        {p.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Dimensions info */}
            <div className="text-xs text-muted-foreground bg-muted/50 rounded-lg px-3 py-2">
              {dimensions.width} × {dimensions.height}px ({dimensions.aspectRatio})
            </div>

            {/* Download button */}
            <Button onClick={handleDownload} disabled={isDownloading} className="w-full" size="lg">
              <Download size={18} />
              {isDownloading ? 'Generating...' : 'Download PNG'}
            </Button>
          </div>

          {/* Preview */}
          <div className="flex-1 flex justify-center">
            <div
              className="border border-border rounded-lg overflow-hidden shadow-xl bg-black"
              style={{
                width: dimensions.width * 0.5,
                height: dimensions.height * 0.5,
              }}
            >
              <LeagueDistributionPreview platform={selectedPlatform} scale={0.5} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
