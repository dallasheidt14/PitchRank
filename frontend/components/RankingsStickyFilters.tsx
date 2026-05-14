'use client';

import { forwardRef } from 'react';

interface RankingsStickyFiltersProps {
  region: string;
  ageGroup: string;
  gender: string;
  visible: boolean;
  onChangeClick: () => void;
}

function formatRegion(region: string) {
  if (!region || region === 'national') return 'National';
  return region.toUpperCase();
}

function formatAge(age: string) {
  return age.toUpperCase();
}

function formatGender(gender: string) {
  if (gender === 'male') return 'Boys';
  if (gender === 'female') return 'Girls';
  return gender;
}

export const RankingsStickyFilters = forwardRef<HTMLDivElement, RankingsStickyFiltersProps>(
  function RankingsStickyFilters({ region, ageGroup, gender, visible, onChangeClick }, ref) {
    return (
      <div
        ref={ref}
        data-testid="rankings-sticky-filters"
        aria-hidden={!visible}
        className={`sm:hidden fixed left-0 right-0 top-16 z-30 bg-background border-b transition-transform duration-150 ${
          visible ? 'translate-y-0' : '-translate-y-full'
        }`}
      >
        <button
          type="button"
          onClick={onChangeClick}
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
