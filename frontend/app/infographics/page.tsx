'use client';

import React, { useRef, useState, useCallback, useEffect } from 'react';
import html2canvas from 'html2canvas';
import { Top10Infographic, PLATFORM_DIMENSIONS, Platform } from '@/components/infographics';
import { useRankings } from '@/hooks/useRankings';
import { US_STATES } from '@/lib/constants';
import { Download, Share2, RefreshCw, Instagram, Facebook, ChevronDown, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';

// X/Twitter icon
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
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [previewScale, setPreviewScale] = useState(0.4);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [canShare, setCanShare] = useState(false);

  // Ref for the HIDDEN full-size capture element
  const captureRef = useRef<HTMLDivElement>(null);

  // Check Web Share API availability
  useEffect(() => {
    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
      // Test if we can share files
      try {
        const testFile = new File(['test'], 'test.png', { type: 'image/png' });
        if (typeof navigator.canShare === 'function' && navigator.canShare({ files: [testFile] })) {
          setCanShare(true);
        }
      } catch {
        // Share API not fully supported
        setCanShare(false);
      }
    }
  }, []);

  // Fetch rankings
  const { data: rankings, isLoading, error, refetch } = useRankings(
    selectedRegion,
    selectedAgeGroup,
    selectedGender
  );

  // Calculate preview scale
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

  const getRegionName = useCallback(() => {
    if (!selectedRegion) return 'National';
    const state = US_STATES.find(s => s.code.toLowerCase() === selectedRegion.toLowerCase());
    return state?.name || selectedRegion.toUpperCase();
  }, [selectedRegion]);

  const getFilename = useCallback(() => {
    const timestamp = new Date().toISOString().split('T')[0];
    const genderLabel = selectedGender === 'M' ? 'boys' : 'girls';
    const regionLabel = selectedRegion || 'national';
    return `pitchrank-${selectedAgeGroup}-${genderLabel}-top10-${regionLabel}-${selectedPlatform}-${timestamp}.png`;
  }, [selectedAgeGroup, selectedGender, selectedRegion, selectedPlatform]);

  // Helper function to sanitize CSS values that use unsupported color functions
  const sanitizeElement = useCallback((element: Element) => {
    if (element instanceof HTMLElement) {
      const style = element.style;
      const computedStyle = window.getComputedStyle(element);

      // List of CSS properties that might contain color values
      const colorProperties = [
        'color', 'backgroundColor', 'borderColor', 'borderTopColor',
        'borderRightColor', 'borderBottomColor', 'borderLeftColor',
        'outlineColor', 'textDecorationColor', 'caretColor',
        'boxShadow', 'textShadow', 'fill', 'stroke'
      ];

      colorProperties.forEach(prop => {
        const cssProperty = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
        const value = computedStyle.getPropertyValue(cssProperty);
        if (value && (value.includes('oklch') || value.includes('lab(') || value.includes('lch('))) {
          // Reset to a safe fallback color or transparent
          if (prop === 'backgroundColor') {
            style.backgroundColor = 'transparent';
          } else if (prop === 'color') {
            style.color = '#FFFFFF';
          } else if (prop.includes('border')) {
            style.setProperty(cssProperty, 'transparent');
          } else {
            style.setProperty(cssProperty, 'none');
          }
        }
      });

      // Also check CSS variables in the style attribute
      const cssText = style.cssText;
      if (cssText && (cssText.includes('oklch') || cssText.includes('lab(') || cssText.includes('lch('))) {
        // Remove problematic CSS variables
        style.cssText = cssText.replace(/[^;]*(?:oklch|lab\(|lch\()[^;]*/g, '');
      }
    }

    // Recursively process children
    Array.from(element.children).forEach(child => sanitizeElement(child));
  }, []);

  // Generate canvas from the hidden full-size element
  const generateImage = useCallback(async (): Promise<Blob | null> => {
    setErrorMessage(null);

    // Check if we have data
    if (!rankings || rankings.length === 0) {
      setErrorMessage('No team data available to generate image.');
      return null;
    }

    // Check if capture element exists
    if (!captureRef.current) {
      setErrorMessage('Capture element not ready. Please try again.');
      return null;
    }

    const dimensions = PLATFORM_DIMENSIONS[selectedPlatform];

    try {
      console.log('Starting image generation...');
      console.log('Capture element:', captureRef.current);
      console.log('Dimensions:', dimensions);

      const canvas = await html2canvas(captureRef.current, {
        width: dimensions.width,
        height: dimensions.height,
        scale: 2,
        useCORS: true,
        allowTaint: true,
        backgroundColor: '#052E27',
        logging: false,
        onclone: (clonedDoc, element) => {
          console.log('Cloned element:', element);

          // Remove only internal stylesheets that contain oklch/lab colors
          // Keep Google Fonts stylesheets (external links to fonts.googleapis.com)
          const stylesheets = clonedDoc.querySelectorAll('style');
          stylesheets.forEach(sheet => {
            // Remove internal style tags that might have oklch colors
            if (sheet.textContent && (
              sheet.textContent.includes('oklch') ||
              sheet.textContent.includes('lab(') ||
              sheet.textContent.includes('lch(')
            )) {
              sheet.remove();
            }
          });

          // For link stylesheets, only remove non-font ones
          const linkSheets = clonedDoc.querySelectorAll('link[rel="stylesheet"]');
          linkSheets.forEach(link => {
            const href = link.getAttribute('href') || '';
            // Keep Google Fonts, remove others that might have oklch
            if (!href.includes('fonts.googleapis.com') && !href.includes('fonts.gstatic.com')) {
              link.remove();
            }
          });

          // Inject Google Fonts and reset stylesheet
          const resetStyle = clonedDoc.createElement('style');
          resetStyle.textContent = `
            @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700;800&display=swap');
            @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
            @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

            * {
              box-sizing: border-box;
              -webkit-font-smoothing: antialiased;
              -moz-osx-font-smoothing: grayscale;
            }
            /* Override any CSS variables that might use oklch */
            :root {
              --background: #052E27;
              --foreground: #FDFEFE;
              --primary: #0B5345;
              --primary-foreground: #FDFEFE;
              --secondary: #F4D03F;
              --muted: #2C3E50;
              --muted-foreground: rgba(255, 255, 255, 0.6);
              --accent: #F4D03F;
              --border: rgba(255, 255, 255, 0.1);
            }
          `;
          clonedDoc.head.appendChild(resetStyle);

          // Sanitize any remaining inline styles that might have problematic colors
          sanitizeElement(element);

          // Ensure the cloned element has proper dimensions
          element.style.transform = 'none';
          element.style.width = `${dimensions.width}px`;
          element.style.height = `${dimensions.height}px`;
          element.style.position = 'relative';
          element.style.left = '0';
          element.style.top = '0';
        }
      });

      console.log('Canvas generated:', canvas.width, 'x', canvas.height);

      // Convert canvas to blob
      return new Promise((resolve, reject) => {
        canvas.toBlob(
          (blob) => {
            if (blob) {
              console.log('Blob created:', blob.size, 'bytes');
              resolve(blob);
            } else {
              reject(new Error('Failed to create image blob'));
            }
          },
          'image/png',
          1.0
        );
      });
    } catch (err) {
      console.error('Error in generateImage:', err);
      const errorMsg = err instanceof Error ? err.message : 'Unknown error occurred';
      setErrorMessage(`Failed to generate image: ${errorMsg}`);
      return null;
    }
  }, [rankings, selectedPlatform, sanitizeElement]);

  // Handle download
  const handleDownload = useCallback(async () => {
    if (isGenerating) return;

    setIsGenerating(true);
    setErrorMessage(null);

    try {
      const blob = await generateImage();
      if (!blob) {
        setIsGenerating(false);
        return;
      }

      // Create download link
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = getFilename();

      // Append to body, click, and remove
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // Clean up URL after a delay
      setTimeout(() => URL.revokeObjectURL(url), 5000);

      console.log('Download initiated');
    } catch (err) {
      console.error('Download error:', err);
      setErrorMessage('Failed to download. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  }, [isGenerating, generateImage, getFilename]);

  // Handle share
  const handleShare = useCallback(async () => {
    if (isGenerating) return;

    setIsGenerating(true);
    setErrorMessage(null);

    try {
      const blob = await generateImage();
      if (!blob) {
        setIsGenerating(false);
        return;
      }

      const file = new File([blob], getFilename(), { type: 'image/png' });
      const genderText = selectedGender === 'M' ? 'Boys' : 'Girls';
      const shareText = `Check out the Top 10 ${selectedAgeGroup.toUpperCase()} ${genderText} ${getRegionName()} Soccer Rankings! #YouthSoccer #${selectedAgeGroup.toUpperCase()}Soccer`;

      if (canShare && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: `PitchRank - ${selectedAgeGroup.toUpperCase()} ${genderText} Rankings`,
          text: shareText,
          files: [file],
        });
        console.log('Share completed');
      } else {
        // Fallback to download
        console.log('Share not available, falling back to download');
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = getFilename();
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }
    } catch (err) {
      // Don't show error if user just cancelled the share
      if (err instanceof Error && err.name === 'AbortError') {
        console.log('Share cancelled by user');
      } else {
        console.error('Share error:', err);
        setErrorMessage('Failed to share. Trying download instead...');
        // Try download as fallback
        try {
          const blob = await generateImage();
          if (blob) {
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = getFilename();
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(() => URL.revokeObjectURL(url), 5000);
          }
        } catch {
          setErrorMessage('Failed to share or download. Please try again.');
        }
      }
    } finally {
      setIsGenerating(false);
    }
  }, [isGenerating, generateImage, getFilename, selectedGender, selectedAgeGroup, getRegionName, canShare]);

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

      {/* HIDDEN: Full-size capture element - this is what we actually capture */}
      <div
        style={{
          position: 'absolute',
          left: '-9999px',
          top: 0,
          width: `${dimensions.width}px`,
          height: `${dimensions.height}px`,
          overflow: 'hidden',
        }}
        aria-hidden="true"
      >
        {top10Teams.length > 0 && (
          <Top10Infographic
            ref={captureRef}
            teams={top10Teams}
            platform={selectedPlatform}
            scale={1} // Full size for capture
            generatedDate={new Date().toISOString()}
            ageGroup={selectedAgeGroup}
            gender={selectedGender}
            region={selectedRegion}
            regionName={getRegionName()}
          />
        )}
      </div>

      {/* Error Message */}
      {errorMessage && (
        <div className="mb-4 p-4 bg-destructive/10 border border-destructive/30 rounded-lg flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-destructive font-medium">Error</p>
            <p className="text-sm text-destructive/80">{errorMessage}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-8">
        {/* Controls Panel */}
        <div className="lg:col-span-1 space-y-6">
          {/* Rankings Selection */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Select Rankings</CardTitle>
              <CardDescription>Choose age group, gender, and region</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Age Group */}
              <div>
                <label className="block text-sm font-medium mb-2">Age Group</label>
                <div className="relative">
                  <select
                    value={selectedAgeGroup}
                    onChange={(e) => setSelectedAgeGroup(e.target.value)}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {AGE_GROUPS.map((age) => (
                      <option key={age.value} value={age.value}>{age.label}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </div>

              {/* Gender */}
              <div>
                <label className="block text-sm font-medium mb-2">Gender</label>
                <div className="relative">
                  <select
                    value={selectedGender}
                    onChange={(e) => setSelectedGender(e.target.value as GenderType)}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {GENDERS.map((g) => (
                      <option key={g.value} value={g.value}>{g.label}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </div>

              {/* Region */}
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
                        <option key={state.code} value={state.code}>{state.name}</option>
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
              <CardDescription>Choose the social media format</CardDescription>
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
                    {PLATFORM_DIMENSIONS[platform.id].width}x{PLATFORM_DIMENSIONS[platform.id].height}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>

          {/* Info */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Category</span>
                <span className="font-medium">{categoryLabel}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Teams</span>
                <span className="font-medium">Top 10</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Size</span>
                <span className="font-mono text-xs">{dimensions.width}x{dimensions.height}px</span>
              </div>
            </CardContent>
          </Card>

          {/* Actions - Desktop */}
          <div className="hidden lg:block space-y-3">
            <Button
              onClick={canShare ? handleShare : handleDownload}
              disabled={isGenerating || isLoading || top10Teams.length === 0}
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              size="lg"
            >
              {isGenerating ? (
                <><RefreshCw className="mr-2 h-4 w-4 animate-spin" />Generating...</>
              ) : canShare ? (
                <><Share2 className="mr-2 h-4 w-4" />Share to Apps</>
              ) : (
                <><Download className="mr-2 h-4 w-4" />Download PNG</>
              )}
            </Button>

            {canShare && (
              <Button
                onClick={handleDownload}
                disabled={isGenerating || isLoading || top10Teams.length === 0}
                variant="outline"
                className="w-full"
                size="lg"
              >
                <Download className="mr-2 h-4 w-4" />Save to Device
              </Button>
            )}

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
                <Share2 size={16} />Tips
              </h4>
              <ul className="text-sm space-y-2 text-muted-foreground">
                <li>Tap the button to {canShare ? 'share directly to Instagram, Twitter, etc.' : 'download the image'}</li>
                <li>Use hashtags: #YouthSoccer #{selectedAgeGroup.toUpperCase()}Soccer</li>
                <li>Best posting times: Tuesday-Thursday</li>
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
                {isLoading ? 'Loading...' : error ? 'Error loading data' : `Top ${top10Teams.length} ${categoryLabel} teams`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                className="overflow-auto bg-muted/30 rounded-lg p-4 flex justify-center items-center"
                style={{ minHeight: `${dimensions.height * previewScale + 40}px` }}
              >
                {isLoading ? (
                  <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
                ) : error ? (
                  <p className="text-destructive">Failed to load rankings</p>
                ) : top10Teams.length === 0 ? (
                  <div className="text-center text-muted-foreground">
                    <p className="font-medium mb-2">No teams found</p>
                    <p className="text-sm">Try a different selection</p>
                  </div>
                ) : (
                  <div style={{ width: dimensions.width * previewScale, height: dimensions.height * previewScale, overflow: 'hidden' }}>
                    <Top10Infographic
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

          {/* Teams List */}
          {top10Teams.length > 0 && (
            <Card className="mt-6">
              <CardHeader>
                <CardTitle className="text-lg">Featured Teams</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {top10Teams.map((team, i) => (
                    <div key={team.team_id_master} className="flex items-center gap-4 py-2 px-3 rounded-lg bg-muted/30">
                      <span className="font-mono font-bold text-lg w-8 text-center text-primary">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold truncate">{team.team_name}</div>
                        <div className="text-sm text-muted-foreground">{team.club_name ? `${team.club_name} | ` : ''}{team.state || 'N/A'}</div>
                      </div>
                      <div className="text-right text-sm">
                        <div className="font-mono">{team.total_wins ?? team.wins}-{team.total_losses ?? team.losses}-{team.total_draws ?? team.draws}</div>
                        <div className="text-xs text-muted-foreground">Score: {(team.power_score_final * 100).toFixed(1)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Mobile Sticky Buttons */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 p-4 bg-background/95 backdrop-blur border-t z-50">
        <div className="flex gap-2">
          <Button
            onClick={canShare ? handleShare : handleDownload}
            disabled={isGenerating || isLoading || top10Teams.length === 0}
            className="flex-1 bg-primary hover:bg-primary/90 text-primary-foreground"
            size="lg"
          >
            {isGenerating ? (
              <><RefreshCw className="mr-2 h-4 w-4 animate-spin" />Generating...</>
            ) : canShare ? (
              <><Share2 className="mr-2 h-4 w-4" />Share</>
            ) : (
              <><Download className="mr-2 h-4 w-4" />Download</>
            )}
          </Button>
          {canShare && (
            <Button
              onClick={handleDownload}
              disabled={isGenerating || isLoading || top10Teams.length === 0}
              variant="outline"
              size="lg"
            >
              <Download className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="lg:hidden h-24" />
    </div>
  );
}
