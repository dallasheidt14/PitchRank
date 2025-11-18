'use client';

import { Twitter, Facebook, Link as LinkIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useState } from 'react';

interface ShareButtonsProps {
  /**
   * The URL to share (defaults to current page)
   */
  url?: string;
  /**
   * The title/text to share
   */
  title: string;
  /**
   * Optional hashtags (Twitter only)
   */
  hashtags?: string[];
  /**
   * Show as compact buttons or full buttons
   */
  variant?: 'default' | 'compact';
}

/**
 * Social media share buttons component
 * Allows users to share team rankings and pages on social media
 */
export function ShareButtons({
  url,
  title,
  hashtags = ['PitchRank', 'YouthSoccer'],
  variant = 'default',
}: ShareButtonsProps) {
  const [copied, setCopied] = useState(false);

  // Use current URL if not provided
  const shareUrl = url || (typeof window !== 'undefined' ? window.location.href : '');

  /**
   * Share on Twitter
   */
  const shareOnTwitter = () => {
    const text = encodeURIComponent(title);
    const urlParam = encodeURIComponent(shareUrl);
    const hashtagsParam = hashtags.join(',');
    const twitterUrl = `https://twitter.com/intent/tweet?text=${text}&url=${urlParam}&hashtags=${hashtagsParam}&via=pitchrank`;

    window.open(twitterUrl, '_blank', 'width=550,height=420');
  };

  /**
   * Share on Facebook
   */
  const shareOnFacebook = () => {
    const urlParam = encodeURIComponent(shareUrl);
    const facebookUrl = `https://www.facebook.com/sharer/sharer.php?u=${urlParam}`;

    window.open(facebookUrl, '_blank', 'width=550,height=420');
  };

  /**
   * Copy link to clipboard
   */
  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const buttonSize = variant === 'compact' ? 'sm' : 'default';

  return (
    <div className="flex items-center gap-2">
      {variant === 'default' && (
        <span className="text-sm text-muted-foreground mr-2">Share:</span>
      )}

      <Button
        variant="outline"
        size={buttonSize}
        onClick={shareOnTwitter}
        className="gap-2"
        aria-label="Share on Twitter"
      >
        <Twitter className="h-4 w-4" />
        {variant === 'default' && 'Twitter'}
      </Button>

      <Button
        variant="outline"
        size={buttonSize}
        onClick={shareOnFacebook}
        className="gap-2"
        aria-label="Share on Facebook"
      >
        <Facebook className="h-4 w-4" />
        {variant === 'default' && 'Facebook'}
      </Button>

      <Button
        variant="outline"
        size={buttonSize}
        onClick={copyToClipboard}
        className="gap-2"
        aria-label="Copy link"
      >
        <LinkIcon className="h-4 w-4" />
        {copied ? 'Copied!' : variant === 'default' ? 'Copy Link' : ''}
      </Button>
    </div>
  );
}
