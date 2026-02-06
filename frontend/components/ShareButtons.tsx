'use client';

import { Twitter, Facebook, Link as LinkIcon, MessageCircle, Share2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useState, useEffect, useRef } from 'react';

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
  const [canNativeShare, setCanNativeShare] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Check for Web Share API support on mount
  useEffect(() => {
    setCanNativeShare(typeof navigator !== 'undefined' && !!navigator.share);
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // Use current URL if not provided
  const shareUrl = url || (typeof window !== 'undefined' ? window.location.href : '');

  /**
   * Native share (iOS/Android share sheet — covers iMessage, Instagram, etc.)
   */
  const nativeShare = async () => {
    try {
      await navigator.share({ title, text: title, url: shareUrl });
    } catch (err) {
      // User cancelled or share failed — ignore
    }
  };

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
   * Share on WhatsApp
   */
  const shareOnWhatsApp = () => {
    const text = encodeURIComponent(`${title}\n${shareUrl}`);
    const whatsappUrl = `https://wa.me/?text=${text}`;

    window.open(whatsappUrl, '_blank', 'width=550,height=420');
  };

  /**
   * Copy link to clipboard
   */
  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const buttonSize = variant === 'compact' ? 'sm' : 'default';

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {variant === 'default' && (
        <span className="text-sm text-muted-foreground mr-2">Share:</span>
      )}

      {/* Native share — shows iOS/Android share sheet (iMessage, Instagram, SMS, etc.) */}
      {canNativeShare && (
        <Button
          variant="outline"
          size={buttonSize}
          onClick={nativeShare}
          className="gap-2"
          aria-label="Share"
        >
          <Share2 className="h-4 w-4" />
          {variant === 'default' && 'Share'}
        </Button>
      )}

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
        onClick={shareOnWhatsApp}
        className="gap-2"
        aria-label="Share on WhatsApp"
      >
        <MessageCircle className="h-4 w-4" />
        {variant === 'default' && 'WhatsApp'}
      </Button>

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
