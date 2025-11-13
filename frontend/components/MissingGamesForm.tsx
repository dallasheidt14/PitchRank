'use client';

import { useState, useEffect } from 'react';
import { AlertCircle, Calendar } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';

interface MissingGamesFormProps {
  teamId: string;
  teamName: string;
}

export function MissingGamesForm({ teamId, teamName }: MissingGamesFormProps) {
  const [open, setOpen] = useState(false);
  const [gameDate, setGameDate] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [lastSubmission, setLastSubmission] = useState<Date | null>(null);

  // Debug: Log component render
  useEffect(() => {
    console.log('[MissingGamesForm] Component rendered', { teamId, teamName });
  }, [teamId, teamName]);

  // Calculate if user can submit (rate limiting: 60 seconds)
  const canSubmit = !lastSubmission || 
    (new Date().getTime() - lastSubmission.getTime() > 60000);

  // Get today's date in YYYY-MM-DD format for max attribute
  const today = new Date().toISOString().split('T')[0];

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setGameDate('');
      setError(null);
      setSuccess(false);
    }
  }, [open]);

  // Auto-close dialog 3 seconds after successful submission
  useEffect(() => {
    if (success) {
      const timer = setTimeout(() => {
        setOpen(false);
        setSuccess(false);
        setGameDate('');
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [success]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!canSubmit) {
      setError('Please wait before submitting another request');
      return;
    }

    if (!gameDate) {
      setError('Please select a game date');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setSuccess(false);

    try {
      const response = await fetch('/api/scrape-missing-game', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          teamId,
          teamName,
          gameDate,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to submit request');
      }

      // Success
      setSuccess(true);
      setLastSubmission(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred. Please try again.');
      setSuccess(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const timeUntilCanSubmit = lastSubmission
    ? Math.ceil((60000 - (new Date().getTime() - lastSubmission.getTime())) / 1000)
    : 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          Missing Games?
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Report Missing Game</DialogTitle>
          <DialogDescription>
            If you notice a game is missing from {teamName}'s history, let us know the date and we'll fetch it.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="game-date">Game Date</Label>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="game-date"
                  type="date"
                  value={gameDate}
                  onChange={(e) => setGameDate(e.target.value)}
                  max={today}
                  className="pl-10"
                  disabled={isSubmitting || !canSubmit}
                  required
                />
              </div>
              {!canSubmit && lastSubmission && (
                <p className="text-sm text-muted-foreground">
                  Please wait {timeUntilCanSubmit} seconds before submitting another request.
                </p>
              )}
            </div>
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
            {success && (
              <div className="rounded-md bg-green-500/10 p-3 text-sm text-green-600 dark:text-green-400">
                Game data requested! It should appear in 1-2 minutes.
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || !canSubmit || !gameDate}
            >
              {isSubmitting ? 'Submitting...' : 'Submit'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

