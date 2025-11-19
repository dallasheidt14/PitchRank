'use client';

import Image from 'next/image';
import { PageHeader } from '@/components/PageHeader';
import { HomeLeaderboard } from '@/components/HomeLeaderboard';
import { RecentMovers } from '@/components/RecentMovers';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Button } from '@/components/ui/button';

export default function Home() {

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex flex-col items-center mb-6 sm:mb-8 w-full">
        <div className="w-full max-w-3xl px-2 sm:px-4 flex justify-center">
          <Image
            src="/logos/pitchrank-logo-white.svg"
            alt="PitchRank"
            width={300}
            height={75}
            priority
            className="w-full h-auto max-w-[300px] sm:max-w-[400px] dark:hidden"
          />
          <Image
            src="/logos/pitchrank-logo-black.svg"
            alt="PitchRank"
            width={300}
            height={75}
            priority
            className="w-full h-auto max-w-[300px] sm:max-w-[400px] hidden dark:block"
          />
        </div>
      </div>
      <PageHeader
        title="Welcome to PitchRank"
        description="Comprehensive rankings for youth soccer teams across the United States"
      />
      
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <HomeLeaderboard />

        <RecentMovers />

        <Card>
          <CardHeader>
            <CardTitle>Quick Links</CardTitle>
            <CardDescription>Navigate to key sections</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/rankings">
                View Rankings
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/compare">
                Compare Teams
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/methodology">
                Methodology
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
