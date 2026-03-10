'use client';

import React, { useState, useMemo, useCallback } from 'react';
import { Copy, Check, RefreshCw, Instagram, Facebook, Shuffle } from 'lucide-react';
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
  teamCount?: number;
}

// ---------------------------------------------------------------------------
// Block 1 — Hook (Stop the Scroll)
// ---------------------------------------------------------------------------
const HOOK_TEMPLATES: Record<InfographicType, string[]> = {
  top10: [
    '🏆 NEW RANKINGS ALERT',
    '⚽ TOP {N} TEAMS IN {STATE}',
    '🔥 WHO MADE THE CUT?',
    '📊 DATA DROP',
    '👀 WHO\'S #1 IN {STATE}?',
    '🚨 RANKINGS JUST DROPPED',
    '⚡ THE TOP {N} ARE HERE',
  ],
  spotlight: [
    '🌟 TEAM SPOTLIGHT',
    '👏 SHOUTOUT TO {TEAM}',
    '📈 WATCH THIS TEAM',
    '🔥 {TEAM} IS ON FIRE',
  ],
  movers: [
    '🔥 BIGGEST RISERS THIS WEEK',
    '📈📉 WHO\'S MOVING?',
    '🚀 RANKINGS SHAKE-UP',
    '⬆️⬇️ BIG MOVERS ALERT',
    '👀 WHO CLIMBED? WHO FELL?',
  ],
  headToHead: [
    '🆚 HEAD TO HEAD',
    '📊 TALE OF THE TAPE',
    '⚡ THE MATCHUP EVERYONE\'S WATCHING',
    '🔥 WHO WINS THIS ONE?',
  ],
  stateChampions: [
    '🏆 STATE CHAMPIONS',
    '👑 THE BEST IN EVERY STATE',
    '🗺️ #1 RANKED BY STATE',
    '⚽ STATE-BY-STATE LEADERS',
  ],
  stories: [
    '🚨 NEW RANKINGS LIVE',
    '📊 RANKINGS UPDATE',
    '⚡ JUST DROPPED',
    '🔥 SWIPE FOR RANKINGS',
  ],
  covers: [
    '🏆 WELCOME TO PITCHRANK',
    '⚽ YOUR RANKING SOURCE',
    '📊 POWERED BY DATA',
  ],
};

// ---------------------------------------------------------------------------
// Block 2 — Context (Explain What They're Seeing)
// ---------------------------------------------------------------------------
const CONTEXT_TEMPLATES: Record<InfographicType, string[]> = {
  top10: [
    'Here are the current PitchRank Top {N} {CATEGORY} teams {REGION}.',
    'The official Top {N} {CATEGORY} rankings {REGION} are here.',
    'These are the {N} highest-ranked {CATEGORY} teams {REGION} right now.',
  ],
  spotlight: [
    '{TEAM} is currently ranked #{RANK} in {CATEGORY} {REGION}.',
    'Meet {TEAM} — #{RANK} in {CATEGORY} {REGION} and making noise.',
    '{TEAM} holds the #{RANK} spot in {CATEGORY} {REGION}.',
  ],
  movers: [
    'Here are the biggest climbers and fallers in {CATEGORY} {REGION} this week.',
    'These {CATEGORY} teams {REGION} made the biggest moves in the latest rankings.',
    'The {CATEGORY} {REGION} rankings saw some big shake-ups this week.',
  ],
  headToHead: [
    'Breaking down the matchup everyone\'s talking about in {CATEGORY} {REGION}.',
    'Two top {CATEGORY} teams {REGION} go head to head. Who has the edge?',
  ],
  stateChampions: [
    'Meet the #1 ranked {CATEGORY} team from every state.',
    'Here are the top-ranked {CATEGORY} teams across the country, state by state.',
  ],
  stories: [
    'The latest {CATEGORY} rankings are live. Swipe up to see where your team stands.',
    '{CATEGORY} {REGION} rankings just updated. Check the standings now.',
  ],
  covers: [
    'PitchRank is the #1 source for {CATEGORY} soccer rankings.',
    'Your go-to source for {CATEGORY} soccer standings and team insights.',
  ],
};

const CONTEXT_SUFFIX_TEMPLATES = [
  'Rankings are based on match results, strength of schedule, and performance metrics.',
  'These rankings are based on match results, strength of schedule, and performance metrics.',
  'Updated weekly using real match data.',
  'Powered by real match data and advanced analytics.',
];

// ---------------------------------------------------------------------------
// Block 3 — Engagement Question (Drives Comments)
// ---------------------------------------------------------------------------
const ENGAGEMENT_TEMPLATES: Record<InfographicType, string[]> = {
  top10: [
    'Did we get it right?',
    'Who should be #1?',
    'Which team is underrated?',
    'Who moves up next week?',
    'Tag your team 👇',
    'Who\'s missing from this list? 👇',
    'Agree or disagree? Drop a comment 👇',
    'Which team surprises you the most?',
  ],
  spotlight: [
    'Is this team for real?',
    'How far can they go?',
    'Tag someone from this team 👇',
    'Where do they finish the season?',
  ],
  movers: [
    'Who climbs higher next week?',
    'Any surprises here?',
    'Is your team trending up or down? 👇',
    'Tag a team that should be rising 👇',
  ],
  headToHead: [
    'Who wins this one? 👇',
    'Pick a side — who\'s better?',
    'Who has the edge? Drop your take 👇',
  ],
  stateChampions: [
    'Find your state — did we get it right?',
    'Which state has the best #1 team?',
    'Tag your state\'s champion 👇',
  ],
  stories: [
    'Where does YOUR team rank?',
    'Check the link to find out 👇',
  ],
  covers: [
    'Follow for weekly ranking updates!',
    'Hit follow to never miss a drop!',
  ],
};

// ---------------------------------------------------------------------------
// Block 4 — Call To Action (Traffic Driver)
// ---------------------------------------------------------------------------
const CTA_TEMPLATES: Record<InfographicType, string[]> = {
  top10: [
    'See full rankings at pitchrank.io',
    'Search your team at pitchrank.io/rankings',
    'Compare teams at pitchrank.io',
    '🔗 Full rankings → pitchrank.io/rankings',
  ],
  spotlight: [
    'See full team stats at pitchrank.io',
    'Search any team at pitchrank.io/rankings',
    '🔗 More details → pitchrank.io',
  ],
  movers: [
    'See all movers at pitchrank.io',
    'Track your team at pitchrank.io/rankings',
    '🔗 Full rankings → pitchrank.io/rankings',
  ],
  headToHead: [
    'Compare any two teams at pitchrank.io',
    '🔗 Try it → pitchrank.io/rankings',
  ],
  stateChampions: [
    'Explore every state at pitchrank.io',
    '🔗 Full rankings → pitchrank.io/rankings',
  ],
  stories: [
    '👆 Tap the link to see full rankings',
    '🔗 pitchrank.io/rankings',
  ],
  covers: [
    '🔗 pitchrank.io',
    'Visit pitchrank.io for the latest rankings',
  ],
};

// ---------------------------------------------------------------------------
// Block 5 — Hashtags
// ---------------------------------------------------------------------------
const BASE_HASHTAGS = ['YouthSoccer', 'ClubSoccer', 'SoccerRankings', 'PitchRank'];
const GENDER_HASHTAGS: Record<string, string[]> = {
  M: ['BoysSoccer'],
  F: ['GirlsSoccer'],
};
const AGE_HASHTAGS: Record<string, string> = {
  u10: 'U10Soccer', u11: 'U11Soccer', u12: 'U12Soccer',
  u13: 'U13Soccer', u14: 'U14Soccer', u15: 'U15Soccer',
  u16: 'U16Soccer', u17: 'U17Soccer', u18: 'U18Soccer',
};
const ROTATING_HASHTAGS = [
  'SoccerParents', 'FutureStars', 'SoccerFamily', 'SoccerLife',
  'ECNL', 'GALeague', 'MLSNext', 'DPL', 'SoccerMom', 'SoccerDad',
];

// State hashtag mapping
const STATE_HASHTAGS: Record<string, string> = {
  Alabama: 'AlabamaSoccer', Alaska: 'AlaskaSoccer', Arizona: 'ArizonaSoccer',
  Arkansas: 'ArkansasSoccer', California: 'CaliforniaSoccer', Colorado: 'ColoradoSoccer',
  Connecticut: 'ConnecticutSoccer', Delaware: 'DelawareSoccer', Florida: 'FloridaSoccer',
  Georgia: 'GeorgiaSoccer', Hawaii: 'HawaiiSoccer', Idaho: 'IdahoSoccer',
  Illinois: 'IllinoisSoccer', Indiana: 'IndianaSoccer', Iowa: 'IowaSoccer',
  Kansas: 'KansasSoccer', Kentucky: 'KentuckySoccer', Louisiana: 'LouisianaSoccer',
  Maine: 'MaineSoccer', Maryland: 'MarylandSoccer', Massachusetts: 'MassachusettsSoccer',
  Michigan: 'MichiganSoccer', Minnesota: 'MinnesotaSoccer', Mississippi: 'MississippiSoccer',
  Missouri: 'MissouriSoccer', Montana: 'MontanaSoccer', Nebraska: 'NebraskaSoccer',
  Nevada: 'NevadaSoccer', 'New Hampshire': 'NewHampshireSoccer', 'New Jersey': 'NewJerseySoccer',
  'New Mexico': 'NewMexicoSoccer', 'New York': 'NewYorkSoccer', 'North Carolina': 'NorthCarolinaSoccer',
  'North Dakota': 'NorthDakotaSoccer', Ohio: 'OhioSoccer', Oklahoma: 'OklahomaSoccer',
  Oregon: 'OregonSoccer', Pennsylvania: 'PennsylvaniaSoccer', 'Rhode Island': 'RhodeIslandSoccer',
  'South Carolina': 'SouthCarolinaSoccer', 'South Dakota': 'SouthDakotaSoccer',
  Tennessee: 'TennesseeSoccer', Texas: 'TexasSoccer', Utah: 'UtahSoccer',
  Vermont: 'VermontSoccer', Virginia: 'VirginiaSoccer', Washington: 'WashingtonSoccer',
  'West Virginia': 'WestVirginiaSoccer', Wisconsin: 'WisconsinSoccer', Wyoming: 'WyomingSoccer',
};

// ---------------------------------------------------------------------------
// Helper: pick a random item from an array using a seed index
// ---------------------------------------------------------------------------
function pickTemplate(templates: string[], index: number): string {
  return templates[index % templates.length];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function CaptionGenerator({
  infographicType,
  ageGroup,
  gender,
  regionName,
  teamName,
  rank,
  teamCount = 10,
}: CaptionGeneratorProps) {
  const [copied, setCopied] = useState(false);
  const [blockSeeds, setBlockSeeds] = useState({
    hook: 0,
    context: 0,
    contextSuffix: 0,
    engagement: 0,
    cta: 0,
    rotatingHashtag: 0,
  });

  const genderLabel = gender === 'M' ? 'Boys' : 'Girls';
  const category = `${ageGroup.toUpperCase()} ${genderLabel}`;
  const stateDisplay = regionName === 'National' ? 'THE NATION' : regionName.toUpperCase();
  const regionPhrase = regionName === 'National' ? 'Nationally' : `in ${regionName}`;
  const n = String(teamCount);

  // Replace template variables
  const fillVars = useCallback((template: string) => {
    return template
      .replace(/\{CATEGORY\}/g, category)
      .replace(/\{REGION\}/g, regionPhrase)
      .replace(/\{STATE\}/g, stateDisplay)
      .replace(/\{TEAM\}/g, teamName || 'Team')
      .replace(/\{RANK\}/g, String(rank || 1))
      .replace(/\{N\}/g, n);
  }, [category, regionPhrase, stateDisplay, teamName, rank, n]);

  // Build hashtags (Block 5)
  const hashtags = useMemo(() => {
    const tags: string[] = [...BASE_HASHTAGS];
    tags.push(...GENDER_HASHTAGS[gender]);
    const ageTag = AGE_HASHTAGS[ageGroup];
    if (ageTag) tags.push(ageTag);
    if (regionName && regionName !== 'National') {
      const stateTag = STATE_HASHTAGS[regionName];
      if (stateTag) tags.push(stateTag);
      else tags.push(`${regionName.replace(/\s/g, '')}Soccer`);
    }
    // Add 2 rotating hashtags based on seed
    const rotIdx = blockSeeds.rotatingHashtag;
    tags.push(ROTATING_HASHTAGS[rotIdx % ROTATING_HASHTAGS.length]);
    tags.push(ROTATING_HASHTAGS[(rotIdx + 1) % ROTATING_HASHTAGS.length]);
    // Cap at 10 hashtags
    return tags.slice(0, 10).map(t => `#${t}`).join(' ');
  }, [ageGroup, gender, regionName, blockSeeds.rotatingHashtag]);

  // Assemble the 5-block caption
  const caption = useMemo(() => {
    const hookTemplates = HOOK_TEMPLATES[infographicType] || HOOK_TEMPLATES.top10;
    const contextTemplates = CONTEXT_TEMPLATES[infographicType] || CONTEXT_TEMPLATES.top10;
    const engagementTemplates = ENGAGEMENT_TEMPLATES[infographicType] || ENGAGEMENT_TEMPLATES.top10;
    const ctaTemplates = CTA_TEMPLATES[infographicType] || CTA_TEMPLATES.top10;

    const hook = fillVars(pickTemplate(hookTemplates, blockSeeds.hook));
    const context = fillVars(pickTemplate(contextTemplates, blockSeeds.context));
    const contextSuffix = fillVars(pickTemplate(CONTEXT_SUFFIX_TEMPLATES, blockSeeds.contextSuffix));
    const engagement = fillVars(pickTemplate(engagementTemplates, blockSeeds.engagement));
    const cta = fillVars(pickTemplate(ctaTemplates, blockSeeds.cta));

    return [
      hook,
      '',
      `${context}\n${contextSuffix}`,
      '',
      engagement,
      '',
      `👇 ${cta}`,
      '',
      hashtags,
    ].join('\n');
  }, [infographicType, blockSeeds, fillVars, hashtags]);

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

  // Shuffle all blocks for a completely new caption
  const handleShuffleAll = () => {
    setBlockSeeds({
      hook: blockSeeds.hook + 1,
      context: blockSeeds.context + 1,
      contextSuffix: blockSeeds.contextSuffix + 1,
      engagement: blockSeeds.engagement + 1,
      cta: blockSeeds.cta + 1,
      rotatingHashtag: blockSeeds.rotatingHashtag + 2,
    });
  };

  // Shuffle a single block
  const handleShuffleBlock = (block: keyof typeof blockSeeds) => {
    setBlockSeeds((prev) => ({
      ...prev,
      [block]: prev[block] + 1,
      ...(block === 'rotatingHashtag' ? { rotatingHashtag: prev.rotatingHashtag + 2 } : {}),
    }));
  };

  // Block labels for the individual shuffle UI
  const blocks: { key: keyof typeof blockSeeds; label: string; color: string }[] = [
    { key: 'hook', label: 'Hook', color: 'bg-red-500/10 text-red-700 dark:text-red-400' },
    { key: 'context', label: 'Context', color: 'bg-blue-500/10 text-blue-700 dark:text-blue-400' },
    { key: 'engagement', label: 'Engagement', color: 'bg-amber-500/10 text-amber-700 dark:text-amber-400' },
    { key: 'cta', label: 'CTA', color: 'bg-green-500/10 text-green-700 dark:text-green-400' },
    { key: 'rotatingHashtag', label: 'Hashtags', color: 'bg-purple-500/10 text-purple-700 dark:text-purple-400' },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>Caption Generator</span>
          <Button variant="ghost" size="sm" onClick={handleShuffleAll} title="Shuffle all blocks">
            <Shuffle className="h-4 w-4 mr-1" />
            <span className="text-xs">Shuffle All</span>
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Block Controls */}
        <div className="flex flex-wrap gap-1.5">
          {blocks.map((block) => (
            <button
              key={block.key}
              onClick={() => handleShuffleBlock(block.key)}
              className={`text-xs font-medium px-2.5 py-1 rounded-full transition-colors hover:opacity-80 flex items-center gap-1 ${block.color}`}
              title={`Shuffle ${block.label}`}
            >
              <RefreshCw className="h-3 w-3" />
              {block.label}
            </button>
          ))}
        </div>

        {/* Caption Preview */}
        <div className="bg-muted/50 rounded-lg p-4 text-sm whitespace-pre-wrap font-mono leading-relaxed">
          {caption}
        </div>

        {/* Character Counts */}
        <div className="flex gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <XIcon />
            <span className={caption.length > charCounts.twitter ? 'text-destructive font-medium' : ''}>
              {caption.length}/{charCounts.twitter}
              {caption.length > charCounts.twitter && ' (too long)'}
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

        {/* Quick Copy Hashtags */}
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Quick Copy Hashtags:</p>
          <div className="flex flex-wrap gap-1">
            {[...BASE_HASHTAGS, ...GENDER_HASHTAGS[gender], AGE_HASHTAGS[ageGroup]].filter(Boolean).slice(0, 8).map((tag) => (
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
