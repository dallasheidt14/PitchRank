'use client';

import React, { forwardRef } from 'react';

// Platform dimensions (in pixels)
export const PLATFORM_DIMENSIONS = {
  instagram: { width: 1080, height: 1080, label: 'Instagram Post', aspectRatio: '1:1' },
  instagramStory: { width: 1080, height: 1920, label: 'Instagram Story', aspectRatio: '9:16' },
  twitter: { width: 1200, height: 675, label: 'Twitter Post', aspectRatio: '16:9' },
  facebook: { width: 1200, height: 630, label: 'Facebook Post', aspectRatio: '1.91:1' },
} as const;

export type Platform = keyof typeof PLATFORM_DIMENSIONS;

// Brand colors
export const BRAND_COLORS = {
  forestGreen: '#0B5345',
  darkGreen: '#052E27',
  electricYellow: '#F4D03F',
  brightWhite: '#FDFEFE',
  softGray: '#ECF0F1',
  charcoal: '#2C3E50',
} as const;

interface InfographicWrapperProps {
  platform: Platform;
  children: React.ReactNode;
  scale?: number;
}

/**
 * Wrapper component that provides proper dimensions and styling for social media infographics.
 * Uses inline styles to ensure proper rendering when converting to canvas/image.
 */
export const InfographicWrapper = forwardRef<HTMLDivElement, InfographicWrapperProps>(
  ({ platform, children, scale = 0.5 }, ref) => {
    const dimensions = PLATFORM_DIMENSIONS[platform];
    const scaledWidth = dimensions.width * scale;
    const scaledHeight = dimensions.height * scale;

    return (
      <div
        ref={ref}
        style={{
          width: `${dimensions.width}px`,
          height: `${dimensions.height}px`,
          background: `linear-gradient(135deg, ${BRAND_COLORS.forestGreen} 0%, ${BRAND_COLORS.darkGreen} 100%)`,
          fontFamily: "'Oswald', 'DM Sans', sans-serif",
          position: 'relative',
          overflow: 'hidden',
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }}
        data-platform={platform}
      >
        {/* Scan lines overlay for brand texture */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundImage: `repeating-linear-gradient(
              0deg,
              rgba(255, 255, 255, 0.03) 0px,
              transparent 1px,
              transparent 2px,
              rgba(255, 255, 255, 0.03) 3px
            )`,
            pointerEvents: 'none',
          }}
        />
        {children}
      </div>
    );
  }
);

InfographicWrapper.displayName = 'InfographicWrapper';

export default InfographicWrapper;
