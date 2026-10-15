'use client';

import { useState, useEffect, useRef, startTransition } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { US_STATES } from '@/lib/constants';
import { trackFilterApplied } from '@/lib/events';

interface RankingsFilterProps {
  onFilterChange?: (region: string, ageGroup: string, gender: string) => void;
}

const FILTER_IDS = {
  region: 'rankings-filter-region',
  ageGroup: 'rankings-filter-age',
  gender: 'rankings-filter-gender',
} as const;

// A filter change loads another board, which remounts this card; the changed dropdown's id waits here to get
// focus back, so keyboard and screen-reader users aren't dropped at the top of the page.
let pendingFocus: { id: string; path: string } | null = null;

export function RankingsFilter({ onFilterChange }: RankingsFilterProps) {
  const router = useRouter();
  const pathname = usePathname();
  const lastChangedIdRef = useRef<string>(FILTER_IDS.region);

  useEffect(() => {
    const note = pendingFocus;
    pendingFocus = null;
    if (note?.path === pathname) document.getElementById(note.id)?.focus({ preventScroll: true });
    // Next writes the new URL before this card unmounts, so leaving for any other address (Back, a link) means the
    // filter change was abandoned and its note must not wait for a later visit to that board.
    return () => {
      if (pendingFocus && window.location.pathname !== pendingFocus.path) pendingFocus = null;
    };
  }, [pathname]);

  // Track if we're navigating internally to prevent infinite loops
  const isNavigatingRef = useRef(false);
  // Track the target path we're navigating to
  const targetPathRef = useRef<string | null>(null);
  // Track if the user has interacted with the filters (prevents auto-redirect on initial load)
  const hasUserInteractedRef = useRef(false);

  // Extract current URL parts → /rankings/[region]/[ageGroup]/[gender]
  const pathParts = pathname.split('/').filter(Boolean);
  const currentRegion = pathParts[1] || 'national';
  const currentAgeGroup = pathParts[2] || 'u12';
  const currentGender = pathParts[3] || 'male';

  const [region, setRegion] = useState(currentRegion);
  const [ageGroup, setAgeGroup] = useState(currentAgeGroup);
  const [gender, setGender] = useState(currentGender);

  // Handlers that track filter changes
  const handleRegionChange = (newRegion: string) => {
    hasUserInteractedRef.current = true;
    lastChangedIdRef.current = FILTER_IDS.region;
    setRegion(newRegion);
    trackFilterApplied({ region: newRegion, age_group: ageGroup, gender });
  };

  const handleAgeGroupChange = (newAgeGroup: string) => {
    hasUserInteractedRef.current = true;
    lastChangedIdRef.current = FILTER_IDS.ageGroup;
    setAgeGroup(newAgeGroup);
    trackFilterApplied({ region, age_group: newAgeGroup, gender });
  };

  const handleGenderChange = (newGender: string) => {
    hasUserInteractedRef.current = true;
    lastChangedIdRef.current = FILTER_IDS.gender;
    setGender(newGender);
    trackFilterApplied({ region, age_group: ageGroup, gender: newGender });
  };

  // Keep dropdowns in sync with the URL when user navigates via links
  // Skip sync if we're the ones causing the navigation (prevents infinite loop)
  useEffect(() => {
    // Check if we've arrived at our target path - reset navigation flags
    if (isNavigatingRef.current && targetPathRef.current && pathname === targetPathRef.current) {
      isNavigatingRef.current = false;
      targetPathRef.current = null;
      hasUserInteractedRef.current = false;
      return;
    }

    // Don't sync state if we're navigating internally
    if (isNavigatingRef.current) {
      return;
    }

    // Don't sync from URL if user just changed a filter — we're about to navigate
    if (hasUserInteractedRef.current) {
      return;
    }

    // On /rankings page (home), don't sync from URL - let user control filters
    if (pathname === '/rankings') {
      return;
    }

    // Only sync if URL params actually changed (external navigation, e.g. back/forward or link)
    if (currentRegion !== region || currentAgeGroup !== ageGroup || currentGender !== gender) {
      startTransition(() => {
        setRegion(currentRegion);
        setAgeGroup(currentAgeGroup);
        setGender(currentGender);
      });
    }
  }, [currentRegion, currentAgeGroup, currentGender, region, ageGroup, gender, pathname]);

  // Handle filter changes
  useEffect(() => {
    // If on home rankings page with callback, use it
    if (pathname === '/rankings' && onFilterChange) {
      onFilterChange(region, ageGroup, gender);
      return;
    }

    // Navigate to filtered route from /rankings or /rankings/...
    if (!pathname.startsWith('/rankings')) {
      return;
    }

    // On the base /rankings page, only navigate when the user changes a filter
    if (pathname === '/rankings' && !hasUserInteractedRef.current) {
      return;
    }

    const targetPath = `/rankings/${region}/${ageGroup}/${gender}`;
    const currentPath = pathname;

    // Prevent navigation if we're already on the target route
    if (currentPath === targetPath) {
      return;
    }

    // Mark that we're navigating internally and set target
    isNavigatingRef.current = true;
    targetPathRef.current = targetPath;
    pendingFocus = { id: lastChangedIdRef.current, path: targetPath };

    // scroll: false keeps the user's scroll position on the filter card.
    // Without it, App Router jumps to the top of the page on every filter change.
    router.replace(targetPath, { scroll: false });
  }, [region, ageGroup, gender, router, pathname, onFilterChange]);

  return (
    <Card data-testid="rankings-filter" className="w-full border-l-4 border-l-accent shadow-md py-0 sm:py-6">
      {/* Below 340px the three dropdowns no longer fit one row, so Region takes a row of its own. */}
      <CardContent className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)] max-[340px]:grid-cols-2 gap-2 px-3 py-3 sm:flex sm:flex-row sm:items-end sm:justify-start sm:gap-6 sm:px-6 sm:py-5">
        {/* Region */}
        <div className="flex flex-col min-w-0 max-[340px]:col-span-2 sm:w-auto sm:min-w-[200px]">
          <label
            htmlFor={FILTER_IDS.region}
            className="text-xs sm:text-sm font-semibold text-foreground uppercase tracking-wide mb-1 sm:mb-2"
          >
            Region
          </label>
          <Select value={region} onValueChange={handleRegionChange}>
            <SelectTrigger id={FILTER_IDS.region} className="w-full h-11 px-2 sm:px-3 font-medium">
              <SelectValue placeholder="Select region" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="national">National</SelectItem>
              {US_STATES.map(({ code, name }) => (
                <SelectItem key={code} value={code}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Age Group */}
        <div className="flex flex-col min-w-0 sm:w-auto sm:min-w-[160px]">
          <label
            htmlFor={FILTER_IDS.ageGroup}
            className="text-xs sm:text-sm font-semibold text-foreground uppercase tracking-wide mb-1 sm:mb-2"
          >
            Age Group
          </label>
          <Select value={ageGroup} onValueChange={handleAgeGroupChange}>
            <SelectTrigger id={FILTER_IDS.ageGroup} className="w-full h-11 px-2 sm:px-3 font-medium">
              <SelectValue placeholder="Select age group" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="u10">U10</SelectItem>
              <SelectItem value="u11">U11</SelectItem>
              <SelectItem value="u12">U12</SelectItem>
              <SelectItem value="u13">U13</SelectItem>
              <SelectItem value="u14">U14</SelectItem>
              <SelectItem value="u15">U15</SelectItem>
              <SelectItem value="u16">U16</SelectItem>
              <SelectItem value="u17">U17</SelectItem>
              <SelectItem value="u19">U19</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Gender */}
        <div className="flex flex-col min-w-0 sm:w-auto sm:min-w-[160px]">
          <label
            htmlFor={FILTER_IDS.gender}
            className="text-xs sm:text-sm font-semibold text-foreground uppercase tracking-wide mb-1 sm:mb-2"
          >
            Gender
          </label>
          <Select value={gender} onValueChange={handleGenderChange}>
            <SelectTrigger id={FILTER_IDS.gender} className="w-full h-11 px-2 sm:px-3 font-medium">
              <SelectValue placeholder="Select gender" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="male">Boys</SelectItem>
              <SelectItem value="female">Girls</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}
