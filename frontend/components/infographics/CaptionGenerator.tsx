'use client';

import React, { useState, useMemo } from 'react';
import { Copy, Check, RefreshCw, Instagram, Facebook } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

// X/Twitter icon
const XIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

type InfographicType = 'top10' | 'spotlight' | 'movers' | 'headToHead' | 'stateChampions' | 'stories' | 'covers';

interface CaptionGeneratorProps {
  infographicType: InfographicType;
  ageGroup: string;
  gender: 'M' | 'F';
  regionName: string;
  teamName?: string;
  rank?: number;
}

// Caption templates by type
const CAPTION_TEMPLATES: Record<InfographicType, string[]> = {
  top10: [
    "🏆 NEW RANKINGS ALERT! Check out the Top 10 {category} teams {region}!\n\nWho's your pick for #1? 👇\n\n{hashtags}",
    "📊 The latest {category} rankings are HERE!\n\nSee which teams are dominating {region}. Is your team on the list?\n\n{hashtags}",
    "🔥 Top 10 {category} {region} Rankings just dropped!\n\nThese teams are putting in WORK. Which team are you rooting for?\n\n{hashtags}",
    "⚽ Who's #1? The official {category} {region} rankings are live!\n\nTag your team if they made the Top 10! 🙌\n\n{hashtags}",
  ],
  spotlight: [
    "🌟 TEAM SPOTLIGHT: {teamName}!\n\nCurrently ranked #{rank} in {category} {region}. This team is on FIRE! 🔥\n\n{hashtags}",
    "👏 Shoutout to {teamName}!\n\nHolding strong at #{rank} in {category} {region}. Keep grinding! 💪\n\n{hashtags}",
    "📈 Rising through the ranks: {teamName}\n\n#{rank} in {category} {region} and climbing! Who's watching this team?\n\n{hashtags}",
  ],
  movers: [
    "📈📉 BIG MOVERS this week in {category} {region}!\n\nSome teams are climbing, others are falling. See who's trending!\n\n{hashtags}",
    "🚀 Who's HOT? Who's NOT?\n\n{category} {region} biggest movers are here! Check out the shake-up!\n\n{hashtags}",
    "⬆️⬇️ Rankings SHAKE-UP!\n\n{category} {region} teams on the move. Is your team climbing or falling?\n\n{hashtags}",
  ],
  headToHead: [
    "🆚 HEAD TO HEAD!\n\nBreaking down the matchup everyone's talking about. Who wins this one?\n\n{hashtags}",
    "📊 TALE OF THE TAPE\n\nTwo top teams. One breakdown. Who's got the edge?\n\n{hashtags}",
  ],
  stateChampions: [
    "🏆 STATE CHAMPIONS!\n\nMeet the #1 ranked teams from every state in {category}!\n\n{hashtags}",
    "👑 The BEST in each state!\n\n{category} state leaders are here. Find your state!\n\n{hashtags}",
  ],
  stories: [
    "🚨 NEW RANKINGS LIVE!\n\nSwipe up to see where your team ranks!\n\n{hashtags}",
    "📊 Rankings Update!\n\nThe wait is over. Check the latest standings NOW!\n\n{hashtags}",
  ],
  covers: [
    "🏆 Welcome to PitchRank!\n\nThe #1 source for {category} soccer rankings. Follow for updates!\n\n{hashtags}",
    "⚽ {category} Soccer Rankings\n\nYour go-to source for the latest standings and team insights.\n\n{hashtags}",
  ],
};

// Hashtag sets
const BASE_HASHTAGS = ['YouthSoccer', 'SoccerRankings', 'PitchRank'];
const GENDER_HASHTAGS = {
  M: ['BoysSoccer', 'BoysClubSoccer'],
  F: ['GirlsSoccer', 'GirlsClubSoccer'],
};
const AGE_HASHTAGS: Record<string, string[]> = {
  u10: ['U10Soccer', 'U10'],
  u11: ['U11Soccer', 'U11'],
  u12: ['U12Soccer', 'U12'],
  u13: ['U13Soccer', 'U13'],
  u14: ['U14Soccer', 'U14'],
  u15: ['U15Soccer', 'U15'],
  u16: ['U16Soccer', 'U16'],
  u17: ['U17Soccer', 'U17'],
  u18: ['U18Soccer', 'U18'],
};
const ENGAGEMENT_HASHTAGS = ['ClubSoccer', 'SoccerLife', 'FutureStars', 'SoccerFamily', 'ECNL', 'GALeague', 'MLSNext'];

export function CaptionGenerator({
  infographicType,
  ageGroup,
  gender,
  regionName,
  teamName,
  rank,
}: CaptionGeneratorProps) {
  const [copied, setCopied] = useState(false);
  const [templateIndex, setTemplateIndex] = useState(0);

  const genderLabel = gender === 'M' ? 'Boys' : 'Girls';
  const category = `${ageGroup.toUpperCase()} ${genderLabel}`;

  // Build hashtags
  const hashtags = useMemo(() => {
    const tags = [
      ...BASE_HASHTAGS,
      ...GENDER_HASHTAGS[gender],
      ...(AGE_HASHTAGS[ageGroup] || []),
      ...ENGAGEMENT_HASHTAGS.slice(0, 3),
    ];
    if (regionName && regionName !== 'National') {
      tags.push(`${regionName.replace(/\s/g, '')}Soccer`);
    }
    return tags.map(t => `#${t}`).join(' ');
  }, [ageGroup, gender, regionName]);

  // Generate caption
  const caption = useMemo(() => {
    const templates = CAPTION_TEMPLATES[infographicType] || CAPTION_TEMPLATES.top10;
    const template = templates[templateIndex % templates.length];

    return template
      .replace('{category}', category)
      .replace('{region}', regionName === 'National' ? 'Nationally' : `in ${regionName}`)
      .replace('{teamName}', teamName || 'Team')
      .replace('{rank}', String(rank || 1))
      .replace('{hashtags}', hashtags);
  }, [infographicType, templateIndex, category, regionName, teamName, rank, hashtags]);

  // Character counts for different platforms
  const charCounts = {
    twitter: 280,
    instagram: 2200,
    facebook: 63206,
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(caption);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const handleRefresh = () => {
    const templates = CAPTION_TEMPLATES[infographicType] || CAPTION_TEMPLATES.top10;
    setTemplateIndex((prev) => (prev + 1) % templates.length);
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>Caption Generator</span>
          <Button variant="ghost" size="sm" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Caption Preview */}
        <div className="bg-muted/50 rounded-lg p-4 text-sm whitespace-pre-wrap font-mono">
          {caption}
        </div>

        {/* Character Counts */}
        <div className="flex gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <XIcon />
            <span className={caption.length > charCounts.twitter ? 'text-destructive' : ''}>
              {caption.length}/{charCounts.twitter}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Instagram className="h-4 w-4" />
            <span>{caption.length}/{charCounts.instagram}</span>
          </div>
          <div className="flex items-center gap-1">
            <Facebook className="h-4 w-4" />
            <span>{caption.length}/{charCounts.facebook}</span>
          </div>
        </div>

        {/* Copy Button */}
        <Button onClick={handleCopy} className="w-full" variant={copied ? 'outline' : 'default'}>
          {copied ? (
            <>
              <Check className="mr-2 h-4 w-4" />
              Copied!
            </>
          ) : (
            <>
              <Copy className="mr-2 h-4 w-4" />
              Copy Caption
            </>
          )}
        </Button>

        {/* Quick Hashtags */}
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Quick Copy Hashtags:</p>
          <div className="flex flex-wrap gap-1">
            {[...BASE_HASHTAGS, ...GENDER_HASHTAGS[gender], ...(AGE_HASHTAGS[ageGroup] || [])].slice(0, 8).map((tag) => (
              <button
                key={tag}
                onClick={() => navigator.clipboard.writeText(`#${tag}`)}
                className="text-xs bg-primary/10 hover:bg-primary/20 text-primary px-2 py-1 rounded transition-colors"
              >
                #{tag}
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default CaptionGenerator;
