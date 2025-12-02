'use client';

import React, { useState, useCallback, useEffect } from 'react';
import { Top10Infographic, PLATFORM_DIMENSIONS, Platform, CaptionGenerator } from '@/components/infographics';
import { renderInfographicToCanvas, canvasToBlob } from '@/components/infographics/canvasRenderer';
import { renderTeamSpotlightToCanvas } from '@/components/infographics/teamSpotlightRenderer';
import { renderRankingMoversToCanvas, generateMoverData } from '@/components/infographics/rankingMoversRenderer';
import { renderHeadToHeadToCanvas } from '@/components/infographics/headToHeadRenderer';
import { renderStateChampionsToCanvas, generateStateChampions } from '@/components/infographics/stateChampionsRenderer';
import { renderStoryTemplateToCanvas, STORY_TYPES } from '@/components/infographics/storyTemplateRenderer';
import { renderCoverImageToCanvas, COVER_PLATFORMS } from '@/components/infographics/coverImageRenderer';
import { useRankings } from '@/hooks/useRankings';
import { US_STATES } from '@/lib/constants';
import { Download, Share2, RefreshCw, Instagram, Facebook, ChevronDown, AlertCircle, Trophy, TrendingUp, Users, Award, Megaphone, Image } from 'lucide-react';
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

type InfographicType = 'top10' | 'spotlight' | 'movers' | 'headToHead' | 'stateChampions' | 'stories' | 'covers';

const INFOGRAPHIC_TYPES: { id: InfographicType; label: string; icon: React.ReactNode; description: string }[] = [
  { id: 'top10', label: 'Top 10 Rankings', icon: <Trophy size={18} />, description: 'Classic top 10 leaderboard' },
  { id: 'spotlight', label: 'Team Spotlight', icon: <Award size={18} />, description: 'Feature a single team' },
  { id: 'movers', label: 'Biggest Movers', icon: <TrendingUp size={18} />, description: 'Teams rising & falling' },
  { id: 'headToHead', label: 'Head-to-Head', icon: <Users size={18} />, description: 'Compare two teams' },
  { id: 'stateChampions', label: 'State Champions', icon: <Award size={18} />, description: '#1 team from each state' },
  { id: 'stories', label: 'Story Templates', icon: <Megaphone size={18} />, description: 'Instagram story announcements' },
  { id: 'covers', label: 'Cover Images', icon: <Image size={18} />, description: 'Social media headers' },
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
  const [selectedInfographicType, setSelectedInfographicType] = useState<InfographicType>('top10');
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>('instagram');
  const [selectedAgeGroup, setSelectedAgeGroup] = useState('u12');
  const [selectedGender, setSelectedGender] = useState<GenderType>('M');
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [previewScale, setPreviewScale] = useState(0.4);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [canShare, setCanShare] = useState(false);

  // Additional options for different infographic types
  const [selectedSpotlightTeamIndex, setSelectedSpotlightTeamIndex] = useState(0);
  const [headToHeadTeam1Index, setHeadToHeadTeam1Index] = useState(0);
  const [headToHeadTeam2Index, setHeadToHeadTeam2Index] = useState(1);
  const [selectedStoryType, setSelectedStoryType] = useState<'newRankings' | 'comingSoon' | 'teamAnnouncement' | 'weeklyUpdate'>('newRankings');
  const [selectedCoverPlatform, setSelectedCoverPlatform] = useState<'twitter' | 'facebook' | 'linkedin'>('twitter');

  // Preview image for canvas-based infographics
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);

  // Check Web Share API availability
  useEffect(() => {
    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
      try {
        const testFile = new File(['test'], 'test.png', { type: 'image/png' });
        if (typeof navigator.canShare === 'function' && navigator.canShare({ files: [testFile] })) {
          setCanShare(true);
        }
      } catch {
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

  // Generate preview for canvas-based infographics
  useEffect(() => {
    // Skip for top10 (uses React component), covers, and stories
    if (selectedInfographicType === 'top10' || selectedInfographicType === 'covers' || selectedInfographicType === 'stories') {
      setPreviewImageUrl(null);
      return;
    }

    // Need rankings for other types
    if (!rankings || rankings.length === 0) {
      setPreviewImageUrl(null);
      return;
    }

    const generatePreview = async () => {
      setIsPreviewLoading(true);
      try {
        let canvas: HTMLCanvasElement;
        const regionName = selectedRegion
          ? (US_STATES.find(s => s.code.toLowerCase() === selectedRegion.toLowerCase())?.name || selectedRegion.toUpperCase())
          : 'National';

        switch (selectedInfographicType) {
          case 'spotlight':
            const spotlightTeam = rankings[selectedSpotlightTeamIndex] || rankings[0];
            canvas = await renderTeamSpotlightToCanvas({
              team: { ...spotlightTeam, rank: selectedSpotlightTeamIndex + 1 },
              platform: selectedPlatform,
              ageGroup: selectedAgeGroup,
              gender: selectedGender,
              region: selectedRegion,
              regionName,
              generatedDate: new Date().toISOString(),
            });
            break;

          case 'movers':
            const { climbers, fallers } = generateMoverData(rankings);
            canvas = await renderRankingMoversToCanvas({
              climbers,
              fallers,
              platform: selectedPlatform,
              ageGroup: selectedAgeGroup,
              gender: selectedGender,
              regionName,
              generatedDate: new Date().toISOString(),
            });
            break;

          case 'headToHead':
            const team1 = rankings[headToHeadTeam1Index] || rankings[0];
            const team2 = rankings[headToHeadTeam2Index] || rankings[1];
            canvas = await renderHeadToHeadToCanvas({
              team1: { ...team1, rank: headToHeadTeam1Index + 1 },
              team2: { ...team2, rank: headToHeadTeam2Index + 1 },
              platform: selectedPlatform,
              ageGroup: selectedAgeGroup,
              gender: selectedGender,
              regionName,
              generatedDate: new Date().toISOString(),
            });
            break;

          case 'stateChampions':
            const stateChampions = generateStateChampions(rankings);
            canvas = await renderStateChampionsToCanvas({
              champions: stateChampions,
              platform: selectedPlatform,
              ageGroup: selectedAgeGroup,
              gender: selectedGender,
              generatedDate: new Date().toISOString(),
            });
            break;

          default:
            setIsPreviewLoading(false);
            return;
        }

        // Convert canvas to data URL for preview
        const dataUrl = canvas.toDataURL('image/png');
        setPreviewImageUrl(dataUrl);
      } catch (err) {
        console.error('Error generating preview:', err);
        setPreviewImageUrl(null);
      }
      setIsPreviewLoading(false);
    };

    // Debounce the preview generation
    const timer = setTimeout(generatePreview, 300);
    return () => clearTimeout(timer);
  }, [selectedInfographicType, selectedPlatform, selectedAgeGroup, selectedGender, selectedRegion, rankings, selectedSpotlightTeamIndex, headToHeadTeam1Index, headToHeadTeam2Index]);

  const getRegionName = useCallback(() => {
    if (!selectedRegion) return 'National';
    const state = US_STATES.find(s => s.code.toLowerCase() === selectedRegion.toLowerCase());
    return state?.name || selectedRegion.toUpperCase();
  }, [selectedRegion]);

  const getFilename = useCallback(() => {
    const timestamp = new Date().toISOString().split('T')[0];
    const genderLabel = selectedGender === 'M' ? 'boys' : 'girls';
    const regionLabel = selectedRegion || 'national';
    const typeLabel = selectedInfographicType === 'covers' ? selectedCoverPlatform : selectedInfographicType;
    const platformLabel = selectedInfographicType === 'covers' ? 'cover' : selectedPlatform;
    return `pitchrank-${selectedAgeGroup}-${genderLabel}-${typeLabel}-${regionLabel}-${platformLabel}-${timestamp}.png`;
  }, [selectedAgeGroup, selectedGender, selectedRegion, selectedPlatform, selectedInfographicType, selectedCoverPlatform]);

  // Generate image using Canvas API directly
  const generateImage = useCallback(async (): Promise<Blob | null> => {
    setErrorMessage(null);

    if (selectedInfographicType !== 'covers' && selectedInfographicType !== 'stories') {
      if (!rankings || rankings.length === 0) {
        setErrorMessage('No team data available to generate image.');
        return null;
      }
    }

    try {
      let canvas: HTMLCanvasElement;

      switch (selectedInfographicType) {
        case 'top10':
          canvas = await renderInfographicToCanvas({
            teams: rankings!.slice(0, 10),
            platform: selectedPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            region: selectedRegion,
            regionName: getRegionName(),
            generatedDate: new Date().toISOString(),
          });
          break;

        case 'spotlight':
          const spotlightTeam = rankings![selectedSpotlightTeamIndex] || rankings![0];
          canvas = await renderTeamSpotlightToCanvas({
            team: { ...spotlightTeam, rank: selectedSpotlightTeamIndex + 1 },
            platform: selectedPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            region: selectedRegion,
            regionName: getRegionName(),
            generatedDate: new Date().toISOString(),
            headline: 'TEAM SPOTLIGHT',
          });
          break;

        case 'movers':
          const moverData = generateMoverData(rankings!);
          canvas = await renderRankingMoversToCanvas({
            climbers: moverData.climbers,
            fallers: moverData.fallers,
            platform: selectedPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            regionName: getRegionName(),
            generatedDate: new Date().toISOString(),
          });
          break;

        case 'headToHead':
          const team1 = rankings![headToHeadTeam1Index] || rankings![0];
          const team2 = rankings![headToHeadTeam2Index] || rankings![1];
          canvas = await renderHeadToHeadToCanvas({
            team1: { ...team1, rank: headToHeadTeam1Index + 1 },
            team2: { ...team2, rank: headToHeadTeam2Index + 1 },
            platform: selectedPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            regionName: getRegionName(),
            generatedDate: new Date().toISOString(),
          });
          break;

        case 'stateChampions':
          const champions = generateStateChampions(rankings!);
          canvas = await renderStateChampionsToCanvas({
            champions,
            platform: selectedPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            generatedDate: new Date().toISOString(),
          });
          break;

        case 'stories':
          canvas = await renderStoryTemplateToCanvas({
            type: selectedStoryType,
            platform: 'instagramStory',
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            regionName: getRegionName(),
          });
          break;

        case 'covers':
          canvas = await renderCoverImageToCanvas({
            platform: selectedCoverPlatform,
            ageGroup: selectedAgeGroup,
            gender: selectedGender,
            regionName: getRegionName(),
          });
          break;

        default:
          throw new Error(`Unknown infographic type: ${selectedInfographicType}`);
      }

      const blob = await canvasToBlob(canvas);
      return blob;
    } catch (err) {
      console.error('Error in generateImage:', err);
      const errorMsg = err instanceof Error ? err.message : 'Unknown error occurred';
      setErrorMessage(`Failed to generate image: ${errorMsg}`);
      return null;
    }
  }, [rankings, selectedInfographicType, selectedPlatform, selectedAgeGroup, selectedGender, selectedRegion, getRegionName, selectedSpotlightTeamIndex, headToHeadTeam1Index, headToHeadTeam2Index, selectedStoryType, selectedCoverPlatform]);

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

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = getFilename();
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 5000);
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
      const shareText = `Check out the ${selectedAgeGroup.toUpperCase()} ${genderText} ${getRegionName()} Soccer Rankings! #YouthSoccer #${selectedAgeGroup.toUpperCase()}Soccer`;

      if (canShare && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: `PitchRank - ${selectedAgeGroup.toUpperCase()} ${genderText} Rankings`,
          text: shareText,
          files: [file],
        });
      } else {
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
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled
      } else {
        console.error('Share error:', err);
        setErrorMessage('Failed to share. Trying download instead...');
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

      {/* Infographic Type Selector */}
      <div className="mt-6 mb-8">
        <div className="flex flex-wrap gap-2">
          {INFOGRAPHIC_TYPES.map((type) => (
            <button
              key={type.id}
              onClick={() => setSelectedInfographicType(type.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                selectedInfographicType === type.id
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted hover:bg-muted/80 text-foreground'
              }`}
            >
              {type.icon}
              <span className="font-medium text-sm">{type.label}</span>
            </button>
          ))}
        </div>
        <p className="text-sm text-muted-foreground mt-2">
          {INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.description}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Controls Panel */}
        <div className="lg:col-span-1 space-y-6">
          {/* Rankings Selection */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Select Rankings</CardTitle>
              <CardDescription>Choose age group, gender, and region</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
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

          {/* Platform Selection - only for types that use standard platforms */}
          {selectedInfographicType !== 'stories' && selectedInfographicType !== 'covers' && (
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
          )}

          {/* Type-specific options */}
          {selectedInfographicType === 'spotlight' && rankings && rankings.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Select Team</CardTitle>
                <CardDescription>Choose which team to spotlight</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="relative">
                  <select
                    value={selectedSpotlightTeamIndex}
                    onChange={(e) => setSelectedSpotlightTeamIndex(Number(e.target.value))}
                    className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    {rankings.slice(0, 25).map((team, i) => (
                      <option key={team.team_id_master} value={i}>#{i + 1} - {team.team_name}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                </div>
              </CardContent>
            </Card>
          )}

          {selectedInfographicType === 'headToHead' && rankings && rankings.length > 1 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Select Teams</CardTitle>
                <CardDescription>Choose two teams to compare</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Team 1</label>
                  <div className="relative">
                    <select
                      value={headToHeadTeam1Index}
                      onChange={(e) => setHeadToHeadTeam1Index(Number(e.target.value))}
                      className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                      {rankings.slice(0, 25).map((team, i) => (
                        <option key={team.team_id_master} value={i}>#{i + 1} - {team.team_name}</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Team 2</label>
                  <div className="relative">
                    <select
                      value={headToHeadTeam2Index}
                      onChange={(e) => setHeadToHeadTeam2Index(Number(e.target.value))}
                      className="w-full appearance-none bg-muted border border-border rounded-lg px-4 py-3 pr-10 font-medium focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                      {rankings.slice(0, 25).map((team, i) => (
                        <option key={team.team_id_master} value={i}>#{i + 1} - {team.team_name}</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {selectedInfographicType === 'stories' && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Story Type</CardTitle>
                <CardDescription>Choose the announcement style</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {STORY_TYPES.map((storyType) => (
                  <button
                    key={storyType.value}
                    onClick={() => setSelectedStoryType(storyType.value)}
                    className={`w-full text-left px-4 py-3 rounded-lg transition-all ${
                      selectedStoryType === storyType.value
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted hover:bg-muted/80 text-foreground'
                    }`}
                  >
                    <span className="font-medium block">{storyType.label}</span>
                    <span className="text-xs opacity-70">{storyType.description}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}

          {selectedInfographicType === 'covers' && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Cover Platform</CardTitle>
                <CardDescription>Choose the header/cover format</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {COVER_PLATFORMS.map((coverPlatform) => (
                  <button
                    key={coverPlatform.value}
                    onClick={() => setSelectedCoverPlatform(coverPlatform.value)}
                    className={`w-full flex items-center justify-between px-4 py-3 rounded-lg transition-all ${
                      selectedCoverPlatform === coverPlatform.value
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted hover:bg-muted/80 text-foreground'
                    }`}
                  >
                    <span className="font-medium">{coverPlatform.label}</span>
                    <span className="text-xs opacity-70">{coverPlatform.dimensions}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}

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
                <span className="text-muted-foreground">Type</span>
                <span className="font-medium">{INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.label}</span>
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
              disabled={isGenerating || (selectedInfographicType !== 'covers' && selectedInfographicType !== 'stories' && (isLoading || top10Teams.length === 0))}
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
                disabled={isGenerating || (selectedInfographicType !== 'covers' && selectedInfographicType !== 'stories' && (isLoading || top10Teams.length === 0))}
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
                {selectedInfographicType === 'covers' || selectedInfographicType === 'stories'
                  ? `${INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.label} - ${categoryLabel}`
                  : isLoading ? 'Loading...' : error ? 'Error loading data' : `${INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.label} - ${categoryLabel}`
                }
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                className="overflow-auto bg-muted/30 rounded-lg p-4 flex justify-center items-center"
                style={{ minHeight: `${dimensions.height * previewScale + 40}px` }}
              >
                {selectedInfographicType === 'covers' || selectedInfographicType === 'stories' ? (
                  <div className="text-center text-muted-foreground">
                    <div className="mb-4">
                      {selectedInfographicType === 'covers' ? <Image size={48} className="mx-auto opacity-50" /> : <Megaphone size={48} className="mx-auto opacity-50" />}
                    </div>
                    <p className="font-medium mb-2">
                      {selectedInfographicType === 'covers'
                        ? `${COVER_PLATFORMS.find(p => p.value === selectedCoverPlatform)?.label}`
                        : `${STORY_TYPES.find(s => s.value === selectedStoryType)?.label}`
                      }
                    </p>
                    <p className="text-sm">Click Download to generate the image</p>
                  </div>
                ) : isLoading ? (
                  <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
                ) : error ? (
                  <p className="text-destructive">Failed to load rankings</p>
                ) : top10Teams.length === 0 ? (
                  <div className="text-center text-muted-foreground">
                    <p className="font-medium mb-2">No teams found</p>
                    <p className="text-sm">Try a different selection</p>
                  </div>
                ) : selectedInfographicType === 'top10' ? (
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
                ) : isPreviewLoading ? (
                  <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
                ) : previewImageUrl ? (
                  <img
                    src={previewImageUrl}
                    alt={`${INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.label} Preview`}
                    style={{
                      width: dimensions.width * previewScale,
                      height: dimensions.height * previewScale,
                      objectFit: 'contain',
                    }}
                  />
                ) : (
                  <div className="text-center text-muted-foreground">
                    <div className="mb-4">
                      {INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.icon}
                    </div>
                    <p className="font-medium mb-2">{INFOGRAPHIC_TYPES.find(t => t.id === selectedInfographicType)?.label}</p>
                    <p className="text-sm">Loading preview...</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Caption Generator */}
          {top10Teams.length > 0 && (
            <Card className="mt-6">
              <CardHeader>
                <CardTitle className="text-lg">Caption Generator</CardTitle>
                <CardDescription>Copy a ready-to-use caption for your post</CardDescription>
              </CardHeader>
              <CardContent>
                <CaptionGenerator
                  infographicType={selectedInfographicType}
                  ageGroup={selectedAgeGroup}
                  gender={selectedGender}
                  regionName={getRegionName()}
                  teamName={selectedInfographicType === 'spotlight' && rankings ? rankings[selectedSpotlightTeamIndex]?.team_name : undefined}
                  rank={selectedInfographicType === 'spotlight' ? selectedSpotlightTeamIndex + 1 : undefined}
                />
              </CardContent>
            </Card>
          )}

          {/* Teams List */}
          {top10Teams.length > 0 && selectedInfographicType === 'top10' && (
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
            disabled={isGenerating || (selectedInfographicType !== 'covers' && selectedInfographicType !== 'stories' && (isLoading || top10Teams.length === 0))}
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
              disabled={isGenerating || (selectedInfographicType !== 'covers' && selectedInfographicType !== 'stories' && (isLoading || top10Teams.length === 0))}
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
