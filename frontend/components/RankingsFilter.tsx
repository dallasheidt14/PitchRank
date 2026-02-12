"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { US_STATES } from "@/lib/constants";
import { trackFilterApplied } from "@/lib/events";

interface RankingsFilterProps {
  onFilterChange?: (region: string, ageGroup: string, gender: string) => void;
}

export function RankingsFilter({ onFilterChange }: RankingsFilterProps) {
  const router = useRouter();
  const pathname = usePathname();

  // Track if we're navigating internally to prevent infinite loops
  const isNavigatingRef = useRef(false);
  // Track the target path we're navigating to
  const targetPathRef = useRef<string | null>(null);

  // Extract current URL parts → /rankings/[region]/[ageGroup]/[gender]
  const pathParts = pathname.split("/").filter(Boolean);
  const currentRegion = pathParts[1] || "national";
  const currentAgeGroup = pathParts[2] || "u12";
  const currentGender = pathParts[3] || "male";

  const [region, setRegion] = useState(currentRegion);
  const [ageGroup, setAgeGroup] = useState(currentAgeGroup);
  const [gender, setGender] = useState(currentGender);

  // Handlers that track filter changes
  const handleRegionChange = (newRegion: string) => {
    setRegion(newRegion);
    trackFilterApplied({ region: newRegion, age_group: ageGroup, gender });
  };

  const handleAgeGroupChange = (newAgeGroup: string) => {
    setAgeGroup(newAgeGroup);
    trackFilterApplied({ region, age_group: newAgeGroup, gender });
  };

  const handleGenderChange = (newGender: string) => {
    setGender(newGender);
    trackFilterApplied({ region, age_group: ageGroup, gender: newGender });
  };

  // Keep dropdowns in sync with the URL when user navigates via links
  // Skip sync if we're the ones causing the navigation (prevents infinite loop)
  useEffect(() => {
    // Check if we've arrived at our target path - reset navigation flag
    if (isNavigatingRef.current && targetPathRef.current && pathname === targetPathRef.current) {
      isNavigatingRef.current = false;
      targetPathRef.current = null;
      return;
    }

    // Don't sync state if we're navigating internally
    if (isNavigatingRef.current) {
      return;
    }

    // On /rankings page (home), don't sync from URL - let user control filters
    if (pathname === '/rankings') {
      return;
    }

    // Only sync if URL params actually changed
    if (
      currentRegion !== region ||
      currentAgeGroup !== ageGroup ||
      currentGender !== gender
    ) {
      setRegion(currentRegion);
      setAgeGroup(currentAgeGroup);
      setGender(currentGender);
    }
  }, [currentRegion, currentAgeGroup, currentGender, region, ageGroup, gender, pathname]);

  // Handle filter changes
  useEffect(() => {
    // If on home rankings page, use callback immediately
    if (pathname === '/rankings' && onFilterChange) {
      onFilterChange(region, ageGroup, gender);
      return;
    }

    // Otherwise, navigate to filtered route
    if (!pathname.startsWith('/rankings/')) {
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

    router.replace(targetPath);
  }, [region, ageGroup, gender, router, pathname, onFilterChange]);

  return (
    <Card data-testid="rankings-filter" className="w-full border-l-4 border-l-accent shadow-md">
      <CardContent className="flex flex-col sm:flex-row items-end justify-start gap-4 sm:gap-6 py-5">
        {/* Region */}
        <div className="flex flex-col w-full sm:w-auto min-w-[200px]">
          <label className="text-sm font-semibold text-foreground uppercase tracking-wide mb-2">Region</label>
          <Select value={region} onValueChange={handleRegionChange}>
            <SelectTrigger className="w-full h-11 font-medium">
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
        <div className="flex flex-col w-full sm:w-auto min-w-[160px]">
          <label className="text-sm font-semibold text-foreground uppercase tracking-wide mb-2">Age Group</label>
          <Select value={ageGroup} onValueChange={handleAgeGroupChange}>
            <SelectTrigger className="w-full h-11 font-medium">
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
              <SelectItem value="u18">U18</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Gender */}
        <div className="flex flex-col w-full sm:w-auto min-w-[160px]">
          <label className="text-sm font-semibold text-foreground uppercase tracking-wide mb-2">Gender</label>
          <Select value={gender} onValueChange={handleGenderChange}>
            <SelectTrigger className="w-full h-11 font-medium">
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

