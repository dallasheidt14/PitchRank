'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Home, Search, ArrowLeft } from 'lucide-react';

export default function TeamNotFound() {
  return (
    <>
      {/* Page Header */}
      <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12">
        <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <div className="container mx-auto px-4 sm:px-6">
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            Team Not Found
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            The team you&apos;re looking for doesn&apos;t exist or may have been removed
          </p>
        </div>
      </div>

      <div className="container mx-auto py-6 sm:py-8 px-4 sm:px-6">
        <Card className="border-l-4 border-l-accent max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="font-display uppercase tracking-wide">
              404 - Team Not Found
            </CardTitle>
            <CardDescription>
              We couldn&apos;t find the team you were looking for. This could happen if:
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <ul className="list-disc list-inside text-muted-foreground space-y-2">
              <li>The team ID in the URL is incorrect</li>
              <li>The team has been removed from our database</li>
              <li>You followed an outdated link</li>
            </ul>

            <div className="flex flex-col sm:flex-row gap-3 pt-4">
              <Button asChild variant="default">
                <Link href="/rankings/national/u12/male">
                  <Search className="mr-2 h-4 w-4" />
                  Browse Rankings
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/">
                  <Home className="mr-2 h-4 w-4" />
                  Go Home
                </Link>
              </Button>
              <Button variant="outline" onClick={() => history.back()}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Go Back
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
