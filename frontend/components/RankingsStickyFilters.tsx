'use client';

import { forwardRef } from 'react';

import { formatGender, US_STATES } from '@/lib/constants';

interface RankingsStickyFiltersProps {
  region: string;
  ageGroup: string;
  gender: string;
  visible: boolean;
  onChangeClick: () => void;
}

function formatRegion(region: string) {
  if (!region || region === 'national') return 'National';
  return US_STATES.find((s) => s.code.toLowerCase() === region.toLowerCase())?.name ?? region.toUpperCase();
}

function formatAge(age: string) {
  if (!age) return '';
  return age.toUpperCase();
}

export const RankingsStickyFilters = forwardRef<HTMLDivElement, RankingsStickyFiltersProps>(
  function RankingsStickyFilters({ region, ageGroup, gender, visible, onChangeClick }, ref) {
    return (
      <div
        ref={ref}
        data-testid="rankings-sticky-filters"
        aria-hidden={!visible}
        style={{ top: 'calc(4rem + env(safe-area-inset-top, 0px))' }}
        className={`sm:hidden fixed left-0 right-0 z-30 bg-background border-b transition-transform duration-150 ${
          visible ? 'translate-y-0' : '-translate-y-full'
        }`}
      >
        <button
          type="button"
          onClick={onChangeClick}
          tabIndex={visible ? 0 : -1}
          aria-label="Change rankings filter"
          className="w-full h-9 px-4 flex items-center justify-between text-sm"
        >
          <span className="font-medium truncate">
            {formatRegion(region)} • {formatAge(ageGroup)} • {formatGender(gender)}
          </span>
          <span className="text-primary font-semibold ml-2 shrink-0">Change</span>
        </button>
      </div>
    );
  }
);
