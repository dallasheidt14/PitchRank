'use client';

import React, { useRef, useState, useCallback, useEffect } from 'react';
import html2canvas from 'html2canvas';
import { Top10Infographic, PLATFORM_DIMENSIONS, Platform } from '@/components/infographics';
import { useRankings } from '@/hooks/useRankings';
import { US_STATES } from '@/lib/constants';
import { Download, Share2, RefreshCw, Instagram, Facebook, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';

// X/Twitter icon (Lucide doesn't have the new X logo)
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

const AGE_GROUPS = [
  { value: 'u10', label: 'U10' },
  { value: 'u11', label: 'U11' },
  { value: 'u12', label: 'U12' },
  { value: 'u13', label: 'U13' },
  { value: 'u14', label: 'U14' },
  { value: 'u15', label: 'U15' },
  { value: 'u16', label: 'U16' },
  { value: 'u17', label: 'U17' },
  { value: 'u18', label: 'U18' },
];

const GENDERS = [
  { value: 'M' as const, label: 'Boys' },
  { value: 'F' as const, label: 'Girls' },
];

type GenderType = 'M' | 'F';

export default function InfographicsPage() {
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>('instagram');
  const [selectedAgeGroup, setSelectedAgeGroup] = useState('u12');
  const [selectedGender, setSelectedGender] = useState<GenderType>('M');
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null); // null = national
  const [isGenerating, setIsGenerating] = useState(false);
  const [previewScale, setPreviewScale] = useState(0.4);
  const infographicRef = useRef<HTMLDivElement>(null);

  // Fetch rankings based on selections
  const { data: rankings, isLoading, error, refetch } = useRankings(
    selectedRegion,
    selectedAgeGroup,
    selectedGender
  );

  // Calculate preview scale based on viewport
  useEffect(() => {
    const updateScale = () => {
      const maxWidth = Math.min(window.innerWidth - 80, 600);
      const dimensions = PLATFORM_DIMENSIONS[selectedPlatform];
      const scale = maxWidth / dimensions.width;
      setPreviewScale(Math.min(scale, 0.6));
    };

    updateScale();
    window.addEventListener('resize', updateScale);
    return () => window.removeEventListener('resize', updateScale);
  }, [selectedPlatform]);

  // Get region name for display
  const getRegionName = () => {
    if (!selectedRegion) return 'National';
    const state = US_STATES.find(s => s.code.toLowerCase() === selectedRegion.toLowerCase());
    return state?.name || selectedRegion.toUpperCase();
  };

  // Generate filename
  const getFilename = () => {
    const timestamp = new Date().toISOString().split('T')[0];
    const genderLabel = selectedGender === 'M' ? 'boys' : 'girls';
    const regionLabel = selectedRegion || 'national';
    return `pitchrank-${selectedAgeGroup}-${genderLabel}-top10-${regionLabel}-${selectedPlatform}-${timestamp}.png`;
  };

  const handleDownload = useCallback(async () => {
    if (!infographicRef.current || !rankings?.length) return;

    setIsGenerating(true);
    try {
      const dimensions = PLATFORM_DIMENSIONS[selectedPlatform];

      // Create a full-size clone for rendering
      const clone = infographicRef.current.cloneNode(true) as HTMLElement;
      clone.style.transform = 'scale(1)';
      clone.style.transformOrigin = 'top left';
      clone.style.position = 'fixed';
      clone.style.left = '-9999px';
      clone.style.top = '0';
      document.body.appendChild(clone);

      const canvas = await html2canvas(clone, {
        width: dimensions.width,
        height: dimensions.height,
        scale: 2, // 2x for high resolution
        useCORS: true,
        backgroundColor: null,
        logging: false,
      });

      document.body.removeChild(clone);

      // Download the image
      const link = document.createElement('a');
      link.download = getFilename();
      link.href = canvas.toDataURL('image/png', 1.0);
      link.click();
    } catch (err) {
      console.error('Error generating infographic:', err);
    } finally {
      setIsGenerating(false);
    }
  }, [rankings, selectedPlatform, selectedAgeGroup, selectedGender, selectedRegion]);

  const top10Teams = rankings?.slice(0, 10) || [];
  const dimensions = PLATFORM_DIMENSIONS[selectedPlatform];
  const genderLabel = selectedGender === 'M' ? 'Boys' : 'Girls';
  const categoryLabel = `${selectedAgeGroup.toUpperCase()} ${genderLabel} - ${getRegionName()}`;

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <PageHeader
        title="Social Media Infographics"
        description="Generate shareable rankings graphics for Twitter, Instagram, and Facebook"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-8">
        {/* Controls Panel */}
        <div className="lg:col-span-1 space-y-6">
          {/* Rankings Selection */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Select Rankings</CardTitle>
              <CardDescription>
                Choose age group, gender, and region
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Age Group Dropdown */}
              <div>
                <label className="block text-sm font-medium mb-2">Age Group</label>
                <div className="relative">
                  <select
                    value={selectedAgeGroup}
                    onChange={(e) => setSelectedAgeGroup(e.target.value)}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {AGE_GROUPS.map((age) => (
                      <option key={age.value} value={age.value}>
                        {age.label}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </div>

              {/* Gender Dropdown */}
              <div>
                <label className="block text-sm font-medium mb-2">Gender</label>
                <div className="relative">
                  <select
                    value={selectedGender}
                    onChange={(e) => setSelectedGender(e.target.value as GenderType)}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {GENDERS.map((gender) => (
                      <option key={gender.value} value={gender.value}>
                        {gender.label}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </div>

              {/* Region Dropdown */}
              <div>
                <label className="block text-sm font-medium mb-2">Region</label>
                <div className="relative">
                  <select
                    value={selectedRegion || ''}
                    onChange={(e) => setSelectedRegion(e.target.value || null)}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="">National</option>
                    <optgroup label="States">
                      {US_STATES.map((state) => (
                        <option key={state.code} value={state.code}>
                          {state.name}
                        </option>
                      ))}
                    </optgroup>
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Platform Selection */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Select Platform</CardTitle>
              <CardDescription>
                Choose the social media platform format
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {platforms.map((platform) => (
                <button
                  key={platform.id}
                  onClick={() => setSelectedPlatform(platform.id)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${
                    selectedPlatform === platform.id
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted hover:bg-muted/80 text-foreground'
                  }`}
                >
                  {platform.icon}
                  <span className="font-medium">{platform.label}</span>
                  <span className="ml-auto text-xs opacity-70">
                    {PLATFORM_DIMENSIONS[platform.id].width} x {PLATFORM_DIMENSIONS[platform.id].height}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          {/* Infographic Info */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Infographic Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Category</span>
                <span className="font-medium">{categoryLabel}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Teams Shown</span>
                <span className="font-medium">Top 10</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Dimensions</span>
                <span className="font-mono text-xs">
                  {dimensions.width} x {dimensions.height}px
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Aspect Ratio</span>
                <span className="font-mono text-xs">{dimensions.aspectRatio}</span>
              </div>
            </CardContent>
          </Card>

          {/* Actions */}
          <div className="space-y-3">
            <Button
              onClick={handleDownload}
              disabled={isGenerating || isLoading || !rankings?.length}
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              size="lg"
            >
              {isGenerating ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" />
                  Download PNG
                </>
              )}
            </Button>

            <Button
              onClick={() => refetch()}
              disabled={isLoading}
              variant="outline"
              className="w-full"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh Data
            </Button>
          </div>

          {/* Tips */}
          <Card className="bg-accent/10 border-accent/30">
            <CardContent className="pt-6">
              <h4 className="font-semibold mb-2 flex items-center gap-2">
                <Share2 size={16} />
                Sharing Tips
              </h4>
              <ul className="text-sm space-y-2 text-muted-foreground">
                <li>Use relevant hashtags: #YouthSoccer #{selectedAgeGroup.toUpperCase()}Soccer #SoccerRankings</li>
                <li>Post on Tuesday-Thursday for best engagement</li>
                <li>Tag team accounts for increased reach</li>
                <li>Add a compelling caption with the full rankings link</li>
              </ul>
            </CardContent>
          </Card>
        </div>

        {/* Preview Panel */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Preview</CardTitle>
              <CardDescription>
                {isLoading
                  ? 'Loading rankings data...'
                  : error
                  ? 'Error loading data'
                  : `Showing top ${top10Teams.length} ${categoryLabel} teams`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                className="overflow-auto bg-muted/30 rounded-lg p-4 flex justify-center"
                style={{
                  minHeight: `${PLATFORM_DIMENSIONS[selectedPlatform].height * previewScale + 40}px`,
                }}
              >
                {isLoading ? (
                  <div className="flex items-center justify-center h-96">
                    <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
                  </div>
                ) : error ? (
                  <div className="flex items-center justify-center h-96 text-destructive">
                    Failed to load rankings. Please try again.
                  </div>
                ) : top10Teams.length === 0 ? (
                  <div className="flex items-center justify-center h-96 text-muted-foreground text-center px-4">
                    <div>
                      <p className="font-medium mb-2">No teams found</p>
                      <p className="text-sm">
                        No {categoryLabel} teams found. Try selecting a different age group, gender, or region.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      width: `${dimensions.width * previewScale}px`,
                      height: `${dimensions.height * previewScale}px`,
                      overflow: 'hidden',
                    }}
                  >
                    <Top10Infographic
                      ref={infographicRef}
                      teams={top10Teams}
                      platform={selectedPlatform}
                      scale={previewScale}
                      generatedDate={new Date().toISOString()}
                      ageGroup={selectedAgeGroup}
                      gender={selectedGender}
                      region={selectedRegion}
                      regionName={getRegionName()}
                    />
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Top 10 Teams List */}
          {!isLoading && !error && top10Teams.length > 0 && (
            <Card className="mt-6">
              <CardHeader>
                <CardTitle className="text-lg">Featured Teams</CardTitle>
                <CardDescription>The top 10 {categoryLabel} teams shown in this infographic</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {top10Teams.map((team, index) => (
                    <div
                      key={team.team_id_master}
                      className="flex items-center gap-4 py-2 px-3 rounded-lg bg-muted/30"
                    >
                      <span className="font-mono font-bold text-lg w-8 text-center text-primary">
                        {index + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold truncate">{team.team_name}</div>
                        <div className="text-sm text-muted-foreground">
                          {team.club_name ? `${team.club_name} | ` : ''}{team.state || 'N/A'}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-mono text-sm">
                          {team.total_wins ?? team.wins}-{team.total_losses ?? team.losses}-{team.total_draws ?? team.draws}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Score: {(team.power_score_final * 100).toFixed(1)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Mobile Sticky Download Button */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 p-4 bg-background/95 backdrop-blur border-t z-50">
        <Button
          onClick={handleDownload}
          disabled={isGenerating || isLoading || !rankings?.length}
          className="w-full bg-forest-green hover:bg-forest-green/90"
          size="lg"
        >
          {isGenerating ? (
            <>
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Download className="mr-2 h-4 w-4" />
              Download PNG
            </>
          )}
        </Button>
      </div>

      {/* Bottom padding for mobile to account for sticky button */}
      <div className="lg:hidden h-20" />
    </div>
  );
}
