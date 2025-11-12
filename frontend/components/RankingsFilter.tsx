"use client";

import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

export function RankingsFilter() {
  const router = useRouter();
  const pathname = usePathname();

  // Extract current URL parts → /rankings/[region]/[ageGroup]/[gender]
  const pathParts = pathname.split("/").filter(Boolean);
  const currentRegion = pathParts[1] || "national";
  const currentAgeGroup = pathParts[2] || "u12";
  const currentGender = pathParts[3] || "male";

  const [region, setRegion] = useState(currentRegion);
  const [ageGroup, setAgeGroup] = useState(currentAgeGroup);
  const [gender, setGender] = useState(currentGender);

  // Keep dropdowns in sync with the URL when user navigates via links
  useEffect(() => {
    setRegion(currentRegion);
    setAgeGroup(currentAgeGroup);
    setGender(currentGender);
  }, [currentRegion, currentAgeGroup, currentGender]);

  // Auto-navigate when filters change (debounced)
  // Only navigate if the current pathname doesn't match the selected filters
  useEffect(() => {
    const targetPath = `/rankings/${region}/${ageGroup}/${gender}`;
    const currentPath = pathname;
    
    // Prevent navigation if we're already on the target route
    if (currentPath === targetPath) {
      return;
    }
    
    const timeout = setTimeout(() => {
      router.replace(targetPath);
    }, 250);
    return () => clearTimeout(timeout);
  }, [region, ageGroup, gender, router, pathname]);

  return (
    <Card className="w-full max-w-3xl mx-auto mb-6">
      <CardContent className="flex flex-col sm:flex-row items-center justify-between gap-4 py-6">
        {/* Region */}
        <div className="flex flex-col w-full sm:w-auto">
          <label className="text-sm text-muted-foreground mb-1">Region</label>
          <Select value={region} onValueChange={setRegion}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Select region" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="national">National</SelectItem>
              <SelectItem value="al">Alabama</SelectItem>
              <SelectItem value="ak">Alaska</SelectItem>
              <SelectItem value="az">Arizona</SelectItem>
              <SelectItem value="ar">Arkansas</SelectItem>
              <SelectItem value="ca">California</SelectItem>
              <SelectItem value="co">Colorado</SelectItem>
              <SelectItem value="ct">Connecticut</SelectItem>
              <SelectItem value="de">Delaware</SelectItem>
              <SelectItem value="fl">Florida</SelectItem>
              <SelectItem value="ga">Georgia</SelectItem>
              <SelectItem value="hi">Hawaii</SelectItem>
              <SelectItem value="id">Idaho</SelectItem>
              <SelectItem value="il">Illinois</SelectItem>
              <SelectItem value="in">Indiana</SelectItem>
              <SelectItem value="ia">Iowa</SelectItem>
              <SelectItem value="ks">Kansas</SelectItem>
              <SelectItem value="ky">Kentucky</SelectItem>
              <SelectItem value="la">Louisiana</SelectItem>
              <SelectItem value="me">Maine</SelectItem>
              <SelectItem value="md">Maryland</SelectItem>
              <SelectItem value="ma">Massachusetts</SelectItem>
              <SelectItem value="mi">Michigan</SelectItem>
              <SelectItem value="mn">Minnesota</SelectItem>
              <SelectItem value="ms">Mississippi</SelectItem>
              <SelectItem value="mo">Missouri</SelectItem>
              <SelectItem value="mt">Montana</SelectItem>
              <SelectItem value="ne">Nebraska</SelectItem>
              <SelectItem value="nv">Nevada</SelectItem>
              <SelectItem value="nh">New Hampshire</SelectItem>
              <SelectItem value="nj">New Jersey</SelectItem>
              <SelectItem value="nm">New Mexico</SelectItem>
              <SelectItem value="ny">New York</SelectItem>
              <SelectItem value="nc">North Carolina</SelectItem>
              <SelectItem value="nd">North Dakota</SelectItem>
              <SelectItem value="oh">Ohio</SelectItem>
              <SelectItem value="ok">Oklahoma</SelectItem>
              <SelectItem value="or">Oregon</SelectItem>
              <SelectItem value="pa">Pennsylvania</SelectItem>
              <SelectItem value="ri">Rhode Island</SelectItem>
              <SelectItem value="sc">South Carolina</SelectItem>
              <SelectItem value="sd">South Dakota</SelectItem>
              <SelectItem value="tn">Tennessee</SelectItem>
              <SelectItem value="tx">Texas</SelectItem>
              <SelectItem value="ut">Utah</SelectItem>
              <SelectItem value="vt">Vermont</SelectItem>
              <SelectItem value="va">Virginia</SelectItem>
              <SelectItem value="wa">Washington</SelectItem>
              <SelectItem value="wv">West Virginia</SelectItem>
              <SelectItem value="wi">Wisconsin</SelectItem>
              <SelectItem value="wy">Wyoming</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Age Group */}
        <div className="flex flex-col w-full sm:w-auto">
          <label className="text-sm text-muted-foreground mb-1">Age Group</label>
          <Select value={ageGroup} onValueChange={setAgeGroup}>
            <SelectTrigger className="w-[180px]">
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
        <div className="flex flex-col w-full sm:w-auto">
          <label className="text-sm text-muted-foreground mb-1">Gender</label>
          <Select value={gender} onValueChange={setGender}>
            <SelectTrigger className="w-[180px]">
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

